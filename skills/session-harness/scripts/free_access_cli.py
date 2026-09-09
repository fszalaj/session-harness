"""Configure and run explicitly authorized recurring free coding work."""
import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import sys

import free_access
from api_transport import APIError, decode_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(free_access.CONFIG))
    actions = parser.add_subparsers(dest='action', required=True)
    configure = actions.add_parser('configure', help='Apply explicit private free-access settings; no paid setup')
    configure.add_argument('--file', required=True)
    actions.add_parser('models')
    actions.add_parser('status')
    actions.add_parser('serve', help='One request on stdin for a trusted SSH executor; never forwards')
    run = actions.add_parser('run', help='Run one bounded text task without paid fallback')
    run.add_argument('--id', required=True)
    run.add_argument('--model', default='auto')
    run.add_argument('--max-output-tokens', type=int, default=4096)
    run.add_argument('--timeout', type=float, default=180)
    reconcile = actions.add_parser('reconcile', help='Close an inspected uncertain request without refunding its quota')
    reconcile.add_argument('id')
    reconcile.add_argument('--confirm-stopped', action='store_true', required=True)
    reconcile.add_argument('--evidence', help='Nonsecret inspected receipt/process evidence reference')
    renew = actions.add_parser('renew-period', help='Record a verified new period without deleting accounting')
    renew.add_argument('provider')
    renew.add_argument('--start', required=True, type=float)
    renew.add_argument('--evidence', required=True)
    args = parser.parse_args(argv)
    serving = args.action == 'serve'
    try:
        if os.environ.get('SESSION_HARNESS_LEAF'):
            raise ValueError('recursion_blocked')
        if args.action == 'configure':
            raw = free_access.private_read(Path(args.file), 32768)
            result = free_access.save_config(decode_json(raw), args.config)
        elif serving:
            raw = sys.stdin.buffer.read(65537)
            if len(raw) > 65536:
                raise ValueError('free_packet_too_large')
            packet = decode_json(raw)
            if (set(packet) != {'version', 'action', 'payload'}
                    or type(packet['version']) is not int or packet['version'] != 1):
                raise ValueError('invalid_free_protocol')
            payload = packet['payload']
            if packet['action'] == 'run' and isinstance(payload, dict) and isinstance(payload.get('timeout'), Decimal):
                payload['timeout'] = float(payload['timeout'])
            result = free_access.dispatch(packet['action'], packet['payload'],
                                          config_path=args.config, local_only=True)
        elif args.action == 'run':
            raw = sys.stdin.buffer.read(8193)
            if len(raw) > 8192:
                raise ValueError('free_packet_too_large')
            result = free_access.dispatch('run', {
                'id': args.id, 'model': args.model, 'prompt': raw.decode('utf-8'),
                'max_output_tokens': args.max_output_tokens, 'timeout': args.timeout},
                config_path=args.config)
        elif args.action in {'reconcile', 'renew-period'}:
            config = free_access.load_config(args.config)
            if config['authority'] != 'local':
                raise ValueError('reconcile_on_free_account_executor')
            if config['schema_version'] == 2:
                import free_accounts
                ledger = free_accounts.AccountsLedger()
                result = (ledger.reconcile_account(args.id, args.evidence, config) if args.action == 'reconcile'
                          else ledger.renew_period(args.provider, args.start, args.evidence))
            elif args.action == 'reconcile':
                result = free_access.FreeLedger().reconcile(args.id)
            else:
                raise ValueError('free_account_group_required')
        elif args.action == 'models' and not Path(args.config).exists():
            result = free_access.catalog()
        else:
            result = free_access.dispatch(args.action, config_path=args.config)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        reason = str(exc) if type(exc) is ValueError or isinstance(exc, APIError) else 'free_access_unavailable'
        result = {'status': 'free_error', 'reason': reason, 'automatic_retry': False}
    print(json.dumps({'protocol_version': 1, 'result': result} if serving else result, default=str, indent=2))
    return 0 if result.get('status') in {'configured', 'completed', 'free_catalog', 'free_ready', 'free_reconciled'} else 2


if __name__ == '__main__':
    raise SystemExit(main())
