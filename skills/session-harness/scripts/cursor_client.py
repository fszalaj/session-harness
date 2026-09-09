"""Personal Cursor Free execution using fresh native quota metadata."""
import json
import math
from pathlib import Path
import re
import tempfile
import time

import credits
import harness
import inventory


def metadata(executable):
    directory = Path(executable).resolve().parent
    node = directory / ('node.exe' if __import__('os').name == 'nt' else 'node')
    raw = harness.checked([str(node), str(Path(__file__).with_name('cursor_native.cjs')), str(directory)],
                          timeout=15, env=inventory.child_env())
    return json.loads(raw)


def quota_snapshot(data):
    observed = data['observed_at']
    fingerprint = data['account_fingerprint']
    if (type(observed) not in (int, float) or not math.isfinite(observed)
            or not 0 <= time.time() - observed <= 30
            or not isinstance(fingerprint, str) or not re.fullmatch('[a-f0-9]{64}', fingerprint)):
        raise ValueError('Invalid Cursor observation')
    if data['plan']['planName'] != 'Free' or data['hard_limit'].get('noUsageBasedAllowed') is not True:
        raise ValueError('Only personal Free accounts with on-demand disabled are supported')
    usage = data['usage']
    start, end = int(usage['billingCycleStart']) / 1000, int(usage['billingCycleEnd']) / 1000
    if not start <= observed < end or not 0 < end - start <= 32 * 86400:
        raise ValueError('Invalid Cursor billing period')
    spend = usage['spendLimitUsage']
    if (spend.get('limitType') != 'user'
            or any(type(spend.get(k)) not in (int, float) or spend[k] != 0
                   for k in ('pooledLimit', 'pooledRemaining', 'individualLimit', 'overallLimit', 'overallRemaining'))
            or any(v != 0 for k, v in spend.items() if k.endswith('Used'))
            or data['grants'] or set(data['limits']) - {'usageLimitPolicyStatus'}):
        raise ValueError('Unverified Cursor credit or limit class')
    values = usage['planUsage']
    for key in ('totalPercentUsed', 'autoPercentUsed', 'apiPercentUsed'):
        value = values[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
            raise ValueError('Invalid Cursor usage percentage')
    if values.get('remainingBonus') is not False:
        raise ValueError('Cursor bonus allowance is unsupported')
    row = credits.resource('cursor', 'cursor.native_dashboard', 'on_demand')
    row.update(enabled=False, auto_reload=False, has_credits=False, balance='0', used='0')
    return {'service': 'cursor', 'observed_at': observed, 'complete': True,
            'source': 'cursor.native_dashboard',
            'pools': [{'pool': 'account:' + fingerprint + ':included',
                       'used_percent': values['totalPercentUsed'], 'resets_at': end,
                       'window_minutes': (end - start) / 60, 'window_source': 'cursor.native_billing_cycle'}],
            'credit_resources': [row]}


def discover(executable, offline=False):
    if offline:
        raise harness.HarnessError('live_metadata_required', 'Cursor requires fresh native account metadata.')
    info = json.loads(harness.checked([executable, 'status', '--format', 'json'], timeout=15, env=inventory.child_env()))
    if info.get('isAuthenticated') is not True:
        raise harness.HarnessError('auth_required', 'Sign in with agent login.')
    raw = harness.checked([executable, 'models'], timeout=15, env=inventory.child_env())
    names = dict(re.findall(r'^([a-z0-9][a-z0-9._/-]+) - (.+)$', raw, re.M))
    names = {key: re.sub(r'(?: \((?:default|current)\))+$', '', value) for key, value in names.items()}
    if 'auto' not in names:
        raise harness.HarnessError('model_unavailable', 'Cursor does not advertise the Free plan Auto route.')
    selected = 'auto'
    quota_snapshot(metadata(executable))
    choice = {'model': selected, 'effort': None, 'selection_status': 'free_plan_auto',
              'basis': 'Free CLI accounts require Auto; routed model and reasoning effort are not exposed.'}
    return {'status': 'available', 'auth': {'status': 'subscription'}, 'executable': executable,
            'models': [{'id': selected, 'display_name': names[selected], 'efforts': []}],
            'planner': choice, 'worker': choice, 'execution_supported': True,
            'review': {'status': 'supervised_only', 'reason': 'Constrained text worker; not independent review.'}}


def execute(artifact, timeout, capability, *, task):
    if not task:
        raise harness.HarnessError('unsupported_capability', 'Cursor supports supervised work, not independent review.')
    choice = capability['planner']
    model = choice['model']
    display = next(row['display_name'] for row in capability['models'] if row['id'] == model)
    before = quota_snapshot(metadata(capability['executable']))['pools'][0]
    identity, terminal, observed_model = None, None, None

    def event(line):
        nonlocal identity, terminal, observed_model
        item = json.loads(line)
        if not isinstance(item, dict):
            raise harness.HarnessError('schema_error', 'Cursor emitted a non-object event.')
        kind = item.get('type')
        if terminal is not None:
            raise harness.HarnessError('schema_error', 'Cursor emitted events after its result.')
        if kind == 'system' and item.get('subtype') == 'init':
            if identity is not None or item.get('apiKeySource') != 'login' or item.get('model') != display:
                raise harness.HarnessError('model_mismatch', 'Cursor did not confirm native login and the selected model.')
            identity, observed_model = item.get('session_id'), item['model']
            if not isinstance(identity, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', identity):
                raise harness.HarnessError('schema_error', 'Cursor session identity is invalid.')
            return
        if identity is None or item.get('session_id') != identity:
            raise harness.HarnessError('session_mismatch', 'Cursor session identity changed.')
        if kind == 'thinking' and item.get('subtype') in {'delta', 'completed'}:
            return
        if kind in ('user', 'assistant'):
            message = item.get('message')
            content = message.get('content') if isinstance(message, dict) else None
            if not isinstance(content, list) or any(not isinstance(part, dict) or part.get('type') != 'text' for part in content):
                raise harness.HarnessError('isolation_violation', 'Cursor emitted a non-text message.')
        elif kind == 'result':
            if (item.get('is_error') is not False or item.get('subtype') != 'success'
                    or not isinstance(item.get('result'), str) or not item['result'].strip()
                    or not isinstance(item.get('request_id'), str) or not item['request_id']):
                raise harness.HarnessError('execution_failed', 'Cursor did not confirm successful completion.')
            if not isinstance(item.get('usage'), dict):
                raise harness.HarnessError('usage_unverified', 'Cursor token usage is missing.')
            for key in ('inputTokens', 'outputTokens', 'cacheReadTokens', 'cacheWriteTokens'):
                if type(item.get('usage', {}).get(key)) is not int or item['usage'][key] < 0:
                    raise harness.HarnessError('usage_unverified', 'Cursor token usage is missing.')
            terminal = item
        else:
            raise harness.HarnessError('isolation_violation', 'Cursor attempted a tool or unsupported event.')

    with tempfile.TemporaryDirectory(prefix='session-harness-cursor-') as directory:
        config = Path(directory) / '.cursor'
        config.mkdir()
        denies = ['Shell(*)', 'Read(**)', 'Read(/**)', 'Write(**)', 'Write(/**)', 'WebFetch(*)', 'Mcp(*:*)']
        (config / 'cli.json').write_text(json.dumps({'permissions': {'allow': [], 'deny': denies}}))
        native_config = Path(directory) / 'native-config'
        native_config.mkdir()
        (native_config / 'cli-config.json').write_text(json.dumps({'version': 1, 'autoAcceptWebSearch': False}))
        prompt = ('Complete this bounded text task without tools, skills, delegation or external context. '
                  'Return at most 500 words.\n\n' + artifact.decode())
        argv = [capability['executable'], '--print', '--output-format', 'stream-json',
                '--mode', 'ask', '--sandbox', 'enabled', '--trust', '--model', model,
                '--workspace', directory]
        environment = harness.child_env(inventory.child_env(), leaf=True)
        environment.update(CURSOR_CONFIG_DIR=str(native_config), CURSOR_DATA_DIR=str(native_config),
                           CURSOR_FORCED_SHELL_EGRESS='1', CURSOR_FORCED_SHELL_EGRESS_ALLOW_WEB_TOOLS='0')
        harness.checked(argv, stdin=prompt.encode(), timeout=timeout, cwd=directory, env=environment,
                        on_stdout_line=event, quota_service='cursor')
    if terminal is None:
        raise harness.HarnessError('usage_unverified', 'Cursor did not return a final receipt.')
    after = quota_snapshot(metadata(capability['executable']))['pools'][0]
    if (before['pool'] != after['pool'] or before['resets_at'] != after['resets_at']
            or after['used_percent'] < before['used_percent']):
        raise harness.HarnessError('usage_unverified', 'Cursor account or billing period changed during execution.')
    return {'status': 'completed', 'result': terminal['result'], 'actual_model': None,
            'observed_model_display': observed_model, 'requested_model': model, 'requested_effort': None,
            'response_id': terminal['request_id'], 'prompt_tokens': terminal['usage']['inputTokens'],
            'completion_tokens': terminal['usage']['outputTokens'],
            'cache_read_tokens': terminal['usage']['cacheReadTokens'],
            'cache_write_tokens': terminal['usage']['cacheWriteTokens'],
            'quota_evidence': {'before_used_percent': before['used_percent'], 'after_used_percent': after['used_percent'],
                               'delta_lower_bound_percent': after['used_percent'] - before['used_percent'],
                               'per_task_charge': 'unknown', 'attribution': 'aggregate_account_change_not_exclusive_task_cost'},
            'model_verification': 'Auto route confirmed; the CLI does not expose the routed model identity.',
            'isolation': 'Ask mode, native sandbox, denied file/shell/web/MCP permissions; tool events rejected.',
            'isolation_limit': 'Native global rules and skill metadata may remain visible; not independent review.'}
