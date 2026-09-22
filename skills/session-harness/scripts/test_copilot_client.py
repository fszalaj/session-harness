"""Copilot task receipts need verified text, model and finite-pool consumption."""
import copy
import io
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

import copilot_client as copilot
import harness
import inventory
import usage
import balance
from quota import Ledger


def quota(used=2):
    row = {'entitlementRequests': 200, 'usedRequests': used, 'remainingPercentage': 100 - used / 2,
           'resetDate': '2026-10-01T00:00:00Z', 'hasQuota': True, 'tokenBasedBilling': True,
           'usageAllowedWithExhaustedQuota': False, 'overageAllowedWithExhaustedQuota': False}
    return {'quotaSnapshots': {'chat': row, 'premium_interactions': {
        **row, 'hasQuota': False, 'entitlementRequests': 0, 'usedRequests': 0, 'remainingPercentage': 0}}}


def paid_quota(used=2):
    row = quota(used)['quotaSnapshots']['chat']
    unlimited = {**row, 'isUnlimitedEntitlement': True, 'entitlementRequests': 0,
                 'usedRequests': 0, 'remainingPercentage': 100}
    return {'quotaSnapshots': {'chat': unlimited, 'completions': dict(unlimited),
                              'premium_interactions': dict(row)}}


class CopilotTests(unittest.TestCase):
    def named_capability(self, model='claude-99.1'):
        return {'executable': 'copilot', 'auth': {'status': 'subscription'},
                'review': {'status': 'supervised_only'},
                'models': inventory.normalize_models({'models': [{'id': model,
                    'supportedReasoningEfforts': ['low', 'medium', 'high']}]}, 'copilot', True)}

    def test_named_selection_requires_catalog_effort_policy_and_other_family(self):
        capability = self.named_capability()
        selected = copilot.select_model(capability, 'claude-99.1', role='reviewer', manager_family='openai')
        self.assertEqual(selected['planner']['effort'], 'high')
        self.assertEqual(selected['review']['status'], 'available')
        pending = dict(capability, status='model_selection_required')
        self.assertEqual(copilot.select_model(pending, 'claude-99.1')['status'], 'available')
        for model, effort, family in [('missing', None, 'openai'), ('claude-99.1', 'max', 'openai'),
                                     ('claude-99.1', None, 'anthropic'), ('claude-99.1', None, None)]:
            with self.assertRaises(harness.HarnessError):
                copilot.select_model(capability, model, effort, role='reviewer', manager_family=family)
        for model in ('auto', 'opaque-model'):
            with self.assertRaises(harness.HarnessError):
                copilot.select_model(self.named_capability(model), model, role='reviewer', manager_family='openai')
        capability['models'][0]['policy_state'] = 'disabled'
        with self.assertRaises(harness.HarnessError):
            copilot.select_model(capability, 'claude-99.1')
        self.assertEqual(inventory.normalize_models({'models': [{'id': 'claude-99.1',
                         'policy': {'state': 'disabled'}}]}, 'copilot', True)[0]['policy_state'], 'disabled')

    def test_no_named_default_requires_selection_without_invoking_execution(self):
        data = self.named_capability()
        data['models'] += self.named_capability('gemini-99.1')['models']
        with patch.object(inventory, 'discover_copilot', return_value=dict(data, authenticated=True)):
            capability = copilot.discover('copilot')
        self.assertEqual(capability['status'], 'model_selection_required')
        with patch.object(copilot, 'execute') as execute:
            with self.assertRaises(harness.HarnessError) as error:
                harness.review('copilot', b'Artifact', 30, capability, 'high')
            self.assertEqual(error.exception.status, 'unsupported_capability')
            execute.assert_not_called()

    def test_named_review_uses_fresh_catalog_exact_identity_and_existing_role_gates(self):
        for scenario in ('success', 'mismatch', 'catalog-removed', 'effort-removed', 'deferred', 'wrong-effort'):
            with self.subTest(scenario=scenario):
                client = MagicMock()
                def rpc(method, params=None):
                    if method == 'account.getQuota':
                        return quota()
                    if method == 'session.model.list':
                        return {'list': [] if scenario == 'catalog-removed' else [{'id': 'claude-99.1',
                            'model_picker_enabled': True, 'capabilities': {'supports': {
                            'reasoning_effort': [] if scenario == 'effort-removed' else ['high']}}}]}
                    if method == 'session.create':
                        self.assertEqual(params['model'], 'auto')
                        self.assertNotIn('reasoningEffort', params)
                        self.assertEqual(params['availableTools'], [])
                        self.assertEqual(params['excludedTools'], ['*'])
                        self.assertEqual(params['mcpServers'], {})
                        for control in ('enableConfigDiscovery', 'enableSkills', 'enableFileHooks',
                                        'enableHostGitOperations', 'enableSessionStore', 'enableOnDemandInstructionDiscovery'):
                            self.assertFalse(params[control])
                        self.assertIn('independent leaf reviewer', params['systemMessage']['content'])
                        return {'sessionId': 'fixture'}
                    if method == 'session.model.switchTo':
                        self.assertEqual(params, {'sessionId': 'fixture', 'modelId': 'claude-99.1',
                                                 'requireAvailable': True, 'reasoningEffort': 'high'})
                        return {'status': 'applied', 'deferred': scenario == 'deferred', 'modelId': 'claude-99.1'}
                    if method == 'session.model.getCurrent':
                        return {'modelId': 'claude-99.1', 'reasoningEffort': 'low' if scenario == 'wrong-effort' else 'high'}
                    if method == 'session.send':
                        for kind, data in [('assistant.message', {'content': 'Approve with checks.'}),
                                           ('assistant.usage', {'model': 'gemini-99.1' if scenario == 'mismatch' else 'claude-99.1',
                                                                'inputTokens': 20, 'outputTokens': 10}), ('session.idle', {})]:
                            client.on_message({'method': 'session.event', 'params': {'sessionId': 'fixture',
                                               'event': {'type': kind, 'data': data}}})
                    return {}
                client.request.side_effect = client._request.side_effect = rpc
                with patch.object(inventory, 'MetadataRPC', return_value=client), patch('supervision.Watch') as watch, \
                     patch.object(harness, 'require_quota') as admission, \
                     patch.object(harness, 'require_role', return_value={}) as role:
                    if scenario == 'success':
                        result = harness.review('copilot', b'Artifact', 30, self.named_capability(),
                                                model='claude-99.1', manager_family='openai')
                        self.assertEqual(result['status'], 'reviewed')
                        self.assertEqual(result['model_family'], 'anthropic')
                        self.assertTrue(result['independent_judgment'])
                        self.assertIsNone(result['actual_effort'])
                        admission.assert_called_once_with('copilot')
                        self.assertEqual(role.call_count, 2)
                    else:
                        with self.assertRaises(harness.HarnessError):
                            harness.review('copilot', b'Artifact', 30, self.named_capability(),
                                           model='claude-99.1', manager_family='openai')
                        if scenario != 'mismatch':
                            self.assertFalse(any(call.args[0] == 'session.send' for call in client._request.call_args_list))
                    watch.return_value.close.assert_called_once()
                client.close.assert_called_once()

    def test_interactive_overrides_cannot_replace_native_billing_or_effort(self):
        capability = {'executable': 'copilot', 'planner': {'model': 'auto', 'effort': None}}
        for flag in ('--reasoning-effort=max', '--provider', '--config-dir', '--headless'):
            with self.assertRaises(harness.HarnessError):
                harness.launch_plan('copilot', 'planner', capability, [flag])
        source = {'HOME': '/test', 'GITHUB_COPILOT_API_TOKEN': 'private', 'COPILOT_API_URL': 'https://alternate.invalid'}
        self.assertEqual(inventory.child_env(source), {'HOME': '/test'})

    def test_wire_transport_propagates_callback_rejection(self):
        client = inventory.MetadataRPC.__new__(inventory.MetadataRPC)
        event = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'permission.request', 'params': {}}).encode()
        client.buffer = b'Content-Length: ' + str(len(event)).encode() + b'\r\n\r\n' + event
        client.timeout, client.serial, client.tick, client.reader = 1, 0, None, None
        client.process = MagicMock(stdin=io.BytesIO())
        client.on_message = MagicMock(side_effect=harness.HarnessError('isolation_violation', 'blocked'))
        with self.assertRaises(harness.HarnessError):
            client._request('session.send', {'sessionId': 'fixture', 'prompt': 'text'})
        client.on_message.assert_called_once()

    def test_execution_receipt_and_tool_or_unaccounted_response_stop(self):
        for scenario in ('success', 'tool', 'unknown-model', 'unchanged-quota', 'paid', 'pool-change'):
            with self.subTest(scenario=scenario):
                client = MagicMock()
                finished = False

                def rpc(method, params=None):
                    nonlocal finished
                    if method == 'account.getQuota':
                        factory = paid_quota if scenario == 'paid' or (scenario == 'pool-change' and not finished) else quota
                        return factory(3 if finished and scenario != 'unchanged-quota' else 2)
                    if method == 'session.create':
                        self.assertEqual(params['tools'], [])
                        self.assertFalse(params['enableConfigDiscovery'])
                        return {'sessionId': 'fixture'}
                    if method == 'session.send':
                        events = [('assistant.message', {'content': 'A bounded answer'}),
                                  ('assistant.usage', {'model': 'auto' if scenario == 'unknown-model' else 'gpt-test',
                                                       'inputTokens': 20, 'outputTokens': 10}), ('session.idle', {})]
                        if scenario == 'tool':
                            events.insert(0, ('tool.execution_start', {}))
                        for kind, data in events:
                            client.on_message({'method': 'session.event', 'params': {'sessionId': 'fixture',
                                               'event': {'type': kind, 'data': data}}})
                        finished = True
                    return {}

                client._request.side_effect = rpc
                client.request.side_effect = rpc
                capability = {'executable': 'copilot', 'planner': {'model': 'auto', 'effort': None}}
                with patch.object(inventory, 'MetadataRPC', return_value=client), patch('supervision.Watch'):
                    if scenario in {'success', 'unchanged-quota', 'paid'}:
                        result = copilot.execute(b'task', 30, capability, task=True)
                        self.assertEqual(result['actual_model'], 'gpt-test')
                        self.assertEqual(result['completion_tokens'], 10)
                        self.assertEqual(result['quota_evidence']['pool'],
                                         'premium_interactions:token_billing' if scenario == 'paid' else 'chat:token_billing')
                        if scenario == 'unchanged-quota':
                            self.assertEqual(result['quota_evidence']['delta_lower_bound_percent'], 0)
                            self.assertEqual(result['quota_evidence']['per_task_charge'], 'unknown')
                    else:
                        with self.assertRaises(harness.HarnessError):
                            copilot.execute(b'task', 30, capability, task=True)
                client.close.assert_called_once()

    def test_paid_control_and_reset_are_never_invented(self):
        raw = quota()
        raw['quotaSnapshots']['chat']['resetDate'] = '1970-01-01T00:01:40Z'
        snapshot = usage.copilot_snapshot(inventory.normalize_quota(raw), now=100, complete=True)
        self.assertEqual(len(snapshot['pools']), 1)
        self.assertIsNone(snapshot['pools'][0]['resets_at'])
        self.assertEqual(snapshot['pools'][0]['window_minutes'], 44640)
        for bad in (True, None):
            data = copy.deepcopy(raw)
            data['quotaSnapshots']['chat']['overageAllowedWithExhaustedQuota'] = bad
            with self.assertRaises(harness.HarnessError):
                copilot.billing_pool(data)

    def test_paid_pool_requires_one_known_finite_pool_and_no_overage(self):
        self.assertEqual(copilot.billing_pool(paid_quota())['pool'], 'premium_interactions')
        for scenario in ('overage', 'unknown-overage', 'request-billing', 'ambiguous', 'unknown-pool', 'missing-quota'):
            data = paid_quota()
            rows = data['quotaSnapshots']
            if scenario == 'overage': rows['completions']['overageAllowedWithExhaustedQuota'] = True
            if scenario == 'unknown-overage': rows['chat'].pop('usageAllowedWithExhaustedQuota')
            if scenario == 'request-billing': rows['premium_interactions']['tokenBasedBilling'] = False
            if scenario == 'ambiguous': rows['chat'] = dict(rows['premium_interactions'])
            if scenario == 'unknown-pool': rows['unknown'] = rows.pop('premium_interactions')
            if scenario == 'missing-quota': rows['premium_interactions'].pop('hasQuota')
            with self.subTest(scenario=scenario), self.assertRaises(harness.HarnessError):
                copilot.billing_pool(data)

    def test_failed_copilot_job_blocks_admission_until_explicit_reconciliation(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / 'ledger.db')
            ledger.complete_setup(services=['copilot'], api_services=[], source='test')
            job = {'id': 'one', 'service': 'copilot', 'status': 'running', 'created_at': 100}
            with ledger._connect() as db:
                balance._table(db)
                db.execute('INSERT INTO balance_jobs VALUES (?,?,?,?,?)', ('one', 'copilot', '2026-09-09', 'running', json.dumps(job)))
            with patch.object(usage, 'require_admission', return_value={'allowed': False}):
                result = balance.finish(ledger, 'one', 'failed')
            self.assertEqual(result['status'], 'running')
            with patch.object(usage, 'refresh', side_effect=AssertionError('must stop before refresh')):
                self.assertEqual(usage.require_admission('copilot', ledger=ledger)['reasons'], ['copilot_execution_unverified'])
            self.assertTrue(balance.reconcile(ledger, 'one', True)['allowed'])


if __name__ == '__main__':
    unittest.main()
