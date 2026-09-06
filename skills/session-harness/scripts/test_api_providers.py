"""Synthetic provider contracts; no API credentials or paid inference."""
from decimal import Decimal, localcontext
import json
import os
import unittest
from unittest.mock import patch

import api_providers as api
from api_transport import APIError, decode_json


def chat(**changes):
    data = {'id': 'request-test', 'model': 'future-model', 'choices': [{'finish_reason': 'stop',
            'message': {'role': 'assistant', 'content': 'Review result'}}],
            'usage': {'prompt_tokens': 20, 'completion_tokens': 10, 'total_tokens': 30}}
    data.update(changes)
    return data


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {row[2]: 'test-private-key' for row in api.SERVICES.values()}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_all_routes_preflight_without_network_or_model_defaults(self):
        with patch('api_providers.request_json') as network:
            for service in api.SERVICES:
                with self.subTest(service=service):
                    prepared = api.preflight(service, 'future-model', b'Review this.', 100)
                    body = json.loads(prepared.body)
                    self.assertEqual(prepared.service, service)
                    self.assertNotIn('test-private-key', repr(prepared))
                    self.assertNotIn('Review this.', repr(prepared))
                    self.assertNotIn('tools', body)
                    self.assertNotIn('thinking', body)
                    if service == 'gemini':
                        self.assertEqual(body['generationConfig'], {'maxOutputTokens': 100, 'candidateCount': 1})
                        self.assertEqual(prepared.headers['x-goog-api-key'], 'test-private-key')
                        self.assertNotIn('key=', prepared.path)
                    elif service == 'anthropic':
                        self.assertEqual(body['max_tokens'], 100)
                        self.assertEqual(prepared.path, '/v1/messages')
                    else:
                        limit = 'max_completion_tokens' if service in {'openai', 'kimi'} else 'max_tokens'
                        self.assertEqual(body[limit], 100)
                        self.assertIs(body['stream'], False)
            network.assert_not_called()
        opened = json.loads(api.preflight('openrouter', 'vendor/model', 'text', 10).body)
        self.assertEqual(opened['usage'], {'include': True})
        self.assertEqual(opened['provider'], {'allow_fallbacks': False, 'require_parameters': True})

    def test_preflight_rejects_bad_key_model_input_limit_effort_locally(self):
        with patch('api_providers.request_json') as network:
            for key in ('', ' ', 'bad\r\nheader', 'bad\x00key', 'bad key', 'unicode-ą'):
                with patch('api_providers.os.environ', {'OPENAI_API_KEY': key}), self.assertRaises(APIError):
                    api.preflight('openai', 'model', 'text', 10)
            for model in ('', '../model', 'a/../model', 'a//b', 'bad?key=x', 'a\nsecret'):
                with self.assertRaises(APIError):
                    api.preflight('openai', model, 'text', 10)
            for limit in (0, -1, True, 1.5, api.MAX_TOKENS + 1):
                with self.assertRaises(APIError):
                    api.preflight('openai', 'model', 'text', limit)
            for prompt in ('', b'\xff', {'tools': []}, '\udfff'):
                with self.assertRaises(APIError):
                    api.preflight('openai', 'model', prompt, 10)
            with self.assertRaises(APIError):
                api.preflight('openai', 'model', 'text', 10, effort='max')
            with self.assertRaises(APIError):
                api.preflight('zai-coding', 'model', 'text', 10)
            network.assert_not_called()

    def test_digest_binds_payload_route_model_and_output_limit_not_key(self):
        original = api.preflight('openai', 'model', 'text', 10)
        for service, model, text, limit in [('xai', 'model', 'text', 10), ('openai', 'other', 'text', 10),
                                             ('openai', 'model', 'different', 10), ('openai', 'model', 'text', 11)]:
            self.assertNotEqual(original.digest, api.preflight(service, model, text, limit).digest)
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'another-test-key'}):
            self.assertEqual(original.digest, api.preflight('openai', 'model', 'text', 10).digest)

    def test_openai_reasoning_already_in_output_cache_disjoint(self):
        data = chat()
        data['usage'].update(prompt_tokens_details={'cached_tokens': 5},
                             completion_tokens_details={'reasoning_tokens': 7})
        result = api.normalize_response('openai', data)
        self.assertTrue(result['output_valid'])
        self.assertTrue(result['usage_complete'])
        self.assertEqual(result['usage'], {'input_tokens': 15, 'cache_read_tokens': 5, 'output_tokens': 10})
        self.assertIsNone(result['actual_cost_ticks'])

    def test_deepseek_cache_miss_parity(self):
        data = chat()
        data['usage'].update(prompt_cache_hit_tokens=4, prompt_cache_miss_tokens=16)
        self.assertEqual(api.normalize_response('deepseek', data)['usage']['input_tokens'], 16)
        data['usage']['prompt_cache_miss_tokens'] = 20
        self.assertFalse(api.normalize_response('deepseek', data)['usage_complete'])

    def test_anthropic_cache_tiers_are_disjoint(self):
        data = {'id': 'msg-test', 'model': 'future-claude', 'type': 'message', 'role': 'assistant',
                'content': [{'type': 'text', 'text': 'Answer'}], 'stop_reason': 'end_turn',
                'usage': {'input_tokens': 10, 'output_tokens': 3, 'cache_read_input_tokens': 20,
                          'cache_creation_input_tokens': 40, 'cache_creation': {
                              'ephemeral_5m_input_tokens': 15, 'ephemeral_1h_input_tokens': 25}}}
        result = api.normalize_response('anthropic', data)
        self.assertTrue(result['output_valid'])
        self.assertEqual(result['usage'], {'input_tokens': 10, 'output_tokens': 3, 'cache_read_tokens': 20,
                                           'cache_write_5m_tokens': 15, 'cache_write_1h_tokens': 25})
        data['content'] = [{'type': 'tool_use', 'id': 'secret', 'name': 'shell', 'input': {}}]
        self.assertFalse(api.normalize_response('anthropic', data)['output_valid'])

    def test_gemini_additional_thought_tokens_and_text_only(self):
        data = {'responseId': 'response-test', 'modelVersion': 'future-gemini',
                'candidates': [{'finishReason': 'STOP', 'content': {'role': 'model',
                    'parts': [{'text': 'private reasoning', 'thought': True}, {'text': 'Answer'}]}}],
                'usageMetadata': {'promptTokenCount': 20, 'cachedContentTokenCount': 5,
                                  'candidatesTokenCount': 10, 'thoughtsTokenCount': 7, 'totalTokenCount': 37}}
        result = api.normalize_response('gemini', data)
        self.assertEqual(result['text'], 'Answer')
        self.assertNotIn('private reasoning', json.dumps(result))
        self.assertEqual(result['usage'], {'input_tokens': 15, 'cache_read_tokens': 5,
                                          'output_tokens': 10, 'reasoning_tokens': 7})
        data['usageMetadata']['totalTokenCount'] = 30
        self.assertFalse(api.normalize_response('gemini', data)['usage_complete'])
        data['candidates'][0]['content']['parts'] = [{'functionCall': {'name': 'shell'}}]
        self.assertFalse(api.normalize_response('gemini', data)['output_valid'])

    def test_exact_cost_decimal_rounds_up_and_preserves_receipt_on_tools(self):
        data = decode_json(json.dumps(chat()).replace('"total_tokens": 30', '"total_tokens": 30, "cost": 0.00000000011'))
        result = api.normalize_response('openrouter', data)
        self.assertEqual(result['actual_cost_ticks'], 2)
        data['usage']['cost_in_usd_ticks'] = 123456789012345
        data['choices'][0]['message']['tool_calls'] = [{'function': {'name': 'private-tool'}}]
        result = api.normalize_response('xai', data)
        self.assertFalse(result['output_valid'])
        self.assertEqual(result['actual_cost_ticks'], 123456789012345)
        self.assertNotIn('private-tool', json.dumps(result))

    def test_invalid_cost_never_becomes_zero(self):
        for value in (True, -1, float('nan'), float('inf'), 0.1, '0.2', Decimal('Infinity'), Decimal('1e30')):
            with self.subTest(value=value), self.assertRaises(APIError):
                api.cost_ticks('openrouter', {'cost': value})
        self.assertIsNone(api.cost_ticks('openrouter', {}))
        self.assertEqual(api.cost_ticks('openrouter', {'cost': Decimal(0)}), 0)

    def test_unknown_billed_class_and_malformed_usage_retain_unresolved(self):
        for usage in [None, {}, {'prompt_tokens': True, 'completion_tokens': 0, 'total_tokens': 1},
                      dict(chat()['usage'], unknown_billable_tokens=50),
                      dict(chat()['usage'], prompt_tokens_details={'audio_tokens': 4})]:
            result = api.normalize_response('openai', chat(usage=usage))
            self.assertFalse(result['usage_complete'])
            self.assertIsNone(result['actual_cost_ticks'])
        data = chat()
        data['usage'].update(cost=Decimal('0.25'), unknown_billable_tokens=50)
        result = api.normalize_response('openrouter', data)
        self.assertFalse(result['usage_complete'])
        self.assertEqual(result['actual_cost_ticks'], 2_500_000_000)

    def test_multiple_candidates_or_private_error_are_not_results(self):
        data = chat()
        data['choices'] *= 2
        self.assertFalse(api.normalize_response('openai', data)['output_valid'])
        with self.assertRaises(APIError) as failure:
            api.normalize_response('openai', {'error': {'message': 'private-key'}})
        self.assertNotIn('private', str(failure.exception))

    def test_execution_uses_prepared_request_once(self):
        prepared = api.preflight('kimi', 'future-model', 'text', 100)
        with patch('api_providers.request_json', return_value=chat()) as request:
            result = api.execute(prepared, timeout=12)
        self.assertTrue(result['output_valid'])
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.kwargs['timeout'], 12)
        self.assertEqual(request.call_args.kwargs['body'], prepared.body)

    def test_model_catalog_no_versions_and_zai_no_fake_endpoint(self):
        with patch('api_providers.request_json') as request:
            self.assertEqual(api.models('zai')['status'], 'catalog_unavailable')
            request.assert_not_called()
        with patch('api_providers.request_json', return_value={'data': [{'id': 'future-grok', 'private': 'secret'}]}):
            result = api.models('xai')
        self.assertTrue(result['models'][0]['account_visible'])
        self.assertFalse(result['models'][0]['entitlement_verified'])
        self.assertNotIn('secret', json.dumps(result))

    def test_catalog_pagination_and_gemini_header_auth(self):
        pages = [{'models': [{'name': 'models/future-one', 'supportedGenerationMethods': ['generateContent']}],
                  'nextPageToken': 'opaque-token'},
                 {'models': [{'name': 'models/future-two', 'supportedGenerationMethods': ['embedContent']}]}]
        with patch('api_providers.request_json', side_effect=pages) as request:
            result = api.models('gemini')
        self.assertEqual(len(result['models']), 2)
        self.assertIn('pageToken=opaque-token', request.call_args.args[1])
        self.assertNotIn('key=', request.call_args.args[1])
        self.assertFalse(result['models'][1]['text_generation_supported'])

    def test_duplicate_catalog_and_pagination_fail(self):
        with patch('api_providers.request_json', return_value={'data': [{'id': 'model'}, {'id': 'model'}]}), self.assertRaises(APIError):
            api.models('openai')
        with patch('api_providers.request_json', return_value={'models': [], 'nextPageToken': 'repeat'}), self.assertRaises(APIError):
            api.models('gemini')


    def test_unknown_service_tiers_and_conflicting_cache_are_unresolved(self):
        data = chat(service_tier='priority')
        self.assertFalse(api.normalize_response('openai', data)['usage_complete'])
        data = chat()
        data['usage'].update(prompt_cache_hit_tokens=5, prompt_tokens_details={'cached_tokens': 8})
        self.assertFalse(api.normalize_response('deepseek', data)['usage_complete'])

    def test_response_id_is_opaque_not_a_model_identifier(self):
        result = api.normalize_response('openai', chat(id='_opaque-base64=='))
        self.assertTrue(result['output_valid'])
        self.assertEqual(result['response_id'], '_opaque-base64==')

    def test_anthropic_empty_tool_meter_is_zero_not_a_tool_execution(self):
        data = {'id': 'msg-test', 'model': 'future-claude', 'type': 'message', 'role': 'assistant',
                'content': [{'type': 'text', 'text': 'Answer'}], 'stop_reason': 'end_turn',
                'usage': {'input_tokens': 10, 'output_tokens': 3,
                          'server_tool_use': {'web_search_requests': 0, 'web_fetch_requests': 0}}}
        self.assertTrue(api.normalize_response('anthropic', data)['usage_complete'])
        data['usage']['server_tool_use']['web_search_requests'] = 1
        self.assertFalse(api.normalize_response('anthropic', data)['usage_complete'])


    def test_arbitrary_decimal_context_cannot_drop_positive_cost_tail(self):
        for precision in (2, 10, 28):
            with localcontext() as context:
                context.prec = precision
                cost = Decimal('1.' + '0' * 100 + '1')
                self.assertEqual(api.cost_ticks('openrouter', {'cost': cost}), 10_000_000_001)
                self.assertEqual(api.cost_ticks('xai', {'cost_in_usd_ticks': cost}), 2)
                self.assertEqual(api.cost_ticks('openrouter', {'cost': Decimal('1e-1000000')}), 1)
        with self.assertRaises(APIError):
            api.cost_ticks('openrouter', {'cost': Decimal('1.' + '0' * 256 + '1')})


if __name__ == '__main__':
    unittest.main()
