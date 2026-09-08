"""Private model metadata and exact-session recovery for supervised Claude."""
from contextlib import contextmanager, closing
import json
import os
from pathlib import Path
import shlex
import sqlite3
import sys
import tempfile
import time
import uuid

import model_scope

ENV = 'SESSION_HARNESS_CLAUDE_STATE'


@contextmanager
def state(path):
    path = Path(path)
    info = path.lstat()
    if path.is_symlink() or not path.is_file() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('invalid private model state')
    db = sqlite3.connect(path, timeout=5)
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            row = json.loads(db.execute('SELECT value FROM state').fetchone()[0])
            if (set(row) != {'session', 'model', 'role', 'children', 'ended', 'started'}
                    or row['role'] not in ('planner', 'worker') or type(row['ended']) is not bool
                    or type(row['started']) is not bool or not isinstance(row['children'], list)
                    or len(row['children']) > 128
                    or (row['model'] is not None and model_scope.tier(row['model']) is None)):
                raise ValueError('invalid model state')
            yield row
            db.execute('UPDATE state SET value=?', (json.dumps(row),))
    finally:
        db.close()


def read(path):
    with state(path) as row:
        return dict(row)


def models(path):
    row = read(path)
    import harness
    if model_scope.tier(row['model']) is None:
        raise ValueError('current model could not be verified')
    harness.require_role('claude', row['model'], 'manager' if row['role'] == 'planner' else 'worker')
    return None if row['children'] else [row['model']]


def hook(payload, path, owner):
    import coordination
    import harness
    event = payload['hook_event_name']
    session = str(uuid.UUID(payload['session_id']))
    if event == 'SessionStart':
        with state(path) as row:
            if not row['started'] and row['session'] != session:
                row['model'] = None
                return {'continue': False, 'stopReason': 'Session harness: resumed session identity differs.'}
            row.update(session=session, started=True, ended=False)
            if payload.get('model') is not None:
                row['model'] = payload['model'] if model_scope.tier(payload['model']) else None
        return {}
    row = read(path)
    if row['session'] != session:
        raise ValueError('model state belongs to another session')
    if event == 'SessionEnd':
        with state(path) as row:
            row['ended'] = True
        return {}
    if event in ('SubagentStart', 'SubagentStop'):
        ident = payload.get('agent_id')
        if not isinstance(ident, str) or not 1 <= len(ident) <= 128:
            raise ValueError('unknown subagent identity')
        with state(path) as row:
            children = set(row['children'])
            children.add(ident) if event == 'SubagentStart' else children.discard(ident)
            row['children'] = sorted(children)
        return {}
    if event == 'PostModelSwitch':
        target = payload.get('to_model')
        with state(path) as row:
            row['model'] = target if model_scope.tier(target) else None
        return {}
    if event == 'Stop':
        return {}
    selected = models(path)
    if event == 'PreModelSwitch':
        target = payload.get('to_model')
        if model_scope.tier(target) is None:
            raise ValueError('unknown target model')
        harness.require_role('claude', target, 'manager' if row['role'] == 'planner' else 'worker')
        selected = None if row['children'] else [target]
    if event == 'PreToolUse' and payload.get('tool_name') in ('Agent', 'Task'):
        selected = None
    result = coordination.dispatch('admit', 'claude', owner, **({'models': selected} if selected else {}))
    if result.get('allowed') is True:
        return {}
    reason = 'Session harness: ' + ', '.join(result.get('reasons', ['quota_admission_denied']))
    if event == 'PreModelSwitch':
        return {'hookSpecificOutput': {'hookEventName': event, 'permissionDecision': 'deny',
                                       'permissionDecisionReason': reason}}
    return {'continue': False, 'stopReason': reason}


def recovery_arguments(argv):
    """Only known resume controls are replay-free; other client arguments stay manual."""
    extra = argv[5:]
    if not extra:
        return []
    if len(extra) == 2 and extra[0] in ('--resume', '-r', '--session-id'):
        uuid.UUID(extra[1])
        return extra
    return None


def run(capability, response, environment):
    import claude_admission
    import harness
    import supervision
    if not capability.get('model_switch_hooks_supported') or os.name != 'posix':
        return supervision.run_terminal(response['argv'], environment, 'claude')
    choice = response['selection']
    extra = recovery_arguments(response['argv'])
    if extra is None:
        return supervision.run_terminal(response['argv'], environment, 'claude')
    attempted = [choice['model']]
    with tempfile.TemporaryDirectory(prefix='session-harness-claude-') as directory:
        path = Path(directory) / 'models.sqlite3'
        path.touch(mode=0o600)
        initial_id = extra[1] if extra else str(uuid.uuid4())
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE state(value TEXT NOT NULL)')
            db.execute('INSERT INTO state VALUES (?)', (json.dumps(dict(session=initial_id,
                model=choice['model'], role=response['role'], children=[], ended=False, started=False)),))
        command = shlex.join([sys.executable, str(Path(__file__).with_name('claude_gate.py'))])
        import claude_gate
        settings = {'hooks': {e: [{'hooks': [{'type': 'command', 'command': command, 'timeout': 45}]}]
                             for e in claude_gate.EVENTS}}
        settings_path = Path(directory) / 'settings.json'
        settings_path.write_text(json.dumps(settings))
        env = dict(environment, **{ENV: str(path)})
        argv = list(response['argv'])
        if extra == []:
            argv += ['--session-id', initial_id]
        while True:
            startup_deadline = time.monotonic() + 30
            def ready():
                startup = read(path)
                if model_scope.tier(startup['model']) is None:
                    raise supervision.Stop('claude', ['quota_refresh_failed'])
                if startup['started']:
                    return True
                if time.monotonic() >= startup_deadline:
                    raise supervision.Stop('claude', ['quota_refresh_failed'])
                return False
            active = argv + ['--settings', str(settings_path), '--fallback-model', choice['model']]
            try:
                return supervision.run_terminal(active, env, 'claude', models=lambda: models(path),
                    on_stop=lambda stop: setattr(stop, 'model_session', read(path)), input_ready=ready)
            except supervision.Stop as stop:
                before = getattr(stop, "model_session", {})
                cleanup = getattr(stop, 'session_cleanup', {})
                if (not stop.model_scope_stop or not getattr(stop, 'inference_interrupted', False)
                        or cleanup.get('state') != 'stopped' or cleanup.get('errors')
                        or cleanup.get('owner_retained') is not False or before.get('ended', True)
                        or not before.get('started') or len(attempted) >= 2):
                    raise
                fresh = harness.discover_provider('claude')
                if not fresh.get('model_switch_hooks_supported') or fresh.get('auth', {}).get('status') != 'subscription':
                    raise stop
                choice, receipt = claude_admission.choose(fresh, response['role'], excluded=attempted)
                harness.require_role('claude', choice['model'], 'manager' if response['role'] == 'planner' else 'worker')
                attempted.append(choice['model'])
                session = str(uuid.UUID(before['session']))
                with state(path) as row:
                    row.update(model=choice['model'], children=[], started=False, ended=False)
                print('\nSession harness: model-specific allowance reached. Resuming this conversation on '
                      + choice['model'] + '; the shared Claude budget still applies.\n', file=sys.stderr, flush=True)
                argv = [fresh['executable'], '--model', choice['model'], '--effort', choice['effort'], '--resume', session]
