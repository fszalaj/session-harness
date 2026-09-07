"""Deterministic Claude hooks: stop on shared admission denial without model calls."""
import argparse
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import time

import coordination

EVENTS = ('UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'Stop', 'SessionEnd')


def evaluate(payload):
    event = payload.get('hook_event_name')
    session = payload.get('session_id')
    if event not in EVENTS or not isinstance(session, str):
        raise ValueError('unknown hook event or session')
    supervised = os.environ.get('SESSION_HARNESS_OWNER')
    owner = supervised or ('claude:' + session)
    if event in ('Stop', 'SessionEnd'):
        finished = event == 'SessionEnd' or payload.get('background_tasks') == []
        if not supervised and finished:
            coordination.dispatch('release', 'claude', owner)
        return {}
    result = coordination.dispatch('admit', 'claude', owner)
    if result.get('allowed') is not True:
        return {'continue': False, 'stopReason': 'Session harness stopped this turn: ' +
                ', '.join(result.get('reasons', ['quota_admission_denied']))}
    return {}


def install(apply=False, home=None):
    home = Path(home) if home else Path.home()
    path = home / '.claude/settings.json'
    if path.is_symlink():
        raise ValueError('merge hooks into the canonical settings target explicitly')
    original = path.read_bytes() if path.exists() else b'{}'
    value = json.loads(original)
    hooks = value.setdefault('hooks', {})
    command = shlex.join([sys.executable, str(home / '.agents/skills/session-harness/scripts/claude_gate.py')])
    if os.name == 'nt':
        import subprocess
        command = subprocess.list2cmdline([sys.executable, str(home / '.agents/skills/session-harness/scripts/claude_gate.py')])
    entry = {'hooks': [{'type': 'command', 'command': command, 'timeout': 60}]}
    changed = []
    for event in EVENTS:
        rows = hooks.setdefault(event, [])
        if not isinstance(rows, list):
            raise ValueError('invalid existing hooks')
        if entry not in rows:
            rows.append(entry)
            changed.append(event)
    if apply and changed:
        backup = home / '.local/state/session-harness/hook-backups'
        backup.mkdir(parents=True, exist_ok=True, mode=0o700)
        backup_file = backup / (str(time.time_ns()) + '.json')
        backup_file.write_bytes(original)
        if os.name == 'posix': backup_file.chmod(0o600)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=path.parent, prefix='.harness-hooks-')
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(json.dumps(value, indent=2) + '\n')
            if (path.read_bytes() if path.exists() else b'{}') != original:
                raise ValueError('settings changed; retry the merge')
            os.replace(name, path)
        finally:
            if os.path.exists(name): os.unlink(name)
    return {'changed_events': changed, 'applied': apply, 'restart_required': bool(changed),
            'boundary': 'Hooks stop supported events; streaming text and external clients remain outside exact bounds.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.install:
            result = install(args.apply)
        else:
            raw = sys.stdin.buffer.read(262145)
            if len(raw) > 262144:
                raise ValueError('hook input exceeds bound')
            result = evaluate(json.loads(raw))
        print(json.dumps(result))
        return 0
    except Exception:
        print(json.dumps({'continue': False, 'stopReason': 'Session harness unavailable; inference remains blocked.'}))
        return 0 if not args.install else 2


if __name__ == '__main__':
    raise SystemExit(main())
