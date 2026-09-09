"""Summarize native usage metadata without retaining conversation content."""
import collections
import datetime as dt
import json
from pathlib import Path
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
        files = list(root.rglob('*.jsonl'))
        if cutoff is not None:
            files = [path for path in files if path.stat().st_mtime >= cutoff]
        for path in files:
            model, session = 'unknown', None
            try:
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
                        day = str(item.get('timestamp', ''))[:10]
                        payload = item.get('payload', {})
                        if not isinstance(payload, dict):
                            payload = {}
                        if service == 'codex':
                            if kind == 'session_meta':
                                session = payload.get('id', payload.get('session_id'))
                            elif kind == 'turn_context':
                                model = payload.get('model', 'unknown')
                            elif kind == 'token_usage_record' and isinstance(payload.get('usage'), dict):
                                key = payload.get('response_id')
                                values = _tokens(payload['usage'], ('input_tokens', 'cached_input_tokens',
                                    'output_tokens', 'reasoning_output_tokens', 'total_tokens'))
                                if isinstance(key, str) and key:
                                    _merge(records, key, day, model, values)
                        elif kind == 'assistant' and isinstance(item.get('message'), dict):
                            message = item['message']
                            usage = message.get('usage')
                            key = message.get('id')
                            model = message.get('model', 'unknown')
                            if isinstance(key, str) and isinstance(usage, dict) and model != '<synthetic>':
                                _merge(records, key, day, model, _tokens(usage, ('input_tokens',
                                    'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')))
                        elif kind == 'cost-state':
                            key, value = item.get('sessionId'), item.get('totalCostUSD')
                            if isinstance(key, str) and type(value) in (int, float) and 0 <= value <= 1e12:
                                costs[key] = max(costs.get(key, 0), value)
            except (OSError, UnicodeError):
                unreadable += 1
        grouped = collections.defaultdict(collections.Counter)
        for day, model, values in records.values():
            try:
                dt.date.fromisoformat(day)
            except ValueError:
                malformed += 1
                continue
            if since is None or day >= since:
                grouped[(day, model)].update(values)
        output[service] = {
            'rows': [dict(day=key[0], model=key[1], **values) for key, values in sorted(grouped.items())],
            'files': len(files), 'unreadable_files': unreadable, 'malformed_records': malformed,
            'coverage': 'local recorded metadata only; files modified since cutoff; mirrored/forked records deduplicated by response/message ID',
            'host_attribution': 'file location does not prove where inference ran',
            'billing': 'token telemetry is not an invoice or subscription quota',
            'cost_estimate_usd_examined_sessions': sum(costs.values()) if costs else None,
            'cost_estimate_scope': 'cumulative native estimates, not date-filtered charges',
        }
    output['antigravity'] = {'rows': [], 'coverage': 'no verified local token-history adapter; use quota history'}
    return output


def _merge(records, key, day, model, values):
    if not isinstance(model, str) or len(model) > 160:
        model = 'unknown'
    previous = records.get(key)
    if previous is None:
        records[key] = (day, model, values)
    else:
        previous[2].update({name: max(value, previous[2].get(name, 0)) for name, value in values.items()})


def report(ledger, since=None, home=None):
    history = {}
    with ledger._connect() as db:
        for key, value in db.execute("SELECT key,value FROM state WHERE key LIKE 'service:%'"):
            state = json.loads(value)
            history[key.removeprefix('service:')] = {
                'days': {day: pools for day, pools in state.get('days', {}).items()
                         if since is None or day >= since},
                'observed_at': state.get('observed_at'),
                'units': 'percentage points per pool; overlapping pools must not be summed',
                'host_attribution': 'aggregate account observations, not per-host billing',
            }
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        money_count = db.execute('SELECT count(*) FROM money_requests').fetchone()[0] if 'money_requests' in tables else 0
    return {'status': 'audit', 'allowed': False, 'host': socket.gethostname(),
            'authority': coordination.settings(ledger)['authority'],
            'setup': ledger.setup_status(), 'quota_history': history,
            'local_token_metadata': token_history(home, since),
            'money_requests_recorded_here': money_count,
            'money_evidence': 'local harness journal only; zero records does not prove zero external API invoices',
            'inference_performed': False}
