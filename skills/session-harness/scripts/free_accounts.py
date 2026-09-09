"""Explicit free account pools, executed on one host without paid fallback."""
from decimal import Decimal, InvalidOperation
from contextlib import contextmanager
import hashlib
import hmac
import json
from pathlib import Path
import re
import time
import unicodedata

import free_access as legacy
from api_transport import APIError, request_json

DATABASE = Path.home() / '.local/state/session-harness/free-accounts.sqlite3'
PROVIDERS = {
    'groq': ('https://api.groq.com', '/openai/v1'),
    'mistral': ('https://api.mistral.ai', '/v1'),
    'huggingface': ('https://router.huggingface.co', '/v1'),
    'morph': ('https://api.morphllm.com', '/v1'),
    'nvidia': ('https://integrate.api.nvidia.com', '/v1'),
}
SHA = re.compile(r'[0-9a-f]{64}\Z')
HF_ROUTES = frozenset({'novita', 'groq', 'scaleway', 'deepinfra', 'ovhcloud'})
RECEIPT_FIELDS = frozenset({'request_id', 'billing_service', 'billing_pool', 'requires_manager_inspection',
    'independent_judgment', 'automatic_retry', 'reservation', 'actual_cost_usd', 'status', 'requested_model',
    'actual_model', 'prompt_tokens', 'completion_tokens', 'model_family', 'reason', 'http_status',
    'entitlement_evidence_kind', 'account_identity_source', 'requested_reasoning_effort'})


def number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)) or len(str(value)) > 64:
        raise ValueError('free_invalid_number')
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError('free_invalid_number') from None
    if not result.is_finite() or result < 0 or (positive and result == 0) or result > 10 ** 12:
        raise ValueError('free_invalid_number')
    return result


def stamp(value):
    if type(value) not in (int, float, Decimal) or not 0 < float(value) < 10 ** 11:
        raise ValueError('free_invalid_timestamp')
    return float(value)


def validate_config(config):
    common = {'schema_version', 'enabled', 'mixed_work', 'mode', 'authority'}
    if (type(config.get('schema_version')) is not int or config['schema_version'] != 2
            or type(config.get('enabled')) is not bool or type(config.get('mixed_work')) is not bool
            or config.get('mode') != 'observed'):
        raise ValueError('invalid_free_configuration')
    if config.get('authority') == 'ssh':
        legacy.validate_config({**config, 'schema_version': 1})
        return config
    if config.get('authority') != 'local' or set(config) != common | {'accounts'}:
        raise ValueError('invalid_free_configuration')
    accounts = config['accounts']
    if not isinstance(accounts, dict) or not accounts or set(accounts) - {'openrouter', *PROVIDERS}:
        raise ValueError('free_invalid_accounts')
    for provider, row in accounts.items():
        if not isinstance(row, dict) or type(row.get('enabled')) is not bool:
            raise ValueError('free_invalid_account')
        if not row['enabled']:
            if set(row) != {'enabled', 'reason'} or not isinstance(row['reason'], str) or len(row['reason']) > 300:
                raise ValueError('free_invalid_disabled_account')
            continue
        if provider == 'openrouter':
            legacy.validate_config(row)
            if row['authority'] != 'local' or row['schema_version'] != 1:
                raise ValueError('free_account_executor_must_be_local')
            continue
        fields = {'enabled', 'credential_file', 'credential_sha256', 'account_sha256', 'model',
                  'response_models', 'family', 'context_tokens', 'max_output_tokens', 'evidence', 'limits'}
        if set(row) not in (fields, fields | {'reasoning_effort'}):
            raise ValueError('free_invalid_account_fields')
        if 'reasoning_effort' in row and (provider not in {'groq', 'mistral'} or row['reasoning_effort'] not in {'none', 'low', 'medium', 'high'}):
            raise ValueError('free_reasoning_control_unsupported')
        if not isinstance(row['credential_file'], str) or not Path(row['credential_file']).is_absolute():
            raise ValueError('free_invalid_credential_path')
        for key in ('credential_sha256', 'account_sha256'):
            if not isinstance(row[key], str) or not SHA.fullmatch(row[key]):
                raise ValueError('free_invalid_account_binding')
        if not isinstance(row['model'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:-]{0,199}', row['model']):
            raise ValueError('free_invalid_model')
        if provider == 'huggingface' and (':' not in row['model'] or row['model'].rsplit(':', 1)[1] in {'auto', 'fastest', 'cheapest', 'preferred'}):
            raise ValueError('free_fixed_hf_provider_required')
        if provider == 'huggingface':
            if row['model'].count(':') != 1 or row['model'].rsplit(':', 1)[1] not in HF_ROUTES:
                raise ValueError('free_fixed_hf_provider_required')
        elif ':' in row['model']:
            raise ValueError('free_invalid_model')
        if (not isinstance(row['response_models'], list) or not 1 <= len(row['response_models']) <= 4
                or any(not isinstance(m, str) or not m or len(m) > 200 for m in row['response_models'])
                or not isinstance(row['family'], str) or not legacy.IDENTIFIER.fullmatch(row['family'])):
            raise ValueError('free_invalid_model_identity')
        for key, maximum in [('context_tokens', 10 ** 7), ('max_output_tokens', 8192)]:
            if type(row[key]) is not int or not 1 <= row[key] <= maximum:
                raise ValueError('free_invalid_model_capacity')
        ev = row['evidence']
        if not isinstance(ev, dict) or set(ev) != {'observed_at', 'expires_at', 'source', 'kind', 'no_paid_overage', 'tokenizer', 'tokenizer_source', 'pricing_source', 'coding', 'hf_routing_only'}:
            raise ValueError('free_invalid_evidence')
        if not 0 < stamp(ev['expires_at']) - stamp(ev['observed_at']) <= 86400:
            raise ValueError('free_evidence_deadline_exceeded')
        for field in ('observed_at', 'expires_at'):
            ev[field] = stamp(ev[field])
        if ev['observed_at'] > time.time():
            raise ValueError('free_future_account_evidence')
        if (ev['kind'] not in {'account_ui_observation', 'account_api_observation'}
                or ev['no_paid_overage'] is not True or ev['tokenizer'] != 'byte_bpe'
                or type(ev['hf_routing_only']) is not bool
                or (provider == 'huggingface' and not ev['hf_routing_only'])):
            raise ValueError('free_account_contract_unverified')
        for field in ('source', 'coding', 'tokenizer_source', 'pricing_source'):
            if not isinstance(ev[field], str) or not ev[field].startswith('https://') or len(ev[field]) > 1000:
                raise ValueError('free_evidence_source_required')
        limits = row['limits']
        if not isinstance(limits, dict) or set(limits) != {'rpm', 'rpd', 'tpm', 'tpd', 'credit_usd', 'input_per_million', 'output_per_million', 'period_start'}:
            raise ValueError('free_invalid_limits')
        for field in ('rpm', 'rpd', 'tpm', 'tpd'):
            if type(limits[field]) is not int or not 1 <= limits[field] <= 10 ** 12:
                raise ValueError('free_invalid_limits')
        for field in ('credit_usd', 'input_per_million', 'output_per_million'):
            number(limits[field])
        if provider in {'mistral', 'huggingface', 'morph'} and number(limits['credit_usd']) == 0:
            raise ValueError('free_credit_allowance_required')
        if provider in {'mistral', 'huggingface', 'morph'} and any(number(limits[k]) == 0 for k in ('input_per_million', 'output_per_million')):
            raise ValueError('free_credit_pricing_required')
        limits['period_start'] = stamp(limits['period_start'])
        if limits['period_start'] > ev['observed_at']:
            raise ValueError('free_future_period')
    return config


def credential(row):
    raw = legacy.private_read(row['credential_file'], 32768).decode('utf-8')
    keys = re.findall(r'^API key: ([A-Za-z0-9_-]{16,256})\r?$', raw, re.M)
    if len(keys) != 1 or not hmac.compare_digest(hashlib.sha256(keys[0].encode()).hexdigest(), row['credential_sha256']):
        raise ValueError('free_credential_binding_changed')
    return {'Authorization': 'Bearer ' + keys[0], 'Accept': 'application/json', 'Content-Type': 'application/json'}


def preflight(provider, row, now):
    ev = row['evidence']
    if not ev['observed_at'] <= now < ev['expires_at']:
        raise ValueError('free_account_evidence_expired')
    headers = credential(row)
    origin, prefix = PROVIDERS[provider]
    data = request_json(origin, prefix + '/models', headers=headers, timeout=20)
    models = data.get('data')
    catalog_id = row['model'].rsplit(':', 1)[0] if provider == 'huggingface' else row['model']
    matches = [m for m in models if isinstance(m, dict) and m.get('id') == catalog_id] if isinstance(models, list) else []
    if len(matches) != 1:
        raise ValueError('free_model_unavailable')
    if provider == 'huggingface':
        routes = matches[0].get('providers', [])
        routes = [r for r in routes if isinstance(r, dict) and r.get('provider') == row['model'].rsplit(':', 1)[1] and r.get('status') == 'live'] if isinstance(routes, list) else []
        if len(routes) != 1:
            raise ValueError('free_hf_route_unavailable')
        prices = routes[0].get('pricing', {})
        if any(number(prices.get(k)) > number(row['limits'][setting]) for k, setting in [('input', 'input_per_million'), ('output', 'output_per_million')]):
            raise ValueError('free_prices_changed')
        who = request_json('https://huggingface.co', '/api/whoami-v2', headers=headers, timeout=20)
        if (who.get('type') != 'user' or not isinstance(who.get('name'), str)
                or hashlib.sha256(who['name'].encode()).hexdigest() != row['account_sha256']):
            raise ValueError('free_account_identity_changed')
    return headers


class AccountsLedger(legacy.FreeLedger):
    @contextmanager
    def connect(self):
        with super().connect() as db:
            if db.execute('PRAGMA journal_mode').fetchone()[0] != 'delete':
                raise ValueError('free_local_delete_journal_required')
            db.execute('PRAGMA synchronous=FULL')
            yield db

    def __init__(self, path=DATABASE):
        if Path(path).resolve() == legacy.DATABASE.resolve():
            raise ValueError('free_group_and_legacy_ledgers_must_differ')
        super().__init__(path)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS account_jobs (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, provider TEXT NOT NULL, created REAL NOT NULL, state TEXT NOT NULL, reservation TEXT NOT NULL, receipt TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS account_bindings (provider TEXT PRIMARY KEY, account TEXT NOT NULL, period REAL NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS account_jobs_provider_created ON account_jobs(provider,created)')

    @staticmethod
    def clock(db, now):
        old = db.execute("SELECT value FROM free_state WHERE key='account_clock'").fetchone()
        if old and now < float(old[0]):
            raise ValueError('free_clock_moved_backwards')
        db.execute("INSERT OR REPLACE INTO free_state VALUES ('account_clock',?)", (str(now),))

    @staticmethod
    def state(db, provider, row, now):
        if not row['enabled']:
            return {'allowed': False, 'status': 'disabled', 'reasons': [row['reason']]}
        if provider == 'openrouter':
            state = legacy.FreeLedger().status(now=now)
            if db.execute("SELECT 1 FROM account_jobs WHERE provider=? AND state IN ('running','unresolved')", (provider,)).fetchone():
                state.update(allowed=False, status='free_blocked', reasons=['free_request_unresolved'])
            return state
        limits = row['limits']
        jobs = db.execute('SELECT created,state,reservation FROM account_jobs WHERE provider=?', (provider,)).fetchall()
        pending = any(j[1] in {'running', 'unresolved'} for j in jobs)
        minute = [json.loads(j[2]) for j in jobs if j[0] > now - 60]
        day = [json.loads(j[2]) for j in jobs if j[0] > now - 86400]
        costs = sum((Decimal(json.loads(j[2])['credit_usd']) for j in jobs if j[0] >= limits['period_start']), Decimal(0))
        used = {'rpm': len(minute), 'rpd': len(day), 'tpm': sum(r['tokens'] for r in minute), 'tpd': sum(r['tokens'] for r in day)}
        ratios = [used[k] / limits[k] for k in used]
        reasons = ['free_request_unresolved'] if pending else []
        if any(used[k] >= limits[k] for k in used):
            reasons.append('free_rate_limit')
        if number(limits['credit_usd']):
            ratios.append(float(costs / number(limits['credit_usd'])))
            if costs >= number(limits['credit_usd']):
                reasons.append('free_credit_limit')
        binding = db.execute('SELECT account,period FROM account_bindings WHERE provider=?', (provider,)).fetchone()
        if binding and (binding[0] != row['account_sha256'] or binding[1] != limits['period_start']):
            reasons.append('free_account_or_period_change_requires_reconciliation')
        if not row['evidence']['observed_at'] <= now < row['evidence']['expires_at']:
            reasons.append('free_account_evidence_expired')
        return {'allowed': not reasons, 'status': 'free_ready' if not reasons else 'free_blocked',
                'reasons': reasons, 'progress': max(ratios), 'reserved': used,
                'reserved_free_credit_usd': str(costs), 'pending': pending,
                'billing_pool': provider + ':free', 'history_partial': True,
                'provider_reset_at': None, 'automatic_refill': False}

    def states(self, config, now):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.clock(db, now)
            return {p: self.state(db, p, row, now) for p, row in config['accounts'].items()}

    def bind(self, config, packet, now):
        fingerprint = self.fingerprint(packet)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.clock(db, now)
            old = db.execute('SELECT fingerprint,provider,state,receipt FROM account_jobs WHERE id=?', (packet['id'],)).fetchone()
            if old:
                if not hmac.compare_digest(fingerprint, old[0]):
                    raise ValueError('free_request_id_conflict')
                return {'status': 'free_duplicate', 'provider': old[1], 'request_status': old[2], 'receipt': json.loads(old[3]) if old[3] else None}
            states = {p: self.state(db, p, row, now) for p, row in config['accounts'].items() if row['enabled']}
            if not states or any(not s['allowed'] for s in states.values()):
                return {'status': 'free_blocked', 'allowed': False, 'accounts': states}
            provider = min(states, key=lambda p: (states[p]['progress'], p)) if packet['model'] == 'auto' else packet['model']
            if provider not in states:
                raise ValueError('free_provider_not_enabled')
            row = config['accounts'][provider]
            reservation = {'tokens': 0, 'credit_usd': '0'}
            if provider != 'openrouter':
                text = packet['prompt']
                input_bound = max(len(text.encode()), len(unicodedata.normalize('NFC', text).encode())) + 1024
                output = packet['max_output_tokens']
                total = input_bound + output
                if total > row['context_tokens'] or output > row['max_output_tokens']:
                    raise ValueError('free_output_limit_exceeded')
                limits = row['limits']
                cost = (input_bound * number(limits['input_per_million']) + output * number(limits['output_per_million'])) / 1000000
                st = states[provider]
                if (any(st['reserved'][k] + total > limits[k] for k in ('tpm', 'tpd'))
                        or (number(limits['credit_usd']) and Decimal(st['reserved_free_credit_usd']) + cost > number(limits['credit_usd']))):
                    return {'status': 'free_blocked', 'allowed': False, 'reasons': ['free_reservation_exceeds_allowance']}
                reservation = {'tokens': total, 'input_tokens': input_bound, 'output_tokens': output, 'credit_usd': str(cost)}
                db.execute('INSERT OR IGNORE INTO account_bindings VALUES (?,?,?)', (provider, row['account_sha256'], limits['period_start']))
            db.execute('INSERT INTO account_jobs VALUES (?,?,?,?,?,?,NULL)', (packet['id'], fingerprint, provider, now, 'running', json.dumps(reservation)))
        return {'status': 'reserved', 'provider': provider, 'reservation': reservation}

    def complete(self, identifier, state, receipt):
        if state not in {'completed', 'unresolved', 'rejected'}:
            raise ValueError('free_receipt_state_invalid')
        if not isinstance(receipt, dict) or set(receipt) - RECEIPT_FIELDS or len(json.dumps(receipt, allow_nan=False)) > 8192:
            raise ValueError('free_receipt_fields_invalid')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            count = db.execute("UPDATE account_jobs SET state=?,receipt=? WHERE id=? AND state='running'", (state, json.dumps(receipt), identifier)).rowcount
            if count != 1:
                raise ValueError('free_receipt_transition_invalid')

    def reconcile_account(self, identifier, evidence, config=None):
        if not legacy.IDENTIFIER.fullmatch(identifier) or not isinstance(evidence, str) or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,200}', evidence):
            raise ValueError('free_reconciliation_evidence_required')
        if config is not None:
            validate_config(config)
            if config['authority'] != 'local':
                raise ValueError('free_account_executor_must_be_local')
        openrouter_verified = False
        if config and config['accounts'].get('openrouter', {}).get('enabled'):
            legacy.evidence(config['accounts']['openrouter'])
            openrouter_verified = True
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state,receipt,provider,created FROM account_jobs WHERE id=?', (identifier,)).fetchone()
            if not row or row[0] not in {'running', 'unresolved'}:
                raise ValueError('free_request_not_unresolved')
            receipt = json.loads(row[1]) if row[1] else {}
            if (row[0] == 'running' or receipt.get('http_status') in {402, 403}) and not (row[2] == 'openrouter' and openrouter_verified):
                observed = (config or {}).get('accounts', {}).get(row[2], {}).get('evidence', {}).get('observed_at', 0)
                expires = (config or {}).get('accounts', {}).get(row[2], {}).get('evidence', {}).get('expires_at', 0)
                if not row[3] < observed <= time.time() < expires:
                    raise ValueError('free_billing_reverification_required')
            receipt['reconciliation_evidence'] = evidence
            count = db.execute("UPDATE account_jobs SET state='abandoned',receipt=? WHERE id=? AND state IN ('running','unresolved')", (json.dumps(receipt), identifier)).rowcount
            if count != 1:
                raise ValueError('free_receipt_transition_invalid')
        return {'status': 'free_reconciled', 'request_id': identifier, 'quota_refunded': False}

    def renew_period(self, provider, start, evidence):
        stamp(start)
        if provider not in PROVIDERS or not isinstance(evidence, str) or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,200}', evidence):
            raise ValueError('free_reconciliation_evidence_required')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.clock(db, time.time())
            old = db.execute('SELECT period FROM account_bindings WHERE provider=?', (provider,)).fetchone()
            if not old or not old[0] < start <= time.time():
                raise ValueError('free_new_observed_period_required')
            if db.execute("SELECT 1 FROM account_jobs WHERE provider=? AND state IN ('running','unresolved')", (provider,)).fetchone():
                raise ValueError('free_request_unresolved')
            db.execute('UPDATE account_bindings SET period=? WHERE provider=?', (start, provider))
            db.execute('INSERT INTO free_state VALUES (?,?)', ('renewal:' + provider + ':' + str(start), evidence))
        return {'status': 'free_reconciled', 'provider': provider, 'period_start': start, 'history_preserved': True}


def dispatch(config, action, packet=None, *, config_path=None, ledger=None):
    validate_config(config)
    if config['authority'] != 'local':
        raise ValueError('free_account_executor_must_be_local')
    if not config['enabled']:
        raise ValueError('free_access_disabled')
    ledger = ledger or AccountsLedger()
    now = time.time()
    if action == 'run':
        if (not isinstance(packet, dict) or set(packet) != {'id', 'model', 'prompt', 'max_output_tokens', 'timeout'}
                or not isinstance(packet['id'], str) or not legacy.IDENTIFIER.fullmatch(packet['id'])
                or not isinstance(packet['prompt'], str) or not packet['prompt'].strip() or len(packet['prompt'].encode()) > 8192
                or packet['model'] not in ['auto', *config['accounts']]
                or type(packet['max_output_tokens']) is not int or not 1 <= packet['max_output_tokens'] <= 8192
                or type(packet['timeout']) not in (int, float) or not 1 <= packet['timeout'] <= 180):
            raise ValueError('invalid_free_packet')
        with ledger.connect() as db:
            old = db.execute('SELECT fingerprint,provider,state,receipt FROM account_jobs WHERE id=?', (packet['id'],)).fetchone()
        if old:
            if not hmac.compare_digest(ledger.fingerprint(packet), old[0]):
                raise ValueError('free_request_id_conflict')
            return {'status': 'free_duplicate', 'provider': old[1], 'request_status': old[2], 'receipt': json.loads(old[3]) if old[3] else None}
    headers = {}
    for provider, row in config['accounts'].items():
        if row['enabled']:
            if provider == 'openrouter':
                legacy.evidence(row)
            else:
                headers[provider] = preflight(provider, row, now)
    if config_path is not None and legacy.load_config(config_path) != config:
        raise ValueError('free_configuration_changed')
    states = ledger.states(config, time.time())
    enabled = [v for p, v in states.items() if config['accounts'][p]['enabled']]
    if action in {'status', 'models'}:
        return {'status': 'free_ready' if enabled and all(s['allowed'] for s in enabled) else 'free_blocked',
                'allowed': bool(enabled) and all(s['allowed'] for s in enabled), 'accounts': states,
                'progress': min((s['progress'] for s in enabled), default=0), 'mixed_work': config['mixed_work'],
                'models': {p: row.get('model', row.get('models')) for p, row in config['accounts'].items() if row['enabled']},
                'paid_fallback': False, 'automatic_retry': False}
    if action != 'run':
        raise ValueError('invalid_free_action')
    bound = ledger.bind(config, packet, time.time())
    if bound['status'] != 'reserved':
        return bound
    provider = bound['provider']
    row = config['accounts'][provider]
    receipt = {'request_id': packet['id'], 'billing_service': provider, 'billing_pool': provider + ':free',
               'requires_manager_inspection': True, 'independent_judgment': False, 'automatic_retry': False,
               'reservation': bound['reservation'], 'actual_cost_usd': None}
    try:
        if provider == 'openrouter':
            result = legacy.run(row, {**packet, 'model': 'auto'})
            receipt.update({k: result[k] for k in ('status', 'requested_model', 'actual_model', 'actual_cost_usd',
                'prompt_tokens', 'completion_tokens', 'model_family', 'reason', 'http_status') if k in result})
            ledger.complete(packet['id'], 'completed' if result['status'] == 'completed' else 'unresolved', receipt)
            return result
        receipt.update(requested_model=row['model'], model_family=row['family'], entitlement_evidence_kind=row['evidence']['kind'],
                       account_identity_source='whoami_api' if provider == 'huggingface' else 'credential_bound_account_observation')
        origin, prefix = PROVIDERS[provider]
        body = {'model': row['model'], 'messages': [{'role': 'user', 'content': packet['prompt']}],
                'max_tokens': packet['max_output_tokens'], 'stream': False}
        if 'reasoning_effort' in row:
            body['reasoning_effort'] = row['reasoning_effort']
            receipt['requested_reasoning_effort'] = row['reasoning_effort']
        response = request_json(origin, prefix + '/chat/completions', 'POST', headers=headers[provider], body=json.dumps(body).encode(), timeout=packet['timeout'])
        actual = response.get('model')
        if isinstance(actual, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:-]{0,199}', actual):
            receipt['actual_model'] = actual
        if actual not in row['response_models']:
            raise ValueError('free_model_mismatch')
        usage = response.get('usage')
        if not isinstance(usage, dict):
            raise ValueError('free_usage_unverified')
        for field, maximum in [('prompt_tokens', bound['reservation']['input_tokens']), ('completion_tokens', bound['reservation']['output_tokens'])]:
            if type(usage.get(field)) is not int or not 0 <= usage[field] <= maximum:
                raise ValueError('free_usage_exceeds_reservation')
            receipt[field] = usage[field]
        receipt['actual_model'] = response['model']
        choices = response.get('choices')
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise ValueError('free_output_unverified')
        choice = choices[0]
        message = choice.get('message')
        if (not isinstance(message, dict) or message.get('tool_calls') or message.get('function_call')
                or not isinstance(message.get('content'), str) or not message['content'].strip()
                or len(message['content'].encode()) > 262144 or choice.get('finish_reason') != 'stop'):
            receipt['status'] = 'free_output_rejected'
            ledger.complete(packet['id'], 'rejected', receipt)
            return receipt
        receipt['status'] = 'completed'
        ledger.complete(packet['id'], 'completed', receipt)
        return {**receipt, 'text': message['content']}
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as exc:
        receipt.update(status='free_unresolved', reason='free_response_or_accounting_unverified')
        if type(exc) is ValueError and str(exc) in {'free_model_mismatch', 'free_usage_unverified', 'free_usage_exceeds_reservation', 'free_output_unverified'}:
            receipt['reason'] = str(exc)
        if isinstance(exc, APIError):
            receipt.update(reason=exc.status, http_status=exc.http_status)
        ledger.complete(packet['id'], 'unresolved', receipt)
        return receipt
