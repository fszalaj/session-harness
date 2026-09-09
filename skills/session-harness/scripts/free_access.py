"""Observed recurring free access with a single account executor and zero-price gates."""
import datetime as dt
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import subprocess
import tempfile
import time

import coding_models
from api_transport import APIError, decode_json, request_json

CONFIG = Path.home() / '.config/session-harness/free-access.json'
DATABASE = Path.home() / '.local/state/session-harness/free-access.sqlite3'
POLICY = Path(__file__).resolve().parent.parent / 'references/free-coding-models.json'
ORIGIN = 'https://openrouter.ai'
DAILY_REQUESTS = 50
MINUTE_REQUESTS = 20
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')


def validate_config(config):
    if isinstance(config, dict) and config.get('schema_version') == 2:
        import free_accounts
        return free_accounts.validate_config(config)
    common = {'schema_version', 'enabled', 'mixed_work', 'mode', 'authority'}
    if (not isinstance(config, dict) or type(config.get('schema_version')) is not int
            or config['schema_version'] != 1 or config.get('mode') != 'observed'
            or type(config.get('enabled')) is not bool or type(config.get('mixed_work')) is not bool):
        raise ValueError('invalid_free_configuration')
    if config.get('authority') == 'local':
        if set(config) != common | {'credential_file', 'models'}:
            raise ValueError('invalid_free_configuration')
        if (not isinstance(config['credential_file'], str)
                or not Path(config['credential_file']).is_absolute()
                or len(config['credential_file']) > 4096):
            raise ValueError('invalid_free_credential_path')
        models = config['models']
        if (not isinstance(models, list) or not 1 <= len(models) <= 32
                or any(not isinstance(x, str) or not x.endswith(':free') for x in models)
                or len(set(models)) != len(models)):
            raise ValueError('invalid_free_models')
        reviewed, _ = coding_models.load_policy(POLICY)
        if set(models) - {row['id'] for row in reviewed['models']}:
            raise ValueError('free_model_not_reviewed')
    elif config.get('authority') == 'ssh':
        if set(config) != common | {'command'}:
            raise ValueError('invalid_free_configuration')
        command = config['command']
        if (not isinstance(command, list) or not 2 <= len(command) <= 40
                or any(not isinstance(x, str) or not x or len(x) > 4096
                       or re.search(r'[\x00-\x1f\x7f]', x) for x in command)
                or Path(command[0]).name != 'ssh'):
            raise ValueError('invalid_free_authority_command')
    else:
        raise ValueError('invalid_free_authority')
    return config


def private_read(path, limit):
    path = Path(path)
    if os.name == 'nt':
        from windows_security import protect
        protect(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as source:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or (os.name != 'nt' and stat.S_IMODE(info.st_mode) & 0o077)
                or (hasattr(os, 'getuid') and info.st_uid != os.getuid())):
            raise ValueError('free_private_file_permissions')
        data = source.read(limit + 1)
        if len(data) > limit:
            raise ValueError('free_private_file_too_large')
        return data


def load_config(path=CONFIG, *, optional=False):
    if optional and not Path(path).exists():
        return None
    try:
        return validate_config(decode_json(private_read(path, 32768)))
    except OSError:
        raise ValueError('free_configuration_unavailable') from None


def save_config(config, path=CONFIG):
    config = validate_config(config)
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == 'nt':
        from windows_security import protect
        protect(path.parent)
    fd, temporary = tempfile.mkstemp(prefix='.free-access-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as target:
            json.dump(config, target, indent=2)
            target.write('\n')
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {'status': 'configured', 'authority': config['authority'],
            'enabled': config['enabled'], 'mixed_work': config['mixed_work'],
            'mode': 'observed', 'paid_fallback': False}


def zero(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        return False
    try:
        parsed = Decimal(value)
        return parsed.is_finite() and parsed == 0
    except (InvalidOperation, ValueError):
        return False


def zero_prices(pricing):
    if not isinstance(pricing, dict) or not {'prompt', 'completion'} <= set(pricing):
        return False
    def check(value):
        if isinstance(value, dict):
            return bool(value) and all(check(v) for v in value.values())
        if isinstance(value, list):
            return bool(value) and all(check(v) for v in value)
        return zero(value)
    return check(pricing)


def catalog():
    result = coding_models.catalog(POLICY)
    data = request_json(ORIGIN, '/api/v1/models', headers={'Accept': 'application/json'}, timeout=20)
    if not isinstance(data.get('data'), list):
        raise ValueError('invalid_free_catalog')
    live = {}
    for row in data['data']:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or row['id'] in live:
            raise ValueError('invalid_free_catalog')
        live[row['id']] = row
    eligible, excluded = [], list(result['excluded'])
    for row in result['models']:
        current = live.get(row['id'], {})
        if not row['id'].endswith(':free') or not zero_prices(current.get('pricing')):
            excluded.append({'id': row['id'], 'reasons': ['free_price_unverified']})
            continue
        canonical = current.get('canonical_slug')
        if canonical is not None and (not isinstance(canonical, str) or len(canonical) > 200):
            raise ValueError('invalid_free_catalog')
        eligible.append({**row, 'canonical_model': canonical,
                         'access_kind': 'recurring_free', 'reset_cadence': 'daily',
                         'billing_pool': 'openrouter:free', 'independent_judgment': False})
    return {**result, 'status': 'free_catalog', 'models': eligible, 'excluded': excluded,
            'execution_requires': ['free_configuration', 'zero_key_cap', 'fresh_free_catalog',
                                   'observed_shared_request_admission'],
            'free_limits_source': 'https://openrouter.ai/docs/api_reference/limits',
            'monthly_money_budget_required': False, 'paid_fallback': False}


def credentials(config):
    try:
        data = private_read(config['credential_file'], 32768).decode('utf-8')
    except (OSError, UnicodeError):
        raise ValueError('free_credential_unavailable') from None
    keys = re.findall(r'^API key: (sk-or-v1-[0-9a-f]{64})\r?$', data, re.M)
    if len(keys) != 1:
        raise ValueError('free_credential_unavailable')
    return {'Accept': 'application/json', 'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + keys[0]}


def evidence(config):
    if not config['enabled']:
        raise ValueError('free_access_disabled')
    headers = credentials(config)
    response = request_json(ORIGIN, '/api/v1/key', headers=headers, timeout=20)
    row = response.get('data')
    if (not isinstance(row, dict) or not zero(row.get('limit'))
            or not zero(row.get('limit_remaining'))):
        raise ValueError('free_zero_key_cap_required')
    result = catalog()
    available = {row['id']: row for row in result['models']}
    if set(config['models']) - set(available):
        raise ValueError('configured_free_model_unavailable')
    return headers, result, {key: row.get(key) for key in ('limit', 'limit_remaining', 'usage')}


class FreeLedger:
    def __init__(self, path=DATABASE):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == 'nt':
            from windows_security import prepare_private_file
            prepare_private_file(self.path)
        elif self.path.exists():
            info = self.path.lstat()
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077
                    or (hasattr(os, 'getuid') and info.st_uid != os.getuid())):
                raise ValueError('free_private_file_permissions')
        else:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS free_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS free_requests (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, '
                       'model TEXT NOT NULL, created REAL NOT NULL, status TEXT NOT NULL, receipt TEXT)')
            db.execute('INSERT OR IGNORE INTO free_state VALUES (?,?)', ('fingerprint_key', secrets.token_hex(32)))

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.execute('PRAGMA busy_timeout=10000')
            with connection:
                yield connection
        finally:
            connection.close()

    def fingerprint(self, packet):
        with self.connect() as db:
            key = db.execute("SELECT value FROM free_state WHERE key='fingerprint_key'").fetchone()[0]
        return hmac.new(bytes.fromhex(key), json.dumps(packet, sort_keys=True).encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def snapshot(db, now):
        date = dt.datetime.fromtimestamp(now, dt.timezone.utc)
        start = date.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        today = db.execute('SELECT count(*) FROM free_requests WHERE created>=?', (start,)).fetchone()[0]
        minute = db.execute('SELECT count(*) FROM free_requests WHERE created>?', (now - 60,)).fetchone()[0]
        pending = [{'id': row[0], 'model': row[1], 'status': row[2]} for row in db.execute(
            "SELECT id,model,status FROM free_requests WHERE status IN ('running','unresolved')")]
        models = dict(db.execute('SELECT model,count(*) FROM free_requests WHERE created>=? GROUP BY model', (start,)))
        reasons = (['free_request_unresolved'] if pending else [])
        if today >= DAILY_REQUESTS:
            reasons.append('free_daily_request_limit')
        if minute >= MINUTE_REQUESTS:
            reasons.append('free_minute_request_limit')
        return {'status': 'free_ready' if not reasons else 'free_blocked', 'allowed': not reasons,
                'reasons': reasons, 'billing_pool': 'openrouter:free', 'authority': 'local',
                'day': date.date().isoformat(), 'reset_at': start + 86400,
                'daily_requests': today, 'daily_limit': DAILY_REQUESTS,
                'minute_requests': minute, 'minute_limit': MINUTE_REQUESTS,
                'progress': today / DAILY_REQUESTS, 'model_requests': models,
                'pending': pending, 'history_partial': True, 'external_remaining': None,
                'quota_mode': 'observed_with_provider_enforced_limits', 'paid_fallback': False}

    def status(self, now=None):
        with self.connect() as db:
            return self.snapshot(db, time.time() if now is None else now)

    def existing(self, identifier, fingerprint):
        with self.connect() as db:
            row = db.execute('SELECT fingerprint,model,status,receipt FROM free_requests WHERE id=?', (identifier,)).fetchone()
        if row is None:
            return None
        if not hmac.compare_digest(row[0], fingerprint):
            raise ValueError('free_request_id_conflict')
        return {'status': 'free_duplicate', 'request_id': identifier, 'requested_model': row[1],
                'request_status': row[2], 'receipt': json.loads(row[3]) if row[3] else None,
                'automatic_retry': False}

    def reserve(self, identifier, fingerprint, models, selected, now=None):
        now = time.time() if now is None else now
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM free_requests WHERE id=?', (identifier,)).fetchone():
                raise ValueError('free_duplicate_race')
            state = self.snapshot(db, now)
            if not state['allowed']:
                return state
            model = (min(models, key=lambda value: (state['model_requests'].get(value, 0), models.index(value)))
                     if selected == 'auto' else selected)
            if model not in models:
                raise ValueError('free_model_not_configured')
            db.execute('INSERT INTO free_requests VALUES (?,?,?,?,?,NULL)',
                       (identifier, fingerprint, model, now, 'running'))
        return {'allowed': True, 'status': 'free_reserved', 'model': model}

    def finish(self, identifier, status, receipt):
        if status not in {'completed', 'unresolved', 'rejected'}:
            raise ValueError('invalid_free_receipt_status')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            count = db.execute("UPDATE free_requests SET status=?,receipt=? WHERE id=? AND status='running'",
                               (status, json.dumps(receipt, default=str), identifier)).rowcount
            if count != 1:
                raise ValueError('invalid_free_receipt_transition')

    def reconcile(self, identifier):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            count = db.execute("UPDATE free_requests SET status='abandoned' WHERE id=? AND status IN ('running','unresolved')",
                               (identifier,)).rowcount
            if count != 1:
                raise ValueError('free_request_not_unresolved')
        return {'status': 'free_reconciled', 'request_id': identifier, 'quota_refunded': False}


def run(config, packet, *, ledger=None, config_path=None):
    if set(packet) != {'id', 'model', 'prompt', 'max_output_tokens', 'timeout'}:
        raise ValueError('invalid_free_packet')
    if (not isinstance(packet['id'], str) or not IDENTIFIER.fullmatch(packet['id'])
            or not isinstance(packet['prompt'], str) or not packet['prompt'].strip()
            or len(packet['prompt'].encode('utf-8')) > 8192
            or type(packet['max_output_tokens']) is not int or not 1 <= packet['max_output_tokens'] <= 8192
            or type(packet['timeout']) not in (int, float) or not 1 <= packet['timeout'] <= 180
            or packet['model'] not in ['auto', *config['models']]):
        raise ValueError('invalid_free_packet')
    ledger = ledger or FreeLedger()
    fingerprint = ledger.fingerprint(packet)
    existing = ledger.existing(packet['id'], fingerprint)
    if existing:
        return existing
    headers, live, before = evidence(config)
    if config_path is not None and load_config(config_path) != config:
        raise ValueError('free_configuration_changed')
    candidates = {row['id']: row for row in live['models']}
    if any(packet['max_output_tokens'] > candidates[model]['max_output_tokens'] for model in config['models']):
        raise ValueError('free_output_limit_exceeded')
    job = ledger.reserve(packet['id'], fingerprint, config['models'], packet['model'])
    if not job['allowed']:
        return job
    model = job['model']
    row = candidates[model]
    body = {'model': model, 'messages': [{'role': 'user', 'content': packet['prompt']}],
            'max_tokens': packet['max_output_tokens'], 'stream': False, 'n': 1,
            'usage': {'include': True},
            'provider': {'allow_fallbacks': False, 'require_parameters': True,
                         'data_collection': 'deny',
                         'max_price': {'prompt': 0, 'completion': 0, 'request': 0, 'image': 0}}}
    receipt = {'request_id': packet['id'], 'requested_model': model,
               'model_family': row['family'], 'billing_service': 'openrouter',
               'billing_pool': 'openrouter:free', 'access_kind': 'recurring_free',
               'requires_manager_inspection': True, 'independent_judgment': False,
               'automatic_retry': False, 'policy_sha256': live['policy_sha256']}
    try:
        response = request_json(ORIGIN, '/api/v1/chat/completions', 'POST', headers=headers,
                                body=json.dumps(body).encode(), timeout=packet['timeout'])
        usage = response.get('usage')
        if not isinstance(usage, dict) or not zero(usage.get('cost')):
            raise ValueError('free_cost_unverified')
        expected = {model}
        if row.get('canonical_model'):
            expected.add(row['canonical_model'])
        if not isinstance(response.get('model'), str) or response['model'] not in expected:
            raise ValueError('free_model_mismatch')
        receipt.update(actual_cost_usd='0', actual_model=response['model'])
        for key in ('prompt_tokens', 'completion_tokens'):
            count = usage.get(key)
            if type(count) is not int or not 0 <= count <= 10 ** 12:
                raise ValueError('free_usage_unverified')
            receipt[key] = count
        choices = response.get('choices')
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise ValueError('free_output_unverified')
        message = choices[0].get('message')
        if (not isinstance(message, dict) or message.get('tool_calls') or message.get('function_call')
                or not isinstance(message.get('content'), str) or not message['content'].strip()
                or len(message['content'].encode()) > 262144 or choices[0].get('finish_reason') != 'stop'):
            ledger.finish(packet['id'], 'rejected', receipt)
            return {**receipt, 'status': 'free_output_rejected'}
        ledger.finish(packet['id'], 'completed', receipt)
        return {**receipt, 'status': 'completed', 'text': message['content']}
    except (ValueError, APIError, OSError, TypeError, KeyError) as exc:
        receipt['status'] = 'free_unresolved'
        receipt['reason'] = str(exc) if type(exc) is ValueError or isinstance(exc, APIError) else 'free_response_unverified'
        if isinstance(exc, APIError) and exc.http_status is not None:
            receipt['http_status'] = exc.http_status
        receipt['error'] = 'Free response, identity or zero cost unconfirmed; inspect receipt before explicit reconciliation.'
        ledger.finish(packet['id'], 'unresolved', receipt)
        return receipt


def dispatch(action, payload=None, *, config_path=CONFIG, local_only=False, ledger=None):
    if os.environ.get('SESSION_HARNESS_LEAF'):
        raise ValueError('recursion_blocked')
    config = load_config(config_path)
    if not config['enabled']:
        raise ValueError('free_access_disabled')
    if action not in {'models', 'status', 'run'}:
        raise ValueError('invalid_free_action')
    if config['authority'] == 'ssh':
        if local_only:
            raise ValueError('free_authority_loop')
        packet = json.dumps({'version': 1, 'action': action, 'payload': payload}).encode()
        if len(packet) > 65536:
            raise ValueError('free_packet_too_large')
        try:
            result = subprocess.run(config['command'], input=packet, capture_output=True, timeout=250)
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError('free_authority_unavailable_inspect_remote_journal') from None
        if len(result.stdout) > 524288:
            raise ValueError('free_authority_invalid_response')
        try:
            response = decode_json(result.stdout)
            response = json.loads(json.dumps(response, default=float, allow_nan=False))
        except ValueError:
            raise ValueError('free_authority_unavailable_inspect_remote_journal') from None
        if response.get('protocol_version') != 1 or not isinstance(response.get('result'), dict):
            raise ValueError('free_authority_invalid_response')
        return response['result']
    if config['schema_version'] == 2:
        import free_accounts
        return free_accounts.dispatch(config, action, payload, config_path=config_path)
    if action == 'models':
        return catalog()
    if action == 'run':
        return run(config, payload, ledger=ledger, config_path=config_path)
    _, live, account = evidence(config)
    return {**(ledger or FreeLedger()).status(), 'authentication': 'verified',
            'key_credit_cap': account['limit'], 'configured_models': config['models'],
            'eligible_models': [row['id'] for row in live['models']], 'mixed_work': config['mixed_work']}
