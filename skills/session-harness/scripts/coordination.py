"""Share account budgets with independently configurable native session capacity."""
import argparse
import json
import math
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


def _validate_maintenance(value):
    if (not isinstance(value, dict) or set(value) != {'owner', 'started'} or
            not isinstance(value['owner'], str) or
            not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value['owner']) or
            type(value['started']) not in (int, float) or
            not math.isfinite(value['started']) or value['started'] < 0):
        raise ValueError('invalid maintenance state; explicit recovery required')
    return value


def _maintenance(db):
    row = db.execute("SELECT value FROM state WHERE key='maintenance_v1'").fetchone()
    return _validate_maintenance(json.loads(row[0])) if row else None


def _maintenance_status(value):
    return {'maintenance_version': 1, 'maintenance': value,
            'maintenance_attention': value is not None and time.time() - value['started'] > 900}


def _sessions(db):
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='native_sessions'").fetchone()
    return [dict(service=r[0], owner=r[1], started=r[2]) for r in
            db.execute('SELECT service,owner,started FROM native_sessions ORDER BY service,started')] if exists else []


def configure(ledger, authority=None, max_sessions=None):
    with ledger._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        previous = _settings(db)
        maintenance = _maintenance(db)
        value = validate_settings({'authority': previous['authority'] if authority is None else authority,
                                   'max_sessions': previous['max_sessions'] if max_sessions is None else max_sessions})
        if maintenance is not None and previous['authority'] != value['authority']:
            raise ValueError('release maintenance before changing authority')
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
        rows = _sessions(db)
        maintenance = _maintenance(db)
    return {**policy, **_maintenance_status(maintenance), 'allowed': False, 'status': 'session_status', 'sessions': rows,
            'active_sessions': {service: sum(r['service'] == service for r in rows) for service in SERVICES}}


def local(action, service, owner, ledger):
    if service not in SERVICES or not isinstance(owner, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', owner):
        raise ValueError('invalid session identity')
    policy = settings(ledger)
    if policy['authority'] != 'local':
        raise ValueError('authority must terminate locally; forwarding chains are forbidden')
    if action == 'check':
        with ledger._connect() as db:
            if _maintenance(db) is not None:
                return {'allowed': False, 'reasons': ['account_maintenance']}
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
        maintenance = _maintenance(db)
        if action == 'maintenance-release':
            if maintenance is not None and maintenance['owner'] != owner:
                raise ValueError('maintenance owner mismatch')
            db.execute("DELETE FROM state WHERE key='maintenance_v1'")
            return {'allowed': False, 'status': 'maintenance_released', **_maintenance_status(None)}
        if action == 'maintenance-acquire':
            rows = _sessions(db)
            if rows or (maintenance is not None and maintenance['owner'] != owner):
                return {'allowed': False, 'status': 'maintenance_busy', 'sessions': rows,
                        **_maintenance_status(maintenance)}
            if maintenance is None:
                maintenance = {'owner': owner, 'started': time.time()}
                db.execute("INSERT INTO state VALUES ('maintenance_v1', ?)", (json.dumps(maintenance),))
            return {'allowed': False, 'status': 'maintenance_acquired', **_maintenance_status(maintenance)}
        if action != 'admit':
            raise ValueError('invalid coordination action')
        if maintenance is not None:
            return {'allowed': False, 'reasons': ['account_maintenance']}
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
    if action not in ('release', 'status', 'maintenance-acquire', 'maintenance-release'):
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
    if action == 'status' and response.get('maintenance_version') is not None:
        if (type(response['maintenance_version']) is not int or response['maintenance_version'] != 1 or
                'maintenance' not in response or type(response.get('maintenance_attention')) is not bool):
            raise ValueError('invalid authority maintenance status')
        if response['maintenance'] is not None:
            _validate_maintenance(response['maintenance'])
    if action in ('maintenance-acquire', 'maintenance-release'):
        expected = ('maintenance_acquired', 'maintenance_busy') if action == 'maintenance-acquire' else ('maintenance_released',)
        if (response['allowed'] is not False or type(response.get('maintenance_version')) is not int or
                response['maintenance_version'] != 1 or response.get('status') not in expected or
                'maintenance' not in response):
            raise ValueError('authority must support maintenance; no local fallback')
        state = response['maintenance']
        if state is not None:
            _validate_maintenance(state)
        if response['status'] == 'maintenance_acquired' and (state is None or state['owner'] != owner):
            raise ValueError('invalid authority maintenance owner')
        if response['status'] == 'maintenance_released' and state is not None:
            raise ValueError('invalid authority maintenance release')
    return response


def balance_local(operation, payload, ledger):
    import balance
    if settings(ledger)['authority'] != 'local':
        raise ValueError('balance authority must terminate locally')
    fields = {'status': set(), 'role_admission': {'service', 'model', 'role', 'supervised'},
              'reserve': {'request', 'client_services'}, 'start': {'id'},
              'finish': {'id', 'status', 'metadata'},
              'reconcile': {'id', 'confirm_stopped'}}
    if operation not in fields or not isinstance(payload, dict) or set(payload) != fields[operation]:
        raise ValueError('invalid balance operation or fields')
    return {'protocol_version': 1, **getattr(balance, operation)(ledger, **payload)}


def balance_dispatch(operation, payload, ledger=None):
    ledger = ledger or Ledger()
    if operation == 'reserve':
        payload = {**payload, 'client_services': ledger.setup_status()['services']}
    authority = settings(ledger)['authority']
    if authority == 'local':
        return balance_local(operation, payload, ledger)
    setup = ledger.setup_status()
    if not setup.get('complete'):
        raise ValueError('environment_setup_required')
    packet = {'action': 'balance', 'version': 1, 'operation': operation, 'payload': payload}
    raw = json.dumps(packet).encode()
    if len(raw) > 4096:
        raise ValueError('balance request too large')
    from platform_runtime import which
    executable = which('ssh')
    if not executable:
        raise ValueError('SSH authority transport unavailable')
    command = 'python3 "$HOME/.agents/skills/session-harness/scripts/coordination.py" serve'
    try:
        result = subprocess.run([executable, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                                 '-o', 'ConnectTimeout=5', authority, command], input=raw,
                                capture_output=True, timeout=90)
    except subprocess.TimeoutExpired as exc:
        raise ValueError('balance authority timed out; keep unresolved task, no local fallback') from exc
    if result.returncode or len(result.stdout) > 256 * 1024:
        raise ValueError('balance authority unavailable; no local fallback')
    response = json.loads(result.stdout)
    if (not isinstance(response, dict) or type(response.get('allowed')) is not bool
            or type(response.get('protocol_version')) is not int or response['protocol_version'] != 1):
        raise ValueError('authority must support balance protocol version 1')
    service = response.get('service')
    if service is not None and service not in setup['services']:
        raise ValueError('service_not_configured on this client')
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
    maintenance_release = sub.add_parser('maintenance-release')
    maintenance_release.add_argument('--owner', required=True)
    maintenance_release.add_argument('--confirm-stopped', action='store_true', required=True)
    args = parser.parse_args(argv)
    try:
        ledger = Ledger()
        if args.action == 'serve':
            raw = sys.stdin.buffer.read(4097)
            if len(raw) > 4096:
                raise ValueError('coordination request too large')
            packet = json.loads(raw)
            if isinstance(packet, dict) and packet.get('action') == 'balance':
                if (set(packet) != {'action', 'version', 'operation', 'payload'}
                        or type(packet['version']) is not int or packet['version'] != 1):
                    raise ValueError('invalid balance protocol')
                result = balance_local(packet['operation'], packet['payload'], ledger)
            elif not isinstance(packet, dict) or set(packet) != {'action', 'service', 'owner'}:
                raise ValueError('invalid coordination request')
            else:
                result = local(**packet, ledger=ledger)
        elif args.action == 'set':
            if args.authority is None and args.max_sessions is None:
                raise ValueError('set requires --authority or --max-sessions')
            result = configure(ledger, args.authority, args.max_sessions)
        elif args.action == 'maintenance-release':
            result = dispatch('maintenance-release', 'claude', args.owner, ledger)
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
                      'local_maintenance_version': local_status['maintenance_version'],
                      'local_maintenance': local_status['maintenance'],
                      'local_maintenance_attention': local_status['maintenance_attention'],
                      'authority_maintenance_version': authority_status.get('maintenance_version'),
                      'authority_maintenance': authority_status.get('maintenance'),
                      'authority_maintenance_attention': authority_status.get('maintenance_attention'),
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
