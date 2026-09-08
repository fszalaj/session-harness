import json
from pathlib import Path
import unittest
from unittest.mock import patch

import claude_models


def event(models=None):
    return {'type': 'control_response', 'response': {'subtype': 'success', 'request_id': 'match',
            'response': {'models': models if models is not None else [{'value': 'opus[1m]',
                'supportedEffortLevels': ['low', 'high'], 'supportsEffort': True}],
                         'account': 'private', 'agents': ['private']}}}


class ClaudeModelsTests(unittest.TestCase):
    def test_safe_models_unresolved_and_private_fields_removed(self):
        models = claude_models.parse_initialize(json.dumps(event()), 'match')
        self.assertEqual(models[0]['id'], 'opus[1m]')
        self.assertEqual(models[0]['alias_resolution'], 'unresolved')
        self.assertIsNone(models[0]['account_visible'])
        self.assertFalse(models[0]['entitlement_verified'])
        self.assertNotIn('private', json.dumps(models))

    def test_reject_unexpected_duplicate_and_error_events(self):
        good = json.dumps(event())
        for text in [good + '\n' + good, good + '\n' + '{"type":"assistant"}',
                     good + '\n' + '{"type":"result"}', '{}', '[]', '',
                     good.replace('success', 'error'), good.replace('match', 'wrong'),
                     good.replace('"type":', '"type":"assistant","type":')]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                claude_models.parse_initialize(text, 'match')

    def test_current_alias_resolution_is_allowlisted_without_entitlement_claim(self):
        row = {'value': 'sonnet', 'resolvedModel': 'claude-sonnet-99-2', 'description': 'private'}
        model = claude_models.parse_initialize(json.dumps(event([row])), 'match')[0]
        self.assertEqual(model['resolved_model'], 'claude-sonnet-99-2')
        self.assertEqual(model['alias_resolution'], 'client_initialize')
        self.assertFalse(model['entitlement_verified'])
        self.assertNotIn('private', json.dumps(model))

    def test_resolution_rejects_malformed_cross_tier_and_concrete_drift(self):
        for alias, resolved in [('opus', 5), ('opus', '../private'), ('opus', 'sonnet'),
                                ('opus', 'claude-sonnet-99'),
                                ('claude-fable-99-1[1m]', 'claude-fable-99-2'),
                                ('opus', 'claude-opus-20260908'),
                                ('haiku', 'claude-haiku-99-20261301')]:
            with self.subTest(alias=alias, resolved=resolved), self.assertRaises(ValueError):
                claude_models.resolved_model(alias, resolved)
        self.assertEqual(claude_models.resolved_model('haiku', 'claude-haiku-99-20260908'),
                         'claude-haiku-99-20260908')
        self.assertIsNone(claude_models.resolved_model('future', 'claude-unknown-99'))
        self.assertEqual(claude_models.resolved_model('claude-opus', 'claude-opus-99'), 'claude-opus-99')
        self.assertEqual(claude_models.resolved_model('claude-sonnet-99', 'claude-sonnet-99-20260908'),
                         'claude-sonnet-99-20260908')

    def test_narrow_identifier_and_capabilities(self):
        for row in [{'value': 'opus[2m]'}, {'value': 'opus[1m]evil'}, {'value': '../bad value'},
                    {'value': 'sonnet', 'supportsEffort': 'true'},
                    {'value': 'sonnet', 'supportedEffortLevels': ['invented']}]:
            with self.subTest(row=row), self.assertRaises(ValueError):
                claude_models.parse_initialize(json.dumps(event([row])), 'match')

    def test_literal_auth_and_single_owned_initialize(self):
        with patch('claude_models.harness.run') as run:
            for auth in [None, False, 1, 'true']:
                self.assertEqual(claude_models.discover('/mock/claude', auth)['status'], 'auth_unverified')
            run.assert_not_called()
        def probe(argv, **kwargs):
            request = json.loads(kwargs['stdin'])
            self.assertEqual(request['request'], {'subtype': 'initialize'})
            self.assertEqual(kwargs['timeout'], 15)
            self.assertTrue(Path(kwargs['cwd']).is_dir())
            self.assertIn('--no-chrome', argv)
            self.assertEqual(argv[argv.index('--tools') + 1], '')
            response = event()
            response['response']['request_id'] = request['request_id']
            return 0, json.dumps(response), 'private diagnostics'
        with patch('claude_models.harness.run', side_effect=probe) as run:
            result = claude_models.discover('/mock/claude', True)
        self.assertEqual(run.call_count, 1)
        self.assertTrue(result['models'][0]['account_selectable'])
        self.assertNotIn('private', json.dumps(result))
        self.assertFalse(Path(run.call_args.kwargs['cwd']).exists())

if __name__ == '__main__':
    unittest.main()
