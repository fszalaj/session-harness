"""Route bounded native text work through the account's balancing authority."""
import argparse
import copy
import json
import math
from pathlib import Path
import re
import socket
import sys
import uuid

import coordination
import inventory
from quota import Ledger


class InteractiveStop(Exception):
    """A pacing failure with bounded diagnostics, separate from CLI schema errors."""
    def __init__(self, service, phase, reasons, task_id=None):
        known = {'max_lead_exceeded', 'busy', 'state_changed', 'balance_policy_changed',
                 'service_not_participating', 'service_not_configured_on_client',
                 'fingerprint_mismatch', 'fingerprint_key_missing', 'job_not_found',
                 'invalid_transition', 'admission_denied', 'evidence_unavailable',
                 'quota_denied', 'balance_disabled', 'authority_unavailable',
                 'invalid_balance_response', 'daily_limit', 'reserve_floor'}
        self.reasons = tuple(dict.fromkeys(
            reason if isinstance(reason, str) and reason in known else 'unknown'
            for reason in reasons[:16])) or ('unknown',)
        self.service = service if service in coordination.SERVICES else 'unknown'
        self.phase = phase if phase in {'status', 'reserve', 'start', 'finish'} else 'unknown'
        self.task_id = task_id if isinstance(task_id, str) and re.fullmatch(r'interactive-[0-9a-f]{32}', task_id) else None
        self.status = 'balance_receipt_unavailable' if phase == 'finish' else 'balance_blocked'
        message = ('Worker receipt is unconfirmed; work may already have completed.' if phase == 'finish'
                   else 'Worker launch was blocked by shared subscription pacing.')
        if 'max_lead_exceeded' in self.reasons:
            message += ' This service is ahead of the configured daily-budget usage balance.'
        super().__init__(message)

    def details(self):
        return {'service': self.service, 'phase': self.phase, 'reasons': list(self.reasons),
                'task_id': self.task_id, 'automatic_retry': False}


def _interactive_dispatch(phase, payload, ledger, provider, task_id=None, expected=()):
    try:
        reply = coordination.balance_dispatch(phase, payload, ledger)
    except (TypeError, KeyError):
        raise InteractiveStop(provider, phase, ['invalid_balance_response'], task_id) from None
    except (OSError, ValueError):
        raise InteractiveStop(provider, phase, ['authority_unavailable'], task_id) from None
    if (not isinstance(reply, dict) or type(reply.get('allowed')) is not bool
            or not isinstance(reply.get('reasons'), list)):
        raise InteractiveStop(provider, phase, ['invalid_balance_response'], task_id)
    if not reply['allowed']:
        raise InteractiveStop(provider, phase, reply['reasons'] or [reply.get('status')], task_id)
    if (reply.get('status') not in expected or reply['reasons']
            or reply.get('duplicate', False) is not False
            or (phase != 'status' and reply.get('service') != provider)):
        raise InteractiveStop(provider, phase, ['invalid_balance_response'], task_id)
    return reply


def request(ledger, task_id, artifact, role, provider):
    import balance
    return {'id': task_id, 'fingerprint': balance.fingerprint(ledger, artifact),
            'host': socket.gethostname(), 'role': role, 'provider': provider}


def _worker_choice(capability, strong_model, effort):
    import harness
    choice = dict(capability['planner' if strong_model else 'worker'])
    selected = choice['model']
    rows = [row for row in capability.get('models', [])
            if selected in (row.get('id'), row.get('resolved_model'))
            or isinstance(row.get('variants'), dict) and selected in row['variants'].values()]
    if not rows:
        raise harness.HarnessError('unsupported_capability', 'Worker model has no advertised effort evidence.')
    supported = set(rows[0].get('efforts', []))
    for row in rows[1:]:
        supported.intersection_update(row.get('efforts', []))
    effort = effort if effort is not None else harness.select_effort(supported, 'worker')
    if effort not in supported:
        raise harness.HarnessError('unsupported_capability', 'Requested worker effort is unavailable.')
    choice.update(model=harness.resolve_variant(rows[0], effort, selected), effort=effort)
    return choice


def run_work(artifact, *, task_id, provider='auto', timeout=180, ledger=None, model=None, effort=None,
             eligible_services=None, basis='daily', strong_model=False, worker_efforts=None):
    import harness
    ledger = ledger or Ledger()
    if not artifact.strip() or len(artifact) > 8192:
        raise ValueError('work packet must contain 1 to 8192 UTF-8 bytes')
    artifact.decode('utf-8')
    if not 1 <= timeout <= 180:
        raise ValueError('work deadline must be between 1 and 180 seconds')
    if (model is not None and provider != 'copilot') or (effort is not None and model is None):
        raise ValueError('model/effort controls require --provider copilot and an explicit --model')
    import balance
    balance.task_options(provider, eligible_services, basis)
    worker_efforts = {} if worker_efforts is None else worker_efforts
    if (not isinstance(worker_efforts, dict)
            or any(s not in coordination.SERVICES or e not in harness.EFFORTS for s, e in worker_efforts.items())):
        raise ValueError('invalid worker effort overrides')
    if (strong_model or worker_efforts) and (provider != 'native' or model is not None or effort is not None):
        raise ValueError('native worker controls cannot be combined with explicit model controls')
    if worker_efforts and eligible_services is not None and not set(worker_efforts).issubset(eligible_services):
        raise ValueError('worker effort targets an excluded service')
    if strong_model and (not eligible_services or not set(eligible_services).issubset({'codex', 'claude', 'antigravity'})):
        raise ValueError('strong model requires an explicit verified native service subset')
    selected = None
    fingerprint_artifact = artifact
    if eligible_services is not None or basis != 'daily' or strong_model or worker_efforts:
        fingerprint_artifact = json.dumps(dict(packet=artifact.decode('utf-8'), basis=basis,
            eligible_services=sorted(eligible_services) if eligible_services else None,
            strong_model=strong_model, worker_efforts=worker_efforts), sort_keys=True).encode()
    if model is not None:
        import copilot_client
        selected = copilot_client.select_model(harness.discover_provider(provider), model, effort)
        fingerprint_artifact = json.dumps({'model': model, 'effort': selected['worker']['effort'],
                                          'packet': artifact.decode('utf-8')}, sort_keys=True).encode()
    if provider == 'auto':
        import free_access
        config = free_access.load_config(optional=True)
        if config and config['enabled'] and config['mixed_work']:
            result = mixed_work(artifact, task_id, timeout, ledger)
            if result is not None:
                return result
    packet = request(ledger, task_id, fingerprint_artifact, 'worker', provider)
    if eligible_services is not None or basis != 'daily':
        packet.update(eligible_services=eligible_services, basis=basis)
    job = coordination.balance_dispatch('reserve', {'request': packet}, ledger)
    if not job.get('allowed') or job.get('status') != 'reserved':
        return job
    service = job['service']
    try:
        capability = copy.deepcopy(selected if selected is not None else harness.discover_provider(service))
        if not capability.get('worker'):
            raise harness.HarnessError('unsupported_capability', 'No verified current worker model')
        if strong_model or service in worker_efforts:
            capability['worker'] = _worker_choice(capability, strong_model, worker_efforts.get(service))
        capability['planner'] = capability['worker']
        started = coordination.balance_dispatch('start', {'id': task_id}, ledger)
        if not started.get('allowed'):
            return started
        response = harness.review(service, artifact, timeout, capability,
                                  capability['worker']['effort'], task=True)
        metadata = {key: response[key] for key in ('requested_model', 'actual_model', 'requested_effort')
                    if response.get(key) is not None}
    except (harness.HarnessError, OSError, ValueError) as exc:
        try:
            receipt = coordination.balance_dispatch('finish', {
                'id': task_id, 'status': 'failed', 'metadata': {}}, ledger)
        except (OSError, ValueError) as receipt_error:
            receipt = {'allowed': False, 'status': 'receipt_unavailable', 'message': str(receipt_error)}
        return {'allowed': False, 'status': 'failed', 'task_id': task_id,
                'reasons': [getattr(exc, 'status', 'work_failed')], 'message': str(exc),
                'balance': receipt, 'automatic_retry': False}
    try:
        receipt = coordination.balance_dispatch('finish', {
            'id': task_id, 'status': 'completed', 'metadata': metadata}, ledger)
    except (OSError, ValueError) as exc:
        receipt = {'allowed': False, 'status': 'receipt_unavailable', 'message': str(exc)}
    recorded = receipt.get('allowed') is True
    return {**response, 'status': 'completed' if recorded else 'receipt_unavailable',
            'allowed': recorded, 'billing_service': service,
            'model_family': inventory.model_vendor(response.get('actual_model') or '')
                if service in {'copilot', 'cursor'} else {'codex': 'openai', 'claude': 'anthropic', 'antigravity': 'google'}[service],
            'billing_route': 'native_subscription', 'task_id': task_id, 'balance': receipt,
            'automatic_retry': False,
            'verdict': 'worker output requires manager inspection; not an independent plan review'}


def mixed_work(artifact, task_id, timeout, ledger):
    import balance
    import free_access
    payload = {'id': task_id, 'fingerprint': balance.fingerprint(ledger, artifact), 'proposed': None}
    route = coordination.balance_dispatch('work_route', payload, ledger)
    if route.get('allowed') is not True:
        return route
    native = coordination.balance_dispatch('status', {}, ledger)
    if native.get('allowed') is not True or native.get('enabled') is not True:
        return native
    if not route.get('bound'):
        try:
            state = free_access.dispatch('status')
        except (OSError, ValueError):
            return {'allowed': False, 'status': 'mixed_work_status_unavailable',
                    'task_id': task_id,
                    'reasons': ['free_authority_status_unavailable'],
                    'message': 'The configured mixed-route authority status is unavailable. '
                               'Restore its existing transport before retrying this task.',
                    'automatic_retry': False}
        if state.get('allowed') is not True:
            return state
        values = [row.get('progress') for row in native.get('services', {}).values()]
        fraction = state.get('progress')
        if (not values or any(type(x) not in (int, float) or not math.isfinite(x) or x < 0 for x in [*values, fraction])):
            raise ValueError('mixed_work_usage_unverified')
        proposed = 'recurring_free' if fraction <= min(values) else 'native'
        route = coordination.balance_dispatch('work_route', {**payload, 'proposed': proposed}, ledger)
        if route.get('allowed') is not True:
            return route
    if route.get('route') == 'native':
        return None
    if route.get('route') != 'recurring_free':
        raise ValueError('mixed_work_route_unverified')
    return free_access.dispatch('run', {'id': task_id, 'model': 'auto',
        'prompt': artifact.decode('utf-8'), 'max_output_tokens': 4096, 'timeout': timeout})


def run_interactive(provider, response, environment, *, ledger=None, capability=None):
    import supervision
    ledger = ledger or Ledger()
    def execute():
        if provider == 'claude' and capability:
            import claude_session
            return claude_session.run(capability, response, environment)
        return supervision.run_terminal(response['argv'], environment, provider)
    state = _interactive_dispatch('status', {}, ledger, provider, expected=('ready', 'disabled'))
    if (type(state.get('enabled')) is not bool
            or (state['status'] == 'disabled') != (state['enabled'] is False)):
        raise InteractiveStop(provider, 'status', ['invalid_balance_response'])
    if not state['enabled']:
        return execute()
    task_id = 'interactive-' + uuid.uuid4().hex
    artifact = json.dumps(response['argv']).encode()
    _interactive_dispatch('reserve', {
        'request': request(ledger, task_id, artifact, 'worker', provider)}, ledger,
        provider, task_id, expected=('reserved',))
    _interactive_dispatch('start', {'id': task_id}, ledger, provider, task_id, expected=('running',))
    code = execute()
    terminal_status = 'completed' if code == 0 else 'failed'
    _interactive_dispatch('finish', {'id': task_id,
        'status': terminal_status,
        'metadata': {'requested_model': response['selection']['model'],
                     'requested_effort': response['selection']['effort']}}, ledger,
        provider, task_id, expected=(terminal_status,))
    return code


def main(argv=None):
    import harness
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    policy = sub.add_parser('balance', help='Inspect or explicitly configure native fractional pacing')
    actions = policy.add_subparsers(dest='action', required=True)
    actions.add_parser('status')
    enable = actions.add_parser('enable')
    enable.add_argument('--services', help='Comma-separated configured native execution services')
    enable.add_argument('--max-lead', type=float, default=0.15)
    actions.add_parser('disable')
    constraints = actions.add_parser('constraints', help='Replace model supervision settings on the authority')
    constraints.add_argument('--file', required=True, help='JSON list of service/model/roles rules; [] clears it')
    recover = actions.add_parser('reconcile')
    recover.add_argument('id')
    recover.add_argument('--confirm-stopped', action='store_true', required=True)
    work = sub.add_parser('work', help='Run one useful bounded text task; no tools or automatic retry')
    work.add_argument('--id', required=True, help='Stable unique task ID; repeat never redispatches')
    work.add_argument('--provider', default='auto', choices=('auto', 'native', *coordination.SERVICES))
    work.add_argument('--timeout', type=float, default=180)
    work.add_argument('--model', help='Exact account-selectable Copilot model ID')
    work.add_argument('--effort', help='Advertised effort for explicit Copilot model')
    work.add_argument('--eligible-services', help='Task-fit native service subset, selected before dispatch')
    work.add_argument('--basis', choices=('daily', 'weekly'), default='daily')
    work.add_argument('--strong-model', action='store_true', help='Use the current strongest native family model as supervised worker')
    work.add_argument('--worker-effort', action='append', default=[], metavar='SERVICE=LEVEL', help='Explicit per-service native worker effort')
    audit = sub.add_parser('audit', help='Read allowlisted usage metadata without model inference')
    audit.add_argument('--since', help='First UTC date (YYYY-MM-DD) for token metadata')
    args = parser.parse_args(argv)
    try:
        import balance
        ledger = Ledger()
        if args.command == 'work':
            overrides = {}
            for value in args.worker_effort:
                service, level = value.split('=', 1)
                if service in overrides:
                    raise ValueError('duplicate worker effort service')
                overrides[service] = level
            result = run_work(sys.stdin.buffer.read(8193), task_id=args.id,
                              provider=args.provider, timeout=args.timeout, ledger=ledger, model=args.model, effort=args.effort,
                              eligible_services=args.eligible_services.split(',') if args.eligible_services else None,
                              basis=args.basis, strong_model=args.strong_model, worker_efforts=overrides)
        elif args.command == 'audit':
            import usage_audit
            result = usage_audit.report(ledger, since=args.since)
        elif args.action == 'constraints':
            if coordination.settings(ledger)['authority'] != 'local':
                raise ValueError('configure model constraints on the account authority')
            with Path(args.file).open('rb') as stream:
                raw = stream.read(32769)
            if len(raw) > 32768:
                raise ValueError('model constraints file exceeds 32 KiB')
            result = balance.set_constraints(ledger, json.loads(raw))
        elif args.action in {'enable', 'disable'}:
            if coordination.settings(ledger)['authority'] != 'local':
                raise ValueError('configure balance on the account authority')
            result = balance.configure(ledger, args.action == 'enable',
                services=args.services.split(',') if args.action == 'enable' and args.services else None,
                max_lead=args.max_lead if args.action == 'enable' else 0.15)
        elif args.action == 'reconcile':
            result = coordination.balance_dispatch('reconcile', {
                'id': args.id, 'confirm_stopped': args.confirm_stopped}, ledger)
        else:
            result = coordination.balance_dispatch('status', {}, ledger)
        print(json.dumps(result, indent=2))
        return 0 if result.get('allowed') or result.get('status') in {'disabled', 'audit', 'reconciled', 'completed'} else 2
    except (ValueError, OSError, KeyError, TypeError, harness.HarnessError) as exc:
        print(json.dumps({'allowed': False, 'status': getattr(exc, 'status', 'balance_error'), 'message': str(exc),
                          'automatic_retry': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
