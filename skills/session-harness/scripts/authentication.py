"""Local authentication checks and explicitly selected native login flows."""
import argparse
import json
import os
import sqlite3
import sys
import time
import webbrowser

import harness
import inventory
import supervision
from quota import Ledger

LOGIN = {
    'codex': ('login', '--device-auth'),
    'claude': ('auth', 'login', '--claudeai'),
    'copilot': ('login',),
    'cursor': ('login',),
}
ACCOUNT_PAGES = {
    'openrouter': 'https://openrouter.ai/settings/keys',
    'groq': 'https://console.groq.com/settings/billing/plans',
    'nvidia': 'https://build.nvidia.com/settings/api-keys',
    'mistral': 'https://console.mistral.ai/',
    'huggingface': 'https://huggingface.co/settings/billing',
    'morph': 'https://morphllm.com/',
}
HISTORY = 'auth_history_v1'


def probe(provider):
    executable = harness.platform_runtime.which(harness.PROVIDERS[provider])
    if not executable:
        return 'missing_cli'
    client = None
    try:
        if provider == 'codex':
            client = harness.CodexRPC(executable)
            client.request('initialize', {'clientInfo': {'name': 'session_harness', 'version': '1.0.0'}})
            client.notify('initialized')
            response = client.request('account/read', {'refreshToken': False})
            if 'account' not in response:
                return 'unverified'
            account = response['account']
            if account is None:
                return 'signed_out'
            return 'authenticated' if account.get('type') == 'chatgpt' else 'unverified'
        if provider == 'claude':
            data = harness.claude_auth_status(executable)
            if (data.get('loggedIn') is True and data.get('authMethod') == 'claude.ai'
                    and data.get('apiProvider') == 'firstParty'):
                return 'authenticated'
            return 'unverified'
        if provider == 'copilot':
            client = inventory.MetadataRPC(executable, 15)
            data = client.request('auth.getStatus')
        elif provider == 'cursor':
            data = json.loads(harness.checked([executable, 'status', '--format', 'json'],
                                             timeout=15, env=inventory.child_env()))
        else:
            return 'unverified'
        value = data.get('isAuthenticated')
        return 'authenticated' if value is True else 'signed_out' if value is False else 'unverified'
    except harness.HarnessError as error:
        if provider == 'claude' and error.status == 'auth_required':
            return 'signed_out'
        return 'unverified'
    except (OSError, ValueError, TimeoutError, KeyError, TypeError, AttributeError):
        return 'unverified'
    finally:
        if client:
            client.close()


def status(ledger=None):
    ledger = ledger or Ledger()
    services = [p for p in ledger.setup_status()['services'] if p in harness.PROVIDERS]
    observed_at = time.time()
    states = {p: {'status': probe(p)} for p in services}
    persistence = 'recorded'
    try:
        with ledger._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT value FROM state WHERE key=?', (HISTORY,)).fetchone()
            history = json.loads(row[0]) if row else {}
            if (not isinstance(history, dict) or set(history) - set(harness.PROVIDERS)
                    or any(type(v) not in (int, float) or not 0 < v <= observed_at for v in history.values())):
                raise ValueError('invalid_auth_history')
            for provider, current in states.items():
                if current['status'] == 'signed_out' and provider in history:
                    current['status'] = 'lost_login'
                elif current['status'] == 'authenticated':
                    history[provider] = observed_at
            db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (HISTORY, json.dumps(history)))
    except (OSError, ValueError, sqlite3.Error, AttributeError):
        persistence = 'unavailable'
        for current in states.values():
            if current['status'] == 'lost_login':
                current['status'] = 'signed_out'
    for provider, current in states.items():
        if current['status'] in {'signed_out', 'lost_login'}:
            current['action'] = ['ai-session', 'auth', 'login', provider]
        elif current['status'] == 'unverified':
            current['action'] = 'Check native client sign-in; authentication was not established.'
    return {'status': 'authentication_report', 'providers': states, 'free_accounts': free_status(),
            'history': persistence, 'scope': 'local_configured_native_clients',
            'inference': False, 'admission_verified': False}


def free_status():
    try:
        import free_access
        config = free_access.load_config(optional=True)
        if not config or not config['enabled']:
            return {}
        if config['authority'] != 'local':
            return {'executor': {'status': 'remote_verification_required',
                                 'action': 'Run ai-session auth status on the configured free executor.'}}
        accounts = config.get('accounts', {'openrouter': config})
        return {p: {'status': 'account_verification_required' if row.get('evidence', {}).get('expires_at', float('inf')) <= time.time()
                    else 'login_unverified', 'action': ['ai-session', 'auth', 'login', p],
                    'account_page': ACCOUNT_PAGES[p]}
                for p, row in accounts.items() if row['enabled']}
    except (OSError, ValueError, KeyError, RuntimeError):
        return {'configuration': {'status': 'unverified'}}


def login(provider, ledger=None):
    if provider in ACCOUNT_PAGES:
        if provider not in free_status():
            return {'status': 'service_not_configured', 'provider': provider}
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            return {'status': 'interactive_required', 'provider': provider, 'account_page': ACCOUNT_PAGES[provider]}
        opened = webbrowser.open(ACCOUNT_PAGES[provider])
        return {'status': 'account_verification_required', 'provider': provider,
                'browser_opened': opened, 'account_page': ACCOUNT_PAGES[provider],
                'action': 'Verify sign-in and free allowance; update private evidence through ai-session free configure.'}
    ledger = ledger or Ledger()
    ledger.require_setup('native', provider)
    if provider not in LOGIN:
        return {'status': 'manual_action', 'provider': provider, 'action': 'Sign in through the native application.'}
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return {'status': 'interactive_required', 'provider': provider,
                'action': ['ai-session', 'auth', 'login', provider]}
    executable = harness.platform_runtime.which(harness.PROVIDERS[provider])
    if not executable:
        return {'status': 'missing_cli', 'provider': provider}
    if os.name == 'nt':
        return {'status': 'manual_action', 'provider': provider,
                'action': [harness.PROVIDERS[provider], *LOGIN[provider]]}
    environment = harness.child_env()
    if provider in {'copilot', 'cursor'}:
        environment = inventory.child_env(environment)
    deadline = time.monotonic() + 600

    def check_login_deadline(_service):
        if time.monotonic() >= deadline:
            raise TimeoutError('Native login exceeded 600 seconds.')
        return {'allowed': True}

    outcome, exit_code = 'manual_action', None
    try:
        exit_code = supervision.run_terminal([executable, *LOGIN[provider]], environment, provider,
                                             check=check_login_deadline, interval=1)
        if exit_code == 130:
            outcome = 'login_cancelled'
    except TimeoutError:
        outcome = 'login_timeout'
    except supervision.Stop:
        outcome = 'login_timeout' if time.monotonic() >= deadline else 'manual_action'
    except KeyboardInterrupt:
        outcome = 'login_cancelled'
    current = status(ledger)['providers'].get(provider, {'status': 'unverified'})
    return {'status': 'authenticated' if current['status'] == 'authenticated' else outcome,
            'provider': provider, 'authentication': current['status'], 'timeout_seconds': 600, 'exit_code': exit_code,
            'admission_verified': False}


def startup(ledger=None):
    try:
        report = status(ledger)
    except (OSError, ValueError, sqlite3.Error, RuntimeError):
        print('Authentication report unavailable; native sign-in and quota checks still apply.', file=sys.stderr)
        return {'status': 'authentication_unavailable', 'admission_verified': False}
    for provider, state in report['providers'].items():
        print(f"Authentication: {provider}: {state['status']}", file=sys.stderr)
        if state['status'] in {'signed_out', 'lost_login'}:
            print(f'  Restore sign-in: ai-session auth login {provider}', file=sys.stderr)
            if sys.stdin.isatty() and sys.stdout.isatty():
                print(f'Open {provider} native login now? [y/N] ', end='', file=sys.stderr, flush=True)
                if sys.stdin.readline().strip().lower() in {'y', 'yes'}:
                    result = login(provider, ledger)
                    print(f"  {result['status']}", file=sys.stderr)
    for provider, state in report['free_accounts'].items():
        print(f"Free account: {provider}: {state['status']}", file=sys.stderr)
        action = state.get('action')
        if action:
            print('  ' + (' '.join(action) if isinstance(action, list) else action), file=sys.stderr)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    command = commands.add_parser('login')
    command.add_argument('provider', choices=[*harness.PROVIDERS, *ACCOUNT_PAGES])
    args = parser.parse_args(argv)
    try:
        result = status() if args.command == 'status' else login(args.provider)
    except (OSError, ValueError, sqlite3.Error, AttributeError, RuntimeError):
        result = {'status': 'authentication_unavailable'}
    print(json.dumps(result, indent=2))
    return 0 if result['status'] in {'authentication_report', 'authenticated'} else 2
