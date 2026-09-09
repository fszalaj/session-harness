"""Coding eligibility never implies account access, free use or paid admission."""
import copy
import datetime as dt
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import api_execution
import api_providers
from api_transport import APIError
import coding_models
from spend import SpendLedger, ticks


TODAY = dt.date(2026, 9, 9)
MODEL = 'reviewed/model-2'


def policy():
    return {'schema_version': 1, 'service': 'openrouter', 'min_context_tokens': 65536,
            'models': [{'id': MODEL, 'family': 'reviewed', 'publisher': 'reviewed',
                        'reviewed_at': '2026-09-09', 'expires_at': '2026-10-09',
                        'evidence': [{'kind': 'vendor_report', 'url': 'https://example.org/report',
                                      'note': 'Fixture coding evaluation.'}]}]}


def model():
    return {'id': MODEL, 'context_length': 262144,
            'top_provider': {'context_length': 131072, 'max_completion_tokens': 4096},
            'supported_parameters': ['tools', 'tool_choice', 'max_tokens'],
            'pricing': {'prompt': '0.000001', 'completion': '0.000002'}}


class PolicyFixture:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'policy.json'
        self.write(policy())

    def write(self, value):
        self.path.write_text(json.dumps(value))


class CodingModelTests(PolicyFixture, unittest.TestCase):
    def catalog(self, rows=None, **kwargs):
        with patch.object(coding_models, 'request_json', return_value={'data': rows or [model()]}) as fetch:
            result = coding_models.catalog(self.path, now=kwargs.get('now', TODAY))
        self.assertEqual('https://openrouter.ai', fetch.call_args.args[0])
        self.assertNotIn('Authorization', fetch.call_args.kwargs['headers'])
        return result

    def test_live_metadata_is_public_and_uses_effective_provider_limits(self):
        row = self.catalog()['models'][0]
        self.assertEqual(131072, row['context_tokens'])
        self.assertEqual(4096, row['max_output_tokens'])
        self.assertFalse(row['account_access_verified'])
        self.assertFalse(row['inference_verified'])
        self.assertFalse(row['catalog_price_is_spending_cap'])

    def test_unreviewed_variants_and_new_generations_never_qualify(self):
        rows = [dict(model(), id=MODEL + suffix) for suffix in (':free', ':nitro', ':exacto', ':batch', '-new')]
        rows.append(dict(model(), id='~synthetic/latest'))
        result = self.catalog(rows)
        self.assertEqual([], result['models'])
        self.assertEqual(['coding_model_not_in_live_catalog'], result['excluded'][0]['reasons'])

    def test_expired_and_future_evidence_are_excluded_at_boundaries(self):
        for day in (dt.date(2026, 9, 8), dt.date(2026, 10, 9)):
            result = self.catalog(now=day)
            self.assertEqual([], result['models'])
            self.assertIn('coding_review_expired_or_future', result['excluded'][0]['reasons'])

    def test_invalid_policy_never_fetches(self):
        cases = []
        for key, value in [('schema_version', True), ('min_context_tokens', 1)]:
            bad = policy(); bad[key] = value; cases.append(bad)
        for key, value in [('id', 'reviewed/*'), ('publisher', 'another'), ('expires_at', '2027-01-01'),
                           ('reviewed_at', '2026-02-30'), ('evidence', [])]:
            bad = policy(); bad['models'][0][key] = value; cases.append(bad)
        bad = policy(); bad['models'].append(copy.deepcopy(bad['models'][0])); cases.append(bad)
        for bad in cases:
            self.write(bad)
            with patch.object(coding_models, 'request_json') as fetch, self.assertRaises(ValueError):
                coding_models.catalog(self.path, now=TODAY)
            fetch.assert_not_called()

    def test_duplicate_keys_and_oversized_policy_fail(self):
        for raw in ('{"service":"one","service":"two"}', ' ' * 65537):
            self.path.write_text(raw)
            with self.assertRaises(ValueError):
                coding_models.load_policy(self.path)

    def test_partial_or_malformed_catalog_never_qualifies(self):
        for data in ({'data': []}, {'data': [model()], 'has_more': True},
                     {'data': [model(), model()]}, {'data': [None]}, {'error': {}, 'data': [model()]}):
            with patch.object(coding_models, 'request_json', return_value=data), self.assertRaises(ValueError):
                coding_models.catalog(self.path, now=TODAY)

    def test_missing_tools_context_output_or_negative_price_excludes_model(self):
        cases = []
        for key, value in [('supported_parameters', ['max_tokens']), ('top_provider', None),
                           ('context_length', True), ('context_length', 32000), ('expiration_date', '2026-09-09')]:
            bad = model(); bad[key] = value; cases.append(bad)
        for value in (None, -1, 'NaN', '-1', True, {}, 'Infinity'):
            bad = model(); bad['pricing']['completion'] = value; cases.append(bad)
        bad = model(); bad['top_provider']['max_completion_tokens'] = None; cases.append(bad)
        for bad in cases:
            with self.subTest(bad=bad):
                result = self.catalog([bad])
                self.assertEqual([], result['models'])
                self.assertTrue(result['excluded'][0]['reasons'])

    def test_zero_price_is_metadata_not_entitlement(self):
        row = model(); row['pricing'] = {'prompt': 0, 'completion': Decimal('0')}
        result = self.catalog([row])['models'][0]
        self.assertEqual('0', result['catalog_usd_per_token']['prompt'])
        self.assertFalse(result['account_access_verified'])

    def test_current_bundled_policy_has_five_reviewed_families(self):
        result, digest = coding_models.load_policy()
        self.assertEqual(5, len({row['family'] for row in result['models']}))
        self.assertEqual(64, len(digest))


class CodingExecutionTests(PolicyFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.money = SpendLedger(self.path.parent / 'quota.db')
        self.money.ledger.complete_setup(services=[], api_services=['openrouter'], source='test')
        self.money.configure('total', '100', mode='observed')
        env = patch.dict(os.environ, {'OPENROUTER_API_KEY': 'fixture-key'})
        env.start(); self.addCleanup(env.stop)
        current = policy()
        today = dt.datetime.now(dt.timezone.utc).date()
        current['models'][0].update(reviewed_at=today.isoformat(), expires_at=(today + dt.timedelta(days=30)).isoformat())
        self.write(current)
        fetch = patch.object(coding_models, 'request_json', return_value={'data': [model()]})
        self.fetch = fetch.start(); self.addCleanup(fetch.stop)

    def run_request(self, **kwargs):
        return api_execution.execute('openrouter', MODEL, 'Review a fixture patch', 100, '0.10',
                                     ledger=self.money, coding_policy=self.path, **kwargs)

    def response(self, model_id=MODEL, cost=ticks('0.01')):
        return dict(output_valid=True, text='fixture response', model=model_id,
                    actual_cost_ticks=cost, response_id='fixture-result')

    def test_model_or_variant_mismatch_hides_output_but_settles_spend(self):
        for index, different in enumerate(('another/model', MODEL + ':free')):
            with patch.object(api_providers, 'execute', return_value=self.response(different)) as post:
                result = self.run_request(request_id='mismatch-' + str(index))
            self.assertEqual('model_mismatch', result['status'])
            self.assertIsNone(result['text'])
            self.assertEqual(ticks('0.01'), result['accounting']['charged_ticks'])
            self.assertEqual(1, post.call_count)

    def test_mismatch_with_unknown_cost_retains_reservation(self):
        with patch.object(api_providers, 'execute', return_value=self.response('another/model', None)):
            result = self.run_request()
        self.assertEqual('model_mismatch', result['status'])
        self.assertEqual('UNRESOLVED', result['accounting']['status'])
        self.assertEqual(ticks('0.10'), self.money.status()['caps'][0]['pending_ticks'])

    def test_success_retains_worker_and_actual_billing_identity(self):
        with patch.object(api_providers, 'execute', return_value=self.response()) as post:
            result = self.run_request()
        self.assertEqual('completed', result['status'])
        self.assertTrue(result['coding']['requires_manager_inspection'])
        self.assertEqual('openrouter', result['coding']['billing_service'])
        body = json.loads(post.call_args.args[0].body)
        self.assertEqual({'include': True}, body['usage'])
        self.assertFalse(body['provider']['allow_fallbacks'])

    def test_network_error_stops_before_reservation_and_post(self):
        self.fetch.side_effect = APIError('api_http_error')
        with patch.object(api_providers, 'execute') as post, self.assertRaises(APIError):
            self.run_request()
        post.assert_not_called()
        self.assertEqual([], self.money.status()['unfinished'])

    def test_valid_key_without_setup_or_money_cannot_dispatch(self):
        self.money.ledger.reset_setup()
        with patch.object(api_providers, 'execute') as post, self.assertRaisesRegex(ValueError, 'setup'):
            self.run_request()
        post.assert_not_called(); self.fetch.assert_not_called()
        self.money.ledger.complete_setup(services=[], api_services=['openrouter'], source='test')
        with self.money.ledger._connect() as db:
            db.execute('DELETE FROM money_caps')
        with patch.object(api_providers, 'execute') as post, self.assertRaisesRegex(ValueError, 'total'):
            self.run_request()
        post.assert_not_called()

    def test_output_limit_loss_blocks_before_dispatch(self):
        row = model(); row['top_provider']['max_completion_tokens'] = 10
        self.fetch.return_value = {'data': [row]}
        with patch.object(api_providers, 'execute') as post, self.assertRaisesRegex(ValueError, 'output_limit'):
            self.run_request()
        post.assert_not_called()

    def test_ordinary_api_run_does_not_depend_on_coding_catalog(self):
        self.fetch.side_effect = AssertionError('unrelated coding catalog')
        with patch.object(api_providers, 'execute', return_value=self.response()):
            result = api_execution.execute('openrouter', MODEL, 'text', 100, '0.10', ledger=self.money)
        self.assertEqual('completed', result['status'])
        self.fetch.assert_not_called()

    def test_duplicate_request_never_repeats_paid_dispatch(self):
        with patch.object(api_providers, 'execute', return_value=self.response()) as post:
            self.assertEqual('completed', self.run_request(request_id='same-request')['status'])
            result = self.run_request(request_id='same-request')
        self.assertEqual('duplicate_accounting_only', result['status'])
        self.assertEqual(1, post.call_count)


if __name__ == '__main__':
    unittest.main()
