import copy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import free_access as free
from api_transport import APIError


class FreeAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = 'nex-agi/nex-n2.5-pro:free'
        self.models = [self.model, 'poolside/laguna-s-2.1:free', 'cohere/north-mini-code:free']
        self.config = {'schema_version': 1, 'enabled': True, 'mixed_work': False,
                       'mode': 'observed', 'authority': 'local',
                       'credential_file': str(self.root / 'credential.md'), 'models': self.models}
        self.ledger = free.FreeLedger(self.root / 'requests.sqlite3')
        self.packet = {'id': 'task-1', 'model': 'auto', 'prompt': 'Find a useful test case.',
                       'max_output_tokens': 1000, 'timeout': 30}
        self.live = {'models': [{'id': value, 'family': value.split('/')[0],
                                'max_output_tokens': 8192, 'canonical_model': value + '-canonical'}
                               for value in self.models], 'policy_sha256': 'a' * 64}

    def response(self, model=None):
        return {'model': model or self.model, 'usage': {'cost': 0, 'prompt_tokens': 10, 'completion_tokens': 20},
                'choices': [{'finish_reason': 'stop', 'message': {'content': 'Test an expired quota observation.'}}]}

    def execute(self, response=None, packet=None):
        with patch.object(free, 'evidence', return_value=({}, self.live, {'limit': 0})):
            with patch.object(free, 'request_json', return_value=response or self.response()) as transport:
                result = free.run(self.config, packet or self.packet, ledger=self.ledger)
        return result, transport

    def test_zero_gate_rejects_invalid_values_and_hidden_charges(self):
        for value in [True, None, 'NaN', 'Infinity', '-1', '0.00001', [], {}]:
            with self.subTest(value=value):
                self.assertFalse(free.zero(value))
        self.assertTrue(free.zero_prices({'prompt': '0', 'completion': '0', 'request': 0}))
        for price in [{'prompt': '0'}, {'prompt': '0', 'completion': '0', 'web_search': '0.01'},
                      {'prompt': '0', 'completion': '0', 'overrides': [{'prompt': '1'}]}]:
            self.assertFalse(free.zero_prices(price))

    def test_completed_request_has_zero_price_controls_and_rotates_models(self):
        first, transport = self.execute()
        self.assertEqual(first['status'], 'completed')
        body = json.loads(transport.call_args.kwargs['body'])
        self.assertEqual(body['provider']['max_price'], dict.fromkeys(['prompt', 'completion', 'request', 'image'], 0))
        self.assertFalse(body['provider']['allow_fallbacks'])
        self.assertEqual(body['provider']['data_collection'], 'deny')
        self.assertEqual(body['usage'], {'include': True})
        self.assertNotIn('tools', body)
        self.assertNotIn('plugins', body)
        second_packet = {**self.packet, 'id': 'task-2'}
        second, _ = self.execute(self.response(self.models[1]), second_packet)
        self.assertEqual(second['requested_model'], self.models[1])
        self.assertEqual(self.ledger.status()['daily_requests'], 2)

    def test_repeat_is_accounting_only_and_changed_prompt_conflicts(self):
        self.execute()
        with patch.object(free, 'evidence') as evidence, patch.object(free, 'request_json') as request:
            repeated = free.run(self.config, self.packet, ledger=self.ledger)
            self.assertEqual(repeated['status'], 'free_duplicate')
            self.assertNotIn('text', repeated)
            evidence.assert_not_called()
            request.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'free_request_id_conflict'):
                free.run(self.config, {**self.packet, 'prompt': 'Different work'}, ledger=self.ledger)

    def test_missing_cost_nonzero_cost_and_wrong_identity_retain_request(self):
        for field, value in [('cost', None), ('cost', '0.001'), ('model', self.model.removesuffix(':free')),
                             ('model', None), ('cost', True)]:
            with self.subTest(field=field, value=value):
                ledger = free.FreeLedger(self.root / ('case-' + str(len(list(self.root.iterdir()))) + '.sqlite3'))
                response = self.response()
                if field == 'cost':
                    response['usage']['cost'] = value
                else:
                    response['model'] = value
                with patch.object(free, 'evidence', return_value=({}, self.live, {})), \
                        patch.object(free, 'request_json', return_value=response):
                    result = free.run(self.config, self.packet, ledger=ledger)
                self.assertEqual(result['status'], 'free_unresolved')
                self.assertNotIn('text', result)
                self.assertFalse(ledger.status()['allowed'])
                self.assertEqual(ledger.status()['daily_requests'], 1)

    def test_transport_failure_does_not_auto_retry_or_release(self):
        with patch.object(free, 'evidence', return_value=({}, self.live, {})), \
                patch.object(free, 'request_json', side_effect=APIError('api_timeout')) as request:
            result = free.run(self.config, self.packet, ledger=self.ledger)
        self.assertEqual(result['reason'], 'api_timeout')
        self.assertEqual(request.call_count, 1)
        self.assertFalse(self.ledger.status()['allowed'])
        self.ledger.reconcile(self.packet['id'])
        self.assertTrue(self.ledger.status()['allowed'])
        self.assertEqual(self.ledger.status()['daily_requests'], 1)

    def test_unresolved_request_blocks_other_model_and_next_day(self):
        self.ledger.reserve('one', 'a', self.models, 'auto', now=1000)
        for now in [1001, 90000]:
            result = self.ledger.reserve('two', 'b', self.models, self.models[1], now=now)
            self.assertFalse(result['allowed'])
            self.assertIn('free_request_unresolved', result['reasons'])

    def test_real_sqlite_concurrency_admits_only_one_worker(self):
        from concurrent.futures import ThreadPoolExecutor
        def reserve(identifier):
            return self.ledger.reserve(identifier, identifier, self.models, 'auto')
        with ThreadPoolExecutor(max_workers=2) as workers:
            replies = list(workers.map(reserve, ['first', 'second']))
        self.assertEqual(sum(reply['allowed'] for reply in replies), 1)
        self.assertEqual(self.ledger.status()['daily_requests'], 1)

    def test_daily_and_minute_limits_are_shared_across_models(self):
        start = 1788912000
        with self.ledger.connect() as db:
            for i in range(50):
                db.execute('INSERT INTO free_requests VALUES (?,?,?,?,?,NULL)',
                           (str(i), str(i), self.models[i % 3], start + i, 'completed'))
        state = self.ledger.status(now=start + 60)
        self.assertIn('free_daily_request_limit', state['reasons'])
        self.assertIn('free_minute_request_limit', state['reasons'])
        next_day = self.ledger.status(now=start + 86400)
        self.assertTrue(next_day['allowed'])
        self.assertEqual(next_day['daily_requests'], 0)
        with self.ledger.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM free_requests').fetchone()[0], 50)

    def test_config_change_during_preflight_blocks_before_reservation(self):
        with patch.object(free, 'evidence', return_value=({}, self.live, {})), \
                patch.object(free, 'load_config', return_value={**self.config, 'enabled': False}), \
                patch.object(free, 'request_json') as request:
            with self.assertRaisesRegex(ValueError, 'free_configuration_changed'):
                free.run(self.config, self.packet, ledger=self.ledger, config_path='unused')
        request.assert_not_called()
        self.assertEqual(self.ledger.status()['daily_requests'], 0)

    def test_key_cap_must_be_explicit_zero(self):
        for limit, remaining in [(None, None), (1, 1), (False, False), (0, None), (0, 1)]:
            with self.subTest(limit=limit, remaining=remaining), \
                    patch.object(free, 'credentials', return_value={}), \
                    patch.object(free, 'request_json', return_value={'data': {'limit': limit, 'limit_remaining': remaining}}), \
                    patch.object(free, 'catalog') as catalog:
                with self.assertRaisesRegex(ValueError, 'free_zero_key_cap_required'):
                    free.evidence(self.config)
                catalog.assert_not_called()

    def test_config_roundtrip_preserves_explicit_opt_in_and_rejects_paid_ids(self):
        config_path = self.root / 'settings.json'
        free.save_config(self.config, config_path)
        self.assertEqual(free.load_config(config_path), self.config)
        self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)
        for change in [{'models': ['openai/gpt-6-astra']}, {'mode': 'strict'}, {'schema_version': True}]:
            with self.assertRaises(ValueError):
                free.validate_config({**self.config, **change})

    def test_remote_executor_never_recurses_or_falls_back(self):
        config = {'schema_version': 1, 'enabled': True, 'mixed_work': True,
                  'mode': 'observed', 'authority': 'ssh', 'command': ['ssh', 'trusted-executor']}
        with patch.object(free, 'load_config', return_value=config), \
                patch.object(free.subprocess, 'run', side_effect=OSError('private diagnostic')) as transport:
            with self.assertRaisesRegex(ValueError, 'free_authority_loop'):
                free.dispatch('status', local_only=True)
            transport.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'free_authority_unavailable_inspect_remote_journal'):
                free.dispatch('status')
        expected = {'status': 'free_ready', 'progress': 0.0125,
                    'accounts': {'groq': {'progress': 0.0125, 'reserved_free_credit_usd': '0.0000000000000001'}}}
        response = free.subprocess.CompletedProcess([], 0, json.dumps({'protocol_version': 1, 'result': expected}).encode())
        with patch.object(free, 'load_config', return_value=config), patch.object(free.subprocess, 'run', return_value=response):
            result = free.dispatch('status')
            self.assertEqual(result, expected)
            self.assertIs(type(result['progress']), float)
            response.stdout = b'{"protocol_version":1,"result":{"progress":1e999}}'
            with self.assertRaisesRegex(ValueError, 'free_authority_unavailable'):
                free.dispatch('status')

    def test_credentials_are_private_and_not_logged(self):
        path = Path(self.config['credential_file'])
        path.write_text('API key: sk-or-v1-' + 'a' * 64 + '\n')
        path.chmod(0o600)
        self.assertTrue(free.credentials(self.config)['Authorization'].startswith('Bearer '))
        if os.name == 'nt':
            import windows_security
            command = "$a=Get-Acl -LiteralPath '" + str(path).replace("'", "''") + "'; [Console]::Write($a.AreAccessRulesProtected)"
            self.assertEqual(free.subprocess.check_output(['pwsh', '-NoProfile', '-Command', command], text=True).strip(), 'True')
            with patch.object(windows_security, 'protect', side_effect=OSError('unsafe ACL')):
                with self.assertRaisesRegex(ValueError, 'free_credential_unavailable'):
                    free.credentials(self.config)
            return
        path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'free_private_file_permissions'):
            free.credentials(self.config)
        path.chmod(0o600)
        alias = self.root / 'alias.md'
        alias.symlink_to(path)
        with self.assertRaisesRegex(ValueError, 'free_credential_unavailable'):
            free.credentials({**self.config, 'credential_file': str(alias)})

    def test_payload_bounds_and_paid_models_fail_without_requests(self):
        for change in [{'model': 'openai/gpt-6-astra'}, {'prompt': 'a' * 8193},
                       {'max_output_tokens': True}, {'timeout': float('nan')}, {'id': '../task'}]:
            with patch.object(free, 'evidence') as evidence:
                with self.assertRaisesRegex(ValueError, 'invalid_free_packet'):
                    free.run(self.config, {**self.packet, **change}, ledger=self.ledger)
                evidence.assert_not_called()


if __name__ == '__main__':
    unittest.main()
