"""Verified local overlays and reversible managed-profile activation."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import uuid

import releases


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def atomic(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError('State must not be a symlink: ' + str(path))
    temporary = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    try:
        with temporary.open('xb') as stream:
            stream.write(raw)
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('Invalid private metadata: ' + str(path))
    return json.loads(path.read_bytes())


def state_path(home, name):
    return home / '.local/state/session-harness' / name


def save(path, value):
    atomic(path, (json.dumps(value, sort_keys=True, indent=2) + '\n').encode())


def snapshot(home, digest):
    if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
        raise ValueError('Invalid snapshot hash')
    root = home / '.local/share/session-harness/releases' / digest
    payload = {}
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Snapshot missing or linked')
    for path in [root, *root.rglob('*')]:
        mode = stat.S_IMODE(path.lstat().st_mode)
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise ValueError('Snapshot contains a nonregular entry')
        if path.is_dir():
            if mode != 0o555:
                raise ValueError('Snapshot directory mode changed')
        else:
            if mode not in (0o444, 0o555):
                raise ValueError('Snapshot file mode changed')
            payload[path.relative_to(root).as_posix()] = {'mode': mode, 'content': path.read_bytes()}
    actual = hashlib.sha256()
    for relative, item in sorted(payload.items()):
        info = json.dumps([relative, item['mode'], len(item['content'])], separators=(',', ':'))
        actual.update(info.encode() + b'\0' + item['content'])
    if actual.hexdigest() != digest:
        raise ValueError('Snapshot bytes differ from installation hash')
    return root, payload


def inspect_path(path):
    if path.is_symlink():
        return {'kind': 'link', 'target': os.readlink(path)}
    if not path.exists():
        return {'kind': 'absent'}
    if not path.is_file():
        raise ValueError('Managed target is not a leaf: ' + str(path))
    return {'kind': 'file', 'sha256': sha(path.read_bytes()), 'mode': stat.S_IMODE(path.stat().st_mode)}


def footprint(paths):
    return {str(path): inspect_path(Path(path)) for path in paths}


def verify_footprint(previous):
    for name, expected in previous.items():
        if inspect_path(Path(name)) != expected:
            raise ValueError('Managed path changed; reconciliation required: ' + name)


def installer(source):
    path = source / 'scripts/install-agent-profile.py'
    if path.is_symlink() or not path.is_file():
        raise ValueError('Regular release installer required')
    spec = importlib.util.spec_from_file_location('auto_update_installer', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def plan_install(module, home, source, previous):
    if previous['link_mode'] != 'symlink':
        raise ValueError('Automatic activation requires a symlink installation; checked copies use explicit update')
    policy = Path(previous['personal_policy']) if previous.get('personal_policy') else None
    return module.plan_install(home, source, previous.get('launcher', False),
                               link_mode=previous['link_mode'], personal_policy=policy)


def baseline(home, source, previous):
    marker = read_json(source / 'RELEASE.json')
    if marker.get('repository') != releases.REPOSITORY or marker.get('version') != previous['version']:
        raise ValueError('Baseline must be the matching published release source')
    module = installer(source)
    policy = Path(previous['personal_policy']) if previous.get('personal_policy') else None
    payload, _ = module.release_sources(source, policy)
    digest = module.release_hash(payload)
    result = {'source_hash': digest, 'release_root': str(home / '.local/share/session-harness/releases' / digest),
              'release_created': False}
    module.install_release(result, payload)
    return module, payload, digest


def register(home, source):
    previous = releases.installation(home)
    _, current = snapshot(home, previous['source_hash'])
    module, base, digest = baseline(home, source, previous)
    overrides = []
    for relative in sorted(set(base) | set(current)):
        original, selected = base.get(relative), current.get(relative)
        if original == selected:
            continue
        if not relative.startswith('session-harness/') or not selected or relative.endswith('/VERSION'):
            raise ValueError('Only skill-file overlays can be registered; reconcile other profile changes')
        fingerprint = sha(selected['content'])
        atomic(state_path(home, 'auto-update-overlays') / fingerprint, selected['content'])
        overrides.append({'path': relative, 'base_sha256': sha(original['content']) if original else None,
                          'sha256': fingerprint, 'mode': selected['mode']})
    root, _ = snapshot(home, previous['source_hash'])
    paths = [home / p for p in ['.agents/AGENTS.md', '.codex/AGENTS.md', '.claude/CLAUDE.md',
             '.gemini/GEMINI.md', '.copilot/copilot-instructions.md']]
    if any(p.resolve() != (root / 'AGENTS.md').resolve() for p in paths):
        raise ValueError('Instruction links do not select the installed snapshot')
    skills = [home / p for p in ['.agents/skills/session-harness', '.codex/skills/session-harness',
              '.claude/skills/session-harness', '.gemini/config/skills/session-harness',
              '.copilot/skills/session-harness', '.cursor/skills/session-harness']]
    if any(p.resolve() != (root / 'session-harness').resolve() for p in skills):
        raise ValueError('Skill links do not select the installed snapshot')
    paths += skills
    for provider, directory in [('codex', '.codex/agents'), ('claude', '.claude/agents'), ('cursor', '.cursor/rules')]:
        for p in (root / 'native' / provider).glob('*'):
            target = home / directory / p.name
            if target.resolve() != p.resolve():
                raise ValueError('Native role differs from installed snapshot')
            paths.append(target)
    launcher = home / '.local/bin/ai-session'
    if not previous.get('launcher') or str(root / 'session-harness/scripts/harness.py') not in launcher.read_text():
        raise ValueError('Launcher does not select the installed snapshot')
    paths.append(launcher)
    result = {'schema': 1, 'installation_hash': previous['source_hash'], 'base_version': previous['version'],
              'base_source_hash': digest, 'overrides': overrides, 'footprint': footprint(paths)}
    save(state_path(home, 'auto-update-installation.json'), result)
    return result


def registered(home, previous):
    value = read_json(state_path(home, 'auto-update-installation.json'))
    if (value.get('schema') != 1 or value.get('installation_hash') != previous['source_hash']
            or value.get('base_version') != previous['version'] or not isinstance(value.get('overrides'), list)):
        raise ValueError('Installation differs from registered baseline; reconciliation required')
    snapshot(home, previous['source_hash'])
    verify_footprint(value['footprint'])
    return value


def prepare(home, source, previous, registration, selected):
    module, _, base_hash = baseline(home, source, {**previous, 'version': selected})
    retained = []
    for entry in registration['overrides']:
        relative = Path(entry['path'])
        if (relative.is_absolute() or '..' in relative.parts or not str(relative).startswith('session-harness/')
                or relative.as_posix() != entry['path'] or relative.name == 'VERSION'):
            raise ValueError('Invalid overlay path')
        path = source / 'skills' / relative
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError('Invalid incoming overlay file')
        incoming = sha(path.read_bytes()) if path.exists() else None
        raw = state_path(home, 'auto-update-overlays') / entry['sha256']
        if not re.fullmatch('[a-f0-9]{64}', entry['sha256']) or raw.is_symlink():
            raise ValueError('Invalid overlay content reference')
        content = raw.read_bytes()
        if sha(content) != entry['sha256'] or entry['mode'] not in (0o444, 0o555):
            raise ValueError('Registered overlay drift')
        if incoming == entry['sha256']:
            continue
        if incoming != entry['base_sha256']:
            raise ValueError('Overlay conflicts with incoming release: ' + entry['path'])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o755 if entry['mode'] == 0o555 else 0o644)
        retained.append(entry)
    if retained:
        (source / 'RELEASE.json').unlink()
    preview, internal = plan_install(module, home, source, previous)
    module.install_release(preview, internal['release'])
    verify_candidate_launcher(home, module, preview)
    preview.update(version=selected, base_source_hash=base_hash, overlays=retained)
    return module, preview, internal


def verify_candidate_launcher(home, module, preview):
    runtime = Path(preview['release_root']) / 'session-harness/scripts/harness.py'
    env = dict(os.environ, HOME=str(home))
    env.pop('SESSION_HARNESS_LEAF', None)
    with tempfile.TemporaryDirectory(prefix='candidate-probe-', dir=state_path(home, '')) as directory:
        launcher = Path(directory) / 'ai-session'
        launcher.write_bytes(module.launcher_content(runtime))
        for args, marker in [(['auto-update', '--help'], 'register'),
                             (['coordination', '--help'], 'maintenance-release')]:
            result = subprocess.run([sys.executable, str(launcher), *args], env=env,
                                    capture_output=True, timeout=20)
            if result.returncode or marker.encode() not in result.stdout:
                raise ValueError('Candidate launcher/runtime lacks automatic maintenance capability')


def backup(home, paths, directory):
    result = {}
    for name in paths:
        path = Path(name)
        if not path.is_relative_to(home):
            raise ValueError('Managed backup outside selected home')
        value = inspect_path(path)
        if value['kind'] == 'file':
            value['content'] = base64.b64encode(path.read_bytes()).decode()
        result[name] = value
    save(directory / 'profile-before.json', result)
    return result


def restore(before, expected):
    for name, value in before.items():
        current = inspect_path(Path(name))
        original = {k: v for k, v in value.items() if k != 'content'}
        if current != original and current != expected.get(name):
            raise ValueError('Rollback refused changed target: ' + name)
    for name, value in reversed(list(before.items())):
        path = Path(name)
        if value['kind'] == 'absent':
            path.unlink(missing_ok=True)
            continue
        temporary = path.with_name('.rollback-' + uuid.uuid4().hex)
        try:
            if value['kind'] == 'link':
                temporary.symlink_to(value['target'])
            else:
                temporary.write_bytes(base64.b64decode(value['content']))
                temporary.chmod(value['mode'])
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def expected_paths(preview, internal):
    values = footprint(preview['unchanged'])
    for entry in preview['changes']:
        if entry['kind'] == 'symlink':
            value = {'kind': 'link', 'target': entry['target']}
        else:
            value = {'kind': 'file', 'sha256': sha(internal['content'][entry['path']]), 'mode': 0o755}
        values[entry['path']] = value
    return values
