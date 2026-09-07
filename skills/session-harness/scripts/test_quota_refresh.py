"""Concurrent sessions observe one account counter in backend-request order."""
import multiprocessing
from pathlib import Path
import os
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

import credits
from quota import Ledger
from quota_refresh import serialized
import usage


def refresh_worker(path, barrier, queue):
    ledger = Ledger(path)
    def backend(service):
        at = time.time()
        prior = ledger.check(service, now=at)['pools'][0]['remaining_percent']
        time.sleep(0.03)
        return {'service': service, 'observed_at': at, 'complete': True, 'source': 'fixture',
                'credit_resources': credits.claude_resources({'extra_usage': {'is_enabled': False}}),
                'pools': [{'pool': 'weekly', 'used_percent': 102 - prior, 'resets_at': at + 86400}]}
    try:
        barrier.wait(timeout=10)
        with patch('native_quota.read_snapshot', side_effect=backend):
            result = usage.refresh('claude', ledger=ledger)
        queue.put({'allowed': result['allowed'], 'consumed': result['pools'][0]['daily_consumed']})
    except Exception as exc:
        queue.put({'error': type(exc).__name__})


def crash_worker(path, ready):
    with serialized(Ledger(path), 'claude'):
        ready.set()
        os._exit(0)


class RefreshTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'ledger.sqlite3'
        self.ledger = Ledger(self.path)
        self.ledger.complete_setup(services=['claude'], api_services=[], source='test')
        self.ledger.set_mode('observed')
        self.ledger.budget_set('claude', 'fixed', daily_limit=5, reserve=0)
        now = time.time()
        self.ledger.record({'service': 'claude', 'observed_at': now, 'complete': True, 'source': 'fixture',
                            'credit_resources': credits.claude_resources({'extra_usage': {'is_enabled': False}}),
                            'pools': [{'pool': 'weekly', 'used_percent': 0, 'resets_at': now + 86400}]},
                           initialize=True)

    def test_three_processes_share_daily_consumption_and_stop_at_one_cap(self):
        context = multiprocessing.get_context('spawn')
        barrier, queue = context.Barrier(3), context.Queue()
        workers = [context.Process(target=refresh_worker, args=(str(self.path), barrier, queue)) for _ in range(3)]
        for worker in workers:
            worker.start()
        try:
            results = [queue.get(timeout=15) for _ in workers]
        finally:
            for worker in workers:
                worker.join(timeout=5)
                if worker.is_alive():
                    worker.terminate(); worker.join()
            queue.close()
        self.assertTrue(all('error' not in r for r in results), results)
        self.assertEqual([2, 4, 6], sorted(r['consumed'] for r in results))
        self.assertEqual(2, sum(r['allowed'] for r in results))
        self.assertEqual(6, self.ledger.check('claude')['pools'][0]['daily_consumed'])

    def test_lock_is_per_service_and_times_out_without_bypassing_contention(self):
        with serialized(self.ledger, 'claude'):
            with serialized(self.ledger, 'codex', timeout=0.01):
                pass
            with self.assertRaises(sqlite3.OperationalError):
                with serialized(self.ledger, 'claude', timeout=0.01):
                    self.fail('overlapping backend refresh')

    def test_exception_and_process_exit_release_refresh_lock_without_erasing_accounting(self):
        with self.assertRaises(RuntimeError):
            with serialized(self.ledger, 'claude'):
                raise RuntimeError('fixture')
        context = multiprocessing.get_context('spawn')
        ready = context.Event()
        worker = context.Process(target=crash_worker, args=(str(self.path), ready))
        worker.start()
        self.assertTrue(ready.wait(timeout=10))
        worker.join(timeout=5)
        if worker.is_alive():
            worker.terminate(); worker.join()
            self.fail('crash fixture did not exit')
        with serialized(self.ledger, 'claude', timeout=0.1):
            self.assertEqual(0, self.ledger.check('claude')['pools'][0]['daily_consumed'])

    @unittest.skipIf(os.name == 'nt', 'POSIX symlink fixture; Windows reparse tests run separately')
    def test_refresh_lock_rejects_symlink(self):
        import hashlib
        name = hashlib.sha256(b'claude').hexdigest()
        path = self.path.with_name(self.path.name + '.refresh-' + name + '.sqlite3')
        path.symlink_to(self.path)
        with self.assertRaises(OSError):
            with serialized(self.ledger, 'claude'):
                self.fail('symlink accepted')
        self.assertTrue(self.ledger.check('claude')['allowed'])


if __name__ == '__main__':
    unittest.main()
