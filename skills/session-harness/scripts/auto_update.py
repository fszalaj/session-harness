"""Opt-in automatic stable updates, deferred until coordinated sessions are idle."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

import auto_install as install
from auto_install import atomic, sha
import auto_scheduler
import coordination
from quota import Ledger, default_path
import releases


def config(home):
    path = install.state_path(home, 'auto-update.json')
    if not path.exists() and not path.is_symlink():
        return {'schema': 1, 'enabled': False, 'interval_hours': 24, 'activation_hook': None}
    value = install.read_json(path)
    if (not isinstance(value, dict) or value.get('schema') != 1 or type(value.get('enabled')) is not bool
            or type(value.get('interval_hours')) is not int or not 1 <= value['interval_hours'] <= 168):
        raise ValueError('Invalid auto-update configuration; no update attempted')
    hook = value.get('activation_hook')
    if hook is not None and (not isinstance(hook, str) or not Path(hook).is_absolute()):
        raise ValueError('Invalid activation hook')
    return value


def save_config(home, value):
    install.save(install.state_path(home, 'auto-update.json'), value)


def journal(home):
    path = install.state_path(home, 'auto-update-last.json')
    return install.read_json(path) if path.exists() or path.is_symlink() else {}


def existing_ledger(ledger=None):
    path = Path(ledger.path if ledger is not None else default_path()).absolute()
    if path.is_symlink() or not path.is_file():
        raise ValueError('Existing coordination ledger required; automatic maintenance never initializes accounting')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        if not db.execute("SELECT value FROM state WHERE key='policy'").fetchone():
            raise ValueError('Existing quota policy is missing; inspect accounting before maintenance')
        coordination._settings(db)
    return ledger if ledger is not None else Ledger(path)


def record(home, value):
    value = {'at': time.time(), **value}
    install.save(install.state_path(home, 'auto-update-last.json'), value)
    return value


def authority_status(ledger):
    local = coordination.session_status(ledger)
    remote = (local if local['authority'] == 'local'
              else coordination.dispatch('status', 'claude', 'auto-update-status', ledger))
    if remote.get('maintenance_version') != 1:
        raise ValueError('Authority lacks maintenance support; update it explicitly before enabling automatic updates')
    return {'local': local, 'authority': remote}


def status(home, ledger=None):
    value = config(home)
    result = {**value, 'last_result': journal(home),
              'update_lock': install.state_path(home, 'update.lock').exists()}
    try:
        result['scheduler_status'] = auto_scheduler.status(home)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result['scheduler_status'] = {'loaded': False, 'detail': str(error)}
    try:
        result['coordination'] = authority_status(existing_ledger(ledger))
    except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError) as error:
        result['coordination'] = {'unavailable': str(error)}
    return result


class AmbiguousActivation(Exception):
    pass


def hook_call(hook, phase, preview):
    if hook is None:
        return
    path = Path(hook)
    if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError('Activation hook must be a regular executable')
    process = subprocess.Popen([hook, phase, str(preview)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=120)
    except subprocess.TimeoutExpired as error:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            process.communicate(timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
        raise AmbiguousActivation('Activation hook timed out; inspect privileged descendants before recovery') from error
    if process.returncode not in (0, 1):
        raise AmbiguousActivation('Activation hook did not confirm a completed outcome during ' + phase)
    if process.returncode == 1:
        raise ValueError('Activation hook failed during ' + phase)
    if len(stdout) > 65536 or len(stderr) > 65536:
        raise ValueError('Activation hook output exceeds contract')


def enable(home, interval=None, hook=None, ledger=None):
    value = config(home)
    previous = releases.installation(home)
    install.registered(home, previous)
    if ledger is None and default_path().absolute() != install.state_path(home, 'quota/ledger.sqlite3').absolute():
        raise ValueError('Automatic scheduling requires the default state location; preserve custom accounting and use explicit updates')
    ledger = existing_ledger(ledger)
    observed = authority_status(ledger)
    value['authority'] = observed['local']['authority']
    if install.state_path(home, 'update.lock').exists():
        raise ValueError('Inspect update.lock before changing automatic maintenance')
    if hook is not None:
        path = Path(hook)
        if not path.is_absolute() or path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError('Activation hook must be an absolute regular executable')
        value['activation_hook'] = hook
    if interval is not None:
        if not 1 <= interval <= 168:
            raise ValueError('interval-hours must be 1..168')
        value['interval_hours'] = interval
    value['enabled'] = False
    save_config(home, value)
    value['scheduler'] = auto_scheduler.install(home, sys.executable, value.get('scheduler'))
    if not value['scheduler']['loaded']:
        save_config(home, value)
        raise ValueError('Scheduler was not loaded; auto-update remains disabled')
    value['enabled'] = True
    save_config(home, value)
    return value


def disable(home):
    value = config(home)
    value['enabled'] = False
    save_config(home, value)
    if install.state_path(home, 'update.lock').exists():
        return {**value, 'scheduler_cleanup_deferred': True,
                'next_step': 'After the running updater finishes, repeat disable to unload the scheduler'}
    if value.get('scheduler'):
        auto_scheduler.uninstall(home, value['scheduler'])
    return value


def recover(home, ledger=None):
    statuses = authority_status(existing_ledger(ledger))
    if statuses['local']['maintenance'] or statuses['authority']['maintenance']:
        raise ValueError('Inspect and explicitly release the stopped maintenance owner before recovery')
    lock = install.state_path(home, 'update.lock')
    if lock.exists():
        lock.rmdir()
    return record(home, {'status': 'recovered', 'previous': journal(home),
                         'next_step': 'Verify installed profiles and shared activation before the next run'})


def run(home, ledger=None):
    value = config(home)
    if not value['enabled']:
        return {'status': 'disabled', 'enabled': False}
    last = journal(home)
    if last.get('status') == 'manual_recovery_required':
        return {**last, 'status': 'manual_recovery_required'}
    if last.get('next_check_at', 0) > time.time():
        return {'status': 'not_due', 'next_check_at': last['next_check_at']}
    try:
        ledger = existing_ledger(ledger)
    except (OSError, ValueError, sqlite3.Error) as error:
        return record(home, {'status': 'deferred_error', 'detail': str(error)})
    if value.get('authority') != coordination.settings(ledger)['authority']:
        return record(home, {'status': 'deferred_error', 'detail': 'Authority changed; inspect and re-enable automatic maintenance'})
    lock = install.state_path(home, 'update.lock')
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError:
        return {'status': 'update_busy', 'previous': last,
                'next_step': 'Inspect auto-update status and verify the recorded updater stopped before recovery'}
    owner = 'update:' + uuid.uuid4().hex
    acquired = False
    ambiguous = False
    result = None
    try:
        record(home, {'status': 'checking', 'owner': owner})
        previous = releases.installation(home)
        registered = install.registered(home, previous)
        metadata = releases.release_metadata()
        selected = releases.version(metadata['tag_name'])
        newer = tuple(map(int, selected.split('.'))) > tuple(map(int, releases.version(previous['version']).split('.')))
        if not newer:
            result = {'status': 'current', 'installed': previous['version'], 'available': selected,
                      'source': previous['source'], 'local_overlays': len(registered['overrides']),
                      'next_check_at': time.time() + value['interval_hours'] * 3600}
            return record(home, result)
        statuses = authority_status(ledger)
        if statuses['local']['sessions'] or statuses['authority']['sessions'] or statuses['authority']['maintenance']:
            return record(home, {'status': 'deferred_sessions', 'available': selected, 'coordination': statuses})
        with tempfile.TemporaryDirectory(prefix='auto-update-', dir=lock.parent) as directory:
            source = releases.download_release(metadata, Path(directory))
            release_marker = install.read_json(source / 'RELEASE.json')
            module, preview, internal = install.prepare(home, source, previous, registered, selected)
            run_dir = lock.parent / 'auto-update-runs' / owner.replace(':', '-')
            run_dir.mkdir(parents=True, mode=0o700)
            preview_path = run_dir / 'preview.json'
            install.save(preview_path, preview)
            hook_call(value.get('activation_hook'), 'prepare', preview_path)
            if install.registered(home, previous) != registered:
                raise ValueError('Overlay registration changed before activation')
            if releases.installation(home) != previous or config(home) != value:
                raise ValueError('Installation or automatic update settings changed before activation')
            if coordination.session_status(ledger)['sessions']:
                return record(home, {'status': 'deferred_sessions', 'available': selected})
            # Persist intent before SSH: lost acknowledgement may still have acquired maintenance.
            record(home, {'status': 'acquiring_maintenance', 'owner': owner, 'run_directory': str(run_dir)})
            try:
                response = coordination.dispatch('maintenance-acquire', 'claude', owner, ledger)
            except Exception as error:
                ambiguous = True
                raise AmbiguousActivation('Maintenance acquisition outcome unknown; inspect authority with recorded owner') from error
            if response.get('status') != 'maintenance_acquired':
                return record(home, {'status': 'deferred_sessions', 'available': selected, 'coordination': response})
            acquired = True
            if config(home) != value:
                raise ValueError('Automatic update was disabled or reconfigured before activation')
            expected = install.expected_paths(preview, internal)
            receipt_paths = [install.state_path(home, name) for name in ('installation.json', 'auto-update-installation.json')]
            before = install.backup(home, [*expected, *map(str, receipt_paths)], run_dir)
            next_registration = {'schema': 1, 'installation_hash': preview['source_hash'], 'base_version': selected,
                                 'base_source_hash': preview['base_source_hash'], 'overrides': preview['overlays'],
                                 'footprint': dict(expected)}
            next_installation = {'schema': 1, 'version': selected,
                                 'source': 'release' if (source / 'RELEASE.json').is_file() else 'checkout',
                                 'source_hash': preview['source_hash'], 'link_mode': previous['link_mode'],
                                 'launcher': previous['launcher'], 'personal_policy': previous['personal_policy'],
                                 'instructions_sha256': sha(internal['release']['AGENTS.md']['content'])}
            record(home, {'status': 'activating', 'owner': owner, 'run_directory': str(run_dir)})
            try:
                module.apply_install(preview, internal)
                policy = Path(previous['personal_policy']) if previous.get('personal_policy') else None
                module.save_installation_state(home, source, preview, policy, previous['link_mode'], previous['launcher'])
                install.save(receipt_paths[1], next_registration)
                expected.update(install.footprint(receipt_paths))
                hook_call(value.get('activation_hook'), 'activate', preview_path)
                install.registered(home, releases.installation(home))
            except AmbiguousActivation:
                ambiguous = True
                raise
            except Exception:
                try:
                    hook_call(value.get('activation_hook'), 'rollback', preview_path)
                    # Accept only the known installation receipt during interrupted writes.
                    for path, old, new in zip(receipt_paths, (previous, registered),
                                               (next_installation, next_registration)):
                        if install.read_json(path) not in (old, new):
                            raise ValueError('Installation receipt drifted during rollback')
                        expected[str(path)] = install.inspect_path(path)
                    install.restore(before, expected)
                except Exception as error:
                    ambiguous = True
                    raise AmbiguousActivation('Activation rollback could not be verified') from error
                raise
            result = {'status': 'updated', 'installed': selected, 'source_hash': preview['source_hash'],
                      'local_overlays': len(preview['overlays']), 'restart_clients': True,
                      'archive_sha256': metadata.get('_verified_archive_sha256'), 'release_commit': release_marker.get('commit'),
                      'run_directory': str(run_dir), 'next_check_at': time.time() + value['interval_hours'] * 3600}
    except AmbiguousActivation as error:
        ambiguous = True
        result = {'status': 'manual_recovery_required', 'detail': str(error), 'owner': owner,
                  'next_step': 'Inspect managed backups and authority maintenance; do not remove a live owner or restore accounting'}
    except Exception as error:
        result = {'status': 'deferred_error', 'detail': str(error), 'owner': owner}
    finally:
        if acquired and not ambiguous:
            try:
                coordination.dispatch('maintenance-release', 'claude', owner, ledger)
            except Exception as error:
                ambiguous = True
                result = {'status': 'manual_recovery_required', 'detail': 'Maintenance release unconfirmed: ' + str(error),
                          'owner': owner}
        if not ambiguous:
            lock.rmdir()
        if result is not None:
            record(home, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('status')
    optin = sub.add_parser('enable')
    optin.add_argument('--interval-hours', type=int)
    optin.add_argument('--activation-hook', help='Explicit trusted same-user executable for prepare/activate/rollback')
    sub.add_parser('disable')
    sub.add_parser('run')
    recovery = sub.add_parser('recover', help='After inspecting rollback and confirming the updater stopped')
    recovery.add_argument('--confirm-stopped', action='store_true', required=True)
    registration = sub.add_parser('register', help='Explicitly reconcile an installed snapshot against its published baseline')
    registration.add_argument('--base-source', type=Path, help='Verified matching release source; otherwise download the published baseline')
    args = parser.parse_args(argv)
    home = Path.home()
    try:
        if args.action == 'status':
            result = status(home)
        elif args.action == 'enable':
            result = enable(home, args.interval_hours, args.activation_hook)
        elif args.action == 'disable':
            result = disable(home)
        elif args.action == 'recover':
            result = recover(home)
        elif args.action == 'register':
            if install.state_path(home, 'update.lock').exists():
                raise ValueError('Do not register during an update; inspect update.lock')
            previous = releases.installation(home)
            if args.base_source:
                result = install.register(home, args.base_source.resolve())
            else:
                metadata = releases.release_metadata(previous['version'])
                with tempfile.TemporaryDirectory(prefix='auto-baseline-', dir=install.state_path(home, '')) as directory:
                    source = releases.download_release(metadata, Path(directory))
                    result = install.register(home, source)
            result = {'status': 'registered', 'source_hash': result['installation_hash'], 'overlays': len(result['overrides'])}
        else:
            result = run(home)
        print(json.dumps(result, indent=2))
        return 2 if result.get('status') in ('manual_recovery_required', 'deferred_error') else 0
    except Exception as error:
        print(json.dumps({'status': 'auto_update_failed', 'detail': str(error)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
