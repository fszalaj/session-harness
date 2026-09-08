import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import balance
import balance_cli
import coordination
import harness
from quota import Ledger


class ModelConstraintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = Ledger(Path(self.temp.name) / 'ledger.sqlite3')
        self.ledger.complete_setup(services=['codex', 'claude', 'antigravity'], api_services=[], source='test')
        self.addCleanup(patch.stopall)
        patch('quota.default_path', return_value=self.ledger.path).start()
        patch.object(harness, 'require_quota').start()
        self.capability = {'review': {'status': 'available'}, 'auth': {'status': 'catalog_access'},
                           'planner': {'model': 'fixture-current', 'effort': 'medium'},
                           'supported_efforts': ['low', 'medium', 'high'], 'executable': 'never-run'}

    def restrict(self, pattern='*', roles=None):
        return balance.set_constraints(self.ledger, [{'service': 'antigravity', 'model': pattern,
            'roles': roles or ['manager', 'reviewer', 'verifier']}])

    def test_independent_review_stops_before_native_execution(self):
        self.restrict()
        with patch.object(harness, 'review_agy') as execute:
            with self.assertRaises(harness.HarnessError) as raised:
                harness.review('antigravity', b'review this', 1, self.capability)
        self.assertEqual(raised.exception.status, 'supervision_required')
        execute.assert_not_called()

    def test_supervised_work_cannot_be_an_independent_approval(self):
        self.restrict(roles=['worker'])
        with patch.object(harness, 'review_agy', return_value={
            'result': 'proposed patch', 'actual_model': 'fixture-current'}):
            result = harness.review('antigravity', b'propose a patch', 1, self.capability, task=True)
        self.assertFalse(result['independent_judgment'])
        self.assertTrue(result['requires_manager_inspection'])
        self.assertEqual(result['role'], 'worker')

    def test_observed_alias_cannot_supply_independent_result(self):
        self.restrict(pattern='restricted-*')
        with patch.object(harness, 'review_agy', return_value={
            'result': 'do not accept this approval', 'actual_model': 'restricted-resolved'}) as execute:
            with self.assertRaises(harness.HarnessError) as raised:
                harness.review('antigravity', b'review this', 1, self.capability)
        self.assertEqual(raised.exception.status, 'supervision_required')
        execute.assert_called_once()

    def test_missing_observed_model_cannot_evade_a_rule(self):
        self.restrict(pattern='restricted-*')
        with patch.object(harness, 'review_agy', return_value={'result': 'unknown model', 'actual_model': None}):
            with self.assertRaises(harness.HarnessError) as raised:
                harness.review('antigravity', b'review this', 1, self.capability)
        self.assertEqual(raised.exception.status, 'model_identity_unverified')

    def test_manager_launch_checks_model_configuration(self):
        self.restrict()
        with patch.dict(harness.os.environ, {}, clear=True), \
             patch.object(harness, 'discover_provider', return_value=self.capability), \
             patch.object(harness.sys.stdin, 'isatty', return_value=True), \
             patch.object(harness.supervision, 'run_terminal') as execute, \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            code = harness.main(['launch', 'antigravity', '--execute'])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())['status'], 'supervision_required')
        execute.assert_not_called()

    def test_unreachable_authority_never_invokes_review(self):
        with patch.object(coordination, 'balance_dispatch', side_effect=ValueError('unreachable')), \
             patch.object(harness, 'review_agy') as execute:
            with self.assertRaises(harness.HarnessError) as raised:
                harness.review('antigravity', b'review this', 1, self.capability)
        self.assertEqual(raised.exception.status, 'role_policy_unavailable')
        execute.assert_not_called()

    def test_launch_preview_reports_model_restriction(self):
        self.restrict()
        with patch.object(harness, 'discover_provider', return_value=self.capability), \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            code = harness.main(['launch', 'antigravity'])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())['status'], 'supervision_required')

    def test_configuration_cli_is_authority_local_and_rpc_cannot_edit(self):
        path = Path(self.temp.name) / 'constraints.json'
        rules = [{'service': 'antigravity', 'model': '*', 'roles': ['reviewer']}]
        path.write_text(json.dumps(rules))
        with patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(balance_cli.main(['balance', 'constraints', '--file', str(path)]), 0)
        self.assertFalse(balance.role_admission(self.ledger, 'antigravity', 'fixture', 'reviewer')['allowed'])
        with self.assertRaises(ValueError):
            coordination.balance_local('set_constraints', {'rules': []}, self.ledger)
        coordination.configure(self.ledger, authority='owner@authority')
        with patch('sys.stdout', new_callable=io.StringIO), patch.object(balance, 'set_constraints') as mutate:
            self.assertEqual(balance_cli.main(['balance', 'constraints', '--file', str(path)]), 2)
        mutate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
