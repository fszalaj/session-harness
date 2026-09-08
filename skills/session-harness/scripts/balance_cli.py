"""Route bounded native text work through the account's balancing authority."""
import argparse
import copy
import json
from pathlib import Path
import socket
import sys
import uuid

import coordination
from quota import Ledger


def request(ledger, task_id, artifact, role, provider):
    import balance
    return {'id': task_id, 'fingerprint': balance.fingerprint(ledger, artifact),
            'host': socket.gethostname(), 'role': role, 'provider': provider}


def run_work(artifact, *, task_id, provider='auto', timeout=180, ledger=None):
    import harness
    ledger = ledger or Ledger()
    if not artifact.strip() or len(artifact) > 8192:
        raise ValueError('work packet must contain 1 to 8192 UTF-8 bytes')
    artifact.decode('utf-8')
    if not 1 <= timeout <= 180:
        raise ValueError('work deadline must be between 1 and 180 seconds')
    job = coordination.balance_dispatch('reserve', {
        'request': request(ledger, task_id, artifact, 'worker', provider)}, ledger)
    if not job.get('allowed') or job.get('status') != 'reserved':
        return job
    service = job['service']
    try:
        capability = copy.deepcopy(harness.discover_provider(service))
        if not capability.get('worker'):
            raise harness.HarnessError('unsupported_capability', 'No verified current worker model')
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
            'model_family': {'codex': 'openai', 'claude': 'anthropic', 'antigravity': 'google'}[service],
            'billing_route': 'native_subscription', 'task_id': task_id, 'balance': receipt,
            'automatic_retry': False,
            'verdict': 'worker output requires manager inspection; not an independent plan review'}


def run_interactive(provider, response, environment, *, ledger=None, capability=None):
    import supervision
    ledger = ledger or Ledger()
    def execute():
        if provider == 'claude' and capability:
            import claude_session
            return claude_session.run(capability, response, environment)
        return supervision.run_terminal(response['argv'], environment, provider)
    state = coordination.balance_dispatch('status', {}, ledger)
    if not state.get('enabled'):
        if state.get('reasons'):
            raise ValueError('balance status unavailable')
        return execute()
    task_id = 'interactive-' + uuid.uuid4().hex
    artifact = json.dumps(response['argv']).encode()
    reserved = coordination.balance_dispatch('reserve', {
        'request': request(ledger, task_id, artifact, 'worker', provider)}, ledger)
    if not reserved.get('allowed'):
        raise ValueError('worker balance denied: ' + ', '.join(reserved.get('reasons', [])))
    started = coordination.balance_dispatch('start', {'id': task_id}, ledger)
    if not started.get('allowed'):
        raise ValueError('worker balance start denied')
    code = execute()
    receipt = coordination.balance_dispatch('finish', {'id': task_id,
        'status': 'completed' if code == 0 else 'failed',
        'metadata': {'requested_model': response['selection']['model'],
                     'requested_effort': response['selection']['effort']}}, ledger)
    if receipt.get('allowed') is not True:
        raise ValueError('interactive worker receipt unavailable; inspect balance status before recovery')
    return code


def main(argv=None):
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
    work.add_argument('--provider', default='auto', choices=('auto', *coordination.SERVICES))
    work.add_argument('--timeout', type=float, default=180)
    audit = sub.add_parser('audit', help='Read allowlisted usage metadata without model inference')
    audit.add_argument('--since', help='First UTC date (YYYY-MM-DD) for token metadata')
    args = parser.parse_args(argv)
    try:
        import balance
        ledger = Ledger()
        if args.command == 'work':
            result = run_work(sys.stdin.buffer.read(8193), task_id=args.id,
                              provider=args.provider, timeout=args.timeout, ledger=ledger)
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
        return 0 if result.get('allowed') or result.get('status') in {'disabled', 'audit', 'reconciled'} else 2
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'allowed': False, 'status': 'balance_error', 'message': str(exc),
                          'automatic_retry': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
