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
        self.assertEqual(5, len(claude_gate.install(home=self.home)['changed_events']))
        self.assertEqual(original, path.read_bytes())
        claude_gate.install(True, self.home)
        self.assertEqual([], claude_gate.install(home=self.home)['changed_events'])
        result = json.loads(path.read_text())
        self.assertEqual('existing', result['hooks']['PreToolUse'][0]['hooks'][0]['command'])
        self.assertEqual('high', result['effortLevel'])


if __name__ == '__main__':
    unittest.main()
