import copy
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


    def aliases(self):
        rows = [{'value': alias, 'resolvedModel': 'claude-opus-99[1m]',
                 'supportedEffortLevels': ['low', 'medium', 'high'], 'supportsEffort': True}
                for alias in ('default', 'opus[1m]')]
        return [dict(row, account_selectable=True, efforts=list(row['native_controls']['reasoning_efforts']))
                for row in claude_models.parse_initialize(json.dumps(event(rows)), 'match')]

    def test_equivalent_aliases_preserve_concrete_identity_and_effort(self):
        entries = self.aliases()
        original = copy.deepcopy(entries)
        self.assertTrue(claude_models.equivalent_review_aliases(entries, 'claude-opus-99[1m]'))
        self.assertEqual(entries, original)
        entries[1]['efforts'].reverse()
        entries[1]['native_controls']['reasoning_efforts'].reverse()
        self.assertTrue(claude_models.equivalent_review_aliases(entries, 'claude-opus-99[1m]'))
        self.assertFalse(claude_models.equivalent_review_aliases(entries, 'claude-opus-99'))

    def test_conflicting_or_unverified_aliases_remain_ambiguous(self):
        changes = [{'id': 'default'}, {'id': 'sonnet'}, {'id': '../invalid'},
                   {'resolved_model': 'claude-opus-98[1m]'},
                   {'resolved_model': 'claude-opus-99'}, {'account_selectable': 1},
                   {'account_selectable': False}, {'alias_resolution': 'unresolved'},
                   {'resolution_source': 'config'}, {'variants': {}},
                   {'efforts': ['high']}, {'efforts': []}, {'efforts': ['medium', 'medium']},
                   {'efforts': [None]}, {'native_controls': {}},
                   {'native_controls': {'reasoning_efforts': ['low', 'medium', 'high'],
                                        'supportsEffort': False}},
                   {'native_controls': {'reasoning_efforts': ['low', 'medium', 'high'],
                                        'supportsEffort': True, 'supportsFastMode': True}},
                   {'native_controls': {'reasoning_efforts': ['low', 'medium', 'high', 'high']}}]
        for change in changes:
            entries = self.aliases()
            entries[1].update(change)
            with self.subTest(change=change):
                self.assertFalse(claude_models.equivalent_review_aliases(entries, 'claude-opus-99[1m]'))
        for missing in ('efforts', 'native_controls', 'account_selectable', 'resolution_source'):
            entries = self.aliases()
            del entries[1][missing]
            self.assertFalse(claude_models.equivalent_review_aliases(entries, 'claude-opus-99[1m]'))

    def test_scope_selection_and_catalog_order_keep_the_same_review_model(self):
        import harness
        from test_claude_admission import receipt
        selected, primary = 'claude-opus-99[1m]', 'claude-fable-99-1'
        for reverse in (False, True):
            entries = self.aliases()[::(-1 if reverse else 1)]
            capability = {'review': {'status': 'available'}, 'auth': {'status': 'subscription'},
                          'planner': {'model': primary, 'effort': 'xhigh'}, 'models': entries,
                          'model_scoped_admission_supported': True, 'executable': 'mock-claude'}
            with patch('coordination.dispatch', side_effect=lambda action, service, owner, models:
                       receipt(models[0], models[0] == selected)) as check, \
                    patch.object(harness, 'require_role', return_value={}), \
                    patch.object(harness, 'checked', return_value='fixture') as execute, \
                    patch.object(harness, 'validate_claude_review',
                                 return_value={'result': 'approve', 'actual_model': selected}):
                result = harness.review('claude', b'plan', 30, capability, 'medium')
            self.assertEqual([call.kwargs['models'] for call in check.call_args_list], [[primary], [selected]])
            self.assertEqual(result['requested_model'], selected)
            self.assertEqual(result['requested_effort'], 'medium')
            self.assertEqual(execute.call_args.kwargs['quota_models'], [selected])

    def test_scoped_review_accepts_aliases_without_bypassing_admission(self):
        import harness
        import supervision
        selected = 'claude-opus-99[1m]'
        capability = {'review': {'status': 'available'}, 'auth': {'status': 'subscription'},
                      'planner': {'model': selected, 'effort': 'xhigh'},
                      'models': self.aliases(), 'model_scoped_admission_supported': True,
                      'executable': 'mock-claude'}
        stream = '\n'.join(json.dumps(row) for row in [
            {'type': 'system', 'subtype': 'init', 'model': 'claude-opus-99',
             'tools': [], 'mcp_servers': []},
            {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'approve'}])
        with patch('claude_admission.choose', return_value=(capability['planner'], {})) as admission, \
                patch.object(harness, 'require_role', return_value={}) as role, \
                patch.object(harness, 'checked', return_value=stream) as execute:
            result = harness.review('claude', b'plan', 30, capability, 'medium')
        admission.assert_called_once_with(capability, 'planner')
        self.assertEqual(execute.call_args.kwargs['quota_models'], [selected])
        self.assertEqual(execute.call_args.kwargs['quota_service'], 'claude')
        self.assertEqual(execute.call_args.args[0][execute.call_args.args[0].index('--model') + 1], selected)
        self.assertEqual(result['requested_model'], selected)
        self.assertEqual(result['requested_effort'], 'medium')
        self.assertEqual(result['actual_model'], 'claude-opus-99')
        self.assertTrue(result['independent_judgment'])
        self.assertEqual(capability['planner']['effort'], 'xhigh')
        role.assert_any_call('claude', selected, 'reviewer', supervised=False)
        with patch('claude_admission.choose', side_effect=supervision.Stop('claude', ['daily_limit'])), \
                patch.object(harness, 'checked') as execute, self.assertRaises(supervision.Stop):
            harness.review('claude', b'plan', 30, capability, 'medium')
        execute.assert_not_called()
        capability['models'][1]['efforts'] = ['high']
        with patch('claude_admission.choose', return_value=(capability['planner'], {})), \
                patch.object(harness, 'checked') as execute, self.assertRaises(harness.HarnessError):
            harness.review('claude', b'plan', 30, capability, 'medium')
        execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
