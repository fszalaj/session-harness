"""Copilot subscription execution through the native CLI protocol."""
import math
import tempfile
import time

import harness
import inventory
import supervision


def chat_pool(payload):
    if not inventory.quota_complete(payload):
        raise harness.HarnessError('usage_unverified', 'Copilot quota metadata is incomplete.')
    rows = inventory.normalize_quota(payload)
    for row in rows:
        if any(row.get(key) is not False for key in ('usageAllowedWithExhaustedQuota', 'overageAllowedWithExhaustedQuota')):
            raise harness.HarnessError('usage_unverified', 'Copilot paid-overage controls are unverified.')
    chat = next((row for row in rows if row['pool'] == 'chat'), {})
    if (chat.get('hasQuota') is not True or chat.get('tokenBasedBilling') is not True
            or chat.get('isUnlimitedEntitlement') is True or chat.get('entitlementRequests', 0) <= 0):
        raise harness.HarnessError('usage_unverified', 'Copilot requires a finite token-billed chat allowance.')
    return {**{k: chat[k] for k in ('entitlementRequests', 'usedRequests', 'remainingPercentage')},
            'inactive_pools': sorted(({k: v for k, v in row.items() if k != 'resetDate'}
                                      for row in rows if row.get('hasQuota') is False), key=lambda row: row['pool'])}


def discover(executable, offline=False):
    if offline:
        raise harness.HarnessError('live_metadata_required', 'Copilot requires fresh account metadata.')
    data = inventory.discover_copilot(executable)
    if data.get('authenticated') is not True or not data.get('models'):
        return {**data, 'status': 'auth_required', 'reason': 'Sign in with copilot login.'}
    candidates = data['models']
    automatic = next((m for m in candidates if m['id'] == 'auto'), None)
    if automatic is None and len(candidates) != 1:
        raise harness.HarnessError('model_selection_required', 'Copilot has no verified default model selector.')
    model = automatic or candidates[0]
    efforts = model['native_controls']['reasoning_efforts']
    return {**data, 'status': 'available', 'auth': {'status': 'subscription'},
            'execution_supported': True, 'execution_scope': 'admitted_native_launch_and_supervised_text',
            'planner': {'model': model['id'], 'effort': harness.select_effort(efforts, 'planner') if efforts else None,
                        'selection_status': 'client_auto_unresolved' if automatic else 'account_selected'},
            'worker': {'model': model['id'], 'effort': harness.select_effort(efforts, 'worker') if efforts else None},
            'review': {'status': 'supervised_only', 'reason': 'Bounded supervised text only; actual model verified from usage events.'}}


def session_config(directory, model, effort):
    value = {'model': model, 'workingDirectory': directory, 'configDir': directory,
             'availableTools': [], 'excludedTools': ['*'], 'toolFilterPrecedence': 'excluded',
             'tools': [], 'customAgents': [], 'mcpServers': {}, 'requestPermission': True,
             'enableConfigDiscovery': False, 'enableOnDemandInstructionDiscovery': False,
             'enableFileHooks': False, 'enableHostGitOperations': False, 'enableSessionStore': False,
             'enableSkills': False, 'instructionDirectories': [], 'streaming': True,
             'infiniteSessions': {'enabled': False},
             'systemMessage': {'mode': 'replace', 'content': 'Complete the bounded text task supplied by the manager. '
                               'Do not use tools, read files, run commands or delegate. Return at most 500 words.'}}
    if effort is not None:
        value['reasoningEffort'] = effort
    return value


def execute(artifact, timeout, capability, *, task):
    if not task:
        raise harness.HarnessError('independent_family_unverified', 'Use Copilot as a supervised worker; auto routing is not an independent provider selection.')
    if (not isinstance(artifact, bytes) or not artifact.strip() or len(artifact) > harness.MAX_INPUT
            or type(timeout) not in (int, float) or not math.isfinite(timeout) or not 1 <= timeout <= 180):
        raise harness.HarnessError('invalid_task', 'Copilot needs bounded UTF-8 text and a deadline of 1 to 180 seconds.')
    try:
        prompt = artifact.decode('utf-8')
    except UnicodeDecodeError:
        raise harness.HarnessError('invalid_encoding', 'Copilot needs UTF-8 text.') from None
    watch = supervision.Watch('copilot')
    client, idle, messages, usages = None, False, [], []
    output_size = 0
    identity = None
    early_ids = set()
    deadline = time.monotonic() + min(timeout, 180)

    def rpc(method, params=None):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise harness.HarnessError('timeout', 'Copilot worker deadline exceeded.')
        client.timeout = min(remaining, 15)
        return client.request(method) if params is None else client._request(method, params)

    def event(message):
        nonlocal idle, output_size
        if 'id' in message:
            status = 'isolation_violation' if 'method' in message else 'schema_error'
            raise harness.HarnessError(status, 'Copilot emitted an unsupported callback or response.')
        if message.get('method') != 'session.event':
            return
        params = message.get('params', {})
        if identity is not None and params.get('sessionId') != identity:
            raise harness.HarnessError('session_mismatch', 'Copilot emitted another session event.')
        item = params.get('event', {})
        kind, data = item.get('type', ''), item.get('data', {})
        if not isinstance(kind, str) or not isinstance(data, dict):
            raise harness.HarnessError('schema_error', 'Malformed Copilot event.')
        if kind in {'session.error', 'session.shutdown'}:
            raise harness.HarnessError('execution_failed', 'Copilot reported an execution failure.')
        if kind.startswith(('tool.', 'subagent.', 'hook.')):
            raise harness.HarnessError('isolation_violation', 'Copilot attempted unsupported execution.')
        if identity is None:
            early = params.get('sessionId')
            if not isinstance(early, str) or len(early) > 128 or kind.startswith('assistant.'):
                raise harness.HarnessError('session_mismatch', 'Copilot emitted output before session identity was verified.')
            early_ids.add(early)
            if len(early_ids) > 1:
                raise harness.HarnessError('session_mismatch', 'Copilot emitted multiple session identities.')
            return
        if kind == 'session.idle':
            idle = bool(messages and usages)
        elif kind == 'assistant.message':
            if data.get('toolRequests') or not isinstance(data.get('content'), str):
                raise harness.HarnessError('isolation_violation', 'Copilot emitted non-text output.')
            messages.append(data['content'])
            output_size += len(data['content'].encode())
            if output_size > 262144:
                raise harness.HarnessError('output_limit', 'Copilot text exceeded the bounded task limit.')
        elif kind == 'assistant.usage':
            if (not isinstance(data.get('model'), str) or not inventory.SAFE_ID.fullmatch(data['model'])
                    or data['model'] == 'auto' or any(type(data.get(k)) is not int or data[k] < 0
                                                       for k in ('inputTokens', 'outputTokens'))):
                raise harness.HarnessError('usage_unverified', 'Copilot did not report model and token usage.')
            usages.append({k: data[k] for k in ('model', 'inputTokens', 'outputTokens')})

    try:
        watch.start()
        with tempfile.TemporaryDirectory(prefix='session-harness-copilot-') as directory:
            client = inventory.MetadataRPC(capability['executable'])
            client.on_message, client.tick = event, watch.tick
            before = chat_pool(rpc('account.getQuota'))
            choice = capability['planner']
            created = rpc('session.create', session_config(directory, choice['model'], choice['effort']))
            identity = created.get('sessionId')
            if not isinstance(identity, str) or not identity or len(identity) > 128:
                raise harness.HarnessError('schema_error', 'Copilot session identity is missing.')
            if early_ids and early_ids != {identity}:
                raise harness.HarnessError('session_mismatch', 'Copilot session identity changed during creation.')
            idle = False
            rpc('session.send', {'sessionId': identity, 'prompt': prompt})
            while not idle:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise harness.HarnessError('timeout', 'Copilot worker deadline exceeded.')
                rpc('status.get')
                time.sleep(min(.1, max(0, deadline - time.monotonic())))
            if not usages or not messages or not ''.join(messages).strip():
                raise harness.HarnessError('usage_unverified', 'Copilot completed without verified text and usage.')
            models = {row['model'] for row in usages}
            if len(models) != 1:
                raise harness.HarnessError('model_mismatch', 'Copilot used multiple models in one bounded task.')
            if choice['model'] != 'auto' and models != {choice['model']}:
                raise harness.HarnessError('model_mismatch', 'Copilot returned a different model than requested.')
            after = chat_pool(rpc('account.getQuota'))
            if (before['entitlementRequests'] != after['entitlementRequests']
                    or before['inactive_pools'] != after['inactive_pools']
                    or after['usedRequests'] < before['usedRequests']
                    or after['remainingPercentage'] > before['remainingPercentage']
                    or (after['usedRequests'] == before['usedRequests']
                        and after['remainingPercentage'] == before['remainingPercentage'])):
                raise harness.HarnessError('usage_unaccounted', 'Copilot chat-pool consumption could not be verified; inspect the retained unresolved job.')
            finished_client, client = client, None
            finished_client.close()
            watch.finish()
            return {'status': 'completed', 'result': '\n'.join(messages), 'actual_model': models.pop(),
                    'prompt_tokens': sum(row['inputTokens'] for row in usages),
                    'completion_tokens': sum(row['outputTokens'] for row in usages),
                    'quota_evidence': {'pool': 'chat:token_billing', 'before': before, 'after': after,
                                       'attribution': 'aggregate_account_change_not_exclusive_task_cost'},
                    'requested_model': choice['model'], 'requested_effort': choice['effort'],
                    'isolation': 'empty tool surface, configuration discovery/hooks/skills disabled; tool callbacks rejected'}
    except supervision.Stop:
        raise harness.HarnessError('quota_blocked', 'Copilot quota supervision stopped this task.') from None
    except (KeyError, TypeError, AttributeError, UnicodeError):
        raise harness.HarnessError('schema_error', 'Copilot returned malformed task metadata.') from None
    finally:
        if client is not None:
            client.close()
        watch.close()
