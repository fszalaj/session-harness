import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import free_accounts as free
from api_transport import APIError, decode_json


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        key = 'dummy-key-for-local-test-only'
        self.credential = self.root / 'key.md'
        self.credential.write_text('API key: ' + key + '\n')
        self.credential.chmod(0o600)
        self.now = time.time()
        self.row = {'enabled': True, 'credential_file': str(self.credential),
                    'credential_sha256': hashlib.sha256(key.encode()).hexdigest(),
                    'account_sha256': 'a' * 64, 'model': 'qwen-test', 'response_models': ['qwen-test'],
                    'family': 'qwen', 'context_tokens': 65536, 'max_output_tokens': 8192,
                    'evidence': {'observed_at': self.now - 10, 'expires_at': self.now + 1000,
                                 'kind': 'account_ui_observation', 'source': 'https://example.com/account',
                                 'no_paid_overage': True, 'tokenizer': 'byte_bpe',
                                 'tokenizer_source': 'https://example.com/tokenizer',
                                 'pricing_source': 'https://example.com/pricing',
                                 'coding': 'https://example.com/coding', 'hf_routing_only': False},
                    'limits': {'rpm': 30, 'rpd': 1000, 'tpm': 8000, 'tpd': 200000,
                               'credit_usd': '0', 'input_per_million': '0', 'output_per_million': '0',
                               'period_start': self.now - 100}}
        self.config = {'schema_version': 2, 'authority': 'local', 'mode': 'observed',
                       'enabled': True, 'mixed_work': True, 'accounts': {'groq': self.row}}
        self.packet = {'id': 'test-1', 'model': 'groq', 'prompt': 'Name one SQLite race.',
                       'max_output_tokens': 256, 'timeout': 60}
        self.ledger = free.AccountsLedger(self.root / 'ledger.sqlite3')
        self.response = {'model': 'qwen-test', 'usage': {'prompt_tokens': 20, 'completion_tokens': 30},
                         'choices': [{'finish_reason': 'stop', 'message': {'content': 'Concurrent check then insert.'}}]}

    def execute(self, response=None):
        with patch.object(free, 'preflight', return_value={}), patch.object(free, 'request_json', return_value=response or self.response) as transport:
            result = free.dispatch(self.config, 'run', self.packet, ledger=self.ledger)
        return result, transport

    def test_completion_and_duplicate_do_not_repeat_post(self):
        self.row['reasoning_effort'] = 'none'
        result, transport = self.execute()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['actual_model'], 'qwen-test')
        self.assertIsNone(result['actual_cost_usd'])
        self.assertNotIn('tools', json.loads(transport.call_args.kwargs['body']))
        self.assertEqual(json.loads(transport.call_args.kwargs['body'])['reasoning_effort'], 'none')
        with patch.object(free, 'preflight') as preflight:
            self.assertEqual(free.dispatch(self.config, 'run', self.packet, ledger=self.ledger)['status'], 'free_duplicate')
            preflight.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'id_conflict'):
                free.dispatch(self.config, 'run', {**self.packet, 'prompt': 'Changed'}, ledger=self.ledger)

    def test_sqlite_concurrency_and_durability(self):
        def reserve(identifier):
            ledger = free.AccountsLedger(self.ledger.path)
            return ledger.bind(self.config, {**self.packet, 'id': identifier}, self.now)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, ['a', 'b']))
        self.assertEqual(sum(r['status'] == 'reserved' for r in results), 1)
        with self.ledger.connect() as db:
            for pragma, expected in [('journal_mode', 'delete'), ('synchronous', 2), ('busy_timeout', 10000)]:
                self.assertEqual(db.execute('PRAGMA ' + pragma).fetchone()[0], expected)

    def test_credit_reservation_retained_and_pending_blocks_period_change(self):
        self.config['accounts'] = {'mistral': self.row}
        self.packet['model'] = 'mistral'
        self.row['limits'].update(credit_usd='0.01', input_per_million='1', output_per_million='2')
        result, _ = self.execute()
        st = self.ledger.states(self.config, time.time())['mistral']
        self.assertEqual(st['reserved_free_credit_usd'], result['reservation']['credit_usd'])
        self.ledger.bind(self.config, {**self.packet, 'id': 'second'}, time.time())
        with self.assertRaisesRegex(ValueError, 'unresolved'):
            self.ledger.renew_period('mistral', time.time() - 1, 'billing:checked')
        self.row['limits']['period_start'] += 10
        st = self.ledger.states(self.config, time.time())['mistral']
        self.assertIn('free_request_unresolved', st['reasons'])
        self.assertIn('free_account_or_period_change_requires_reconciliation', st['reasons'])

    def test_failure_and_reconcile_never_refund_or_retry(self):
        with patch.object(free, 'preflight', return_value={}), patch.object(free, 'request_json', side_effect=APIError('api_http_error', 429)) as transport:
            result = free.dispatch(self.config, 'run', self.packet, ledger=self.ledger)
        self.assertEqual(result['http_status'], 429)
        self.assertEqual(transport.call_count, 1)
        before = self.ledger.states(self.config, time.time())['groq']
        self.assertTrue(before['pending'])
        self.ledger.reconcile_account(self.packet['id'], 'process:confirmed-stopped')
        after = self.ledger.states(self.config, time.time())['groq']
        self.assertFalse(after['pending'])
        self.assertEqual(before['reserved'], after['reserved'])

    def test_identity_and_usage_failure_hide_output(self):
        for change in [{'model': 'wrong'}, {'usage': {'prompt_tokens': 10, 'completion_tokens': 9000}}]:
            self.packet['id'] += 'x'
            result, _ = self.execute({**self.response, **change})
            self.assertEqual(result['status'], 'free_unresolved')
            self.assertNotIn('text', result)
            self.ledger.reconcile_account(self.packet['id'], 'process:stopped')

    def test_rolling_windows_reservation_and_clock_guard(self):
        self.row['limits']['tpm'] = 1200
        self.assertEqual(self.ledger.bind(self.config, self.packet, self.now)['status'], 'free_blocked')
        self.row['limits']['tpm'] = 8000
        self.ledger.bind(self.config, self.packet, self.now)
        self.ledger.complete(self.packet['id'], 'completed', {})
        st = self.ledger.states(self.config, self.now + 61)['groq']
        self.assertEqual(st['reserved']['rpm'], 0)
        self.assertEqual(st['reserved']['rpd'], 1)
        with self.assertRaisesRegex(ValueError, 'clock_moved_backwards'):
            self.ledger.states(self.config, self.now)

    def test_evidence_bindings_and_numeric_validation(self):
        normalized = free.validate_config(decode_json(json.dumps(self.config)))
        self.assertEqual(normalized, self.config)
        json.dumps(normalized)
        for field, value in [('expires_at', float('nan')), ('no_paid_overage', False), ('tokenizer', 'unknown')]:
            config = copy.deepcopy(self.config)
            config['accounts']['groq']['evidence'][field] = value
            with self.assertRaises(ValueError):
                free.validate_config(config)
        for value in [True, 'NaN', 'Infinity', '-1', 0.5]:
            with self.assertRaises(ValueError):
                free.number(value)
        self.row['credential_sha256'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'binding_changed'):
            free.credential(self.row)
        self.credential.chmod(0o644)
        with self.assertRaises(ValueError):
            free.credential(self.row)

    def test_expiry_disables_dispatch_without_fallback(self):
        self.config['accounts']['nvidia'] = {'enabled': False, 'reason': 'unverified'}
        self.row['evidence']['expires_at'] = self.now - 1
        with self.assertRaisesRegex(ValueError, 'evidence_expired'):
            free.preflight('groq', self.row, self.now)
        with patch.object(free, 'preflight', return_value={}), patch.object(free, 'request_json') as transport:
            result = free.dispatch(self.config, 'run', self.packet, ledger=self.ledger)
        self.assertEqual(result['status'], 'free_blocked')
        transport.assert_not_called()

    def test_hf_fixed_provider_rate_and_account_checks(self):
        row = copy.deepcopy(self.row)
        row['model'] = 'qwen-test:novita'
        row['account_sha256'] = hashlib.sha256(b'testuser').hexdigest()
        row['limits'].update(credit_usd='0.1', input_per_million='1', output_per_million='2')
        row['evidence']['hf_routing_only'] = True
        config = {**self.config, 'accounts': {'huggingface': row}}
        free.validate_config(config)
        models = {'data': [{'id': 'qwen-test', 'providers': [{'provider': 'novita', 'status': 'live', 'pricing': {'input': '1', 'output': '2'}}]}]}
        with patch.object(free, 'request_json', side_effect=[models, {'type': 'user', 'name': 'testuser'}]):
            self.assertIn('Authorization', free.preflight('huggingface', row, self.now))
        models['data'][0]['providers'][0]['pricing']['input'] = '3'
        with patch.object(free, 'request_json', return_value=models):
            with self.assertRaisesRegex(ValueError, 'prices_changed'):
                free.preflight('huggingface', row, self.now)
        row['model'] = 'qwen-test:fastest'
        with self.assertRaisesRegex(ValueError, 'fixed_hf_provider'):
            free.validate_config(config)

    def test_configuration_and_account_change_fail_closed(self):
        with patch.object(free, 'preflight', return_value={}), patch.object(free.legacy, 'load_config', return_value={}), patch.object(free, 'request_json') as transport:
            with self.assertRaisesRegex(ValueError, 'configuration_changed'):
                free.dispatch(self.config, 'run', self.packet, config_path='unused', ledger=self.ledger)
            transport.assert_not_called()
        self.execute()
        self.row['account_sha256'] = 'b' * 64
        self.assertIn('free_account_or_period_change_requires_reconciliation', self.ledger.states(self.config, time.time())['groq']['reasons'])
        for change in [{'timeout': float('nan')}, {'max_output_tokens': True}, {'model': 'paid'}, {'id': '../escape'}]:
            with self.assertRaisesRegex(ValueError, 'invalid_free_packet'):
                free.dispatch(self.config, 'run', {**self.packet, **change}, ledger=self.ledger)

    def test_completed_receipt_cannot_be_abandoned_and_billing_needs_reverification(self):
        self.execute()
        with self.assertRaisesRegex(ValueError, 'not_unresolved'):
            self.ledger.reconcile_account(self.packet['id'], 'process:stopped')
        self.packet['id'] = 'billing-failure'
        with patch.object(free, 'preflight', return_value={}), patch.object(free, 'request_json', side_effect=APIError('api_http_error', 402)):
            free.dispatch(self.config, 'run', self.packet, ledger=self.ledger)
        with self.assertRaisesRegex(ValueError, 'billing_reverification'):
            self.ledger.reconcile_account(self.packet['id'], 'process:stopped', self.config)
        with self.assertRaisesRegex(ValueError, 'receipt_state_invalid'):
            self.ledger.complete(self.packet['id'], 'typo', {})

    def test_legacy_group_pending_and_separate_file_invariants(self):
        with patch.object(free.legacy, 'DATABASE', self.ledger.path):
            with self.assertRaisesRegex(ValueError, 'must_differ'):
                free.AccountsLedger(self.ledger.path)
        row = {'enabled': True}
        with self.ledger.connect() as db:
            db.execute('INSERT INTO account_jobs VALUES (?,?,?,?,?,?,NULL)', ('legacy', 'hash', 'openrouter', self.now, 'running', '{}'))
            with patch.object(free.legacy.FreeLedger, 'status', return_value={'allowed': True, 'progress': 0, 'reasons': []}):
                st = self.ledger.state(db, 'openrouter', row, self.now)
        self.assertFalse(st['allowed'])


if __name__ == '__main__':
    unittest.main()
