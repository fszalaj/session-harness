"""Serialize protected account sessions locally or through one explicit SSH authority."""
import argparse
import json
import os
import re
import subprocess
import sys
import time

from quota import Ledger

SERVICES = ('codex', 'claude', 'antigravity')


def configure(ledger, authority, max_sessions=1):
    if (type(max_sessions) is not int or not 1 <= max_sessions <= 4 or
            not isinstance(authority, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]{0,252}', authority)):
        raise ValueError('invalid authority or session count')
    value = {'authority': authority, 'max_sessions': max_sessions}
    if settings(ledger) == value:
        return value
    with ledger._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='native_sessions'").fetchone()
        if exists and db.execute('SELECT 1 FROM native_sessions LIMIT 1').fetchone():
            raise ValueError('finish active sessions before changing authority')
        db.execute("INSERT OR REPLACE INTO state VALUES ('coordination_v1', ?)", (json.dumps(value),))
    return value


def settings(ledger):
    with ledger._connect() as db:
        row = db.execute("SELECT value FROM state WHERE key='coordination_v1'").fetchone()
    value = json.loads(row[0]) if row else {'authority': 'local', 'max_sessions': 1}
    if (not isinstance(value, dict) or type(value.get('max_sessions')) is not int
            or not 1 <= value['max_sessions'] <= 4):
        raise ValueError('invalid coordination settings')
    host = value.get('authority')
    if not isinstance(host, str) or (host != 'local' and not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]{0,252}', host)):
        raise ValueError('invalid SSH authority')
    return value


def local(action, service, owner, ledger):
    if service not in SERVICES or not isinstance(owner, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', owner):
        raise ValueError('invalid session identity')
    policy = settings(ledger)
    if policy['authority'] != 'local':
        raise ValueError('authority must terminate locally; forwarding chains are forbidden')
    if action == 'check':
        import usage
        return usage.require_admission(service, ledger=ledger)
    with ledger._connect() as db:
        db.execute('BEGIN IMMEDIATE')
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
            return {'allowed': False, 'reasons': ['account_session_busy']}
        if not present:
            db.execute('INSERT INTO native_sessions VALUES (?,?,?)', (service, owner, time.time()))
    import usage
    result = usage.require_admission(service, ledger=ledger)
    if not result.get('allowed') and not present:
        local('release', service, owner, ledger)
    return result


def dispatch(action, service, owner, ledger=None):
    ledger = ledger or Ledger()
    policy = settings(ledger)
    if policy['authority'] == 'local':
        return local(action, service, owner, ledger)
    if action != 'release':
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
    config.add_argument('--authority', required=True, help='local or existing trusted SSH user@host')
    config.add_argument('--max-sessions', type=int, default=1)
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
            result = configure(ledger, args.authority, args.max_sessions)
        elif args.action == 'release':
            result = dispatch('release', args.service, args.owner, ledger)
        else:
            result = settings(ledger)
            with ledger._connect() as db:
                exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='native_sessions'").fetchone()
                result['local_sessions'] = [dict(service=r[0], owner=r[1], started=r[2]) for r in
                    db.execute('SELECT service,owner,started FROM native_sessions')] if exists else []
            result['boundary'] = 'One configured authority per account; clients outside it remain uncontrolled.'
        print(json.dumps(result))
        return 0
    except Exception:
        print(json.dumps({'allowed': False, 'reasons': ['coordination_unavailable']}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
