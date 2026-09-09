import concurrent.futures
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import balance
import credits
from quota import Ledger


class BalanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = Ledger(Path(self.tmp.name) / 'ledger.db')
        self.ledger.complete_setup(services=['codex', 'claude'], api_services=[], source='test')
        self.ledger.set_mode('observed')
        self.ledger.budget_defaults(strategy='fixed')
        owner = patch.object(credits, 'codex_owner_policy', return_value={'confirmed_at': time.time()})
        owner.start()
        self.addCleanup(owner.stop)
        self.seed('codex')
        self.seed('claude')
        self.guard = patch.object(balance.usage, 'require_admission', side_effect=lambda service, ledger: ledger.check(service))
        self.guard.start()
        self.addCleanup(self.guard.stop)
        result = balance.configure(self.ledger, True)
        self.assertTrue(result['allowed'], result)

    def seed(self, service, used=0, extra=None):
        pools = [dict(pool='weekly', used_percent=used, resets_at=time.time() + 604800)]
        pools.extend(extra or [])
        resources = credits.claude_resources({'extra_usage': {'is_enabled': False}}) if service == 'claude' else credits.codex_resources({'native': {'credits': {'hasCredits': False, 'unlimited': False, 'balance': '0'}}})
        return self.ledger.record(dict(service=service, observed_at=time.time(), complete=True,
                                      source='test', pools=pools, credit_resources=resources), initialize=True)

    def request(self, id='task', **kwargs):
        return dict(id=id, fingerprint=balance.fingerprint(self.ledger, id.encode()), host='host', role='worker', **kwargs)

    def test_zero_rotation_and_lifecycle(self):
        services = []
        for n in range(6):
            result = balance.reserve(self.ledger, self.request(str(n)))
            self.assertTrue(result['allowed'], result)
            services.append(result['service'])
            balance.start(self.ledger, str(n))
            balance.finish(self.ledger, str(n), 'completed', {'exit_code': 0})
        self.assertEqual(services, ['claude', 'codex'] * 3)

    def test_interactive_cli_round_trip_uses_real_authority_contract_and_journal(self):
        import balance_cli
        response = {'argv': ['fixture'], 'selection': {'model': 'fixture', 'effort': 'medium'}}
        for code in (0, 9):
            with patch('supervision.run_terminal', return_value=code) as execute:
                self.assertEqual(balance_cli.run_interactive('claude', response, {}, ledger=self.ledger), code)
            execute.assert_called_once()
        jobs = balance.status(self.ledger)['jobs']
        self.assertEqual({job['status'] for job in jobs}, {'completed', 'failed'})
        self.assertEqual(len(jobs), 2)
        self.seed('claude', 8)
        with patch('supervision.run_terminal') as execute:
            with self.assertRaises(balance_cli.InteractiveStop) as caught:
                balance_cli.run_interactive('claude', response, {}, ledger=self.ledger)
        self.assertEqual(caught.exception.reasons, ('max_lead_exceeded',))
        execute.assert_not_called()
        balance.configure(self.ledger, False)
        with patch('supervision.run_terminal', return_value=0):
            self.assertEqual(balance_cli.run_interactive('claude', response, {}, ledger=self.ledger), 0)
        self.assertEqual(len(balance.status(self.ledger)['jobs']), 2)

    def test_leader_and_manager_overhead(self):
        self.seed('claude', 8)
        result = balance.reserve(self.ledger, self.request(provider='claude'))
        self.assertEqual(result['status'], 'max_lead_exceeded')
        self.assertEqual(balance.reserve(self.ledger, self.request())['service'], 'codex')

    def test_duplicate_crash_and_disable(self):
        request = self.request()
        self.assertTrue(balance.reserve(self.ledger, request)['allowed'])
        self.assertFalse(balance.reserve(self.ledger, request)['dispatch_required'])
        mismatch = dict(request, fingerprint='0' * 64)
        self.assertEqual(balance.reserve(self.ledger, mismatch)['status'], 'fingerprint_mismatch')
        balance.configure(self.ledger, False)
        self.assertTrue(balance.configure(self.ledger, True)['allowed'])
        jobs = balance.status(self.ledger)['jobs']
        self.assertEqual(len(jobs), 1)
        self.assertIn('--confirm-stopped', jobs[0]['reconcile_command'])
        self.assertFalse(balance.reconcile(self.ledger, 'task', False)['allowed'])
        self.assertEqual(balance.reconcile(self.ledger, 'task', True)['status'], 'abandoned')

    def test_concurrent_sqlite_slots(self):
        barrier = threading.Barrier(4)
        def reserve(n):
            barrier.wait()
            return balance.reserve(Ledger(self.ledger.path), self.request(str(n)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(reserve, range(4)))
        self.assertEqual(sum(r['allowed'] for r in results), 2, results)
        self.assertEqual({r['service'] for r in results if r['allowed']}, {'claude', 'codex'})

    def test_strict_and_missing_evidence_pause_everyone(self):
        self.ledger.set_mode('strict')
        self.assertFalse(balance.reserve(self.ledger, self.request())['allowed'])
        self.ledger.set_mode('observed')
        with patch.object(balance.usage, 'require_admission', return_value={'allowed': False, 'reasons': ['quota_refresh_failed']}):
            result = balance.reserve(self.ledger, self.request())
        self.assertTrue(any('evidence_unavailable' in r for r in result['reasons']))

    def test_refresh_outside_transaction_and_policy_drift(self):
        def admission(service, ledger):
            with ledger._connect() as db:
                db.execute('BEGIN IMMEDIATE')
            check = ledger.check(service)
            if service == 'claude':
                ledger.set_mode('strict')
            return check
        with patch.object(balance.usage, 'require_admission', side_effect=admission):
            result = balance.reserve(self.ledger, self.request())
        self.assertIn('state_changed', result['reasons'])

    def test_concurrent_refresh_reevaluates_new_consumption_without_network_retry(self):
        calls = []
        def admission(service, ledger):
            calls.append(service)
            result = ledger.check(service)
            if service == 'codex':
                self.seed('claude', 8)
            return result
        with patch.object(balance.usage, 'require_admission', side_effect=admission):
            result = balance.reserve(self.ledger, self.request())
        self.assertTrue(result['allowed'], result)
        self.assertEqual(result['service'], 'codex')
        self.assertEqual(calls, ['claude', 'codex'])
        self.assertEqual(result['job']['before']['claude']['pools'][0]['daily_consumed'], 8)

    def test_concurrent_refresh_cannot_hide_exhaustion(self):
        def admission(service, ledger):
            result = ledger.check(service)
            if service == 'codex':
                self.seed('claude', 100)
            return result
        with patch.object(balance.usage, 'require_admission', side_effect=admission):
            result, _ = balance._evaluate(self.ledger)
        self.assertFalse(result['allowed'])
        self.assertTrue(any('daily_limit' in reason for reason in result['reasons']), result)

    def test_concurrent_refresh_cannot_hide_missing_scoped_pool(self):
        self.seed('claude', 0, [dict(pool='scoped', used_percent=0, resets_at=time.time()+604800)])
        def admission(service, ledger):
            result = ledger.check(service)
            if service == 'codex':
                self.seed('claude', 0)
            return result
        with patch.object(balance.usage, 'require_admission', side_effect=admission):
            result, _ = balance._evaluate(self.ledger)
        self.assertFalse(result['allowed'])
        self.assertTrue(any('incomplete_pools' in reason for reason in result['reasons']), result)

    def test_repeated_race_stops_after_one_read_only_reevaluation(self):
        original = self.ledger.check
        def inconsistent(service):
            result = original(service)
            if service == 'claude':
                result['observed_at'] -= 1
            return result
        with self.ledger._connect() as db:
            before = balance._snapshot(db)
        with patch.object(self.ledger, 'check', side_effect=inconsistent) as check, \
                patch.object(balance, '_evaluate', wraps=balance._evaluate) as evaluate, \
                patch.object(balance.usage, 'require_admission', side_effect=lambda service, ledger: ledger.check(service)) as refresh:
            result, _ = balance._evaluate(self.ledger)
        self.assertFalse(result['allowed'])
        self.assertEqual(evaluate.call_count, 2)
        self.assertEqual(refresh.call_count, 2)
        self.assertEqual(check.call_count, 4)
        with self.ledger._connect() as db:
            self.assertEqual(before, balance._snapshot(db))

    def test_mixed_refresh_failure_and_race_never_retries(self):
        def admission(service, ledger):
            result = ledger.check(service)
            if service == 'claude':
                result.update(allowed=False, reasons=['quota_refresh_failed'])
            else:
                self.seed('claude', 1)
            return result
        with patch.object(balance.usage, 'require_admission', side_effect=admission), \
                patch.object(balance, '_evaluate', wraps=balance._evaluate) as evaluate:
            result, _ = balance._evaluate(self.ledger)
        self.assertFalse(result['allowed'])
        self.assertEqual(evaluate.call_count, 1)

    def test_invalid_requests_metadata_and_no_key(self):
        for edit in ({'provider': 'openai-api'}, {'id': 'unsafe id'}, {'fingerprint': 'abc'}, {'prompt': 'private'}):
            with self.assertRaises(ValueError):
                balance.reserve(self.ledger, dict(self.request(), **edit))
        balance.reserve(self.ledger, self.request())
        with self.assertRaises(ValueError):
            balance.finish(self.ledger, 'task', 'completed', {'duration_seconds': float('nan')})
        with self.ledger._connect() as db:
            config = balance._load(db)
            del config['hmac_key']
            balance._save(db, config)
        self.assertEqual(balance.status(self.ledger)['status'], 'fingerprint_key_missing')

    def test_short_window_gate(self):
        short = dict(pool='short', used_percent=0, resets_at=time.time() + 3600,
                     window_minutes=60, window_source='claude.native_limit_kind')
        self.ledger.budget_defaults(strategy='adaptive')
        self.seed('claude', extra=[short])
        self.seed('codex')
        result = balance.status(self.ledger)
        self.assertTrue(result['allowed'], result)
        self.assertEqual(result['services']['claude']['progress'], 0)
        short['used_percent'] = 100
        self.seed('claude', extra=[short])
        self.assertFalse(balance.reserve(self.ledger, self.request())['allowed'])

    def test_asymmetric_daily_budgets(self):
        self.ledger.budget_set('claude', 'fixed', daily_limit=40)
        self.seed('claude', 10)
        self.seed('codex', 8)
        result = balance.status(self.ledger)
        self.assertAlmostEqual(result['services']['claude']['progress'], .25)
        self.assertAlmostEqual(result['services']['codex']['progress'], .4)
        self.assertEqual(balance.reserve(self.ledger, self.request())['service'], 'claude')

    def test_stale_new_day_and_credit_stop(self):
        with patch.object(balance.time, 'time', return_value=time.time() + 86400):
            self.assertFalse(balance.reserve(self.ledger, self.request())['allowed'])
        with patch.object(credits, 'codex_owner_policy', return_value=None):
            result = balance.reserve(self.ledger, self.request())
        self.assertTrue(any('native_paid_execution_unsupported' in r for r in result['reasons']))
        with self.ledger._connect() as db:
            state = self.ledger._service(db, 'claude')
            state['complete'] = False
            db.execute("UPDATE state SET value=? WHERE key='service:claude'", (json.dumps(state),))
        self.assertFalse(balance.reserve(self.ledger, self.request())['allowed'])

    def test_busy_laggard_stays_in_progress_comparison(self):
        balance.reserve(self.ledger, self.request('busy', provider='claude'))
        self.seed('codex', 8)
        result = balance.reserve(self.ledger, self.request('next'))
        self.assertEqual(result['status'], 'busy')
        self.assertEqual(result['jobs'][0]['id'], 'busy')

    def test_zero_ceiling_blocks_and_local_fingerprint_is_stable(self):
        original = self.ledger.check
        def invalid(service, ledger):
            result = original(service)
            result['pools'][0]['daily_ceiling'] = 0
            return result
        with patch.object(balance.usage, 'require_admission', side_effect=invalid):
            self.assertFalse(balance.reserve(self.ledger, self.request())['allowed'])
        local = Ledger(Path(self.tmp.name) / 'client.db')
        first = balance.fingerprint(local, b'task')
        self.assertEqual(first, balance.fingerprint(local, b'task'))
        with local._connect() as db:
            self.assertFalse(balance._load(db)['enabled'])

    def test_unsupported_default_reported_and_explicit_api_rejected(self):
        self.ledger.complete_setup(services=['codex', 'claude', 'cursor'], api_services=['openai'], source='test')
        result = balance.configure(self.ledger, True)
        self.assertEqual(result['unsupported_services'], ['cursor'])
        self.assertEqual(result['api_services_excluded'], ['openai'])
        with self.assertRaises(ValueError):
            balance.configure(self.ledger, True, services=['codex', 'openai'])

    def test_safe_decision_and_aggregate_completion_evidence(self):
        request = self.request('evidence')
        before = balance.reserve(self.ledger, request)
        snapshot = before['job']['before']['claude']
        self.assertEqual(snapshot['binding_pool'], 'weekly')
        self.assertEqual(snapshot['progress'], 0)
        self.assertNotIn('hmac_key', json.dumps(before))
        self.assertNotIn('anchor', json.dumps(before['job']))
        self.seed('claude', 2)
        result = balance.finish(self.ledger, 'evidence', 'completed')
        after = result['job']['after']
        self.assertEqual(after['status'], 'observed')
        self.assertEqual(after['observation']['pools'][0]['daily_consumed'], 2)
        self.assertFalse(after['per_task_attribution'])
        self.assertEqual(after['usage_attribution'], 'aggregate_account_only')

    def test_failed_refresh_never_loses_terminal_result(self):
        balance.reserve(self.ledger, self.request('failed'))
        with patch.object(balance.usage, 'require_admission', side_effect=RuntimeError('offline')):
            result = balance.finish(self.ledger, 'failed', 'failed', {'exit_code': 1})
        self.assertTrue(result['allowed'])
        self.assertEqual(result['job']['status'], 'failed')
        self.assertEqual(result['job']['after']['status'], 'unavailable')
        self.assertIsNone(result['job']['after']['observation'])

    def test_bounded_status_preserves_fairness_history(self):
        balance.reserve(self.ledger, self.request('open'))
        day = self.ledger._day(time.time())
        with self.ledger._connect() as db:
            for n in range(60):
                job = dict(id=str(n), service='codex', day=day, status='completed', created_at=time.time())
                db.execute('INSERT INTO balance_jobs VALUES (?, ?, ?, ?, ?)',
                           (str(n), 'codex', day, 'completed', json.dumps(job)))
        result = balance.status(self.ledger)
        self.assertEqual(len(result['jobs']), 51)
        self.assertEqual(result['dispatch_counts_today']['codex'], 60)
        self.assertEqual(result['drift_status'], 'within_tolerance')
        self.assertEqual(result['max_lead'], .15)
        with self.ledger._connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM balance_jobs').fetchone()[0], 61)

    def test_malformed_disabled_policy_fails_closed(self):
        with self.ledger._connect() as db:
            config = balance._load(db)
            config['enabled'] = 'false'
            balance._save(db, config)
        with self.assertRaises(ValueError):
            balance.status(self.ledger)
        with self.assertRaises(ValueError):
            balance.configure(self.ledger, True)

    def test_client_subset_blocks_before_refresh_without_job(self):
        with patch.object(balance.usage, 'require_admission') as refresh:
            result = balance.reserve(self.ledger, self.request(), client_services=['codex'])
        self.assertEqual(result['status'], 'service_not_configured_on_client')
        refresh.assert_not_called()
        with self.ledger._connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM balance_jobs').fetchone()[0], 0)
        for services in ([], ['codex', 'codex'], 'codex', [3]):
            with self.assertRaises(ValueError):
                balance.reserve(self.ledger, self.request(), client_services=services)

    def test_client_subset_rechecked_after_config_expansion(self):
        original = balance._evaluate
        def evaluate(*args, **kwargs):
            result = original(*args, **kwargs)
            with self.ledger._connect() as db:
                config = balance._load(db)
                config['services'].append('antigravity')
                balance._save(db, config)
            return result
        with patch.object(balance, '_evaluate', side_effect=evaluate):
            result = balance.reserve(self.ledger, self.request(), client_services=['claude', 'codex'])
        self.assertEqual(result['status'], 'service_not_configured_on_client')
        with self.ledger._connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM balance_jobs').fetchone()[0], 0)

    def test_start_refreshes_all_and_denies_unselected_quota_stop(self):
        balance.reserve(self.ledger, self.request('start', provider='codex'))
        self.seed('claude', 100)
        result = balance.start(self.ledger, 'start')
        self.assertFalse(result['allowed'])
        self.assertEqual(result['job']['status'], 'denied')
        self.assertTrue(any('claude:quota_denied' in r for r in result['reasons']))
        with patch.object(balance.usage, 'require_admission') as refresh:
            self.assertFalse(balance.start(self.ledger, 'start')['allowed'])
        refresh.assert_not_called()

    def test_start_rechecks_atomic_snapshot_and_disabled_policy(self):
        balance.reserve(self.ledger, self.request('start'))
        original = balance._evaluate
        def evaluate(*args, **kwargs):
            result = original(*args, **kwargs)
            self.ledger.set_mode('strict')
            return result
        with patch.object(balance, '_evaluate', side_effect=evaluate):
            result = balance.start(self.ledger, 'start')
        self.assertEqual(result['status'], 'denied')
        self.assertIn('state_changed', result['reasons'])
        self.ledger.set_mode('observed')
        balance.reserve(self.ledger, self.request('disabled'))
        balance.configure(self.ledger, False)
        result = balance.start(self.ledger, 'disabled')
        self.assertFalse(result['allowed'])
        self.assertEqual(result['status'], 'denied')

    def test_start_duplicate_never_refreshes_or_redispatches(self):
        balance.reserve(self.ledger, self.request('start'))
        self.assertTrue(balance.start(self.ledger, 'start')['allowed'])
        with patch.object(balance.usage, 'require_admission') as refresh:
            result = balance.start(self.ledger, 'start')
        self.assertFalse(result['allowed'])
        self.assertFalse(result['dispatch_required'])
        refresh.assert_not_called()

    def test_start_denies_new_lead_even_when_all_quota_is_allowed(self):
        balance.reserve(self.ledger, self.request('leader', provider='codex'))
        self.seed('codex', 8)
        self.assertTrue(self.ledger.check('codex')['allowed'])
        self.assertTrue(self.ledger.check('claude')['allowed'])
        result = balance.start(self.ledger, 'leader')
        self.assertFalse(result['allowed'])
        self.assertEqual(result['status'], 'denied')
        self.assertIn('max_lead_exceeded', result['reasons'])
        self.assertEqual(result['job']['start_admission']['services']['codex']['progress'], .4)

    def test_status_wire_size_preserves_unresolved_jobs(self):
        balance.reserve(self.ledger, self.request('open-claude', provider='claude'))
        balance.reserve(self.ledger, self.request('open-codex', provider='codex'))
        day = self.ledger._day(time.time())
        large = {'pools': [{'pool': 'weekly', 'evidence': 'x' * 1000}] * 10}
        with self.ledger._connect() as db:
            for n in range(50):
                job = dict(id=f'old-{n}', service='codex', day=day, status='completed',
                           created_at=time.time(), before=large, after=large, start_admission=large)
                db.execute('INSERT INTO balance_jobs VALUES (?, ?, ?, ?, ?)',
                           (job['id'], 'codex', day, 'completed', json.dumps(job)))
        result = balance.status(self.ledger)
        self.assertLess(len(json.dumps(result).encode()), 256 * 1024)
        unresolved = {job['id'] for job in result['jobs'] if job['status'] in balance.OPEN}
        self.assertEqual(unresolved, {'open-claude', 'open-codex'})
        self.assertEqual(len(result['jobs']), 52)
        self.assertTrue(all('before' not in job and 'after' not in job and 'start_admission' not in job
                            for job in result['jobs']))
        self.assertTrue(all('reset_history' not in service for service in result['services'].values()))
        with self.ledger._connect() as db:
            raw = json.loads(db.execute("SELECT value FROM balance_jobs WHERE id='old-0'").fetchone()[0])
        self.assertEqual(raw['before'], large)

    def test_model_constraints_match_role_service_and_supervision(self):
        self.ledger.complete_setup(services=['codex', 'claude', 'antigravity'], api_services=[], source='test')
        rules = [dict(service='antigravity', model='model-*', roles=['manager', 'reviewer', 'verifier'])]
        with patch.object(balance.usage, 'require_admission') as refresh:
            balance.set_constraints(self.ledger, rules)
            for role in ('manager', 'reviewer', 'verifier'):
                result = balance.role_admission(self.ledger, 'antigravity', 'model-pro', role)
                self.assertFalse(result['allowed'])
                self.assertEqual(result['status'], 'supervision_required')
                supervised = balance.role_admission(self.ledger, 'antigravity', 'model-pro', role, supervised=True)
                self.assertTrue(supervised['allowed'])
                self.assertTrue(supervised['requires_supervision'])
            for role in ('worker', 'investigator'):
                self.assertTrue(balance.role_admission(self.ledger, 'antigravity', 'model-pro', role)['allowed'])
            for service in ('codex', 'claude'):
                self.assertTrue(balance.role_admission(self.ledger, service, 'model-pro', 'reviewer')['allowed'])
            self.assertTrue(balance.role_admission(self.ledger, 'antigravity', 'other', 'reviewer')['allowed'])
        refresh.assert_not_called()

    def test_constraint_globs_treat_model_brackets_literally(self):
        balance.set_constraints(self.ledger, [dict(service='claude', model='model-?[1m]', roles=['worker'])])
        self.assertFalse(balance.role_admission(self.ledger, 'claude', 'model-a[1m]', 'worker')['allowed'])
        self.assertTrue(balance.role_admission(self.ledger, 'claude', 'model-a1', 'worker')['allowed'])
        self.assertTrue(balance.role_admission(self.ledger, 'claude', 'model-ab[1m]', 'worker')['allowed'])
        self.assertTrue(balance.role_admission(self.ledger, 'claude', 'MODEL-a[1m]', 'worker')['allowed'])

    def test_constraints_preserved_disabled_and_configure_omission(self):
        rules = [dict(service='claude', model='*', roles=['reviewer'])]
        with self.ledger._connect() as db:
            before = balance._snapshot(db)
        balance.set_constraints(self.ledger, rules)
        with self.ledger._connect() as db:
            after = balance._snapshot(db)
        self.assertEqual({k: v for k, v in before.items() if k != balance.KEY},
                         {k: v for k, v in after.items() if k != balance.KEY})
        self.assertTrue(balance.configure(self.ledger, False)['solo_blocked'])
        self.assertFalse(balance.role_admission(self.ledger, 'claude', 'any', 'reviewer')['allowed'])
        self.assertEqual(balance.status(self.ledger)['solo_blocked'], rules)
        self.assertTrue(balance.configure(self.ledger, True)['allowed'])
        self.assertFalse(balance.role_admission(self.ledger, 'claude', 'any', 'reviewer')['allowed'])
        balance.configure(self.ledger, False, solo_blocked=[])
        self.assertTrue(balance.role_admission(self.ledger, 'claude', 'any', 'reviewer')['allowed'])

    def test_constraint_invalid_or_unauthorized_rules_fail_closed(self):
        valid = dict(service='claude', model='*', roles=['reviewer'])
        for rules in (None, [valid] * 33, [dict(valid, model='a' * 201)],
                      [dict(valid, service='openai')], [dict(valid, roles=['unknown'])],
                      [dict(valid, roles=['reviewer', 'reviewer'])], [dict(valid, prompt='private')],
                      [dict(valid, service='antigravity')]):
            with self.assertRaises(ValueError):
                balance.set_constraints(self.ledger, rules)
        with self.ledger._connect() as db:
            config = balance._load(db)
            config['solo_blocked'] = [dict(valid, roles=[])]
            balance._save(db, config)
        result = balance.role_admission(self.ledger, 'claude', 'any', 'worker')
        self.assertFalse(result['allowed'])
        self.assertEqual(result['status'], 'invalid_role_policy')

    def test_role_admission_arguments_setup_and_legacy_default(self):
        self.assertTrue(balance.role_admission(self.ledger, 'codex', 'any', 'manager')['allowed'])
        self.assertFalse(balance.role_admission(self.ledger, 'antigravity', 'any', 'worker')['allowed'])
        for args in (('codex', '*', 'worker'), ('codex', 'any', 'bad'), ('api', 'any', 'worker')):
            with self.assertRaises(ValueError):
                balance.role_admission(self.ledger, *args)
        with self.assertRaises(ValueError):
            balance.role_admission(self.ledger, 'codex', 'any', 'worker', supervised=1)

    def test_unknown_actual_model_cannot_evade_constraints(self):
        balance.set_constraints(self.ledger, [dict(service='codex', model='only-one-model', roles=['reviewer'])])
        result = balance.role_admission(self.ledger, 'codex', None, 'reviewer')
        self.assertFalse(result['allowed'])
        self.assertEqual(result['status'], 'model_identity_unverified')
        supervised = balance.role_admission(self.ledger, 'codex', None, 'reviewer', supervised=True)
        self.assertTrue(supervised['allowed'])
        self.assertTrue(supervised['requires_supervision'])
        self.assertTrue(balance.role_admission(self.ledger, 'codex', None, 'worker')['allowed'])
        self.assertTrue(balance.role_admission(self.ledger, 'claude', None, 'reviewer')['allowed'])


if __name__ == '__main__':
    unittest.main()
