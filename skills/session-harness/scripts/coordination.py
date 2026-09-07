"""Share account budgets with independently configurable native session capacity."""
import argparse
import json
import os
import re
import subprocess
import sys
import time

from quota import Ledger

SERVICES = ('codex', 'claude', 'antigravity')
DEFAULT_MAX_SESSIONS = 4
MAX_SESSIONS = 32


def validate_settings(value):
    authority, maximum = value.get('authority'), value.get('max_sessions')
    if (type(maximum) is not int or not 1 <= maximum <= MAX_SESSIONS or
            not isinstance(authority, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]{0,252}', authority)):
        raise ValueError('invalid authority or session count')
    return value


def _settings(db):
    row = db.execute("SELECT value FROM state WHERE key='coordination_v1'").fetchone()
    value = json.loads(row[0]) if row else {'authority': 'local', 'max_sessions': DEFAULT_MAX_SESSIONS}
    if not isinstance(value, dict):
        raise ValueError('invalid coordination settings')
    return validate_settings(value)


def configure(ledger, authority=None, max_sessions=None):
    with ledger._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        previous = _settings(db)
        value = validate_settings({'authority': previous['authority'] if authority is None else authority,
                                   'max_sessions': previous['max_sessions'] if max_sessions is None else max_sessions})
        if previous == value:
            return value
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='native_sessions'").fetchone()
        if exists:
            counts = [r[0] for r in db.execute('SELECT COUNT(*) FROM native_sessions GROUP BY service')]
            if counts and previous['authority'] != value['authority']:
                raise ValueError('finish active sessions before changing authority')
            if counts and max(counts) > value['max_sessions']:
                raise ValueError('requested capacity is below active session count; finish sessions first')
        db.execute("INSERT OR REPLACE INTO state VALUES ('coordination_v1', ?)", (json.dumps(value),))
    return value


def settings(ledger):
    with ledger._connect() as db:
        return _settings(db)


def session_status(ledger):
    with ledger._connect() as db:
        db.execute('BEGIN DEFERRED')
        policy = _settings(db)
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='native_sessions'").fetchone()
        rows = [dict(service=r[0], owner=r[1], started=r[2]) for r in
                db.execute('SELECT service,owner,started FROM native_sessions ORDER BY service,started')] if exists else []
    return {**policy, 'allowed': False, 'status': 'session_status', 'sessions': rows,
            'active_sessions': {service: sum(r['service'] == service for r in rows) for service in SERVICES}}


def local(action, service, owner, ledger):
    if service not in SERVICES or not isinstance(owner, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', owner):
        raise ValueError('invalid session identity')
    policy = settings(ledger)
    if policy['authority'] != 'local':
        raise ValueError('authority must terminate locally; forwarding chains are forbidden')
    if action == 'check':
        import usage
        return usage.require_admission(service, ledger=ledger)
    if action == 'status':
        return session_status(ledger)
    with ledger._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        policy = _settings(db)
        if policy['authority'] != 'local':
            raise ValueError('authority changed before admission')
        db.execute('CREATE TABLE IF NOT EXISTS native_sessions (service TEXT, owner TEXT, started REAL, PRIMARY KEY(service,owner))')
        if action == 'release':
            db.execute('DELETE FROM native_sessions WHERE service=? AND owner=?', (service, owner))
            return {'allowed': False, 'status': 'released'}
        if action != 'admit':
            raise ValueError('invalid coordination action')
        ledger._require_setup(db, 'native', service)
        existing = db.execute('SELECT owner FROM native_sessions WHERE service=?', (service,)).fetchall()
        present = (owner,) in existing
        if not present and len(existing) >= policy['max_sessions']:
            return {'allowed': False, 'reasons': ['account_session_busy'],
                    'active_sessions': len(existing), 'max_sessions': policy['max_sessions'],
                    'next_step': 'ai-session coordination status',
                    'capacity_command': 'ai-session coordination set --max-sessions NUMBER',
                    'capacity_scope': 'Configure on the account authority; quota budgets are unchanged.'}
        if not present:
            db.execute('INSERT INTO native_sessions VALUES (?,?,?)', (service, owner, time.time()))
    import usage
    result = None
    try:
        result = usage.require_admission(service, ledger=ledger)
    finally:
        if not present and (not isinstance(result, dict) or not result.get('allowed')):
            local('release', service, owner, ledger)
    return result


def dispatch(action, service, owner, ledger=None):
    ledger = ledger or Ledger()
    policy = settings(ledger)
    if policy['authority'] == 'local':
        return local(action, service, owner, ledger)
    if action not in ('release', 'status'):
        ledger.require_setup('native', service)
    from platform_runtime import which
    executable = which('ssh')
    if not executable:
        raise ValueError('SSH authority transport unavailable')
    packet = json.dumps({'action': action, 'service': service, 'owner': owner}).encode()
    command = 'python3 "$HOME/.agents/skills/session-harness/scripts/coordination.py" serve'
    result = subprocess.run([executable, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                             '-o', 'ConnectTimeout=5', policy['authority'], command], input=packet,
                            capture_output=True, timeout=45)
    if result.returncode or len(result.stdout) > 256 * 1024:
        raise ValueError('SSH authority unavailable; no local fallback')
    response = json.loads(result.stdout)
    if not isinstance(response, dict) or type(response.get('allowed')) is not bool:
        raise ValueError('invalid authority response')
    return response


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('serve')
    sub.add_parser('status')
    config = sub.add_parser('set')
    config.add_argument('--authority', help='local or existing trusted SSH user@host; omitted preserves current authority')
    config.add_argument('--max-sessions', type=int, help='Concurrent sessions per service, 1..32; does not change quota')
    release = sub.add_parser('release')
    release.add_argument('--service', choices=SERVICES, required=True)
    release.add_argument('--owner', required=True)
    release.add_argument('--confirm-stopped', action='store_true', required=True)
    args = parser.parse_args(argv)
    try:
        ledger = Ledger()
        if args.action == 'serve':
            raw = sys.stdin.buffer.read(4097)
            if len(raw) > 4096:
                raise ValueError('coordination request too large')
            packet = json.loads(raw)
            if not isinstance(packet, dict) or set(packet) != {'action', 'service', 'owner'}:
                raise ValueError('invalid coordination request')
            result = local(**packet, ledger=ledger)
        elif args.action == 'set':
            if args.authority is None and args.max_sessions is None:
                raise ValueError('set requires --authority or --max-sessions')
            result = configure(ledger, args.authority, args.max_sessions)
        elif args.action == 'release':
            result = dispatch('release', args.service, args.owner, ledger)
        else:
            local_status = session_status(ledger)
            authority_status = (local_status if local_status['authority'] == 'local'
                                else dispatch('status', 'claude', 'status', ledger))
            if authority_status.get('status') != 'session_status':
                raise ValueError('authority must support session status')
            result = {**settings(ledger), 'local_sessions': local_status['sessions'],
                      'authority_sessions': authority_status['sessions'],
                      'authority_max_sessions': authority_status['max_sessions'],
                      'active_sessions': authority_status['active_sessions']}
            result['boundary'] = 'One configured authority per account; clients outside it remain uncontrolled.'
        print(json.dumps(result))
        return 0
    except Exception as exc:
        result = {'allowed': False, 'reasons': ['coordination_unavailable']}
        if args.action == 'set' and isinstance(exc, ValueError):
            result['message'] = str(exc)
        print(json.dumps(result))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
