"""Interactively add one provider route using existing private configuration."""
import argparse
import copy
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

import api_providers
import coordination
import free_access
import free_accounts
import setup_environment
from quota import Ledger, default_path


FAMILIES = {'claude': 'anthropic', 'codex': 'openai', 'antigravity': 'gemini'}
ALIASES = {'google': 'gemini', **FAMILIES}


def registry():
    result = {}
    for native in coordination.SERVICES:
        result.setdefault(FAMILIES.get(native, native), {})['native'] = native
    for service in api_providers.SERVICES:
        result.setdefault(service, {})['api'] = service
    for service in [*free_accounts.PROVIDERS, 'openrouter']:
        result.setdefault(service, {})['free'] = service
    result.setdefault('ollama', {})['local'] = 'ollama'
    return result


class Input:
    def __init__(self, stream):
        self.stream = stream

    def isatty(self):
        return self.stream.isatty()

    def readline(self):
        value = self.stream.readline()
        if value.strip().casefold() in {'cancel', 'quit', 'q'}:
            raise EOFError
        return value


def choose(stream, output, label, choices, *, aliases=None):
    for index, name in enumerate(choices, 1):
        output.write(f'{index}. {name}\n')
    while True:
        answer = setup_environment._ask(stream, output, label).casefold()
        answer = (aliases or {}).get(answer, answer)
        if answer in choices:
            return answer
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return list(choices)[int(answer) - 1]
        output.write('Choose a listed name or number, or cancel.\n')


def yes(stream, output, label):
    while True:
        answer = setup_environment._ask(stream, output, label, 'no').casefold()
        if answer in {'yes', 'no'}:
            return answer == 'yes'
        output.write('Type yes or no, or cancel.\n')


def authorize(args, route, service, stream, output):
    path = Path(args.ledger) if args.ledger else default_path()
    ledger = Ledger(path) if path.exists() else None
    settings = coordination.settings(ledger) if ledger else {
        'authority': 'local', 'max_sessions': coordination.DEFAULT_MAX_SESSIONS}
    if route == 'api' and settings['authority'] != 'local':
        output.write(f"Incomplete: run ai-session onboard {service} on account authority {settings['authority']}; remote money admission is unsupported.\n")
        return 2
    if route == 'native':
        import harness
        try:
            capability = harness.discover_provider(service)
        except harness.HarnessError:
            output.write('Incomplete: native discovery failed; check installation and native sign-in, then rerun onboarding.\n')
            return 2
        auth = capability.get('auth', {}).get('status')
        if capability.get('status') != 'available' or not (
                auth == 'subscription' or service == 'antigravity' and auth == 'catalog_access'):
            output.write(f'Incomplete: install {harness.PROVIDERS[service]} and sign in through its native client; rerun ai-session onboard {service}.\n')
            return 2
    else:
        variable = api_providers.SERVICES[service][2]
        if not bool(os.environ.get(variable)):
            output.write(f'Incomplete: {variable} is absent. Configure it securely outside this wizard, then rerun onboarding.\n')
            return 2
        output.write(f'{variable}: present (value not inspected).\n')
    status = ledger.setup_status() if ledger else {'services': [], 'api_services': []}
    native, apis = list(status.get('services', [])), list(status.get('api_services', []))
    selected = native if route == 'native' else apis
    if service not in selected:
        selected.append(service)
    calendar = ledger.budget_calendar()['calendar'] if ledger else {
        'workdays': list(range(7)), 'reset_cutoff': '08:30'}
    options = ['--ledger', str(path), '--services', ','.join(native), '--api-services', ','.join(apis),
               '--timezone', ledger.policy['timezone'] if ledger else 'UTC',
               '--workdays', ','.join(setup_environment.WEEKDAYS[day] for day in calendar['workdays']),
               '--cutoff', calendar['reset_cutoff'], '--max-sessions', str(settings['max_sessions'])]
    if ledger:
        options += ['--mode', ledger.mode(), '--authority', settings['authority']]
    previous = setup_environment._money_defaults(ledger)
    if apis and previous:
        options += ['--monthly-budget', str(previous['monthly']), '--currency', previous['currency'],
                    '--money-mode', previous['mode']]
    result = setup_environment.main(options, input_stream=stream, output_stream=output)
    if result:
        return result
    output.write('Route authorization saved; inference readiness is not verified. Advanced changes: ai-session configure.\n')
    if route == 'native':
        output.write(f'Next: ai-session usage check {service}. Shared authority requires its own authorization.\n')
    else:
        output.write(f'Next: ai-session api models {service}; configure required rate evidence with ai-session spend --help.\n')
    try:
        if yes(stream, output, 'Inspect model metadata now? No inference'):
            if route == 'api':
                metadata = api_providers.models(service)
                output.write(f"Catalog entries: {len(metadata.get('models', []))}; entitlement and inference remain unverified.\n")
            else:
                output.write(f"Catalog entries: {len(capability.get('models', []))}; quota readiness still requires the next check.\n")
    except (EOFError, KeyboardInterrupt):
        output.write('Metadata skipped; saved authorization remains.\n')
    except Exception:
        output.write('Metadata unavailable; saved authorization remains, readiness unverified.\n')
    return 0


def accounts(config):
    if config['schema_version'] == 2:
        return copy.deepcopy(config['accounts'])
    if not config['enabled']:
        raise ValueError('free_legacy_disabled_group_requires_migration')
    return {'openrouter': copy.deepcopy(config)}


def account_summary(row):
    summary = {key: row[key] for key in ('enabled', 'model', 'models', 'family',
               'context_tokens', 'max_output_tokens') if key in row}
    if 'evidence' in row:
        summary['expires_at'] = row['evidence']['expires_at']
    if 'limits' in row:
        summary['limits'] = {key: row['limits'][key] for key in (
            'rpm', 'rpd', 'tpm', 'tpd', 'credit_usd', 'input_per_million', 'output_per_million', 'period_start')}
    return summary


def free(args, service, stream, output):
    path = Path(args.free_config) if args.free_config else free_access.CONFIG
    current = free_access.load_config(path, optional=True)
    if current and current['authority'] != 'local':
        output.write('Incomplete: run onboarding on the existing free account executor; remote configuration is unchanged.\n')
        return 2
    source = setup_environment._ask(stream, output, 'Prepared private free configuration file')
    imported = free_access.load_config(Path(source))
    if imported['authority'] != 'local':
        raise ValueError('free_account_executor_must_be_local')
    row = accounts(imported).get(service)
    if row is None:
        raise ValueError('selected_free_account_missing')
    if row.get('enabled') and service != 'openrouter' and row['evidence']['expires_at'] <= time.time():
        raise ValueError('free_account_evidence_expired')
    merged = accounts(current) if current else {}
    if service in merged and merged[service] != row:
        before = merged[service]
        preview = {'existing': account_summary(before), 'incoming': account_summary(row),
                   'binding_changed': any(before.get(key) != row.get(key) for key in (
                       'credential_file', 'credential_sha256', 'account_sha256'))}
        output.write(f'Replace {service}: ' + json.dumps(preview, sort_keys=True) + '\n')
        if not yes(stream, output, 'Replace this existing provider row?'):
            return 130
    merged[service] = row
    enabled = current['enabled'] if current else row['enabled'] and yes(stream, output, 'Enable this free group?')
    candidate = {'schema_version': 2, 'authority': 'local', 'mode': 'observed',
                 'enabled': enabled, 'mixed_work': current['mixed_work'] if current else False, 'accounts': merged}
    free_access.validate_config(candidate)
    output.write(f"Save {service} free configuration: group enabled={enabled}, account enabled={row['enabled']}, mixed_work={candidate['mixed_work']}; other accounts preserved. No paid fallback.\n")
    if not yes(stream, output, 'Apply these private settings?'):
        return 130
    free_access.save_config(candidate, path)
    output.write('Free configuration saved; live account allowance and inference readiness remain unverified.\n')
    return 0


def local(stream, output):
    output.write('Local Ollama uses installed models at 127.0.0.1:11434. No setup, download or cloud fallback.\n')
    if not yes(stream, output, 'Inspect installed model metadata?'):
        return 0
    import local_ollama
    rows = local_ollama.models(deadline=time.monotonic() + 5)
    output.write(f'Installed local models: {len(rows)}; inference not verified.\n')
    return 0 if rows else 2


def main(argv=None, *, input_stream=None, output_stream=None):
    output = sys.stdout if output_stream is None else output_stream
    if os.environ.get('SESSION_HARNESS_LEAF'):
        output.write('Onboarding blocked: recursion_blocked.\n')
        return 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('provider', nargs='?')
    parser.add_argument('--list', action='store_true', help='List installed provider adapters and access routes')
    parser.add_argument('--ledger', help='Private ledger path')
    parser.add_argument('--free-config', help='Private free configuration destination')
    args = parser.parse_args(argv)
    providers = registry()
    if args.list:
        for provider, routes in providers.items():
            output.write(provider + ': ' + ', '.join(routes) + '\n')
        return 0
    stream = Input(sys.stdin if input_stream is None else input_stream)
    if not stream.isatty():
        output.write('Onboarding requires a human terminal; use --list for read-only discovery.\n')
        return 2
    try:
        provider = ALIASES.get(args.provider.casefold(), args.provider.casefold()) if args.provider else choose(
            stream, output, 'Provider', providers, aliases=ALIASES)
        if provider not in providers:
            output.write('Unknown provider; use ai-session onboard --list.\n')
            return 2
        route = choose(stream, output, 'Access route', providers[provider])
        service = providers[provider][route]
        if route == 'local':
            return local(stream, output)
        if route == 'free':
            return free(args, service, stream, output)
        return authorize(args, route, service, stream, output)
    except (EOFError, KeyboardInterrupt):
        output.write('Onboarding cancelled.\n')
        return 130
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as exc:
        # Errors may contain credential paths or transport details.
        reason = str(exc)
        output.write('Onboarding incomplete: ' + (reason if reason.startswith('free_') and reason.replace('_', '').isalnum() else 'configuration or metadata unavailable') + '.\n')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
