"""Decision protocols and billed costs remain independent trust boundaries."""
from contextlib import redirect_stdout
from io import BytesIO, StringIO, TextIOWrapper
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import api_execution
import api_providers
from api_transport import APIError, decode_json
import decisions
from spend import SpendLedger, ticks

MODEL = 'typesafe/jev-1.13'
CANONICAL = MODEL + '-20260917'
CATALOG = {'data': [
    {'id': decisions.LATEST, 'alias_target': {'slug': MODEL}},
    {'id': MODEL, 'canonical_slug': CANONICAL, 'architecture': {'output_modalities': ['decisions']}},
]}
QUESTIONS = {
    'urgent': {'type': 'noul', 'instructions': 'Does this need action now?'},
    'team': {'type': 'choice', 'instructions': 'Which team?', 'criteria': {'billing': None, 'support': 'Other help'}},
    'severity': {'type': 'score', 'instructions': 'How severe?', 'criteria': ['Minor', 'Blocking']},
}
ANSWERS = {
    'urgent': {'type': 'noul', 'noul': 0.9},
    'team': {'type': 'choice', 'choice': 'billing', 'confidence': 0.8,
             'probabilities': {'billing': 0.9, 'support': 0.1}},
    'severity': {'type': 'score', 'score': 0.75, 'confidence': 0.5,
                 'probabilities': {'0': 0.25, '1': 0.75}, 'legend': {'0': 'Minor', '1': 'Blocking'}},
}


class DecisionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.money = SpendLedger(Path(temporary.name) / 'ledger.db')
        self.money.ledger.complete_setup(services=[], api_services=['openrouter'], source='test')
        self.money.configure('total', '5', mode='observed')
        environment = patch.dict(os.environ, {'OPENROUTER_API_KEY': 'fixture-key'})
        environment.start()
        self.addCleanup(environment.stop)
        catalog = patch.object(decisions, 'request_json', return_value=CATALOG)
        self.catalog_request = catalog.start()
        self.addCleanup(catalog.stop)
        post = patch.object(api_providers, 'request_json', side_effect=lambda *a, **k: self.response())
        self.post = post.start()
        self.addCleanup(post.stop)

    def prompt(self, **changes):
        return json.dumps(dict(state='Płatność nie działa', questions=QUESTIONS, **changes))

    def response(self, **changes):
        data = {'id': 'receipt-fixture', 'model': CANONICAL, 'answers': ANSWERS,
                'usage': {'input_tokens': 476, 'output_tokens': 70, 'cost': 0.000019992}}
        data.update(changes)
        return decode_json(json.dumps(data))

    def run_request(self, prompt=None, **kwargs):
        return api_execution.execute('openrouter', None, prompt or self.prompt(), None, '0.01',
                                     ledger=self.money, decision=True, **kwargs)

    def test_mixed_questions_canonical_model_micro_cost_and_unicode(self):
        result = self.run_request()
        self.assertEqual('completed', result['status'])
        self.assertEqual(CANONICAL, result['model'])
        self.assertEqual(MODEL, result['requested_model'])
        self.assertEqual(ANSWERS, result['answers'])
        self.assertEqual(ticks('0.000019992'), result['accounting']['charged_ticks'])
        args, kwargs = self.post.call_args
        self.assertEqual(('https://openrouter.ai', '/api/alpha/decisions', 'POST'), args)
        body = json.loads(kwargs['body'])
        self.assertEqual('Płatność nie działa', body['state'])
        self.assertEqual({'allow_fallbacks': False, 'require_parameters': True}, body['provider'])
        self.assertNotIn('headers', self.catalog_request.call_args.kwargs)
        self.assertNotIn(b'P\xc5\x82atno', self.money.ledger.path.read_bytes())
        self.assertNotIn(b'fixture-key', self.money.ledger.path.read_bytes())

    def test_optional_response_metadata_is_not_synthesized(self):
        answers = {'urgent': {'type': 'noul', 'noul': 1}, 'team': {'type': 'choice', 'choice': 'support'},
                   'severity': {'type': 'score', 'score': 0.4}}
        self.post.side_effect = lambda *a, **k: self.response(answers=answers)
        self.assertEqual(answers, self.run_request()['answers'])

    def test_input_numbers_preserve_precision(self):
        number = '0.12345678901234567890123456789'
        prompt = '{"state":{"value":' + number + '},"questions":' + json.dumps(QUESTIONS) + '}'
        self.assertEqual('completed', self.run_request(prompt.encode())['status'])
        body = self.post.call_args.kwargs['body']
        self.assertIn(number.encode(), body)
        self.assertEqual(decode_json(prompt)['state'], decode_json(body)['state'])

    def test_malformed_required_usage_still_settles_cost(self):
        self.post.side_effect = lambda *a, **k: self.response(usage={'input_tokens': True, 'cost': 0.001})
        result = self.run_request()
        self.assertEqual('output_rejected', result['status'])
        self.assertEqual('SETTLED', result['accounting']['status'])
        self.assertEqual(ticks('0.001'), result['accounting']['charged_ticks'])

    def test_invalid_or_extra_answers_still_settle_actual_cost(self):
        for answers in [[], {}, {**ANSWERS, 'extra': {'type': 'noul', 'noul': 1}},
                        {**ANSWERS, 'urgent': {'type': 'noul', 'noul': True}},
                        {**ANSWERS, 'team': {'type': 'choice', 'choice': 'unknown'}},
                        {**ANSWERS, 'severity': {'type': 'score', 'score': 2}},
                        {**ANSWERS, 'severity': {'type': 'score', 'score': 0, 'confidence': -1}},
                        {**ANSWERS, 'severity': {'type': 'score', 'score': 0, 'legend': {'0': 'Wrong'}}}]:
            with self.subTest(answers=answers):
                self.post.side_effect = lambda *a, **k: self.response(answers=answers)
                result = self.run_request()
                self.assertEqual('output_rejected', result['status'])
                self.assertIsNone(result['answers'])
                self.assertEqual('SETTLED', result['accounting']['status'])

    def test_probability_tolerance_and_exact_keys(self):
        for distribution, valid in [({'billing': 0.5, 'support': 0.4995}, True),
                                    ({'billing': 0.5, 'support': 0.49}, False),
                                    ({'billing': 1}, False), ({'billing': 2, 'support': -1}, False)]:
            answers = {**ANSWERS, 'team': {**ANSWERS['team'], 'probabilities': distribution}}
            self.post.side_effect = lambda *a, **k: self.response(answers=answers)
            self.assertEqual('completed' if valid else 'output_rejected', self.run_request()['status'])

    def test_wrong_model_is_billed_but_not_exposed(self):
        self.post.side_effect = lambda *a, **k: self.response(model='typesafe/jev-unknown')
        result = self.run_request()
        self.assertEqual('output_rejected', result['status'])
        self.assertIsNone(result['answers'])
        self.assertEqual('SETTLED', result['accounting']['status'])

    def test_missing_cost_and_transport_failure_retain_liability(self):
        self.post.side_effect = lambda *a, **k: self.response(usage={'input_tokens': 1, 'output_tokens': 1})
        result = self.run_request()
        self.assertEqual('UNRESOLVED', result['accounting']['status'])
        self.assertIsNone(result['answers'])
        for error in [TimeoutError('secret'), APIError('api_http_error', 404), APIError('api_http_error', 502)]:
            self.post.reset_mock()
            self.post.side_effect = error
            result = self.run_request()
            self.assertEqual('unresolved_dispatch', result['status'])
            self.assertEqual('UNRESOLVED', result['accounting']['status'])
            self.assertEqual(1, self.post.call_count)
            self.assertNotIn('secret', str(result))

    def test_invalid_cost_never_settles_and_verified_zero_is_preserved(self):
        for cost in [True, -1, '0.1']:
            self.post.side_effect = lambda *a, **k: self.response(usage={'input_tokens': 1, 'output_tokens': 1, 'cost': cost})
            result = self.run_request()
            self.assertEqual('UNRESOLVED', result['accounting']['status'])
        self.post.side_effect = lambda *a, **k: self.response(usage={'input_tokens': 1, 'output_tokens': 1, 'cost': 0})
        self.assertEqual(0, self.run_request()['accounting']['charged_ticks'])

    def test_duplicate_id_never_redispatches(self):
        self.run_request(request_id='once')
        self.assertEqual('duplicate_accounting_only', self.run_request(request_id='once')['status'])
        self.assertEqual(1, self.post.call_count)

    def test_bad_inputs_do_not_reserve_or_post(self):
        for prompt in ['null', '42', '[]', '"text"', '{"state":"a","state":"b","questions":{}}',
                       '{"state":"a","questions":{"x":{"type":"noul","type":"choice"}}}',
                       '{"state":NaN,"questions":{}}', self.prompt(extra='unsupported'),
                       json.dumps({'state': 'x', 'questions': {'': QUESTIONS['urgent']}}),
                       json.dumps({'state': 'x', 'questions': {'x': {'type': 'score', 'instructions': 'Rate', 'criteria': ['One']}}}),
                       json.dumps({'state': 'x' * 30000, 'questions': QUESTIONS})]:
            with self.subTest(prompt=prompt[:80]), self.assertRaises(ValueError):
                self.run_request(prompt)
        self.post.assert_not_called()
        self.assertEqual([], self.money.status()['unfinished'])

    def test_catalog_failure_precedes_reservation(self):
        for data in [{'data': []}, {'data': [CATALOG['data'][0]]},
                     {'data': [{**CATALOG['data'][1], 'canonical_slug': None}]}]:
            self.catalog_request.return_value = data
            with self.assertRaises(ValueError):
                self.run_request()
        self.catalog_request.side_effect = APIError('api_timeout')
        with self.assertRaises(ValueError):
            self.run_request()
        self.post.assert_not_called()
        self.assertEqual([], self.money.status()['unfinished'])

    def test_missing_alias_requires_explicit_model(self):
        self.catalog_request.return_value = {'data': [CATALOG['data'][1]]}
        with self.assertRaisesRegex(ValueError, 'pass_explicit_model'):
            self.run_request()
        result = api_execution.execute('openrouter', MODEL, self.prompt(), None, '0.01', ledger=self.money, decision=True)
        self.assertEqual('completed', result['status'])

    def test_setup_key_authority_and_money_gates_precede_post(self):
        with patch.dict(os.environ, OPENROUTER_API_KEY=''), self.assertRaises(ValueError):
            self.run_request()
        import coordination
        with patch.object(coordination, 'settings', return_value={'authority': 'remote'}), self.assertRaises(ValueError):
            self.run_request()
        self.money.configure('total', '0', mode='observed')
        with self.assertRaises(ValueError):
            self.run_request()
        self.money.ledger.complete_setup(services=['codex'], api_services=[], source='test')
        with self.assertRaises(ValueError):
            self.run_request()
        self.post.assert_not_called()

    def test_overrun_is_recorded_in_full_and_latches(self):
        self.post.side_effect = lambda *a, **k: self.response(usage={'input_tokens': 1, 'output_tokens': 1, 'cost': 0.02})
        result = self.run_request()
        self.assertEqual(ticks('0.02'), result['accounting']['charged_ticks'])
        with self.assertRaisesRegex(ValueError, 'overrun'):
            self.run_request()

    def test_direct_unadmitted_execution_and_text_route_rejected(self):
        prepared = decisions.preflight('openrouter', MODEL, self.prompt(), None)
        with self.assertRaisesRegex(ValueError, 'monetary_admission_required'):
            api_providers.execute(prepared)
        with self.assertRaisesRegex(ValueError, 'use_api_decide'):
            api_providers.preflight('openrouter', MODEL, 'classify', 10)
        self.post.assert_not_called()

    def test_cli_emits_valid_json(self):
        output = StringIO()
        with patch('sys.stdin', TextIOWrapper(BytesIO(self.prompt().encode()))), redirect_stdout(output):
            code = api_execution.main(['--db', str(self.money.ledger.path), 'decide', 'openrouter', '--reserve-cost', '0.01'])
        self.assertEqual(0, code)
        self.assertEqual(0.75, json.loads(output.getvalue())['answers']['severity']['score'])


if __name__ == '__main__':
    unittest.main()
