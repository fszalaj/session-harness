import io
import json
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import balance_cli
import free_access
import coordination
import harness
from quota import Ledger


class WorkTests(unittest.TestCase):
    def setUp(self):
        free_config = patch.object(free_access, 'load_config', return_value=None)
        free_config.start()
        self.addCleanup(free_config.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = Ledger(Path(self.temp.name) / 'ledger.sqlite3')
        self.ledger.complete_setup(services=['codex', 'claude', 'antigravity'], api_services=[], source='test')
        self.capability = {'worker': {'model': 'example-current', 'effort': 'medium'}}

    def test_mixed_free_selection_and_native_stop(self):
        replies = [{'allowed': True, 'bound': False},
                   {'allowed': True, 'enabled': True, 'services': {'claude': {'progress': 0.4}}},
                   {'allowed': True, 'bound': True, 'route': 'recurring_free'}]
        with patch.object(free_access, 'load_config', return_value={'enabled': True, 'mixed_work': True}), \
             patch.object(coordination, 'balance_dispatch', side_effect=replies) as authority, \
             patch.object(free_access, 'dispatch', side_effect=[{'allowed': True, 'progress': 0.02}, {'status': 'completed'}]) as free:
            result = balance_cli.run_work(b'Bounded task', task_id='mixed-one', ledger=self.ledger)
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(authority.call_args.args[1]['proposed'], 'recurring_free')
            self.assertEqual(free.call_args.args[0], 'run')
        for bound in (False, True):
            with patch.object(coordination, 'balance_dispatch', side_effect=[{'allowed': True, 'bound': bound, 'route': 'recurring_free'}, {'allowed': False, 'status': 'quota_denied'}]), \
                 patch.object(free_access, 'dispatch') as free:
                result = balance_cli.mixed_work(b'task', 'stopped', 60, self.ledger)
                self.assertFalse(result['allowed'])
                free.assert_not_called()

        with patch.object(balance_cli, 'run_work', return_value={'status': 'completed'}), \
             patch.object(balance_cli, 'Ledger', return_value=self.ledger), \
             patch('sys.stdin', io.TextIOWrapper(io.BytesIO(b'bounded task'))), patch('sys.stdout', io.StringIO()):
            self.assertEqual(balance_cli.main(['work', '--id', 'completed-free']), 0)

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
            *self.interactive_replies()[:3],
            {'allowed': False, 'status': 'invalid_transition', 'reasons': ['invalid_transition']}]), \
             patch('supervision.run_terminal', return_value=0):
            with self.assertRaisesRegex(balance_cli.InteractiveStop, 'receipt is unconfirmed'):
                balance_cli.run_interactive('claude', {'argv': ['claude'],
                    'selection': {'model': 'example', 'effort': 'medium'}}, {}, ledger=self.ledger)

    def test_interactive_worker_lead_denial_before_process(self):
        with patch.object(coordination, 'balance_dispatch', side_effect=[
            self.interactive_replies()[0],
            {'allowed': False, 'reasons': ['max_lead_exceeded']}]), \
             patch('supervision.run_terminal') as execute:
            with self.assertRaises(balance_cli.InteractiveStop) as caught:
                balance_cli.run_interactive('claude', {'argv': ['claude']}, {}, ledger=self.ledger)
            self.assertEqual(caught.exception.reasons, ('max_lead_exceeded',))
            execute.assert_not_called()

    def interactive_replies(self, code=0):
        return [{'allowed': True, 'status': 'ready', 'reasons': [], 'enabled': True},
                *[{'allowed': True, 'status': status, 'reasons': [], 'service': 'claude'}
                  for status in ('reserved', 'running', 'completed' if code == 0 else 'failed')]]

    def interactive(self):
        return balance_cli.run_interactive('claude', {'argv': ['claude'],
            'selection': {'model': 'example', 'effort': 'medium'}}, {}, ledger=self.ledger)

    def test_interactive_transport_and_malformed_replies_preserve_phase_without_retry(self):
        bad_replies = [ValueError('private transport'), OSError(1, 'private path'), None,
                       {'allowed': 1, 'reasons': []}, {'allowed': True, 'reasons': 'private'},
                       {'allowed': True, 'status': 'unexpected', 'reasons': []}]
        for index, phase in enumerate(('status', 'reserve', 'start', 'finish')):
            for bad in bad_replies:
                with self.subTest(phase=phase, bad=type(bad).__name__):
                    with patch.object(coordination, 'balance_dispatch',
                                      side_effect=[*self.interactive_replies()[:index], bad]) as dispatch, \
                         patch('supervision.run_terminal', return_value=0) as execute:
                        with self.assertRaises(balance_cli.InteractiveStop) as caught:
                            self.interactive()
                    error = caught.exception
                    self.assertEqual(error.phase, phase)
                    self.assertEqual(error.status, 'balance_receipt_unavailable' if phase == 'finish' else 'balance_blocked')
                    self.assertEqual(execute.call_count, int(phase == 'finish'))
                    self.assertEqual(dispatch.call_count, index + 1)
                    self.assertFalse(error.details()['automatic_retry'])
                    self.assertNotIn('private', str(error) + json.dumps(error.details()))
                    if index:
                        self.assertEqual(error.task_id, dispatch.call_args_list[1].args[1]['request']['id'])

    def test_interactive_disabled_shape_and_successful_execution(self):
        for state in ({'allowed': True, 'status': 'disabled', 'reasons': []},
                      {'allowed': True, 'status': 'disabled', 'reasons': [], 'enabled': 0},
                      {'allowed': True, 'status': 'ready', 'reasons': [], 'enabled': False}):
            with patch.object(coordination, 'balance_dispatch', return_value=state), \
                 patch('supervision.run_terminal') as execute:
                with self.assertRaises(balance_cli.InteractiveStop):
                    self.interactive()
                execute.assert_not_called()
        disabled = {'allowed': True, 'status': 'disabled', 'reasons': [], 'enabled': False}
        for code in (0, 9):
            for replies in ([disabled], self.interactive_replies(code)):
                with patch.object(coordination, 'balance_dispatch', side_effect=replies) as dispatch, \
                     patch('supervision.run_terminal', return_value=code) as execute:
                    self.assertEqual(self.interactive(), code)
                execute.assert_called_once()
                self.assertEqual(dispatch.call_count, len(replies))

    def test_interactive_quota_stop_remains_primary_and_retains_job(self):
        error = harness.supervision.Stop('claude', ['daily_limit'])
        error.session_cleanup = {'state': 'unknown', 'owner_retained': True}
        with patch.object(coordination, 'balance_dispatch', side_effect=self.interactive_replies()) as dispatch, \
             patch('supervision.run_terminal', side_effect=error):
            with self.assertRaises(harness.supervision.Stop) as caught:
                self.interactive()
        self.assertIs(caught.exception, error)
        self.assertEqual(dispatch.call_count, 3)

    def test_worker_cli_reports_policy_denial_in_imported_and_script_namespaces(self):
        fresh = runpy.run_path(str(Path(harness.__file__)))['main']
        for main in (harness.main, fresh):
            for phase in ('reserve', 'finish'):
                replies = self.interactive_replies()[:1 if phase == 'reserve' else 3]
                replies.append({'allowed': False, 'reasons': ['max_lead_exceeded', 'private-secret\n\x1b']})
                globals_ = main.__globals__
                with patch.dict(harness.os.environ, {}, clear=True), \
                     patch.object(balance_cli, 'Ledger', return_value=self.ledger), \
                     patch.dict(globals_, {
                         'discover_provider': lambda *a, **kw: {'auth': {'status': 'subscription'}},
                         'launch_plan': lambda *a, **kw: {'selection': {'model': 'fixture', 'effort': 'medium'}, 'argv': ['fixture']},
                         'require_role': lambda *a, **kw: {}, 'require_quota': lambda *a, **kw: {}}), \
                     patch.object(harness.sys.stdin, 'isatty', return_value=True), \
                     patch.object(coordination, 'balance_dispatch', side_effect=replies), \
                     patch('supervision.run_terminal', return_value=0) as execute, \
                     patch('sys.stdout', new_callable=io.StringIO) as output, \
                     patch('sys.stderr', new_callable=io.StringIO) as diagnostic:
                    code = main(['launch', 'claude', '--role', 'worker', '--execute'])
                self.assertEqual(code, 2)
                result = json.loads(output.getvalue())
                self.assertEqual(result['status'], 'balance_blocked' if phase == 'reserve' else 'balance_receipt_unavailable')
                self.assertEqual(result['reasons'], ['max_lead_exceeded', 'unknown'])
                self.assertEqual(result['phase'], phase)
                self.assertFalse(result['automatic_retry'])
                self.assertIn('ai-session balance status', diagnostic.getvalue())
                self.assertNotIn('private-secret', output.getvalue() + diagnostic.getvalue())
                self.assertNotIn('schema_error', output.getvalue())
                self.assertEqual(execute.call_count, int(phase == 'finish'))


if __name__ == '__main__':
    unittest.main()
