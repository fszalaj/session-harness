"""Opt-in native dispatch balancing using the shared private quota ledger."""
import fnmatch
import hashlib
import hmac
import json
import math
import re
import secrets
import time

import budget_policy
import usage

NATIVE = frozenset({'codex', 'claude', 'antigravity', 'copilot', 'cursor'})
AUTOMATIC_NATIVE = frozenset({'codex', 'claude', 'antigravity'})
OPEN = {'reserved', 'running'}
TERMINAL = {'completed', 'failed', 'denied'}
KEY = 'balance_v1'
ROLES = frozenset({'manager', 'reviewer', 'verifier', 'worker', 'investigator'})


def _load(db):
    row = db.execute('SELECT value FROM state WHERE key=?', (KEY,)).fetchone()
    value = json.loads(row[0]) if row else {'enabled': False, 'services': [], 'max_lead': .15}
    if not isinstance(value, dict) or type(value.get('enabled')) is not bool:
        raise ValueError('invalid balance policy')
    if not isinstance(value.get('services'), list) or any(not isinstance(s, str) for s in value['services']):
        raise ValueError('invalid balance participants')
    if not 0 <= budget_policy.numeric(value.get('max_lead'), 'max lead') <= 1:
        raise ValueError('invalid balance tolerance')
    _validate_constraints(value.get('solo_blocked', []))
    return value


def _validate_constraints(rules):
    if not isinstance(rules, list) or len(rules) > 32:
        raise ValueError('solo_blocked must be a list of at most 32 rules')
    clean = []
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {'service', 'model', 'roles'}:
            raise ValueError('invalid model constraint fields')
        service, model, roles = rule['service'], rule['model'], rule['roles']
        if not isinstance(service, str) or service not in NATIVE:
            raise ValueError('unsupported constrained native service')
        if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9_.:/@+\[\]*?-]{1,200}', model):
            raise ValueError('invalid model pattern')
        if (not isinstance(roles, list) or not roles
                or any(not isinstance(role, str) or role not in ROLES for role in roles)
                or len(roles) != len(set(roles))):
            raise ValueError('invalid constrained roles')
        clean.append(dict(service=service, model=model, roles=sorted(roles)))
    return clean


def _constraints(ledger, db, rules):
    clean = _validate_constraints(rules)
    for rule in clean:
        ledger._require_setup(db, 'native', rule['service'])
    return clean


def set_constraints(ledger, rules):
    with ledger._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        config = _load(db)
        config['solo_blocked'] = _constraints(ledger, db, rules)
        _save(db, config)
        return dict(_reply(), enabled=config['enabled'], solo_blocked=config['solo_blocked'])


def role_admission(ledger, service, model, role, supervised=False):
    if not isinstance(service, str) or service not in NATIVE:
        raise ValueError('unsupported native service')
    if model is not None and (not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9_.:/@+\[\]-]{1,200}', model)):
        raise ValueError('invalid model')
    if not isinstance(role, str) or role not in ROLES:
        raise ValueError('unsupported role')
    if type(supervised) is not bool:
        raise ValueError('supervised must be boolean')
    try:
        with ledger._connect() as db:
            db.execute('BEGIN DEFERRED')
            ledger._require_setup(db, 'native', service)
            rules = _constraints(ledger, db, _load(db).get('solo_blocked', []))
    except ValueError as exc:
        reason = str(exc).split(';', 1)[0]
        if reason not in {'environment_setup_required', 'service_not_configured'}:
            reason = 'invalid_role_policy'
        return dict(_reply(reason), service=service, solo_blocked=[], requires_supervision=False)
    requires_supervision = False
    for rule in rules:
        pattern = ''.join('[[]' if c == '[' else '[]]' if c == ']' else c for c in rule['model'])
        if service == rule['service'] and role in rule['roles'] and (model is None or fnmatch.fnmatchcase(model, pattern)):
            requires_supervision = True
            break
    reason = ('model_identity_unverified' if model is None else 'supervision_required') if requires_supervision and not supervised else None
    return dict(_reply(reason), service=service, solo_blocked=rules, requires_supervision=requires_supervision)


def _fingerprint_key(db):
    row = db.execute("SELECT value FROM state WHERE key='balance_fingerprint_key'").fetchone()
    return json.loads(row[0]) if row else None


def _save(db, value):
    db.execute('INSERT OR REPLACE INTO state VALUES (?, ?)', (KEY, json.dumps(value, allow_nan=False)))


def _table(db):
    db.execute('CREATE TABLE IF NOT EXISTS balance_jobs (id TEXT PRIMARY KEY, service TEXT NOT NULL, day TEXT NOT NULL, status TEXT NOT NULL, value TEXT NOT NULL)')
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS balance_open_service ON balance_jobs(service) WHERE status IN ('reserved', 'running')")
    db.execute('CREATE TABLE IF NOT EXISTS work_routes (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, route TEXT NOT NULL)')


def work_route(ledger, id, fingerprint, proposed):
    _identifier(id, 'id')
    if not isinstance(fingerprint, str) or not re.fullmatch('[0-9a-f]{64}', fingerprint):
        raise ValueError('invalid fingerprint')
    if proposed not in {None, 'native', 'recurring_free'}:
        raise ValueError('invalid work route')
    with ledger._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        _table(db)
        old = db.execute('SELECT value FROM balance_jobs WHERE id=?', (id,)).fetchone()
        bound = db.execute('SELECT fingerprint,route FROM work_routes WHERE id=?', (id,)).fetchone()
        if old:
            job = json.loads(old[0])
            if not hmac.compare_digest(job['fingerprint'], fingerprint):
                return _reply('fingerprint_mismatch')
            return _reply(route='native', bound=True)
        if bound:
            if not hmac.compare_digest(bound[0], fingerprint):
                return _reply('fingerprint_mismatch')
            return _reply(route=bound[1], bound=True)
        if proposed is not None:
            db.execute('INSERT INTO work_routes VALUES (?,?,?)', (id, fingerprint, proposed))
        return _reply(route=proposed, bound=proposed is not None)


def _snapshot(db, settings=False):
    result = dict(db.execute('SELECT key, value FROM state'))
    if settings:
        result = {k: v for k, v in result.items() if not k.startswith('service:')}
        if 'budget_v1' in result:
            budget = json.loads(result['budget_v1'])
            for key in ('anchors', 'audit', 'deadline_states'):
                budget.pop(key, None)
            result['budget_v1'] = json.dumps(budget, sort_keys=True)
    return result


def _policy(ledger, db, config):
    persisted = db.execute("SELECT value FROM state WHERE key='policy'").fetchone()
    if not persisted or json.loads(persisted[0]) != ledger.policy:
        return 'quota_policy_changed'
    if config.get('enabled') is not True:
        return 'balance_disabled'
    services = config.get('services')
    if (not isinstance(services, list) or len(services) < 2 or len(services) != len(set(services))
            or any(s not in NATIVE for s in services)):
        return 'unsupported_participants'
    if not re.fullmatch('[0-9a-f]{64}', config.get('hmac_key', '')):
        return 'fingerprint_key_missing'
    if not 0 <= budget_policy.numeric(config.get('max_lead'), 'max lead') <= 1:
        return 'invalid_max_lead'
    for service in services:
        ledger._require_setup(db, 'native', service)
    return None


def _reply(reason=None, **extra):
    return dict(allowed=reason is None, status=reason or 'ready', reasons=[reason] if reason else [], service=None, **extra)


def configure(ledger, enabled, services=None, max_lead=.15, solo_blocked=None):
    if type(enabled) is not bool:
        raise ValueError('enabled must be boolean')
    if not 0 <= budget_policy.numeric(max_lead, 'max lead') <= 1:
        raise ValueError('max lead must be between zero and one')
    with ledger._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        _table(db)
        old = _load(db)
        rules = _constraints(ledger, db, old.get('solo_blocked', []) if solo_blocked is None else solo_blocked)
        if not enabled:
            old['enabled'] = False
            old['solo_blocked'] = rules
            _save(db, old)
            return dict(_reply(), enabled=False, status='disabled', solo_blocked=rules)
        setup = ledger._setup(db)
        selected = sorted(NATIVE.intersection(setup['services'])) if services is None else services
        if (not isinstance(selected, list) or any(not isinstance(s, str) for s in selected)
                or len(selected) < 2 or len(selected) != len(set(selected)) or any(s not in NATIVE for s in selected)):
            raise ValueError('at least two supported native participants required; API routes are unsupported')
        for service in selected:
            ledger._require_setup(db, 'native', service)
        if old.get('enabled') and not old.get('hmac_key'):
            return _reply('fingerprint_key_missing')
        candidate = dict(enabled=True, services=sorted(selected), max_lead=max_lead,
                         hmac_key=old.get('hmac_key') or _fingerprint_key(db) or secrets.token_hex(32))
        candidate['solo_blocked'] = rules
        before = _snapshot(db)
        settings_before = _snapshot(db, settings=True)
    result, validated = _evaluate(ledger, candidate, override=True)
    if not result['allowed']:
        return result
    with ledger._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current = _snapshot(db)
        # Refresh can change accounting, but never configuration.
        if current != validated or _snapshot(db, settings=True) != settings_before:
            return _reply('state_changed')
        if current.get(KEY) != before.get(KEY):
            return _reply('state_changed')
        _save(db, candidate)
    result['enabled'] = True
    result['solo_blocked'] = rules
    result['unsupported_services'] = sorted(set(setup['services']) - NATIVE)
    result['api_services_excluded'] = sorted(setup['api_services'])
    return result


def fingerprint(ledger, content):
    if not isinstance(content, bytes):
        raise ValueError('fingerprint input must be bytes')
    with ledger._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        config = _load(db)
        row = db.execute("SELECT value FROM state WHERE key='balance_fingerprint_key'").fetchone()
        key = config.get('hmac_key') or (json.loads(row[0]) if row else '')
        if config.get('enabled') and not config.get('hmac_key'):
            raise ValueError('fingerprint_key_missing')
        if not key:
            key = secrets.token_hex(32)
            db.execute("INSERT INTO state VALUES ('balance_fingerprint_key', ?)", (json.dumps(key),))
        if not re.fullmatch('[0-9a-f]{64}', key):
            raise ValueError('fingerprint_key_missing')
    return hmac.new(bytes.fromhex(key), content, hashlib.sha256).hexdigest()


def _evaluate(ledger, config=None, override=False, refresh=True):
    with ledger._connect() as db:
        db.execute('BEGIN DEFERRED')
        config = config if override else _load(db)
        error = _policy(ledger, db, config)
        before = _snapshot(db, settings=True)
    if error:
        return _reply(error), None
    summaries, captured, reasons = {}, {}, []
    for service in config['services']:
        check = usage.require_admission(service, ledger=ledger) if refresh else ledger.check(service)
        if service == 'claude' and not check.get('allowed'):
            import claude_admission
            check = claude_admission.worker_check(ledger, check)
        with ledger._connect() as db:
            captured['service:' + service] = _snapshot(db).get('service:' + service)
        pools = check.get('pools', [])
        progress = []
        for pool in pools:
            if pool.get('strategy') == 'window' or pool.get('model_scope') is not None:
                continue
            try:
                ceiling = budget_policy.numeric(pool.get('daily_ceiling'), 'daily ceiling')
                consumed = budget_policy.numeric(pool.get('daily_consumed'), 'daily consumed')
                if ceiling <= 0 or consumed < 0 or pool.get('strategy') not in {'adaptive', 'fixed'}:
                    raise ValueError('invalid pacing budget')
                ratio = consumed / ceiling
                if not math.isfinite(ratio):
                    raise ValueError('nonfinite pacing progress')
                progress.append(ratio)
            except ValueError:
                reasons.append(f'{service}:evidence_unavailable:invalid_pacing_budget')
        if not progress:
            reasons.append(f'{service}:evidence_unavailable:no_pacing_pool')
        if not check.get('allowed'):
            details = check.get('reasons') or ['missing_admission']
            for reason in details:
                evidence = any(token in reason for token in ('missing', 'stale', 'incomplete', 'unknown', 'invalid', 'refresh', 'new_day', 'future'))
                reasons.append(f"{service}:{'evidence_unavailable' if evidence else 'quota_denied'}:{reason}")
        summaries[service] = dict(progress=max(progress) if progress else None, day=check.get('day'),
                                  observed_at=check.get('observed_at'), pools=pools,
                                  reasons=check.get('reasons', []))
    with ledger._connect() as db:
        db.execute('BEGIN DEFERRED')
        snapshot = _snapshot(db)
        settings_changed = before != _snapshot(db, settings=True)
        if settings_changed or any(snapshot.get(k) != v for k, v in captured.items()):
            reasons.append('state_changed')
        now = time.time()
        for service, summary in summaries.items():
            state = ledger._service(db, service)
            if (not ledger._fresh(state, now) or summary['day'] != ledger._day(now)
                    or not state or summary['observed_at'] != state['observed_at']):
                reasons.append(f'{service}:evidence_unavailable:stale_or_changed_snapshot')
    changed_only = {'state_changed', *(f'{service}:evidence_unavailable:stale_or_changed_snapshot'
                                       for service in config['services'])}
    if refresh and reasons and not settings_changed and set(reasons).issubset(changed_only):
        return _evaluate(ledger, config, override=override, refresh=False)
    result = _reply(services=summaries, max_lead=config['max_lead'],
                    automatic_selection=_selection(summaries))
    progress_values = [v['progress'] for v in summaries.values() if v['progress'] is not None]
    result['drift'] = (max(progress_values) - min(progress_values)) if len(progress_values) == len(summaries) else None
    result['drift_status'] = ('unavailable' if result['drift'] is None else
                              'within_tolerance' if result['drift'] <= config['max_lead'] + 1e-12 else 'above_tolerance')
    for summary in summaries.values():
        summary['binding_pool'] = _compact(summary)['binding_pool']
    if reasons:
        result.update(allowed=False, status='paused', reasons=reasons)
    return result, snapshot



def _selection(services, provider='auto'):
    automatic = provider in {'auto', 'native'}
    eligible = sorted(set(services) & AUTOMATIC_NATIVE if automatic else services)
    progress = [services[s]['progress'] for s in eligible]
    return dict(mode='current_model' if automatic else 'explicit_provider',
                eligible_services=eligible,
                explicit_only_services=sorted(set(services) - AUTOMATIC_NATIVE),
                minimum_progress=min(progress) if progress and all(p is not None for p in progress) else None)


def _compact(summary):
    fields = ('pool', 'strategy', 'daily_consumed', 'daily_ceiling', 'resets_at',
              'window_minutes', 'window_source', 'history_partial', 'daily_consumption_lower_bound')
    pools = [{key: pool.get(key) for key in fields} for pool in summary.get('pools', [])]
    pacing = []
    for pool in pools:
        if pool['strategy'] in {'adaptive', 'fixed'}:
            try:
                ceiling = budget_policy.numeric(pool['daily_ceiling'], 'daily ceiling')
                consumed = budget_policy.numeric(pool['daily_consumed'], 'daily consumption')
                if ceiling > 0 and math.isfinite(consumed / ceiling):
                    pacing.append((consumed / ceiling, pool['pool']))
            except ValueError:
                pass
    binding = max(pacing, key=lambda value: (value[0], value[1])) if pacing else None
    return dict(day=summary.get('day'), observed_at=summary.get('observed_at'), pools=pools,
                progress=binding[0] if binding else None, binding_pool=binding[1] if binding else None)


def status(ledger, refresh=True):
    result, _ = _evaluate(ledger, refresh=refresh)
    with ledger._connect() as db:
        config = _load(db)
        result['enabled'] = config.get('enabled', False)
        result['max_lead'] = config['max_lead']
        result['solo_blocked'] = _constraints(ledger, db, config.get('solo_blocked', []))
        if not result['enabled'] and result['status'] == 'balance_disabled':
            result.update(allowed=True, status='disabled', reasons=[])
        setup = ledger._setup(db)
        result['unsupported_services'] = sorted(set(setup['services']) - NATIVE)
        result['api_services_excluded'] = sorted(setup['api_services'])
        _table(db)
        rows = db.execute("SELECT value FROM balance_jobs WHERE status IN ('reserved', 'running') ORDER BY id").fetchall()
        rows += db.execute("SELECT value FROM balance_jobs WHERE status NOT IN ('reserved', 'running') ORDER BY rowid DESC LIMIT 50").fetchall()
        result['jobs'] = [_status_job(json.loads(row[0])) for row in rows]
        result['services'] = {service: dict(_compact(summary), reasons=summary.get('reasons', []))
                              for service, summary in result.get('services', {}).items()}
        result['dispatch_counts_today'] = dict(db.execute('SELECT service, COUNT(*) FROM balance_jobs WHERE day=? GROUP BY service', (ledger._day(time.time()),)))
    return result


def _status_job(job):
    public = _public(job)
    fields = {'id', 'service', 'day', 'status', 'created_at', 'updated_at', 'metadata',
              'age_seconds', 'reconcile_command'}
    return {key: value for key, value in public.items() if key in fields}


def _public(job):
    result = {k: v for k, v in job.items() if k != 'fingerprint'}
    if job['status'] in OPEN:
        result.update(age_seconds=max(0, time.time() - job['created_at']),
                      reconcile_command=f"ai-session balance reconcile {job['id']} --confirm-stopped")
    return result


def _job_reply(job, duplicate=False):
    return dict(allowed=not duplicate and job['status'] == 'reserved', status=job['status'], reasons=[],
                service=job['service'], job=_public(job), duplicate=duplicate,
                dispatch_required=not duplicate and job['status'] == 'reserved')


def _identifier(value, name):
    if not isinstance(value, str) or not re.fullmatch('[A-Za-z0-9_.:@-]{1,128}', value):
        raise ValueError(f'invalid {name}')
    return value


def _client_services(ledger, db, supplied):
    services = ledger._setup(db)['services'] if supplied is None else supplied
    if (not isinstance(services, list) or not services or any(not isinstance(s, str) for s in services)
            or len(services) != len(set(services))):
        raise ValueError('invalid client services')
    for service in services:
        budget_policy.label(service, 'client service')
    return set(services)


def reserve(ledger, request, client_services=None):
    if not isinstance(request, dict) or set(request) - {'id', 'fingerprint', 'host', 'role', 'provider'}:
        raise ValueError('invalid request fields')
    for key in ('id', 'host', 'role'):
        _identifier(request.get(key), key)
    if not isinstance(request.get('fingerprint'), str) or not re.fullmatch('[0-9a-f]{64}', request['fingerprint']):
        raise ValueError('invalid fingerprint')
    provider = request.get('provider', 'auto')
    if provider not in NATIVE | {'auto', 'native'}:
        raise ValueError('unsupported native provider')
    with ledger._connect() as db:
        _table(db)
        configured = _client_services(ledger, db, client_services)
        if not set(_load(db)['services']).issubset(configured):
            return _reply('service_not_configured_on_client')
        route = db.execute('SELECT fingerprint,route FROM work_routes WHERE id=?', (request['id'],)).fetchone()
        if route and (route[1] != 'native' or not hmac.compare_digest(route[0], request['fingerprint'])):
            return _reply('work_route_conflict')
        row = db.execute('SELECT value FROM balance_jobs WHERE id=?', (request['id'],)).fetchone()
    if row:
        job = json.loads(row[0])
        if not hmac.compare_digest(job['fingerprint'], request['fingerprint']):
            return _reply('fingerprint_mismatch')
        return _job_reply(job, True)
    result, snapshot = _evaluate(ledger)
    if not result['allowed']:
        return result
    with ledger._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        configured = _client_services(ledger, db, client_services)
        if not set(_load(db)['services']).issubset(configured):
            return _reply('service_not_configured_on_client')
        route = db.execute('SELECT fingerprint,route FROM work_routes WHERE id=?', (request['id'],)).fetchone()
        if route and (route[1] != 'native' or not hmac.compare_digest(route[0], request['fingerprint'])):
            return _reply('work_route_conflict')
        row = db.execute('SELECT value FROM balance_jobs WHERE id=?', (request['id'],)).fetchone()
        if row:
            job = json.loads(row[0])
            return _job_reply(job, True) if hmac.compare_digest(job['fingerprint'], request['fingerprint']) else _reply('fingerprint_mismatch')
        if _snapshot(db) != snapshot:
            return _reply('state_changed')
        now, config = time.time(), _load(db)
        day = ledger._day(now)
        if any(not ledger._fresh(ledger._service(db, s), now) or v['day'] != day for s, v in result['services'].items()):
            return _reply('evidence_unavailable')
        jobs = [json.loads(r[0]) for r in db.execute("SELECT value FROM balance_jobs WHERE status IN ('reserved', 'running')")]
        busy = {j['service'] for j in jobs if j['status'] in OPEN}
        selection = _selection(result['services'], provider)
        if not selection['eligible_services']:
            return _reply('current_model_selection_required', selection=selection)
        minimum = selection['minimum_progress']
        if minimum is None:
            return _reply('evidence_unavailable', selection=selection)
        band = [s for s in selection['eligible_services']
                if result['services'][s]['progress'] <= minimum + config['max_lead'] + 1e-12]
        if provider in NATIVE and provider not in result['services']:
            return _reply('service_not_participating')
        if provider in NATIVE and provider not in band:
            return _reply('max_lead_exceeded', services=result['services'])
        candidates = [s for s in band if s not in busy and (provider not in NATIVE or s == provider)]
        if not candidates:
            return _reply('busy', jobs=[_public(j) for j in jobs if j['status'] in OPEN], services=result['services'])
        counts = dict(db.execute('SELECT service, COUNT(*) FROM balance_jobs WHERE day=? GROUP BY service', (day,)))
        selected = min(candidates, key=lambda s: (counts.get(s, 0), s))
        job = dict(request, provider=provider, service=selected, day=day, status='reserved', created_at=now, updated_at=now,
                   usage_attribution='aggregate_account_only',
                   balance_policy_hash=hashlib.sha256(snapshot[KEY].encode()).hexdigest(),
                   before={s: _compact(v) for s, v in result['services'].items()},
                   decision=dict(max_lead=config['max_lead'], drift=result['drift'],
                                 drift_status=result['drift_status'],
                                 dispatch_counts_today=counts, **selection))
        db.execute('INSERT INTO balance_jobs VALUES (?, ?, ?, ?, ?)',
                   (job['id'], selected, day, 'reserved', json.dumps(job)))
        result.update(_job_reply(job))
        return result


def _metadata(value):
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - {'exit_code', 'duration_seconds', 'reason_code', 'requested_model', 'actual_model', 'requested_effort'}:
        raise ValueError('unsupported metadata fields')
    for key, item in value.items():
        if key in {'requested_model', 'actual_model', 'requested_effort'}:
            if not isinstance(item, str) or not re.fullmatch(r'[A-Za-z0-9_.:/@+\[\]-]{1,200}', item):
                raise ValueError('invalid model metadata')
        elif key == 'reason_code':
            _identifier(item, key)
        else:
            number = budget_policy.numeric(item, key)
            if abs(number) > 1e12 or key == 'duration_seconds' and number < 0:
                raise ValueError('metadata out of bounds')
    return value


def _transition(ledger, identifier, target, metadata=None, observation=None):
    _identifier(identifier, 'id')
    metadata = _metadata(metadata)
    with ledger._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        _table(db)
        row = db.execute('SELECT value FROM balance_jobs WHERE id=?', (identifier,)).fetchone()
        if not row:
            return _reply('job_not_found')
        job = json.loads(row[0])
        if job['status'] == target:
            return _job_reply(job, True)
        valid = job['status'] == 'reserved' if target == 'running' else job['status'] in OPEN
        if not valid:
            return _reply('invalid_transition', job=_public(job))
        job.update(status=target, updated_at=time.time(), metadata=metadata)
        if observation is not None:
            job['after'] = observation
        db.execute('UPDATE balance_jobs SET status=?, value=? WHERE id=?', (target, json.dumps(job), identifier))
        result = _job_reply(job)
        result['allowed'] = True
        return result


def start(ledger, id):
    _identifier(id, 'id')
    with ledger._connect() as db:
        _table(db)
        row = db.execute('SELECT value FROM balance_jobs WHERE id=?', (id,)).fetchone()
    if not row:
        return _reply('job_not_found')
    job = json.loads(row[0])
    if job['status'] != 'reserved':
        return _job_reply(job, True)
    try:
        admission, snapshot = _evaluate(ledger)
    except Exception:
        admission, snapshot = _reply('evidence_unavailable'), None
    with ledger._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT value FROM balance_jobs WHERE id=?', (id,)).fetchone()
        job = json.loads(row[0])
        if job['status'] != 'reserved':
            return _job_reply(job, True)
        reasons = list(admission.get('reasons', []))
        current = _snapshot(db)
        if hashlib.sha256(current.get(KEY, '').encode()).hexdigest() != job.get('balance_policy_hash'):
            reasons.append('balance_policy_changed')
        if snapshot is None or current != snapshot:
            reasons.append('state_changed')
        now = time.time()
        selection = _selection(admission.get('services', {}), job.get('provider', 'auto'))
        if admission.get('allowed'):
            config = _load(db)
            services = admission['services']
            if job['service'] not in config['services'] or job['service'] not in services:
                reasons.append('service_not_participating')
            elif job['service'] not in selection['eligible_services']:
                reasons.append('current_model_selection_required')
            elif selection['minimum_progress'] is None:
                reasons.append('evidence_unavailable')
            elif services[job['service']]['progress'] > selection['minimum_progress'] + config['max_lead'] + 1e-12:
                reasons.append('max_lead_exceeded')
            for service, summary in services.items():
                if (not ledger._fresh(ledger._service(db, service), now)
                        or summary['day'] != ledger._day(now)):
                    reasons.append(f'{service}:evidence_unavailable:stale_or_changed_snapshot')
        elif not reasons:
            reasons.append('admission_denied')
        job.update(status='denied' if reasons else 'running', updated_at=now,
                   start_admission=dict(allowed=not reasons, reasons=reasons, **selection,
                                        services={s: _compact(v) for s, v in admission.get('services', {}).items()}))
        db.execute('UPDATE balance_jobs SET status=?, value=? WHERE id=?', (job['status'], json.dumps(job), id))
        result = _job_reply(job)
        result.update(allowed=not reasons, reasons=reasons)
        return result


def finish(ledger, id, status, metadata=None):
    if status not in TERMINAL:
        raise ValueError('invalid terminal status')
    _identifier(id, 'id')
    _metadata(metadata)
    with ledger._connect() as db:
        _table(db)
        row = db.execute('SELECT value FROM balance_jobs WHERE id=?', (id,)).fetchone()
    if not row:
        return _reply('job_not_found')
    job = json.loads(row[0])
    if job['status'] not in OPEN:
        return _transition(ledger, id, status, metadata)
    observation = dict(status='unavailable', observation=None, reasons=['quota_refresh_failed'],
                       usage_attribution='aggregate_account_only', per_task_attribution=False)
    try:
        check = usage.require_admission(job['service'], ledger=ledger)
        summary = dict(pools=check.get('pools', []), day=check.get('day'), observed_at=check.get('observed_at'))
        with ledger._connect() as db:
            state = ledger._service(db, job['service'])
            fresh = (ledger._fresh(state, time.time()) and state['observed_at'] == summary['observed_at']
                     and summary['day'] == ledger._day(time.time()))
        observation.update(status='observed' if fresh else 'unavailable',
                           observation=_compact(summary) if fresh else None,
                           admission_allowed=check.get('allowed') is True,
                           reasons=check.get('reasons', []))
    except Exception:
        pass
    if job['service'] in {'copilot', 'cursor'} and status == 'failed' and job['status'] == 'running':
        with ledger._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = json.loads(db.execute('SELECT value FROM balance_jobs WHERE id=?', (id,)).fetchone()[0])
            if current['status'] == 'running':
                current.update(metadata={'reason_code': job['service'] + '_execution_unverified'}, after=observation)
                db.execute('UPDATE balance_jobs SET value=? WHERE id=?', (json.dumps(current), id))
            return _job_reply(current)
    return _transition(ledger, id, status, metadata, observation)


def reconcile(ledger, id, confirm_stopped):
    if confirm_stopped is not True:
        return _reply('confirm_stopped_required')
    return _transition(ledger, id, 'abandoned')
