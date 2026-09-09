"""Shared-account exclusion and deterministic hook stops without inference."""
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import claude_gate
import coordination
from quota import Ledger


class CoordinationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.ledger = Ledger(self.home / 'ledger.db')
        self.ledger.complete_setup(services=['claude','codex'], api_services=[], source='test')
        default = patch('quota.default_path', return_value=self.ledger.path)
        default.start(); self.addCleanup(default.stop)

    def admit(self, owner):
        return coordination.dispatch('admit', 'claude', owner, self.ledger)

    def test_parallel_sessions_have_one_winner_and_no_timeout_refund(self):
        coordination.configure(self.ledger, max_sessions=1)
        with patch('usage.require_admission', return_value={'allowed': True}):
            with ThreadPoolExecutor(2) as workers:
                results = list(workers.map(self.admit, ['session-a', 'session-b']))
            self.assertEqual(1, sum(r['allowed'] for r in results))
            winner = 'session-a' if results[0]['allowed'] else 'session-b'
            self.assertTrue(self.admit(winner)['allowed'])
            with patch('coordination.time.time', return_value=10**11):
                self.assertFalse(self.admit('session-c')['allowed'])
            coordination.dispatch('release', 'claude', winner, self.ledger)
            self.assertTrue(self.admit('session-c')['allowed'])

    def test_budget_denial_does_not_reserve_new_session(self):
        with patch('usage.require_admission', return_value={'allowed': False, 'reasons': ['daily_limit']}):
            self.assertFalse(self.admit('a')['allowed'])
        with patch('usage.require_admission', return_value={'allowed': True}):
            self.assertTrue(self.admit('b')['allowed'])

    def test_parallel_capacity_is_separate_from_shared_account_budget(self):
        with patch('usage.require_admission', return_value={'allowed': True}):
            with ThreadPoolExecutor(6) as workers:
                results = list(workers.map(self.admit, ['session-' + str(i) for i in range(6)]))
        self.assertEqual(4, sum(r['allowed'] for r in results))
        stopped = next(r for r in results if not r['allowed'])
        self.assertEqual((4, 4), (stopped['active_sessions'], stopped['max_sessions']))
        with patch('usage.require_admission', return_value={'allowed': False, 'reasons': ['daily_limit']}):
            for index, result in enumerate(results):
                if result['allowed']:
                    self.assertEqual(['daily_limit'], self.admit('session-' + str(index))['reasons'])

    def test_capacity_can_increase_live_without_changing_accounting_or_owners(self):
        coordination.configure(self.ledger, max_sessions=1)
        with patch('usage.require_admission', return_value={'allowed': True}):
            self.admit('first')
            before = coordination.session_status(self.ledger)['sessions']
            with self.ledger._connect() as db:
                accounting = db.execute("SELECT key,value FROM state WHERE key!='coordination_v1' ORDER BY key").fetchall()
            coordination.configure(self.ledger, max_sessions=8)
            self.assertEqual(before, coordination.session_status(self.ledger)['sessions'])
            self.assertTrue(self.admit('second')['allowed'])
            with self.ledger._connect() as db:
                self.assertEqual(accounting, db.execute("SELECT key,value FROM state WHERE key!='coordination_v1' ORDER BY key").fetchall())
            with self.assertRaises(ValueError):
                coordination.configure(self.ledger, authority='another@example.test')
            with self.assertRaises(ValueError):
                coordination.configure(self.ledger, max_sessions=1)
        self.assertEqual(8, coordination.settings(self.ledger)['max_sessions'])

    def test_explicit_existing_single_session_and_omitted_fields_are_preserved(self):
        coordination.configure(self.ledger, 'owner@example.test', 1)
        self.assertEqual({'authority': 'owner@example.test', 'max_sessions': 1}, coordination.configure(self.ledger))
        self.assertEqual('owner@example.test', coordination.configure(self.ledger, max_sessions=8)['authority'])
        self.assertEqual(8, coordination.configure(self.ledger, authority='local')['max_sessions'])

    def test_separate_account_authorities_have_independent_capacity(self):
        other = Ledger(self.home / 'another-account.db')
        other.complete_setup(services=['claude'], api_services=[], source='test')
        coordination.configure(self.ledger, max_sessions=1)
        coordination.configure(other, max_sessions=1)
        with patch('usage.require_admission', return_value={'allowed': True}):
            self.assertTrue(self.admit('first')['allowed'])
            self.assertFalse(self.admit('second')['allowed'])
            self.assertTrue(coordination.dispatch('admit', 'claude', 'second', other)['allowed'])

    def test_backend_exception_releases_only_new_owner(self):
        with patch('usage.require_admission', side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError):
                self.admit('new')
        self.assertEqual([], coordination.session_status(self.ledger)['sessions'])
        with patch('usage.require_admission', return_value={'allowed': True}):
            self.admit('existing')
        with patch('usage.require_admission', side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError):
                self.admit('existing')
        self.assertEqual('existing', coordination.session_status(self.ledger)['sessions'][0]['owner'])

    def test_capacity_cli_does_not_require_authority_and_reports_invalid_decrease(self):
        with redirect_stdout(StringIO()):
            self.assertEqual(0, coordination.main(['set', '--max-sessions', '8']))
        self.assertEqual(8, coordination.settings(self.ledger)['max_sessions'])
        for limit in ('0', '33'):
            with redirect_stdout(StringIO()):
                self.assertEqual(2, coordination.main(['set', '--max-sessions', limit]))
        self.assertEqual(8, coordination.settings(self.ledger)['max_sessions'])

    def test_status_reads_actual_authority_sessions_without_inference(self):
        coordination.configure(self.ledger, 'owner@example.test', 8)
        authority = {'allowed': False, 'status': 'session_status', 'max_sessions': 12,
                     'active_sessions': {'claude': 1}, 'sessions': [{'service': 'claude', 'owner': 'remote'}]}
        output = StringIO()
        with patch('coordination.dispatch', return_value=authority) as dispatch, redirect_stdout(output):
            self.assertEqual(0, coordination.main(['status']))
        result = json.loads(output.getvalue())
        self.assertEqual(12, result['authority_max_sessions'])
        self.assertEqual('remote', result['authority_sessions'][0]['owner'])
        dispatch.assert_called_once_with('status', 'claude', 'status', unittest.mock.ANY)

    def test_busy_hook_explains_capacity_without_recommending_quota_bypass(self):
        with patch('coordination.dispatch', return_value={'allowed': False, 'reasons': ['account_session_busy'],
                                                         'active_sessions': 1, 'max_sessions': 1}):
            result = claude_gate.evaluate({'hook_event_name': 'UserPromptSubmit', 'session_id': 'second'})
        self.assertFalse(result['continue'])
        self.assertIn('(1/1)', result['stopReason'])
        self.assertIn('coordination set --max-sessions', result['stopReason'])
        self.assertIn('same quota budget', result['stopReason'])

    def test_missing_setup_cannot_acquire(self):
        self.ledger.reset_setup()
        with patch('usage.require_admission') as usage:
            with self.assertRaisesRegex(ValueError, 'environment_setup_required'):
                self.admit('a')
            usage.assert_not_called()

    def test_remote_failure_never_falls_back_to_local(self):
        with self.ledger._connect() as db:
            db.execute("INSERT INTO state VALUES ('coordination_v1', ?)",
                       (json.dumps({'authority': 'user@example.test', 'max_sessions': 1}),))
        with patch('platform_runtime.which', return_value='/trusted/ssh'), \
                patch('coordination.subprocess.run', side_effect=TimeoutError), \
                patch('coordination.local') as local:
            with self.assertRaises(TimeoutError): self.admit('a')
            local.assert_not_called()

    def test_hook_denial_stops_instead_of_requesting_another_model_turn(self):
        with patch('coordination.dispatch', return_value={'allowed': False, 'reasons': ['daily_limit']}):
            result = claude_gate.evaluate({'hook_event_name': 'PreToolUse', 'session_id': 'a'})
        self.assertEqual(False, result['continue'])
        self.assertNotIn('decision', result)

    def test_hook_preserves_supervisor_lease_until_process_exit(self):
        with patch.dict(os.environ, {'SESSION_HARNESS_OWNER': 'supervisor'}), \
                patch('coordination.dispatch') as dispatch:
            claude_gate.evaluate({'hook_event_name': 'Stop', 'session_id': 'a'})
            dispatch.assert_not_called()

    def test_unknown_background_work_does_not_release_a_direct_session(self):
        with patch.dict(os.environ, {}, clear=True), patch('coordination.dispatch') as dispatch:
            claude_gate.evaluate({'hook_event_name': 'Stop', 'session_id': 'a'})
            dispatch.assert_not_called()
            claude_gate.evaluate({'hook_event_name': 'Stop', 'session_id': 'a', 'background_tasks': []})
            dispatch.assert_called_once_with('release', 'claude', 'claude:a')

    def test_hook_merge_is_opt_in_idempotent_and_preserves_settings(self):
        path = self.home / '.claude/settings.json'
        path.parent.mkdir()
        data = {'effortLevel': 'high', 'hooks': {'PreToolUse': [{'hooks': [{'type': 'command', 'command': 'existing'}]}]}}
        path.write_text(json.dumps(data))
        original = path.read_bytes()
        self.assertEqual(len(claude_gate.EVENTS), len(claude_gate.install(home=self.home)['changed_events']))
        self.assertEqual(original, path.read_bytes())
        claude_gate.install(True, self.home)
        self.assertEqual([], claude_gate.install(home=self.home)['changed_events'])
        result = json.loads(path.read_text())
        self.assertEqual('existing', result['hooks']['PreToolUse'][0]['hooks'][0]['command'])
        self.assertEqual('high', result['effortLevel'])


if __name__ == '__main__':
    unittest.main()
