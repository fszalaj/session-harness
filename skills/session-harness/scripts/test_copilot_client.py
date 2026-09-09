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


class CopilotTests(unittest.TestCase):
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
        for scenario in ('success', 'tool', 'unknown-model', 'unchanged-quota'):
            with self.subTest(scenario=scenario):
                client = MagicMock()
                finished = False

                def rpc(method, params=None):
                    nonlocal finished
                    if method == 'account.getQuota':
                        return quota(3 if finished and scenario != 'unchanged-quota' else 2)
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
                    if scenario == 'success':
                        result = copilot.execute(b'task', 30, capability, task=True)
                        self.assertEqual(result['actual_model'], 'gpt-test')
                        self.assertEqual(result['completion_tokens'], 10)
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
                copilot.chat_pool(data)

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
