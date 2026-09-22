"""Summarize native usage metadata without retaining conversation content."""
import collections
import datetime as dt
import json
from pathlib import Path
import re
import socket

import coordination


def _tokens(value, names):
    return {key: item for key, item in value.items()
            if key in names and type(item) is int and 0 <= item <= 10**15}


def token_history(home=None, since=None):
    home = Path.home() if home is None else Path(home)
    if since is not None:
        if dt.date.fromisoformat(since).isoformat() != since:
            raise ValueError('since must be YYYY-MM-DD')
    cutoff = dt.datetime.combine(dt.date.fromisoformat(since), dt.time(), tzinfo=dt.timezone.utc).timestamp() if since else None
    output = {}
    formats = {'codex': home / '.codex/sessions', 'claude': home / '.claude/projects'}
    for service, root in formats.items():
        records, costs, unreadable, malformed = {}, {}, 0, 0
        session_roles = {}
        files = list(root.rglob('*.jsonl'))
        for path in files:
            model, session, role = 'unknown', 'unknown', 'unknown'
            try:
                if cutoff is not None and path.stat().st_mtime < cutoff:
                    continue
                with path.open(encoding='utf-8') as stream:
                    for line in stream:
                        try:
                            item = json.loads(line)
                            if not isinstance(item, dict):
                                raise ValueError('not an object')
                        except (ValueError, TypeError):
                            malformed += 1
                            continue
                        kind = item.get('type')
                        try:
                            stamp = dt.datetime.fromisoformat(str(item.get('timestamp', '')).replace('Z', '+00:00'))
                            day = stamp.astimezone(dt.timezone.utc).date().isoformat() if stamp.tzinfo else ''
                        except ValueError:
                            day = ''
                        payload = item.get('payload', {})
                        if not isinstance(payload, dict):
                            payload = {}
                        if service == 'codex':
                            if kind == 'session_meta':
                                session = payload.get('id', payload.get('session_id'))
                                source = payload.get('source')
                                role = 'subagent' if isinstance(source, dict) and 'subagent' in source else 'manager' if source in ('cli', 'exec', 'vscode') else 'unknown'
                                if isinstance(session, str):
                                    session_roles[session] = role
                            elif kind == 'turn_context':
                                model = payload.get('model', 'unknown')
                            elif kind == 'token_usage_record' and isinstance(payload.get('usage'), dict):
                                key = payload.get('response_id')
                                values = _tokens(payload['usage'], ('input_tokens', 'cached_input_tokens',
                                    'output_tokens', 'reasoning_output_tokens', 'total_tokens'))
                                if isinstance(key, str) and key:
                                    _merge(records, key, day, model, values,
                                           payload.get('session_id', payload.get('thread_id', session)), role)
                        elif kind == 'assistant' and isinstance(item.get('message'), dict):
                            message = item['message']
                            usage = message.get('usage')
                            key = message.get('id')
                            model = message.get('model', 'unknown')
                            if isinstance(key, str) and isinstance(usage, dict) and model != '<synthetic>':
                                _merge(records, key, day, model, _tokens(usage, ('input_tokens',
                                    'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')),
                                    item.get('sessionId'), 'subagent' if item.get('isSidechain') is True else 'unknown')
                        elif kind == 'cost-state':
                            key, value = item.get('sessionId'), item.get('totalCostUSD')
                            if isinstance(key, str) and type(value) in (int, float) and 0 <= value <= 1e12:
                                costs[key] = max(costs.get(key, 0), value)
            except (OSError, UnicodeError):
                unreadable += 1
        grouped = collections.defaultdict(collections.Counter)
        sessions = collections.defaultdict(collections.Counter)
        for day, model, values, session, role in records.values():
            try:
                dt.date.fromisoformat(day)
            except ValueError:
                malformed += 1
                continue
            if since is None or day >= since:
                role = session_roles.get(session, role)
                grouped[(day, model)].update(values)
                grouped[(day, model)]['response_count'] += 1
                sessions[(day, model, session, role)].update(values)
                sessions[(day, model, session, role)]['response_count'] += 1
        output[service] = {
            'rows': [dict(day=key[0], model=key[1], **values) for key, values in sorted(grouped.items())],
            'sessions': [dict(day=key[0], model=key[1], session_id=key[2], role=key[3], **values)
                         for key, values in sorted(sessions.items())],
            'files': len(files), 'unreadable_files': unreadable, 'malformed_records': malformed,
            'coverage': 'local recorded metadata only; files modified since cutoff; mirrored/forked records deduplicated by response/message ID',
            'host_attribution': 'file location does not prove where inference ran',
            'billing': 'token telemetry is not an invoice or subscription quota',
            'cost_estimate_usd_examined_sessions': sum(costs.values()) if costs else None,
            'cost_estimate_scope': 'cumulative native estimates, not date-filtered charges',
        }
    output['antigravity'] = {'rows': [], 'coverage': 'no verified local token-history adapter; use quota history'}
    return output


def _merge(records, key, day, model, values, session=None, role='unknown'):
    if not day:
        return
    if not isinstance(model, str) or len(model) > 160:
        model = 'unknown'
    if not isinstance(session, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', session):
        session = 'unknown'
    previous = records.get(key)
    if previous is None:
        records[key] = (day, model, values, session, role)
    else:
        previous[2].update({name: max(value, previous[2].get(name, 0)) for name, value in values.items()})


def account_report(ledger, since=None):
    if since is not None and dt.date.fromisoformat(since).isoformat() != since:
        raise ValueError('since must be YYYY-MM-DD')
    history = {}
    with ledger._connect() as db:
        for key, value in db.execute("SELECT key,value FROM state WHERE key LIKE 'service:%'"):
            state = json.loads(value)
            history[key.removeprefix('service:')] = {
                'days': {day: pools for day, pools in state.get('days', {}).items()
                         if since is None or day >= since},
                'observed_at': state.get('observed_at'),
                'source': state.get('source'),
                'current_pools': [{'pool': name, 'used_percent': pool.get('used_percent'),
                                   'resets_at': pool.get('resets_at')}
                                  for name, pool in state.get('pools', {}).items()],
                'units': 'percentage points per pool; overlapping pools must not be summed',
                'host_attribution': 'aggregate account observations, not per-host billing',
            }
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        money_count = db.execute('SELECT count(*) FROM money_requests').fetchone()[0] if 'money_requests' in tables else 0
        work = [dict(day=day, service=service, status=status, count=count)
                for day, service, status, count in db.execute(
                    'SELECT day,service,status,count(*) FROM balance_jobs WHERE (? IS NULL OR day>=?) GROUP BY day,service,status',
                    (since, since))] if 'balance_jobs' in tables else []
        money = collections.defaultdict(collections.Counter)
        if 'money_requests' in tables:
            for scope, status, charged, reserved, created, currency in db.execute(
                    'SELECT scope,status,charged,reserved,created,currency FROM money_requests'):
                day = ledger._day(created)
                if since is None or day >= since:
                    row = money[(day, scope, status, currency)]
                    row['count'] += 1
                    row['charged_ticks'] += charged or 0
                    if status in {'RESERVED', 'DISPATCHED', 'UNRESOLVED'}:
                        row['pending_ticks'] += reserved
    return {'allowed': False, 'status': 'audit', 'quota_history': history,
            'work_receipts': work, 'money_requests_recorded_here': money_count,
            'api_requests': [dict(day=k[0], scope=k[1], status=k[2], currency=k[3], **v)
                             for k, v in sorted(money.items())],
            'api_units': 'ticks are 1e-10 currency units; reservations are not charges',
            'coverage': 'work receipts exclude direct managers and independent reviews; API journal excludes external calls',
            'accounting_timezone': ledger.policy['timezone']}


def report(ledger, since=None, home=None):
    authority = coordination.settings(ledger)['authority']
    local = account_report(ledger, since)
    accounting = local
    accounting_status = 'local_authority'
    if authority != 'local':
        try:
            accounting = coordination.balance_dispatch('audit', {'since': since}, ledger)
            if (not isinstance(accounting, dict) or accounting.get('status') != 'audit'
                    or accounting.get('allowed') is not False
                    or type(accounting.get('protocol_version')) is not int
                    or accounting.get('protocol_version') != 1):
                raise ValueError('invalid audit response')
            accounting_status = 'shared_authority'
        except (OSError, ValueError, KeyError, TypeError):
            accounting = {}
            accounting_status = 'authority_unavailable'
    return {'status': 'audit', 'allowed': False, 'host': socket.gethostname(),
            'authority': authority, 'accounting_status': accounting_status,
            'setup': ledger.setup_status(), 'quota_history': accounting.get('quota_history', {}),
            'accounting': accounting, 'local_accounting': local,
            'local_token_metadata': token_history(home, since),
            'money_requests_recorded_here': local['money_requests_recorded_here'],
            'money_evidence': 'local harness journal only; zero records does not prove zero external API invoices',
            'inference_performed': False}
