"""Optional clients with conservative metadata provenance and no inference."""
import re
import shutil
import platform_runtime
import tempfile

import harness
import inventory


def parse_ollama(text):
    lines = text.splitlines()
    if not lines or not re.fullmatch(r'NAME\s+ID\s+SIZE\s+MODIFIED\s*', lines[0].strip()):
        raise ValueError('Unrecognized local model list')
    models = []
    for line in lines[1:]:
        fields = line.split()
        if not fields:
            continue
        if len(fields) < 4 or not inventory.SAFE_ID.fullmatch(fields[0]) or not re.fullmatch(r'[0-9a-f]{12,64}', fields[1]):
            raise ValueError('Unrecognized local model row')
        models.append({'id': fields[0]})
    return {'models': models}


def discover(service, executable=None, timeout=15):
    if service not in inventory.CLIENTS or service in {'copilot', 'cursor'}:
        raise ValueError('Unsupported optional client')
    executable = executable or next((path for name in inventory.CLIENTS[service]
                                     if (path := platform_runtime.which(name))), None)
    result = inventory.base_record(service, executable)
    if not executable:
        return result
    result['status'] = 'installed_presence_only'
    result['evidence']['kind'] = 'executable_presence'
    result['quota_status'] = 'unsupported'
    if service != 'ollama':
        result['metadata_status'] = 'safe_catalog_contract_unverified'
        return result
    env = inventory.child_env()
    for key in list(env):
        if key.startswith('OLLAMA_') or key.lower() in {'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'}:
            env.pop(key)
    env['OLLAMA_HOST'] = 'http://127.0.0.1:11434'
    env['NO_PROXY'] = '127.0.0.1,localhost'
    try:
        with tempfile.TemporaryDirectory(prefix='session-harness-inventory-') as directory:
            code, stdout, _ = harness.run([executable, 'list'], timeout=min(timeout, 15), cwd=directory, env=env)
        if code:
            raise ValueError('Local catalog unavailable')
        result['models'] = inventory.normalize_models(parse_ollama(stdout), service,
                               evidence_kind='local_inventory', source='ollama list loopback')
        result['status'] = 'local_inventory'
        result['evidence']['kind'] = 'local_inventory'
    except (OSError, ValueError, harness.HarnessError):
        result['metadata_status'] = 'metadata_probe_failed'
    return result
