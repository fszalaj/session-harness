"""Maintenance excludes native reservations without changing quota accounting."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
import json
import multiprocessing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import coordination
from quota import Ledger


def race_operation(path, action, barrier, results):
    ledger = Ledger(path)
    with patch('usage.require_admission', return_value={'allowed': True}):
        barrier.wait()
        results.put(coordination.dispatch(action, 'claude', action, ledger))


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.ledger = Ledger(Path(directory.name) / 'ledger.db')

    def dispatch(self, action, owner='updater'):
        return coordination.dispatch(action, 'claude', owner, self.ledger)

    def test_acquire_idempotent_exact_release_and_stale_attention(self):
        with patch('coordination.time.time', return_value=100):
            first = self.dispatch('maintenance-acquire')
        self.assertEqual('maintenance_acquired', first['status'])
        self.assertFalse(first['allowed'])
        self.assertEqual(first['maintenance'], self.dispatch('maintenance-acquire')['maintenance'])
        self.assertEqual('maintenance_busy', self.dispatch('maintenance-acquire', 'other')['status'])
        with self.assertRaisesRegex(ValueError, 'owner mismatch'):
            self.dispatch('maintenance-release', 'other')
        with patch('coordination.time.time', return_value=1000):
            self.assertFalse(coordination.session_status(self.ledger)['maintenance_attention'])
        with patch('coordination.time.time', return_value=1001):
            self.assertTrue(coordination.session_status(self.ledger)['maintenance_attention'])
        with self.assertRaisesRegex(ValueError, 'maintenance'):
            coordination.configure(self.ledger, authority='remote')
        for _ in range(2):
            result = self.dispatch('maintenance-release')
            self.assertEqual('maintenance_released', result['status'])
            self.assertIsNone(result['maintenance'])

    def test_held_maintenance_denies_without_setup_or_quota_inference(self):
        self.dispatch('maintenance-acquire')
        with patch('usage.require_admission') as usage:
            for action in ('admit', 'check'):
                for service in coordination.SERVICES:
                    result = coordination.dispatch(action, service, 'native', self.ledger)
                    self.assertEqual(['account_maintenance'], result['reasons'])
            usage.assert_not_called()
        self.assertEqual([], coordination.session_status(self.ledger)['sessions'])

    def test_all_services_make_busy_and_preserve_owners(self):
        self.ledger.complete_setup(services=list(coordination.SERVICES), api_services=[], source='test')
        with patch('usage.require_admission', return_value={'allowed': True}):
            for service in coordination.SERVICES:
                coordination.dispatch('admit', service, service, self.ledger)
                before = coordination.session_status(self.ledger)['sessions']
                result = self.dispatch('maintenance-acquire')
                self.assertEqual('maintenance_busy', result['status'])
                self.assertEqual(before, result['sessions'])
                self.assertEqual(before, coordination.session_status(self.ledger)['sessions'])
                coordination.dispatch('release', service, service, self.ledger)

    def test_separate_process_admit_race_excludes_maintenance(self):
        self.ledger.complete_setup(services=['claude'], api_services=[], source='test')
        context = multiprocessing.get_context('spawn')
        for _ in range(8):
            barrier, results = context.Barrier(2), context.Queue()
            processes = [context.Process(target=race_operation, args=(self.ledger.path, action, barrier, results))
                         for action in ('admit', 'maintenance-acquire')]
            for process in processes:
                process.start()
            values = [results.get(timeout=15) for _ in processes]
            for process in processes:
                process.join(15)
                self.assertEqual(0, process.exitcode)
            self.assertEqual(1, sum(v.get('allowed') or v.get('status') == 'maintenance_acquired' for v in values))
            coordination.dispatch('release', 'claude', 'admit', self.ledger)
            self.dispatch('maintenance-release', 'maintenance-acquire')
            results.close()

    def test_second_concurrent_contender_is_busy(self):
        with ThreadPoolExecutor(2) as pool:
            values = list(pool.map(lambda owner: self.dispatch('maintenance-acquire', owner), ('a', 'b')))
        self.assertEqual(['maintenance_acquired', 'maintenance_busy'], sorted(v['status'] for v in values))

    def test_corrupt_state_fails_closed(self):
        for corrupt in ('null', '{}', 'not json', '{"owner":"x","started":NaN}', '{"owner":"x","started":true}'):
            with self.ledger._connect() as db:
                db.execute("INSERT OR REPLACE INTO state VALUES ('maintenance_v1', ?)", (corrupt,))
            with patch('usage.require_admission') as usage:
                for action in ('admit', 'check', 'maintenance-acquire', 'maintenance-release', 'status'):
                    with self.assertRaises(ValueError):
                        self.dispatch(action)
                usage.assert_not_called()

    def test_remote_metadata_without_setup_and_no_old_authority_fallback(self):
        coordination.configure(self.ledger, authority='owner@example.test')
        response = {'allowed': False, 'status': 'maintenance_acquired', 'maintenance_version': 1,
                    'maintenance': {'owner': 'updater', 'started': 100}}
        with patch('platform_runtime.which', return_value='/trusted/ssh'), \
                patch('coordination.subprocess.run') as run, patch('coordination.local') as local:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps(response).encode()
            self.assertEqual(response, self.dispatch('maintenance-acquire'))
            self.assertIn('StrictHostKeyChecking=yes', run.call_args.args[0])
            for invalid in ({'allowed': False, 'status': 'unknown'}, {**response, 'maintenance_version': 0},
                            {**response, 'maintenance': None}):
                run.return_value.stdout = json.dumps(invalid).encode()
                with self.assertRaises(ValueError):
                    self.dispatch('maintenance-acquire')
            run.return_value.returncode = 1
            with self.assertRaisesRegex(ValueError, 'no local fallback'):
                self.dispatch('maintenance-acquire')
            local.assert_not_called()

    def test_recovery_cli_and_status_surface_state(self):
        self.dispatch('maintenance-acquire')
        output = StringIO()
        with patch('quota.default_path', return_value=self.ledger.path), redirect_stdout(output):
            self.assertEqual(0, coordination.main(['status']))
        result = json.loads(output.getvalue())
        self.assertEqual(1, result['authority_maintenance_version'])
        self.assertEqual('updater', result['local_maintenance']['owner'])
        with patch('quota.default_path', return_value=self.ledger.path), redirect_stdout(StringIO()):
            self.assertEqual(0, coordination.main(['maintenance-release', '--owner', 'updater', '--confirm-stopped']))
        self.assertIsNone(coordination.session_status(self.ledger)['maintenance'])


if __name__ == '__main__':
    unittest.main()
