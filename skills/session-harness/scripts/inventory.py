#!/usr/bin/env python3
"""Metadata-only optional client inventory; never create or send an AI session."""
import datetime as dt
import json
import math
import os
import re
import selectors
import shutil
import subprocess
import time

import harness

METHODS = frozenset({'status.get', 'auth.getStatus', 'models.list', 'account.getQuota'})
EFFORTS = frozenset({'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'})
SAFE_ID = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}(?:\[1m\])?$')
QUOTA_NUMBERS = ('entitlementRequests', 'usedRequests', 'remainingPercentage', 'overage')
QUOTA_FLAGS = ('isUnlimitedEntitlement', 'hasQuota', 'tokenBasedBilling',
               'usageAllowedWithExhaustedQuota', 'overageAllowedWithExhaustedQuota')


def child_env(env=None):
    """Keep native auth paths while removing model, API and routing overrides."""
    clean = harness.child_env(env)
    blocked = ('COPILOT_PROVIDER_', 'COPILOT_MODEL', 'CURSOR_API_KEY', 'CURSOR_MODEL', 'CURSOR_BASE_URL')
    return {key: value for key, value in clean.items()
            if not any(key.startswith(prefix) for prefix in blocked)}


def model_vendor(ident):
    """Recognize documented families, never infer vendors from arbitrary names."""
    name = ident.rsplit('/', 1)[-1].lower()
    for prefix, vendor in [('claude-', 'anthropic'), ('gpt-', 'openai'),
                           ('gemini-', 'google'), ('grok-', 'xai'),
                           ('deepseek-', 'deepseek'), ('kimi-', 'moonshot'),
                           ('moonshot-', 'moonshot'), ('glm-', 'zai')]:
        if name.startswith(prefix):
            return vendor
    return None


def model_generation(ident):
    """Generation is comparable only within the returned family, not globally."""
    match = re.match(r'^(gpt|gemini|claude(?:-sonnet|-opus|-haiku|-fable)?)-(\d+(?:\.\d+)*)', ident)
    return {'family': match[1], 'generation': [int(n) for n in match[2].split('.')]} if match else None


def normalize_models(payload, service, authenticated=None, *, evidence_kind=None, source=None):
    rows = payload.get('models', []) if isinstance(payload, dict) else []
    if not isinstance(rows, list) or authenticated is False:
        return []
    kind = evidence_kind or ('client_selectable_metadata' if service == 'copilot' and authenticated is True
                             else 'advertised_catalog')
    if kind not in {'client_selectable_metadata', 'advertised_catalog', 'local_inventory'}:
        raise ValueError('Unsupported model evidence')
    selectable = kind == 'client_selectable_metadata'
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        ident = row.get('id')
        if not isinstance(ident, str) or not SAFE_ID.fullmatch(ident) or ident in seen:
            continue
        seen.add(ident)
        efforts = row.get('supportedReasoningEfforts', [])
        if not isinstance(efforts, list):
            efforts = []
        result.append({'id': ident, 'service': service, 'model_vendor': model_vendor(ident),
                       'generation': model_generation(ident), 'account_visible': None,
                       'account_selectable': True if selectable and authenticated is True else None,
                       'client_selectable': True if selectable else None,
                       'advertised': kind == 'advertised_catalog', 'local': kind == 'local_inventory',
                       'entitlement_verified': False, 'inference_verified': False,
                       'native_controls': {'reasoning_efforts': [e for e in efforts if isinstance(e, str) and e in EFFORTS]},
                       'evidence': {'source': source or ('models.list' if service == 'copilot' else 'agent models'),
                                    'kind': kind}})
    return result


def normalize_quota(payload, service='copilot'):
    rows = payload.get('quotaSnapshots', {}) if isinstance(payload, dict) else {}
    if not isinstance(rows, dict):
        return []
    result = []
    for pool, row in rows.items():
        if not isinstance(pool, str) or not re.fullmatch(r'[a-z_]{1,64}', pool) or not isinstance(row, dict):
            continue
        item = {'service': service, 'pool': pool, 'unit': 'server_defined', 'scope': 'account'}
        for key in QUOTA_NUMBERS:
            value = row.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                item[key] = value
        for key in QUOTA_FLAGS:
            if isinstance(row.get(key), bool):
                item[key] = row[key]
        reset = row.get('resetDate')
        if isinstance(reset, str):
            try:
                dt.datetime.fromisoformat(reset.replace('Z', '+00:00'))
                item['resetDate'] = reset
            except ValueError:
                pass
        if len(item) > 4:
            result.append(item)
    return result


def quota_complete(payload):
    """Validate every raw pool before normalization can discard missing evidence."""
    rows = payload.get('quotaSnapshots') if isinstance(payload, dict) else None
    if not isinstance(rows, dict) or not rows:
        return False
    for pool, row in rows.items():
        if not isinstance(pool, str) or not re.fullmatch(r'[a-z_]{1,64}', pool) or not isinstance(row, dict):
            return False
        for key in QUOTA_FLAGS:
            if key in row and not isinstance(row[key], bool):
                return False
        for key in QUOTA_NUMBERS:
            if key not in row:
                continue
            value = row[key]
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                return False
            if key == 'entitlementRequests' and value < 0 and value != -1:
                return False
            if key == 'remainingPercentage' and not 0 <= value <= 100:
                return False
            if key in {'usedRequests', 'overage'} and value < 0:
                return False
        unlimited = row.get('isUnlimitedEntitlement') is True or row.get('entitlementRequests') == -1
        if row.get('isUnlimitedEntitlement') is False and row.get('entitlementRequests') == -1:
            return False
        reset = row.get('resetDate')
        if reset is not None:
            if not isinstance(reset, str):
                return False
            try:
                parsed = dt.datetime.fromisoformat(reset.replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    return False
            except ValueError:
                return False
        if not unlimited and (reset is None or any(key not in row for key in
                                ('entitlementRequests', 'usedRequests', 'remainingPercentage'))):
            return False
    return True


class MetadataRPC:
    """Bounded JSON-RPC metadata transport for Copilot CLI."""
    def __init__(self, executable, timeout=15):
        self.timeout, self.buffer, self.serial = timeout, b'', 0
        self.process = subprocess.Popen([executable, '--headless', '--stdio', '--no-auto-update',
                                         '--log-level', 'none'], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
                                        start_new_session=True, env=child_env())
        harness.register_process(self.process)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def request(self, method):
        if method not in METHODS:
            raise ValueError('Only inventory metadata methods are allowed')
        self.serial += 1
        data = json.dumps({'jsonrpc': '2.0', 'id': self.serial, 'method': method, 'params': {}}).encode()
        self.process.stdin.write(b'Content-Length: ' + str(len(data)).encode() + b'\r\n\r\n' + data)
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if b'\r\n\r\n' in self.buffer:
                header, body = self.buffer.split(b'\r\n\r\n', 1)
                match = re.search(rb'(?im)^Content-Length:\s*(\d+)\s*$', header)
                if not match or len(header) > 8192:
                    raise ValueError('Malformed metadata frame')
                length = int(match[1])
                if length > 2_000_000:
                    raise ValueError('Metadata frame too large')
                if len(body) >= length:
                    message = json.loads(body[:length])
                    self.buffer = body[length:]
                    if not isinstance(message, dict):
                        raise ValueError('Malformed metadata response')
                    if message.get('id') == self.serial:
                        if 'error' in message:
                            raise ValueError('Metadata method unavailable')
                        return message.get('result', {})
                    continue
            if self.selector.select(max(0, deadline - time.monotonic())):
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise ValueError('Metadata process exited')
                self.buffer += chunk
                if len(self.buffer) > 2_010_000:
                    raise ValueError('Metadata buffer too large')
        raise TimeoutError('Metadata deadline exceeded')

    def close(self):
        self.selector.close()
        try:
            harness.stop_group(self.process)
        finally:
            harness.unregister_process(self.process)
            self.process.stdin.close()
            self.process.stdout.close()



def base_record(service, executable):
    return {'service': service, 'installed': executable is not None, 'executable': executable,
            'authenticated': None, 'models': [], 'quota': [], 'quota_complete': False, 'inference_verified': False,
            'execution_supported': False, 'status': 'metadata_unavailable' if executable else 'not_installed',
            'native_controls': {}, 'evidence': {'observed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                                               'kind': 'metadata_only'}}


def discover_copilot(executable=None, timeout=15):
    executable = executable or shutil.which('copilot')
    result = base_record('copilot', executable)
    if not executable:
        return result
    client = None
    try:
        client = MetadataRPC(executable, timeout)
        status = client.request('status.get')
        version = status.get('version') if isinstance(status, dict) else None
        if isinstance(version, str) and re.fullmatch(r'[\w.+-]{1,64}', version):
            result['version'] = version
        auth = client.request('auth.getStatus')
        authenticated = auth.get('isAuthenticated') if isinstance(auth, dict) else None
        result['authenticated'] = authenticated if isinstance(authenticated, bool) else None
        if result['authenticated'] is not True:
            result['status'] = 'unauthenticated' if authenticated is False else 'auth_unknown'
            return result
        result['models'] = normalize_models(client.request('models.list'), 'copilot', True)
        result['status'] = 'account_metadata' if result['models'] else 'no_account_models'
        try:
            raw_quota = client.request('account.getQuota')
            result['quota'] = normalize_quota(raw_quota)
            result['quota_complete'] = quota_complete(raw_quota)
        except (OSError, ValueError, TimeoutError, harness.HarnessError):
            result['quota_status'] = 'unavailable'
        result['native_controls'] = {'model_selection': '--model', 'reasoning_selection': '--effort',
                                     'execution_verification': 'required_before_dispatch'}
    except (OSError, ValueError, TimeoutError, harness.HarnessError):
        result['error'] = 'metadata_probe_failed'
    finally:
        if client:
            client.close()
    return result


def parse_cursor_models(text):
    """Accept JSON metadata or explicit ID/display rows; reject incidental text."""
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {'models': value if isinstance(value, list) else []}
    except ValueError:
        rows = []
        for line in text.splitlines():
            match = re.fullmatch(r'\s*([a-z0-9][a-z0-9._/-]+)\s+-\s+\S.*', line)
            if match:
                rows.append({'id': match[1]})
        return {'models': rows}


def discover_cursor(executable=None, timeout=15):
    executable = executable or shutil.which('cursor-agent') or shutil.which('agent')
    result = base_record('cursor', executable)
    if not executable:
        return result
    try:
        def run(*args):
            return harness.run([executable, *args], timeout=timeout, env=child_env())
        help_result = run('--help')
        if help_result[0] or 'cursor' not in help_result[1].lower():
            result['status'] = 'unrecognized_executable'
            return result
        listed = run('models')
        if listed[0]:
            return result
        result['models'] = normalize_models(parse_cursor_models(listed[1]), 'cursor')
        result['status'] = 'advertised_catalog' if result['models'] else 'unrecognized_model_output'
        result['quota_status'] = 'unsupported_personal_cli_metadata'
        result['native_controls'] = {'model_selection': '--model', 'execution_verification': 'required_before_dispatch'}
    except (OSError, ValueError, subprocess.TimeoutExpired, harness.HarnessError):
        result['error'] = 'metadata_probe_failed'
    return result


CLIENTS = {
    'copilot': ('copilot',), 'cursor': ('cursor-agent', 'agent'),
    'kimi': ('kimi',), 'opencode': ('opencode',), 'aider': ('aider',),
    'continue': ('cn',), 'ollama': ('ollama',), 'gemini': ('gemini',),
}


def discover(service, **kwargs):
    if service not in CLIENTS:
        raise ValueError('Unsupported optional client')
    if service in {'copilot', 'cursor'}:
        return {'copilot': discover_copilot, 'cursor': discover_cursor}[service](**kwargs)
    import optional_clients
    return optional_clients.discover(service, **kwargs)


def discover_all():
    return {service: discover(service) for service in CLIENTS}


if __name__ == '__main__':
    print(json.dumps(discover_all(), indent=2))
