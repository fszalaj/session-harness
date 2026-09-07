"""Automatic maintenance integration with real profile installation and private state."""
from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import auto_install
import auto_scheduler
import auto_update
import coordination
from quota import Ledger
import releases


ROOT = Path(__file__).resolve().parents[3]


class AutoUpdateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.home = self.root / 'private home'
        self.home.mkdir()
        environment = patch.dict(os.environ, {'CODEX_HOME': str(self.home / '.codex'),
                                 'CLAUDE_CONFIG_DIR': str(self.home / '.claude'),
                                 'COPILOT_HOME': str(self.home / '.copilot')})
        environment.start()
        self.addCleanup(environment.stop)
        self.addCleanup(self.writable_cleanup)
        self.base = self.source('base', '0.1.2')
        self.incoming = self.source('incoming', '0.1.3')
        self.policy = self.home / 'owner-policy.md'
        self.policy.write_text('Private owner addendum: preserve my accounting and preferences.\n')
        self.module = auto_install.installer(self.base)
        self.install(self.base)
        self.ledger = Ledger(auto_install.state_path(self.home, 'quota.sqlite3'))
        self.ledger.complete_setup(services=['claude'], api_services=[], source='test')
        self.ledger.set_mode('observed')
        self.ledger.budget_defaults(strategy='fixed', daily_limit=17, reserve=3)
        for timestamp, used in ((1000, 20), (1001, 23)):
            self.ledger.record({'service': 'claude', 'observed_at': timestamp, 'complete': True,
                                'source': 'native-test', 'pools': [{'pool': 'weekly', 'used_percent': used,
                                                                 'resets_at': 100000}]},
                               now=timestamp, initialize=True)
        auto_install.register(self.home, self.base)
        self.metadata = {'tag_name': 'v0.1.3', '_verified_archive_sha256': 'a' * 64}

    def writable_cleanup(self):
        for path in self.root.rglob('*'):
            if not path.is_symlink():
                path.chmod(0o700 if path.is_dir() else 0o600)

    def source(self, name, version):
        source = self.root / name
        shutil.copytree(ROOT / 'profile', source / 'profile')
        for relative in ('scripts/install-agent-profile.py', 'skills/session-harness/SKILL.md',
                         'skills/session-harness/scripts/harness.py', 'LICENSE', 'NOTICE'):
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        runtime = source / 'skills/session-harness/scripts'
        for script in (ROOT / 'skills/session-harness/scripts').glob('*.py'):
            if not script.name.startswith('test_'):
                shutil.copy2(script, runtime / script.name)
        (source / 'skills/session-harness/VERSION').write_text(version + '\n')
        (source / 'skills/session-harness/local-note.md').write_text('Published baseline.\n')
        auto_install.save(source / 'RELEASE.json', {'repository': releases.REPOSITORY, 'version': version})
        return source

    def install(self, source):
        preview, internal = self.module.plan_install(self.home, source, True, personal_policy=self.policy)
        self.module.apply_install(preview, internal)
        self.module.save_installation_state(self.home, source, preview, self.policy, 'symlink', True)

    def enabled(self, hook=None):
        auto_update.save_config(self.home, {'schema': 1, 'enabled': True, 'interval_hours': 24,
                                          'authority': coordination.settings(self.ledger)['authority'],
                                          'activation_hook': str(hook) if hook else None})

    def network(self):
        stack = ExitStack()
        stack.enter_context(patch('releases.release_metadata', return_value=self.metadata))
        stack.enter_context(patch('releases.download_release', side_effect=lambda metadata, directory:
                                 Path(shutil.copytree(self.incoming, directory / 'release'))))
        return stack

    def run_update(self):
        with self.network(), patch('usage.require_admission') as usage:
            result = auto_update.run(self.home, self.ledger)
            usage.assert_not_called()
            return result

    @contextmanager
    def hook_processes(self, hook, processes):
        popen = subprocess.Popen
        hook_popen = Mock(side_effect=processes)

        def launch(args, **kwargs):
            if args[0] == str(hook):
                return hook_popen(args, **kwargs)
            return popen(args, **kwargs)

        with patch('auto_update.subprocess.Popen', side_effect=launch):
            yield hook_popen

    def state_rows(self):
        with self.ledger._connect() as db:
            return db.execute("SELECT key,value FROM state WHERE key != 'maintenance_v1' ORDER BY key").fetchall()

    def test_disabled_default_never_checks_release_or_admission(self):
        with patch('releases.release_metadata') as metadata, patch('usage.require_admission') as usage:
            self.assertEqual({'status': 'disabled', 'enabled': False}, auto_update.run(self.home, self.ledger))
            metadata.assert_not_called()
            usage.assert_not_called()
        self.assertFalse(auto_install.state_path(self.home, 'update.lock').exists())

    def test_missing_ledger_never_creates_replacement_accounting(self):
        self.enabled()
        self.ledger.path.unlink()
        with patch('auto_update.Ledger') as constructor, patch('releases.release_metadata') as metadata:
            result = auto_update.run(self.home, self.ledger)
        self.assertEqual('deferred_error', result['status'])
        self.assertFalse(self.ledger.path.exists())
        constructor.assert_not_called()
        metadata.assert_not_called()

    def test_empty_ledger_is_not_initialized_by_maintenance(self):
        self.enabled()
        self.ledger.path.write_bytes(b'')
        with patch('auto_update.Ledger') as constructor:
            result = auto_update.run(self.home, self.ledger)
        self.assertEqual('deferred_error', result['status'])
        self.assertEqual(b'', self.ledger.path.read_bytes())
        constructor.assert_not_called()

    def test_changed_authority_requires_explicit_reenable(self):
        self.enabled()
        value = auto_update.config(self.home)
        value['authority'] = 'owner@example.test'
        auto_update.save_config(self.home, value)
        before = self.state_rows()
        with patch('releases.release_metadata') as metadata:
            result = auto_update.run(self.home, self.ledger)
        self.assertEqual('deferred_error', result['status'])
        self.assertEqual(before, self.state_rows())
        metadata.assert_not_called()

    def test_newer_only_and_cadence_prevent_download_or_maintenance(self):
        self.enabled()
        for version in ('0.1.1', '0.1.2'):
            with self.subTest(version=version), patch('releases.release_metadata', return_value={'tag_name': version}), \
                    patch('releases.download_release') as download, patch('coordination.dispatch') as dispatch:
                auto_install.state_path(self.home, 'auto-update-last.json').unlink(missing_ok=True)
                self.assertEqual('current', auto_update.run(self.home, self.ledger)['status'])
                download.assert_not_called()
                dispatch.assert_not_called()
        with patch('releases.release_metadata') as metadata:
            self.assertEqual('not_due', auto_update.run(self.home, self.ledger)['status'])
            metadata.assert_not_called()

    def test_upgrade_then_second_run_preserves_private_policy_and_ledger(self):
        self.enabled()
        before = self.state_rows()
        policy = self.policy.read_bytes()
        result = self.run_update()
        self.assertEqual('updated', result['status'], result)
        self.assertEqual('0.1.3', releases.installation(self.home)['version'])
        self.assertEqual(before, self.state_rows())
        self.assertEqual(policy, self.policy.read_bytes())
        self.assertIn(policy, (self.home / '.agents/AGENTS.md').read_bytes())
        self.assertIsNone(coordination.session_status(self.ledger)['maintenance'])
        self.assertFalse(auto_install.state_path(self.home, 'update.lock').exists())
        auto_install.registered(self.home, releases.installation(self.home))
        with patch('releases.release_metadata') as metadata:
            self.assertEqual('not_due', auto_update.run(self.home, self.ledger)['status'])
            metadata.assert_not_called()
        auto_install.state_path(self.home, 'auto-update-last.json').unlink()
        self.assertEqual('current', self.run_update()['status'])
        value = auto_update.config(self.home)
        value['enabled'] = False
        auto_update.save_config(self.home, value)
        launcher = self.home / '.local/bin/ai-session'
        process = subprocess.run([sys.executable, str(launcher), 'auto-update', 'run'],
                                 env=dict(os.environ, HOME=str(self.home)), capture_output=True,
                                 text=True, timeout=20)
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual({'status': 'disabled', 'enabled': False}, json.loads(process.stdout))

    def test_incoming_installer_without_auto_update_route_preserves_current_installation(self):
        self.overlay()
        self.enabled()
        previous = releases.installation(self.home)
        registration = auto_install.registered(self.home, previous)
        accounting = self.state_rows()
        installer = self.incoming / 'scripts/install-agent-profile.py'
        original = installer.read_text()
        outdated = original.replace("'update', 'auto-update', 'coordination'", "'update', 'coordination'")
        self.assertNotEqual(original, outdated)
        installer.write_text(outdated)
        result = self.run_update()
        self.assertEqual('deferred_error', result['status'], result)
        self.assertIn('lacks automatic maintenance capability', result['detail'])
        self.assertEqual(previous, releases.installation(self.home))
        self.assertEqual(registration, auto_install.registered(self.home, previous))
        self.assertEqual(accounting, self.state_rows())
        self.assertIsNone(coordination.session_status(self.ledger)['maintenance'])
        self.assertFalse(auto_install.state_path(self.home, 'update.lock').exists())

    def test_snapshot_bytes_drift_defers_before_download(self):
        self.enabled()
        previous = releases.installation(self.home)
        target = self.home / '.local/share/session-harness/releases' / previous['source_hash'] / 'session-harness/SKILL.md'
        target.chmod(0o644)
        target.write_text('Changed immutable snapshot.\n')
        target.chmod(0o444)
        with patch('releases.release_metadata') as metadata:
            result = auto_update.run(self.home, self.ledger)
            self.assertEqual('deferred_error', result['status'])
            self.assertIn('Snapshot bytes', result['detail'])
            metadata.assert_not_called()
        self.assertEqual(previous, releases.installation(self.home))

    def test_managed_link_drift_is_preserved_and_defers(self):
        self.enabled()
        target = self.home / '.codex/AGENTS.md'
        target.unlink()
        target.write_text('Owner replacement.\n')
        with patch('releases.release_metadata') as metadata:
            result = auto_update.run(self.home, self.ledger)
            self.assertEqual('deferred_error', result['status'])
            metadata.assert_not_called()
        self.assertEqual('Owner replacement.\n', target.read_text())

    def overlay(self):
        local = self.root / 'local'
        shutil.copytree(self.base, local)
        (local / 'RELEASE.json').unlink()
        (local / 'skills/session-harness/local-note.md').write_text('Owner skill overlay.\n')
        self.install(local)
        registered = auto_install.register(self.home, self.base)
        self.assertEqual(1, len(registered['overrides']))

    def test_unregistered_installation_cannot_enable_or_auto_reconcile(self):
        auto_install.state_path(self.home, 'auto-update-installation.json').unlink()
        with patch('auto_scheduler.install') as scheduler:
            with self.assertRaises(ValueError):
                auto_update.enable(self.home, ledger=self.ledger)
            scheduler.assert_not_called()
        self.enabled()
        with patch('releases.release_metadata') as metadata:
            self.assertEqual('deferred_error', auto_update.run(self.home, self.ledger)['status'])
            metadata.assert_not_called()
        self.assertFalse(auto_install.state_path(self.home, 'auto-update-installation.json').exists())

    def test_registered_overlay_carries_forward(self):
        self.overlay()
        self.enabled()
        result = self.run_update()
        self.assertEqual('updated', result['status'], result)
        self.assertEqual(1, result['local_overlays'])
        self.assertEqual('Owner skill overlay.\n', (self.home / '.agents/skills/session-harness/local-note.md').read_text())
        self.assertEqual('checkout', releases.installation(self.home)['source'])
        auto_install.registered(self.home, releases.installation(self.home))

    def test_registered_overlay_absorbed_when_release_matches(self):
        self.overlay()
        (self.incoming / 'skills/session-harness/local-note.md').write_text('Owner skill overlay.\n')
        self.enabled()
        result = self.run_update()
        self.assertEqual('updated', result['status'], result)
        self.assertEqual(0, result['local_overlays'])
        self.assertEqual('release', releases.installation(self.home)['source'])

    def test_overlay_conflict_keeps_current_installation(self):
        self.overlay()
        before = releases.installation(self.home)
        (self.incoming / 'skills/session-harness/local-note.md').write_text('Upstream incompatible edit.\n')
        self.enabled()
        result = self.run_update()
        self.assertEqual('deferred_error', result['status'])
        self.assertIn('Overlay conflicts', result['detail'])
        self.assertEqual(before, releases.installation(self.home))
        self.assertIsNone(coordination.session_status(self.ledger)['maintenance'])

    def test_busy_native_owner_defers_without_touching_owner(self):
        self.enabled()
        with patch('usage.require_admission', return_value={'allowed': True}):
            coordination.dispatch('admit', 'claude', 'protected-owner', self.ledger)
        before = coordination.session_status(self.ledger)['sessions']
        with self.network(), patch('releases.download_release') as download:
            self.assertEqual('deferred_sessions', auto_update.run(self.home, self.ledger)['status'])
            download.assert_not_called()
        self.assertEqual(before, coordination.session_status(self.ledger)['sessions'])

    def test_acquire_lost_acknowledgement_retains_recorded_owner_for_recovery(self):
        self.enabled()
        dispatch = coordination.dispatch

        def lose_acknowledgement(action, service, owner, ledger):
            result = dispatch(action, service, owner, ledger)
            if action == 'maintenance-acquire':
                raise TimeoutError('SSH acknowledgement lost')
            return result

        previous = releases.installation(self.home)
        with patch('coordination.dispatch', side_effect=lose_acknowledgement):
            result = self.run_update()
        self.assertEqual('manual_recovery_required', result['status'], result)
        self.assertEqual(result['owner'], coordination.session_status(self.ledger)['maintenance']['owner'])
        self.assertTrue(auto_install.state_path(self.home, 'update.lock').is_dir())
        self.assertEqual(previous, releases.installation(self.home))

    def test_partial_installer_failure_restores_changed_instructions_and_old_receipt(self):
        self.enabled()
        incoming_instructions = self.incoming / 'profile/AGENTS.md'
        incoming_instructions.write_bytes(incoming_instructions.read_bytes() + b'\nNew release instruction.\n')
        previous = releases.installation(self.home)
        registration = auto_install.registered(self.home, previous)
        instructions = self.home / '.agents/AGENTS.md'
        original_bytes = instructions.read_bytes()
        accounting = self.state_rows()
        replace = os.replace
        interrupted = []

        def fail_after_first_replacement(source, destination, *args, **kwargs):
            result = replace(source, destination, *args, **kwargs)
            if Path(destination) == instructions and not interrupted:
                interrupted.append(True)
                self.assertNotEqual(original_bytes, instructions.read_bytes())
                self.assertEqual(previous, auto_install.read_json(auto_install.state_path(self.home, 'installation.json')))
                raise OSError('Injected partial installer replacement failure')
            return result

        with patch('os.replace', side_effect=fail_after_first_replacement):
            result = self.run_update()
        self.assertEqual([True], interrupted)
        self.assertEqual('deferred_error', result['status'], result)
        self.assertIn('Injected partial installer', result['detail'])
        self.assertEqual(original_bytes, instructions.read_bytes())
        self.assertEqual(previous, releases.installation(self.home))
        self.assertEqual(registration, auto_install.registered(self.home, previous))
        self.assertEqual(accounting, self.state_rows())
        self.assertIsNone(coordination.session_status(self.ledger)['maintenance'])
        self.assertFalse(auto_install.state_path(self.home, 'update.lock').exists())

    def test_activation_hook_failure_rolls_back_profile_and_receipts(self):
        hook = self.home / 'activation-hook'
        hook.write_text('#!/bin/sh\n[ "$1" != activate ]\n')
        hook.chmod(0o700)
        self.enabled(hook)
        previous = releases.installation(self.home)
        registration = auto_install.registered(self.home, previous)
        policy = (self.home / '.agents/AGENTS.md').read_bytes()
        before = self.state_rows()
        result = self.run_update()
        self.assertEqual('deferred_error', result['status'], result)
        self.assertIn('Activation hook failed during activate', result['detail'])
        self.assertEqual(previous, releases.installation(self.home))
        self.assertEqual(registration, auto_install.registered(self.home, previous))
        self.assertEqual(policy, (self.home / '.agents/AGENTS.md').read_bytes())
        self.assertEqual(before, self.state_rows())
        self.assertIsNone(coordination.session_status(self.ledger)['maintenance'])
        self.assertFalse(auto_install.state_path(self.home, 'update.lock').exists())

    def assert_unconfirmed_hook_exit_retains_maintenance(self, returncode):
        hook = self.home / 'activation-hook'
        hook.write_text('#!/bin/sh\nexit 0\n')
        hook.chmod(0o700)
        self.enabled(hook)
        accounting = self.state_rows()
        prepared = Mock(returncode=0)
        prepared.communicate.return_value = (b'', b'')
        activation = Mock(returncode=returncode)
        activation.communicate.return_value = (b'', b'')
        with self.hook_processes(hook, [prepared, activation]) as popen:
            result = self.run_update()
        self.assertEqual('manual_recovery_required', result['status'], result)
        self.assertIn('did not confirm a completed outcome during activate', result['detail'])
        self.assertEqual(['prepare', 'activate'], [call.args[0][1] for call in popen.call_args_list])
        self.assertTrue(auto_install.state_path(self.home, 'update.lock').is_dir())
        self.assertEqual(result['owner'], coordination.session_status(self.ledger)['maintenance']['owner'])
        self.assertEqual('0.1.3', releases.installation(self.home)['version'])
        self.assertEqual(accounting, self.state_rows())

    def test_temporary_failure_hook_exit_retains_maintenance_without_rollback(self):
        self.assert_unconfirmed_hook_exit_retains_maintenance(75)

    def test_signaled_hook_exit_retains_maintenance_without_rollback(self):
        self.assert_unconfirmed_hook_exit_retains_maintenance(-15)

    def assert_timeout_retains_maintenance(self, uncertain_exit=False):
        hook = self.home / 'activation-hook'
        hook.write_text('#!/bin/sh\nexit 0\n')
        hook.chmod(0o700)
        self.enabled(hook)
        prepared = Mock(returncode=0)
        prepared.communicate.return_value = (b'', b'')
        timed_out = Mock(pid=12345678)
        tail = subprocess.TimeoutExpired('hook', 10) if uncertain_exit else (b'', b'')
        timed_out.communicate.side_effect = [subprocess.TimeoutExpired('hook', 120), tail]
        with self.hook_processes(hook, [prepared, timed_out, prepared]), patch('auto_update.os.killpg'):
            result = self.run_update()
        self.assertEqual('manual_recovery_required', result['status'], result)
        self.assertTrue(auto_install.state_path(self.home, 'update.lock').is_dir())
        self.assertEqual(result['owner'], coordination.session_status(self.ledger)['maintenance']['owner'])
        with patch('releases.release_metadata') as metadata:
            self.assertEqual('manual_recovery_required', auto_update.run(self.home, self.ledger)['status'])
            metadata.assert_not_called()

    def test_activation_timeout_retains_maintenance_and_update_lock(self):
        self.assert_timeout_retains_maintenance()

    def test_hook_timeout_with_unconfirmed_process_exit_retains_maintenance(self):
        self.assert_timeout_retains_maintenance(uncertain_exit=True)

    def test_disable_during_active_update_does_not_stop_scheduler_or_owner(self):
        self.enabled()
        value = auto_update.config(self.home)
        value['scheduler'] = {'kind': 'systemd'}
        auto_update.save_config(self.home, value)
        auto_install.state_path(self.home, 'update.lock').mkdir()
        coordination.dispatch('maintenance-acquire', 'claude', 'updater', self.ledger)
        with patch('auto_scheduler.uninstall') as uninstall:
            result = auto_update.disable(self.home)
            uninstall.assert_not_called()
        self.assertFalse(auto_update.config(self.home)['enabled'])
        self.assertTrue(result['scheduler_cleanup_deferred'])
        self.assertTrue(auto_install.state_path(self.home, 'update.lock').is_dir())
        self.assertEqual('updater', coordination.session_status(self.ledger)['maintenance']['owner'])

    def test_recovery_refuses_local_maintenance_and_preserves_evidence(self):
        lock = auto_install.state_path(self.home, 'update.lock')
        lock.mkdir()
        prior = auto_update.record(self.home, {'status': 'manual_recovery_required', 'owner': 'updater'})
        coordination.dispatch('maintenance-acquire', 'claude', 'updater', self.ledger)
        accounting = self.state_rows()
        with self.assertRaisesRegex(ValueError, 'release the stopped maintenance owner'):
            auto_update.recover(self.home, self.ledger)
        self.assertTrue(lock.is_dir())
        self.assertEqual(prior, auto_update.journal(self.home))
        self.assertEqual('updater', coordination.session_status(self.ledger)['maintenance']['owner'])
        self.assertEqual(accounting, self.state_rows())

    def test_recovery_refuses_authority_maintenance_even_when_local_is_idle(self):
        lock = auto_install.state_path(self.home, 'update.lock')
        lock.mkdir()
        coordination.configure(self.ledger, authority='owner@example.test')
        remote = {**coordination.session_status(self.ledger), 'maintenance': {'owner': 'remote-updater', 'started': 100}}
        with patch('coordination.dispatch', return_value=remote) as dispatch:
            with self.assertRaisesRegex(ValueError, 'release the stopped maintenance owner'):
                auto_update.recover(self.home, self.ledger)
        dispatch.assert_called_once_with('status', 'claude', 'auto-update-status', self.ledger)
        self.assertTrue(lock.is_dir())
        self.assertIsNone(coordination.session_status(self.ledger)['maintenance'])

    def test_recovery_of_stopped_empty_lock_retains_prior_journal_and_accounting(self):
        lock = auto_install.state_path(self.home, 'update.lock')
        lock.mkdir()
        prior = auto_update.record(self.home, {'status': 'manual_recovery_required', 'owner': 'stopped-updater'})
        accounting = self.state_rows()
        installation = releases.installation(self.home)
        result = auto_update.recover(self.home, self.ledger)
        self.assertEqual('recovered', result['status'])
        self.assertEqual(prior, result['previous'])
        self.assertFalse(lock.exists())
        self.assertEqual(result, auto_update.journal(self.home))
        self.assertEqual(accounting, self.state_rows())
        self.assertEqual(installation, releases.installation(self.home))

    def test_recovery_does_not_remove_nonempty_lock_evidence(self):
        lock = auto_install.state_path(self.home, 'update.lock')
        lock.mkdir()
        evidence = lock / 'owner-evidence'
        evidence.write_text('Preserve this evidence.\n')
        prior = auto_update.record(self.home, {'status': 'manual_recovery_required'})
        with self.assertRaises(OSError):
            auto_update.recover(self.home, self.ledger)
        self.assertEqual('Preserve this evidence.\n', evidence.read_text())
        self.assertEqual(prior, auto_update.journal(self.home))

    def test_enable_requires_loaded_scheduler_and_disable_unloads(self):
        self.ledger.reset_setup()
        with patch('auto_scheduler.install', return_value={'loaded': False}):
            with self.assertRaisesRegex(ValueError, 'not loaded'):
                auto_update.enable(self.home, ledger=self.ledger)
        self.assertFalse(auto_update.config(self.home)['enabled'])
        with patch('auto_scheduler.install', return_value={'loaded': True, 'kind': 'systemd'}):
            self.assertTrue(auto_update.enable(self.home, interval=12, ledger=self.ledger)['enabled'])
        self.assertEqual(12, auto_update.config(self.home)['interval_hours'])
        with patch('auto_scheduler.uninstall') as uninstall:
            self.assertFalse(auto_update.disable(self.home)['enabled'])
            uninstall.assert_called_once()


class AutoSchedulerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name) / 'home with spaces $cash %unit "quote"'
        launcher = self.home / '.local/bin/ai-session'
        launcher.parent.mkdir(parents=True)
        launcher.write_text('# launcher\n')

    def test_launchd_keeps_absolute_argument_boundaries(self):
        with patch('auto_scheduler.platform', return_value='launchd'):
            definitions = auto_scheduler.definitions(self.home, sys.executable)
        data = plistlib.loads(next(iter(definitions.values())))
        self.assertEqual([sys.executable, str(self.home / '.local/bin/ai-session'), 'auto-update', 'run'], data['ProgramArguments'])
        self.assertEqual(str(self.home), data['EnvironmentVariables']['HOME'])
        self.assertTrue(Path(data['StandardErrorPath']).is_absolute())

    def test_systemd_escapes_paths_and_rejects_control_characters(self):
        with patch('auto_scheduler.platform', return_value='systemd'):
            definitions = auto_scheduler.definitions(self.home, sys.executable)
            service = next(value.decode() for path, value in definitions.items() if path.suffix == '.service')
            self.assertIn('$$cash %%unit \\"quote\\"', service)
            self.assertIn('ExecStart="' + sys.executable + '"', service)
            with self.assertRaises(ValueError):
                auto_scheduler.definitions(self.home, '/python\nInjected=yes')

    def test_launchd_install_uninstall_loads_and_removes_only_owned_plist(self):
        with patch('auto_scheduler.platform', return_value='launchd'), \
                patch('auto_scheduler.command', return_value=Mock(returncode=0, stdout='')) as command:
            receipt = auto_scheduler.install(self.home, sys.executable, None)
            plist = self.home / 'Library/LaunchAgents' / (auto_scheduler.LABEL + '.plist')
            self.assertTrue(receipt['loaded'])
            command.assert_any_call(['/bin/launchctl', 'bootstrap', f'gui/{os.getuid()}', str(plist)])
            auto_scheduler.uninstall(self.home, receipt)
            self.assertFalse(plist.exists())
            command.assert_any_call(['/bin/launchctl', 'bootout', f'gui/{os.getuid()}/{auto_scheduler.LABEL}'])

    def test_systemd_install_uninstall_preserves_changed_definitions(self):
        with patch('auto_scheduler.platform', return_value='systemd'), \
                patch('auto_scheduler.command', return_value=Mock(returncode=0, stdout='yes\n')) as command:
            receipt = auto_scheduler.install(self.home, sys.executable, None)
            self.assertTrue(receipt['loaded'])
            command.assert_any_call(['systemctl', '--user', 'enable', '--now', auto_scheduler.UNIT + '.timer'])
            service = self.home / '.config/systemd/user' / (auto_scheduler.UNIT + '.service')
            original = service.read_bytes()
            service.write_bytes(original + b'# owner edit\n')
            with self.assertRaisesRegex(ValueError, 'Changed scheduler retained'):
                auto_scheduler.uninstall(self.home, receipt)
            self.assertTrue(service.exists())
            service.write_bytes(original)
            auto_scheduler.uninstall(self.home, receipt)
            self.assertFalse(service.exists())
            command.assert_any_call(['systemctl', '--user', 'disable', '--now', auto_scheduler.UNIT + '.timer'])


if __name__ == '__main__':
    unittest.main()
