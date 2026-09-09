import io
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

import coordination
import free_access
import harness
import onboard
from quota import Ledger
from spend import SpendLedger


class Terminal(io.StringIO):
    def isatty(self):
        return True


class OnboardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.db = self.root / 'quota.sqlite3'
        self.config = self.root / 'free.json'
        self.env = patch.dict(os.environ, {'XDG_STATE_HOME': str(self.root / 'state')})
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_onboard(self, provider, answers='', tty=True):
        output = io.StringIO()
        stream = Terminal(answers) if tty else io.StringIO(answers)
        with patch.object(harness, 'discover_provider', return_value={
                'status': 'available', 'auth': {'status': 'subscription'}}):
            result = onboard.main([provider, '--ledger', str(self.db), '--free-config', str(self.config)],
                                  input_stream=stream, output_stream=output)
        return result, output.getvalue()

    def existing(self, api=False, authority='local'):
        ledger = Ledger(self.db, timezone='Europe/Warsaw')
        ledger.set_mode('observed')
        ledger.budget_defaults(strategy='window', reserve=11, daily_limit=23)
        ledger.budget_calendar(workdays=[0, 2, 4], reset_cutoff='09:45')
        coordination.configure(ledger, authority, 8)
        ledger.complete_setup(services=['codex'], api_services=['xai'] if api else [], source='test')
        if api:
            money = SpendLedger(ledger=ledger)
            money.configure('total', '12.34', mode='observed')
            money.add('total', '1', grant_id='existing-grant')
        return ledger

    def snapshot(self):
        with closing(sqlite3.connect(self.db)) as db:
            return {table: db.execute('SELECT * FROM "' + table + '" ORDER BY 1').fetchall()
                    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def test_native_addition_preserves_all_other_state(self):
        ledger = self.existing(api=True)
        before = self.snapshot()
        code, output = self.run_onboard('copilot', 'native\nyes\nno\n')
        self.assertEqual(code, 0, output)
        after = self.snapshot()
        before['state'] = [r for r in before['state'] if r[0] != 'setup_v1']
        after['state'] = [r for r in after['state'] if r[0] != 'setup_v1']
        self.assertEqual(before, after)
        self.assertEqual(set(ledger.setup_status()['services']), {'codex', 'copilot'})
        self.assertEqual(ledger.setup_status()['api_services'], ['xai'])

    def test_cancel_and_eof_leave_existing_bytes_and_new_home_unchanged(self):
        self.existing()
        before = self.db.read_bytes()
        for answers in ('native\nno\n', 'native\n', 'cancel\n'):
            code, output = self.run_onboard('copilot', answers)
            self.assertEqual(code, 130, output)
            self.assertEqual(self.db.read_bytes(), before)
        self.db.unlink()
        for answers in ('', 'native\n', 'native\nobserved\nlocal\nno\n'):
            code, output = self.run_onboard('copilot', answers)
            self.assertEqual(code, 130, output)
            self.assertFalse(self.db.exists())
            self.assertFalse(self.config.exists())

    def test_non_tty_unknown_and_leaf_fail_without_storage_access(self):
        with patch.object(onboard, 'Ledger', side_effect=AssertionError('storage accessed')):
            self.assertEqual(self.run_onboard('copilot', tty=False)[0], 2)
        self.assertEqual(self.run_onboard('not-a-provider', 'native\nyes\n')[0], 2)
        with patch.dict(os.environ, {'SESSION_HARNESS_LEAF': '1'}):
            self.assertEqual(self.run_onboard('copilot', 'native\nyes\n')[0], 2)
        self.assertFalse(self.db.exists())

    def test_missing_key_and_remote_api_preserve_state(self):
        self.existing(authority='trusted-authority')
        before = self.db.read_bytes()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fake-key-never-print-this'}):
            code, output = self.run_onboard('openai', 'api\nyes\n')
        self.assertEqual(code, 2, output)
        self.assertNotIn('fake-key-never-print-this', output)
        self.assertEqual(self.db.read_bytes(), before)
        coordination.configure(Ledger(self.db), 'local', 8)
        before = self.db.read_bytes()
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            self.assertEqual(self.run_onboard('openai', 'api\nyes\n')[0], 2)
        self.assertEqual(self.db.read_bytes(), before)

    def test_api_preserves_existing_caps_and_auth_and_redacts_key(self):
        ledger = self.existing(api=True)
        before = self.snapshot()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fake-key-never-print-this'}):
            code, output = self.run_onboard('openai', 'api\nyes\nno\n')
        self.assertEqual(code, 0, output)
        self.assertNotIn('fake-key-never-print-this', output)
        after = self.snapshot()
        for snapshot in (before, after):
            snapshot['state'] = [r for r in snapshot['state'] if r[0] != 'setup_v1']
        self.assertEqual(before, after)
        self.assertEqual(set(ledger.setup_status()['api_services']), {'xai', 'openai'})

    def test_new_api_requires_explicit_positive_cap_and_money_mode(self):
        for cap, mode, expected in [('0', 'observed', 2), ('5', 'strict', 0), ('5', 'observed', 0)]:
            if self.db.exists():
                self.db.unlink()
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'fake-key-never-print-this'}):
                code, output = self.run_onboard('openai', f'api\nstrict\nlocal\n{cap}\n{mode}\nyes\nno\n')
            self.assertEqual(code, expected, output)
            self.assertNotIn('fake-key-never-print-this', output)
            if expected:
                self.assertFalse(self.db.exists())
            else:
                with closing(sqlite3.connect(self.db)) as db:
                    self.assertEqual(db.execute("SELECT mode FROM money_caps WHERE scope='total'").fetchone()[0], mode)

    def test_native_auth_failure_and_exception_are_sanitized_before_writes(self):
        self.existing()
        original = self.db.read_bytes()
        for response in ({'status': 'auth_required'}, harness.HarnessError('provider_error', 'fake-key-never-print-this')):
            output = io.StringIO()
            with patch.object(harness, 'discover_provider',
                              side_effect=response if isinstance(response, Exception) else None, return_value=response):
                code = onboard.main(['copilot', '--ledger', str(self.db)],
                                    input_stream=Terminal('native\nyes\n'), output_stream=output)
            self.assertEqual(code, 2, output.getvalue())
            self.assertNotIn('fake-key-never-print-this', output.getvalue())
            self.assertEqual(original, self.db.read_bytes())

    def test_native_remote_authority_stays_shared(self):
        ledger = self.existing(authority='trusted-authority')
        code, output = self.run_onboard('copilot', 'native\nyes\nno\n')
        self.assertEqual(code, 0, output)
        self.assertEqual(coordination.settings(ledger), {'authority': 'trusted-authority', 'max_sessions': 8})
        self.assertIn('Shared authority', output)

    def test_local_catalog_is_bounded_without_setup_or_fallback(self):
        import local_ollama
        from api_transport import APIError
        for response in ([], APIError('local_transport_error')):
            with patch.object(local_ollama, 'models', side_effect=response if isinstance(response, Exception) else None,
                              return_value=response) as models:
                started = time.monotonic()
                code, output = self.run_onboard('ollama', 'local\nyes\n')
                self.assertEqual(code, 2, output)
                deadline = models.call_args.kwargs.get('deadline', models.call_args.args[0] if models.call_args.args else 0)
                self.assertLessEqual(deadline, started + 5.5)
        self.assertFalse(self.db.exists())

    def test_free_import_preserves_other_rows_and_cancel(self):
        before = {'schema_version': 2, 'authority': 'local', 'mode': 'observed',
                  'enabled': False, 'mixed_work': False,
                  'accounts': {'groq': {'enabled': False, 'reason': 'keep this'},
                               'mistral': {'enabled': False, 'reason': 'old'}}}
        free_access.save_config(before, self.config)
        source = self.root / 'import.json'
        incoming = {**before, 'accounts': {'mistral': {'enabled': False, 'reason': 'new'}}}
        free_access.save_config(incoming, source)
        original = self.config.read_bytes()
        code, output = self.run_onboard('mistral', f'free\n{source}\nno\n')
        self.assertEqual(code, 130, output)
        self.assertEqual(original, self.config.read_bytes())
        code, output = self.run_onboard('mistral', f'free\n{source}\nyes\nyes\n')
        self.assertEqual(code, 0, output)
        result = free_access.load_config(self.config)
        self.assertEqual(result['accounts']['groq'], before['accounts']['groq'])
        self.assertEqual(result['accounts']['mistral'], incoming['accounts']['mistral'])
        self.assertFalse(result['enabled'])
        self.assertFalse(result['mixed_work'])
        self.assertFalse(self.db.exists())

    def test_free_stale_import_remote_executor_and_malformed_data_do_not_write(self):
        from test_free_accounts import AccountTests
        fixture = AccountTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.row['evidence'].update(observed_at=time.time() - 100, expires_at=time.time() - 1)
        source = self.root / 'stale.json'
        free_access.save_config(fixture.config, source)
        code, output = self.run_onboard('groq', f'free\n{source}\nyes\nyes\n')
        self.assertEqual(code, 2, output)
        self.assertIn('expired', output)
        self.assertFalse(self.config.exists())
        remote = {'schema_version': 2, 'authority': 'ssh', 'mode': 'observed',
                  'enabled': True, 'mixed_work': False, 'command': ['ssh', 'trusted-host', 'ai-session', 'free', 'serve']}
        free_access.save_config(remote, self.config)
        before = self.config.read_bytes()
        code, output = self.run_onboard('groq', f'free\n{source}\nyes\n')
        self.assertEqual(code, 2, output)
        self.assertEqual(before, self.config.read_bytes())
        self.config.unlink()
        source.write_text('{"secret":"fake-key-never-print-this", broken')
        source.chmod(0o600)
        code, output = self.run_onboard('groq', f'free\n{source}\nyes\n')
        self.assertEqual(code, 2, output)
        self.assertNotIn('fake-key-never-print-this', output)
        self.assertFalse(self.config.exists())

    def test_disabled_fresh_free_import_skips_enable_prompt_and_redacts_shape_errors(self):
        source = self.root / 'disabled.json'
        free_access.save_config({'schema_version': 2, 'authority': 'local', 'mode': 'observed',
                                'enabled': False, 'mixed_work': False,
                                'accounts': {'groq': {'enabled': False, 'reason': 'unverified'}}}, source)
        code, output = self.run_onboard('groq', f'free\n{source}\nyes\n')
        self.assertEqual(code, 0, output)
        self.assertNotIn('Enable this free group?', output)
        self.assertFalse(free_access.load_config(self.config)['enabled'])
        for error in (KeyError('fake-key-never-print-this'), TypeError('fake-key-never-print-this')):
            with patch.object(free_access, 'load_config', side_effect=error):
                code, output = self.run_onboard('groq', 'free\n')
            self.assertEqual(code, 2, output)
            self.assertNotIn('fake-key-never-print-this', output)

    def test_core_both_spellings_dispatch_to_one_wizard(self):
        with patch.object(onboard, 'main', return_value=0) as main:
            self.assertEqual(harness.main(['onboard', 'claude', '--list']), 0)
            main.assert_called_with(['claude', '--list'])
            self.assertEqual(harness.main(['claude', 'onboard', '--list']), 0)
            main.assert_called_with(['claude', '--list'])


if __name__ == '__main__':
    unittest.main()
