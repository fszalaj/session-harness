import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import balance_cli
import coordination
import harness
from quota import Ledger


class WorkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = Ledger(Path(self.temp.name) / 'ledger.sqlite3')
        self.ledger.complete_setup(services=['codex', 'claude', 'antigravity'], api_services=[], source='test')
        self.capability = {'worker': {'model': 'example-current', 'effort': 'medium'}}

    def test_real_adapter_entry_uses_current_worker_and_native_service(self):
        replies = [{'allowed': True, 'status': 'reserved', 'service': 'claude'},
                   {'allowed': True, 'status': 'running'}, {'allowed': True, 'status': 'completed'}]
        with patch.object(coordination, 'balance_dispatch', side_effect=replies) as dispatch, \
             patch.object(harness, 'discover_provider', return_value=self.capability) as discover, \
             patch.object(harness, 'review', return_value={'result': 'proposed patch',
                 'actual_model': 'example-current', 'requested_model': 'example-current',
                 'requested_effort': 'medium'}) as execute:
            result = balance_cli.run_work(b'Bounded task', task_id='one', ledger=self.ledger)
        self.assertEqual(result['billing_route'], 'native_subscription')
        self.assertEqual(result['billing_service'], 'claude')
        discover.assert_called_once_with('claude')
        self.assertTrue(execute.call_args.kwargs['task'])
        self.assertEqual(execute.call_args.args[3]['planner']['effort'], 'medium')
        self.assertNotIn('Bounded task', json.dumps(dispatch.call_args_list[0].args[1]))

    def test_denial_and_duplicate_never_execute_or_switch(self):
        for reply in [{'allowed': False, 'status': 'max_lead_exceeded'},
                      {'allowed': False, 'status': 'reserved', 'duplicate': True}]:
            with patch.object(coordination, 'balance_dispatch', return_value=reply), \
                 patch.object(harness, 'discover_provider') as discover:
                result = balance_cli.run_work(b'task', task_id='one', ledger=self.ledger)
            self.assertFalse(result['allowed'])
            discover.assert_not_called()

    def test_failure_retains_terminal_attempt_and_never_retries(self):
        replies = [{'allowed': True, 'status': 'reserved', 'service': 'claude'},
                   {'allowed': True, 'status': 'running'}, {'allowed': True, 'status': 'failed'}]
        with patch.object(coordination, 'balance_dispatch', side_effect=replies) as dispatch, \
             patch.object(harness, 'discover_provider', return_value=self.capability), \
             patch.object(harness, 'review', side_effect=harness.HarnessError('quota_blocked', 'stop')) as execute:
            result = balance_cli.run_work(b'task', task_id='one', ledger=self.ledger)
        self.assertFalse(result['automatic_retry'])
        self.assertEqual(result['reasons'], ['quota_blocked'])
        execute.assert_called_once()
        self.assertEqual(dispatch.call_args.args[1]['status'], 'failed')

    def test_unresolved_actual_model_preserves_output_and_valid_receipt(self):
        replies = [{'allowed': True, 'status': 'reserved', 'service': 'codex'},
                   {'allowed': True, 'status': 'running'}, {'allowed': True, 'status': 'completed'}]
        with patch.object(coordination, 'balance_dispatch', side_effect=replies) as dispatch, \
             patch.object(harness, 'discover_provider', return_value=self.capability), \
             patch.object(harness, 'review', return_value={'result': 'useful patch',
                 'actual_model': None, 'requested_model': 'example-current',
                 'model_verification': 'explicit catalog argument only'}):
            result = balance_cli.run_work(b'task', task_id='codex-one', ledger=self.ledger)
        self.assertTrue(result['allowed'])
        self.assertIsNone(result['actual_model'])
        self.assertNotIn('actual_model', dispatch.call_args.args[1]['metadata'])

    def test_remote_missing_protocol_and_transport_fail_closed(self):
        coordination.configure(self.ledger, authority='owner@authority')
        for reply in [subprocess.CompletedProcess([], 0, b'{"allowed": true}', b''),
                      subprocess.CompletedProcess([], 1, b'', b'unavailable')]:
            with patch.object(coordination.subprocess, 'run', return_value=reply), \
                 patch.object(coordination, 'balance_local') as local:
                with self.assertRaises(ValueError):
                    coordination.balance_dispatch('status', {}, self.ledger)
                local.assert_not_called()

    def test_lost_receipt_preserves_output_without_second_dispatch(self):
        replies = [{'allowed': True, 'status': 'reserved', 'service': 'claude'},
                   {'allowed': True, 'status': 'running'}, ValueError('authority disconnected')]
        with patch.object(coordination, 'balance_dispatch', side_effect=replies), \
             patch.object(harness, 'discover_provider', return_value=self.capability), \
             patch.object(harness, 'review', return_value={'result': 'completed useful work'}) as execute:
            result = balance_cli.run_work(b'task', task_id='one', ledger=self.ledger)
        self.assertFalse(result['allowed'])
        self.assertFalse(result['automatic_retry'])
        self.assertEqual(result['status'], 'receipt_unavailable')
        self.assertEqual(result['result'], 'completed useful work')
        execute.assert_called_once()

    def test_remote_fixed_schema_never_accepts_extra_fields(self):
        with self.assertRaises(ValueError):
            coordination.balance_local('status', {'command': 'run something'}, self.ledger)
        with self.assertRaises(ValueError):
            coordination.balance_local('__getattribute__', {}, self.ledger)

    def test_remote_reserve_transmits_client_setup_and_timeout_is_safe(self):
        coordination.configure(self.ledger, authority='owner@authority')
        with patch.object(coordination.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['ssh'], 90)) as remote:
            with self.assertRaisesRegex(ValueError, 'timed out'):
                coordination.balance_dispatch('reserve', {'request': {}}, self.ledger)
        packet = json.loads(remote.call_args.kwargs['input'])
        self.assertEqual(packet['payload']['client_services'], ['codex', 'claude', 'antigravity'])

    def test_interactive_receipt_denial_is_not_process_success(self):
        with patch.object(coordination, 'balance_dispatch', side_effect=[
            {'allowed': True, 'enabled': True}, {'allowed': True}, {'allowed': True},
            {'allowed': False, 'status': 'invalid_transition'}]), \
             patch('supervision.run_terminal', return_value=0):
            with self.assertRaisesRegex(ValueError, 'receipt unavailable'):
                balance_cli.run_interactive('claude', {'argv': ['claude'],
                    'selection': {'model': 'example', 'effort': 'medium'}}, {}, ledger=self.ledger)

    def test_interactive_worker_lead_denial_before_process(self):
        with patch.object(coordination, 'balance_dispatch', side_effect=[
            {'allowed': True, 'enabled': True},
            {'allowed': False, 'reasons': ['max_lead_exceeded']}]), \
             patch('supervision.run_terminal') as execute:
            with self.assertRaises(ValueError):
                balance_cli.run_interactive('claude', {'argv': ['claude']}, {}, ledger=self.ledger)
            execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
