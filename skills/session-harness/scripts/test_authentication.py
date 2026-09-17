import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import authentication as auth
from quota import Ledger


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        free_config = patch('free_access.load_config', return_value=None)
        free_config.start()
        self.addCleanup(free_config.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = Ledger(Path(self.tmp.name) / 'ledger.db')
        self.ledger.complete_setup(services=['copilot'], api_services=[], source='test')

    def test_regression_requires_verified_history_and_unknown_preserves_it(self):
        with patch.object(auth, 'probe', return_value='signed_out'):
            self.assertEqual(auth.status(self.ledger)['providers']['copilot']['status'], 'signed_out')
        with patch.object(auth, 'probe', return_value='authenticated'):
            auth.status(self.ledger)
        with patch.object(auth, 'probe', return_value='unverified'):
            self.assertEqual(auth.status(self.ledger)['providers']['copilot']['status'], 'unverified')
        with patch.object(auth, 'probe', return_value='signed_out'):
            result = auth.status(self.ledger)
        self.assertEqual(result['providers']['copilot']['status'], 'lost_login')
        with self.ledger._connect() as db:
            saved = json.loads(db.execute('SELECT value FROM state WHERE key=?', (auth.HISTORY,)).fetchone()[0])
        self.assertEqual(set(saved), {'copilot'})
        self.assertNotIn('account_email', json.dumps(result))
        self.assertNotIn('token', json.dumps(result))
        if auth.os.name != 'nt':
            self.assertEqual(self.ledger.path.stat().st_mode & 0o777, 0o600)

    def test_copilot_boolean_only_no_catalog_or_error_text_logout(self):
        for payload, expected in [({'isAuthenticated': True}, 'authenticated'),
                                  ({'isAuthenticated': False}, 'signed_out'),
                                  ({'isAuthenticated': 'false'}, 'unverified'), ({}, 'unverified')]:
            client = Mock()
            client.request.return_value = payload
            with patch.object(auth.harness.platform_runtime, 'which', return_value='/native/copilot'), patch.object(auth.inventory, 'MetadataRPC', return_value=client):
                self.assertEqual(auth.probe('copilot'), expected)
            client.request.assert_called_once_with('auth.getStatus')
            client.close.assert_called_once()
        with patch.object(auth.harness.platform_runtime, 'which', return_value='/native/copilot'), patch.object(auth.inventory, 'MetadataRPC', side_effect=auth.harness.HarnessError('auth_required', 'network login error')):
            self.assertEqual(auth.probe('copilot'), 'unverified')

    def test_corrupt_history_never_claims_lost_login(self):
        with self.ledger._connect() as db:
            db.execute('INSERT INTO state VALUES (?,?)', (auth.HISTORY, '{broken'))
        with patch.object(auth, 'probe', return_value='signed_out'):
            result = auth.status(self.ledger)
        self.assertEqual(result['history'], 'unavailable')
        self.assertEqual(result['providers']['copilot']['status'], 'signed_out')

    def test_external_ledger_without_local_storage_reports_current_state(self):
        class ExternalLedger:
            def setup_status(self):
                return {'services': ['copilot']}
        with patch.object(auth, 'probe', return_value='signed_out'):
            result = auth.status(ExternalLedger())
        self.assertEqual(result['history'], 'unavailable')
        self.assertEqual(result['providers']['copilot']['status'], 'signed_out')

    def test_noninteractive_login_and_startup_have_no_side_effect(self):
        with patch.object(auth.sys, 'stdin', io.StringIO()), patch.object(auth.sys, 'stdout', io.StringIO()), patch.object(auth.supervision, 'run_terminal') as execute, patch.object(auth, 'probe', return_value='signed_out'):
            self.assertEqual(auth.login('copilot', self.ledger)['status'], 'interactive_required')
            auth.startup(self.ledger)
        execute.assert_not_called()

    def test_unavailable_history_does_not_replace_native_admission(self):
        with patch.object(auth, 'Ledger', side_effect=RuntimeError('Could not determine home directory.')), patch.object(auth, 'login') as login, patch.object(auth.sys, 'stderr', io.StringIO()):
            result = auth.startup()
        self.assertEqual(result['status'], 'authentication_unavailable')
        self.assertFalse(result['admission_verified'])
        login.assert_not_called()

    def test_optional_free_configuration_without_home_is_unverified(self):
        with patch('builtins.__import__', side_effect=RuntimeError('Could not determine home directory.')):
            self.assertEqual(auth.free_status(), {'configuration': {'status': 'unverified'}})

    def test_expired_plan_is_not_a_logout_and_browser_requires_explicit_tty(self):
        config = {'enabled': True, 'authority': 'local', 'accounts': {
            'groq': {'enabled': True, 'evidence': {'expires_at': 1}}}}
        with patch('free_access.load_config', return_value=config), patch.object(auth, 'probe', return_value='authenticated'), patch.object(auth.sys, 'stdin', io.StringIO()), patch.object(auth.webbrowser, 'open') as browser:
            report = auth.status(self.ledger)
            self.assertEqual(report['free_accounts']['groq']['status'], 'account_verification_required')
            self.assertEqual(auth.login('groq', self.ledger)['status'], 'interactive_required')
        browser.assert_not_called()

    @unittest.skipIf(auth.os.name == 'nt', 'Windows returns a manual native command')
    def test_deadline_stop_from_real_watch_is_reported_without_traceback(self):
        terminal = Mock()
        terminal.isatty.return_value = True
        def execute(argv, environment, provider, **options):
            with patch.object(auth.time, 'monotonic', return_value=float('inf')):
                auth.supervision.Watch(provider, check=options['check']).start()
        with patch.object(auth.sys, 'stdin', terminal), patch.object(auth.sys, 'stdout', terminal), patch.object(auth.harness.platform_runtime, 'which', return_value='/native/copilot'), patch.object(auth.supervision, 'run_terminal', side_effect=execute), patch.object(auth, 'probe', return_value='unverified'), patch.object(auth.time, 'monotonic', side_effect=[0, 601]):
            result = auth.login('copilot', self.ledger)
        self.assertEqual(result['status'], 'login_timeout')

    @unittest.skipIf(auth.os.name == 'nt', 'Windows returns a manual native command')
    def test_login_rechecks_status_and_cleans_up_timeout(self):
        terminal = Mock()
        terminal.isatty.return_value = True
        for failure in (None, TimeoutError(), KeyboardInterrupt()):
            with patch.object(auth.sys, 'stdin', terminal), patch.object(auth.sys, 'stdout', terminal), patch.object(auth.harness.platform_runtime, 'which', return_value='/native/copilot'), patch.object(auth.supervision, 'run_terminal', return_value=0, side_effect=failure) as execute, patch.object(auth, 'probe', return_value='unverified'):
                result = auth.login('copilot', self.ledger)
            self.assertNotEqual(result['status'], 'authenticated')
            self.assertEqual(execute.call_args.args[0], ['/native/copilot', 'login'])
            check = execute.call_args.kwargs['check']
            self.assertTrue(check('copilot')['allowed'])
            with patch.object(auth.time, 'monotonic', return_value=float('inf')):
                with self.assertRaises(TimeoutError):
                    check('copilot')



if __name__ == '__main__':
    unittest.main()
