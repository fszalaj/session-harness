#!/usr/bin/env python3
"""Preview or install shared agent instructions without changing client settings."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import uuid
import tempfile

WINDOWS = os.name == "nt"
from datetime import datetime, timezone


class InstallationError(Exception):
    pass


def fingerprint(path: Path) -> tuple | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    target = os.readlink(path) if stat.S_ISLNK(info.st_mode) else None
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, target)


def kind(path: Path) -> str:
    if path.is_symlink():
        return "symlink"
    if path.is_file():
        return "file"
    if path.exists():
        return "directory" if path.is_dir() else "special"
    return "absent"


def link_matches(path: Path, target: Path) -> bool:
    if not path.is_symlink():
        return False
    current = os.path.abspath(path.parent / os.readlink(path))
    return current == os.path.abspath(target)


def launcher_content(runtime: Path) -> bytes:
    return (
        "#!/usr/bin/env python3\n"
        '"""Launch the current provider through the shared session harness."""\n'
        "import os\n"
        "import sys\n\n"
        f"python = {sys.executable!r}\n"
        "if os.name != 'nt' and sys.executable != python:\n"
        "    os.execv(python, [python, *sys.argv])\n"
        f"runtime = {str(runtime)!r}\n"
        "args = sys.argv[1:]\n"
        "if not args:\n"
        "    forwarded = ['--help']\n"
        "elif args[0] in {'setup', 'configure', 'version', 'update', 'auto-update', 'coordination', 'hooks', 'budget', 'inventory', 'usage', 'api', 'spend', 'discover', 'review', '--help', '-h'}:\n"
        "    forwarded = args\n"
        "else:\n"
        "    forwarded = ['launch', *args[:1], '--execute', *args[1:]]\n"
        "if os.name == 'nt':\n"
        "    import runpy\n"
        "    sys.argv = [runtime, *forwarded]\n"
        "    sys.path.insert(0, os.path.dirname(runtime))\n"
        "    runpy.run_path(runtime, run_name='__main__')\n"
        "else:\n"
        "    os.execv(sys.executable, [sys.executable, runtime, *forwarded])\n"
    ).encode()


def windows_security():
    roots = [Path(__file__).resolve().parents[1] / 'skills/session-harness/scripts',
             Path(__file__).resolve().parents[1] / '.claude/skills/session-harness/scripts']
    directory = next((root for root in roots if (root / 'windows_security.py').is_file()), None)
    if directory is None:
        raise InstallationError('Windows security helper is missing')
    import importlib.util
    spec = importlib.util.spec_from_file_location('installer_windows_security', directory / 'windows_security.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def set_permissions(path, mode):
    if WINDOWS:
        windows_security().protect(path)
    else:
        path.chmod(mode)


def launcher_files(home, runtime):
    if not WINDOWS:
        return {str(home / '.local/bin/ai-session'): launcher_content(runtime)}
    entry = home / '.local/bin/ai-session.py'
    python = str(Path(sys.executable).resolve()).replace("'", "''")
    script = str(entry).replace("'", "''")
    wrapper = ("#requires -Version 7.3\n"
               "$PSNativeCommandArgumentPassing = 'Standard'\n"
               f"& '{python}' '{script}' @args\n"
               "exit $LASTEXITCODE\n")
    return {str(entry): launcher_content(runtime),
            str(home / '.local/bin/ai-session.ps1'): wrapper.encode('utf-8')}


def copy_state_path(home):
    return home / '.local/state/session-harness/copy-state.json'


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan_copy(home, repo, include_launcher, personal_policy=None):
    payload, native = release_sources(repo, personal_policy)
    source_hash = release_hash(payload)
    release = home / '.local/share/session-harness/releases' / source_hash
    state_path = copy_state_path(home)
    if WINDOWS:
        windows_security().reject_reparse(state_path)
    if state_path.is_symlink():
        raise InstallationError('Copy installation state must not be a symlink')
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    if not isinstance(previous, dict) or any(not isinstance(k, str) or not isinstance(v, str) or
                                            len(v) != 64 for k, v in previous.items()):
        raise InstallationError('Invalid copy installation state')
    content = {}
    instruction_paths = ['.agents/AGENTS.md', '.codex/AGENTS.md', '.claude/CLAUDE.md',
                         '.gemini/GEMINI.md', '.copilot/copilot-instructions.md']
    for destination in instruction_paths:
        content[str(home / destination)] = payload['AGENTS.md']['content']
    roots = [home / path for path in ['.agents/skills/session-harness', '.codex/skills/session-harness',
             '.claude/skills/session-harness', '.gemini/config/skills/session-harness',
             '.copilot/skills/session-harness', '.cursor/skills/session-harness']]
    for root in roots:
        if root.is_symlink():
            raise InstallationError('Resolve existing skill symlinks before selecting copy mode')
        for relative, item in payload.items():
            if relative.startswith('session-harness/'):
                content[str(root / relative[len('session-harness/'):])] = item['content']
        if root.exists():
            for path in root.rglob('*'):
                if '__pycache__' in path.parts or path.suffix in {'.pyc', '.pyo'}:
                    continue
                if path.is_symlink() or (path.is_file() and str(path) not in previous):
                    raise InstallationError('Unmanaged content in copied skill; preserve and reconcile it first')
    for destination, relative in native:
        content[str(home / destination)] = payload[relative]['content']
    if include_launcher:
        content.update(launcher_files(home, release / 'session-harness/scripts/harness.py'))
    else:
        for name in ('ai-session', 'ai-session.py', 'ai-session.ps1'):
            path = home / '.local/bin' / name
            if str(path) in previous and path.is_file():
                content[str(path)] = path.read_bytes()
    result = dict(home=str(home), repo=str(repo), source_hash=source_hash, release_root=str(release),
                  release_files=len(payload), release_created=False, link_mode='copy', changes=[], unchanged=[])
    snapshots = {}
    for name in sorted(set(content) | set(previous)):
        path = Path(name)
        if not path.is_absolute() or not path.resolve().is_relative_to(home.resolve()):
            raise InstallationError('Copy state path is outside the selected home')
        if WINDOWS: windows_security().reject_reparse(path)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise InstallationError('Copy destination must be a regular file')
        if name in previous and (not path.exists() or file_digest(path) != previous[name]):
            raise InstallationError('Managed copy was modified; preserve and reconcile it first')
        if name in content and path.is_file() and path.read_bytes() == content[name]:
            result['unchanged'].append(name); continue
        action = 'delete' if name not in content else ('replace' if path.exists() else 'create')
        result['changes'].append(dict(path=name, kind='copy', action=action, applied=False))
        snapshots[name] = fingerprint(path)
    return result, dict(content=content, release=payload, snapshots=snapshots,
                        state_snapshot=fingerprint(state_path))


def apply_copy(result, internal):
    home = Path(result['home'])
    lock = copy_state_path(home).with_name('copy-install.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    if WINDOWS:
        windows_security().prepare_private_file(lock)
    elif lock.is_symlink():
        raise InstallationError('Copy installation lock must not be a symlink')
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | (getattr(os, 'O_NOFOLLOW', 0)), 0o600)
    try:
        if WINDOWS:
            import msvcrt
            if not os.fstat(descriptor).st_size: os.write(descriptor, b'0')
            os.lseek(descriptor, 0, os.SEEK_SET)
            try: msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as error: raise InstallationError('Another copy installation is active') from error
        else:
            import fcntl
            try: fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error: raise InstallationError('Another copy installation is active') from error
        _apply_copy_locked(result, internal)
    finally:
        os.close(descriptor)


def _apply_copy_locked(result, internal):
    home = Path(result['home']); state_path = copy_state_path(home)
    if fingerprint(state_path) != internal['state_snapshot']:
        raise InstallationError('Copy installation state changed after preview')
    for entry in result['changes']:
        if fingerprint(Path(entry['path'])) != internal['snapshots'][entry['path']]:
            raise InstallationError('Copy destination changed after preview')
    install_release(result, internal['release'])
    if not result['changes'] and state_path.exists():
        return
    run = private_backup_run(home)
    result['backup_root'] = str(run)
    try:
        for entry in result['changes']:
            path = Path(entry['path']); expected = internal['snapshots'][str(path)]
            if fingerprint(path) != expected:
                raise InstallationError('Copy destination changed during installation')
            if entry['action'] in {'replace', 'delete'}:
                backup = run / path.relative_to(home); backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup); entry['backup'] = str(backup)
            if entry['action'] == 'delete':
                if fingerprint(path) != expected:
                    raise InstallationError('Copy destination changed while backing up')
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                if WINDOWS: windows_security().reject_reparse(path)
                temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
                try:
                    temporary.write_bytes(internal['content'][str(path)])
                    set_permissions(temporary, 0o755 if path.name.startswith('ai-session') else 0o644)
                    if fingerprint(path) != expected:
                        raise InstallationError('Copy destination changed before replacement')
                    os.replace(temporary, path)
                finally:
                    if temporary.exists(): temporary.unlink()
            entry['applied'] = True
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state = {name: hashlib.sha256(value).hexdigest() for name, value in internal['content'].items()}
        temporary = state_path.with_name('.copy-state-' + uuid.uuid4().hex)
        try:
            temporary.write_text(json.dumps(state, sort_keys=True), encoding='utf-8')
            set_permissions(temporary, 0o600)
            os.replace(temporary, state_path)
        finally:
            if temporary.exists(): temporary.unlink()
    finally:
        write_manifest(run, result)


def release_sources(repo: Path, personal_policy: Path | None = None) -> tuple[dict, list]:
    profile = repo / "profile"
    skill = repo / "skills/session-harness"
    legal_root = repo
    if not profile.is_dir():
        profile = repo / "infra/host/agent-profile"
        skill = repo / ".claude/skills/session-harness"
        legal_root = skill
    sources = {"AGENTS.md": profile / "AGENTS.md"}
    if not sources["AGENTS.md"].is_file():
        raise InstallationError(f"Missing profile instructions: {sources['AGENTS.md']}")
    if not (skill / "SKILL.md").is_file():
        raise InstallationError(f"Missing harness skill: {skill / 'SKILL.md'}")
    for path in sorted(skill.rglob("*")):
        relative = path.relative_to(skill)
        if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_symlink():
            raise InstallationError(f"Snapshot sources must not contain symlinks: {path}")
        if path.is_file():
            sources[(Path("session-harness") / relative).as_posix()] = path
    legal_names = ("LICENSE", "NOTICE")
    if any((legal_root / name).exists() or (legal_root / name).is_symlink() for name in legal_names):
        for name in legal_names:
            path = legal_root / name
            if path.is_symlink() or not path.is_file():
                raise InstallationError(f"Missing or nonregular licensing artifact: {path}")
            sources[name] = path
            sources[(Path("session-harness") / name).as_posix()] = path
    native = []
    for provider, directory, pattern, destination in [
        ("codex", "codex-agents", "*.toml", ".codex/agents"),
        ("claude", "claude-agents", "*.md", ".claude/agents"),
    ]:
        for path in sorted((profile / directory).glob(pattern)):
            relative = (Path("native") / provider / path.name).as_posix()
            sources[relative] = path
            native.append((Path(destination) / path.name, relative))
    payload = {}
    for relative, path in sorted(sources.items()):
        if path.is_symlink() or not path.is_file():
            raise InstallationError(f"Snapshot source must be a regular file: {path}")
        mode = 0o555 if path.stat().st_mode & 0o111 else 0o444
        payload[relative] = {"content": path.read_bytes(), "mode": mode}
    if personal_policy is not None:
        if not personal_policy.is_file() or personal_policy.is_symlink():
            raise InstallationError("Personal policy must be a regular private Markdown file")
        extra = personal_policy.read_bytes()
        if len(extra) > 128 * 1024:
            raise InstallationError("Personal policy is too large; move detail to on-demand references")
        payload["AGENTS.md"]["content"] += b"\n\n---\n\n" + extra
    return payload, native


def release_hash(payload: dict) -> str:
    digest = hashlib.sha256()
    for relative, item in sorted(payload.items()):
        metadata = json.dumps([relative, item["mode"], len(item["content"])], separators=(",", ":"))
        digest.update(metadata.encode() + b"\0" + item["content"])
    return digest.hexdigest()


def verify_release(release: Path, payload: dict) -> None:
    if WINDOWS: windows_security().reject_reparse(release)
    if release.is_symlink() or not release.is_dir():
        raise InstallationError(f"Release must be an immutable directory: {release}")
    if not WINDOWS and stat.S_IMODE(release.stat().st_mode) != 0o555:
        raise InstallationError(f"Installed release directory permissions were modified: {release}")
    actual = set()
    for path in release.rglob("*"):
        if WINDOWS: windows_security().reject_reparse(path)
        if path.is_symlink():
            raise InstallationError(f"Unexpected symlink in installed release: {path}")
        if path.is_file():
            actual.add(path.relative_to(release).as_posix())
        elif not WINDOWS and path.is_dir() and stat.S_IMODE(path.stat().st_mode) != 0o555:
            raise InstallationError(f"Installed release directory permissions were modified: {path}")
        elif not path.is_dir():
            raise InstallationError(f"Unexpected special file in installed release: {path}")
    if actual != set(payload):
        raise InstallationError(f"Installed release file set differs from its source hash: {release}")
    for relative, item in payload.items():
        path = release / relative
        if path.read_bytes() != item["content"] or (not WINDOWS and stat.S_IMODE(path.stat().st_mode) != item["mode"]):
            raise InstallationError(f"Installed release was modified; preserve and inspect it: {path}")


def install_release(result: dict, payload: dict) -> None:
    release = Path(result["release_root"])
    if release.exists() or release.is_symlink():
        verify_release(release, payload)
        return
    for directory in [release.parent.parent, release.parent]:
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise InstallationError(f"Release location must be a real directory: {directory}")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        set_permissions(directory, 0o700)
    staging = release.parent / (".building-" + uuid.uuid4().hex)
    staging.mkdir(mode=0o700)
    try:
        for relative, item in payload.items():
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_bytes(item["content"])
            set_permissions(path, item["mode"])
        for directory in [path for path in staging.rglob("*") if path.is_dir()]:
            set_permissions(directory, 0o555)
        set_permissions(staging, 0o555)
        try:
            staging.rename(release)
        except OSError:
            if not release.exists():
                raise
            verify_release(release, payload)
        else:
            result["release_created"] = True
    finally:
        if staging.exists():
            set_permissions(staging, 0o700)
            for directory in [path for path in staging.rglob("*") if path.is_dir()]:
                set_permissions(directory, 0o700)
            shutil.rmtree(staging)


def plan_install(home: Path, repo: Path, include_launcher: bool, link_mode="symlink", personal_policy=None) -> tuple[dict, dict]:
    for variable, directory in [("CODEX_HOME", ".codex"), ("CLAUDE_CONFIG_DIR", ".claude"),
                                ("COPILOT_HOME", ".copilot")]:
        override = os.environ.get(variable)
        if override and Path(override).expanduser().resolve() != (home / directory).resolve():
            raise InstallationError(f"Custom {variable} is unsupported by this installer; preserve it and configure its instruction links explicitly")
    if link_mode == 'copy':
        return plan_copy(home, repo, include_launcher, personal_policy)
    if link_mode != 'symlink':
        raise InstallationError('Link mode must be symlink or copy')
    payload, native = release_sources(repo, personal_policy)
    source_hash = release_hash(payload)
    release = home / ".local/share/session-harness/releases" / source_hash
    if release.exists() or release.is_symlink():
        verify_release(release, payload)
    instructions = release / "AGENTS.md"
    skill = release / "session-harness"
    shared_instructions = home / ".agents/AGENTS.md"
    shared_skill = home / ".agents/skills/session-harness"
    links = [
        (shared_instructions, instructions),
        (home / ".codex/AGENTS.md", shared_instructions),
        (home / ".claude/CLAUDE.md", shared_instructions),
        (home / ".gemini/GEMINI.md", shared_instructions),
        (home / ".copilot/copilot-instructions.md", shared_instructions),
        (shared_skill, skill),
        (home / ".codex/skills/session-harness", shared_skill),
        (home / ".claude/skills/session-harness", shared_skill),
        (home / ".gemini/config/skills/session-harness", shared_skill),
        (home / ".copilot/skills/session-harness", shared_skill),
        (home / ".cursor/skills/session-harness", shared_skill),
    ]
    links.extend((home / destination, release / relative) for destination, relative in native)

    entries = [{"path": str(path), "kind": "symlink", "target": str(target)}
               for path, target in links]
    content: dict[str, bytes] = {}
    if include_launcher:
        runtime = skill / "scripts/harness.py"
        if "session-harness/scripts/harness.py" not in payload:
            raise InstallationError("Missing harness runtime: session-harness/scripts/harness.py")
        launchers = launcher_files(home, runtime)
        content.update(launchers)
        entries.extend({'path': path, 'kind': 'launcher', 'mode': '0755'} for path in launchers)

    result = {"home": str(home), "repo": str(repo), "source_hash": source_hash,
              "release_root": str(release), "release_files": len(payload),
              "release_created": False, "changes": [], "unchanged": []}
    snapshots = {}
    for entry in entries:
        path = Path(entry["path"])
        previous_kind = kind(path)
        if previous_kind in {"directory", "special"}:
            raise InstallationError(f"Managed leaf is a {previous_kind}; preserve and resolve it first: {path}")
        for parent in path.parents:
            if parent == home.parent:
                break
            if (parent.exists() or parent.is_symlink()) and not parent.is_dir():
                raise InstallationError(f"Parent is not an accessible directory: {parent}")
        if entry["kind"] == "symlink":
            matches = link_matches(path, Path(entry["target"]))
        else:
            matches = (previous_kind == "file"
                       and path.read_bytes() == content[str(path)]
                       and (WINDOWS or stat.S_IMODE(path.stat().st_mode) == 0o755))
        if matches:
            result["unchanged"].append(str(path))
            continue
        entry.update(action="create" if previous_kind == "absent" else "replace",
                     previous_kind=previous_kind, applied=False)
        if previous_kind == "symlink":
            entry["previous_target"] = os.readlink(path)
        result["changes"].append(entry)
        snapshots[str(path)] = fingerprint(path)
    return result, {"snapshots": snapshots, "content": content, "release": payload}


def private_backup_run(home: Path) -> Path:
    root = home / ".local/state/session-harness"
    for path in [root, root / "backups"]:
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise InstallationError(f"Backup location must be a real directory: {path}")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        set_permissions(path, 0o700)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8]
    run = root / "backups" / run_id
    run.mkdir(mode=0o700)
    return run


def write_manifest(run: Path, result: dict) -> None:
    path = run / "manifest.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")


def apply_install(result: dict, internal: dict) -> None:
    if result.get('link_mode') == 'copy':
        return apply_copy(result, internal)
    home = Path(result["home"])
    changes = result["changes"]
    backup_run = None
    for entry in changes:
        path = Path(entry["path"])
        if fingerprint(path) != internal["snapshots"][str(path)]:
            raise InstallationError(f"Managed path changed after preflight: {path}")
    if WINDOWS:
        with tempfile.TemporaryDirectory(prefix='harness-link-probe-') as directory:
            root = Path(directory)
            source = root / 'source'; source.write_text('probe')
            try:
                (root / 'file-link').symlink_to(source)
                (root / 'directory-link').symlink_to(home, target_is_directory=True)
            except OSError as error:
                raise InstallationError('Windows symlinks unavailable; explicitly select --link-mode copy') from error
    install_release(result, internal["release"])
    if any(entry["action"] == "replace" for entry in changes):
        backup_run = private_backup_run(home)
        result["backup_root"] = str(backup_run)
        write_manifest(backup_run, result)

    try:
        for entry in changes:
            path = Path(entry["path"])
            expected = internal["snapshots"][str(path)]
            if fingerprint(path) != expected:
                raise InstallationError(f"Managed path changed after preflight: {path}")
            if entry["action"] == "replace":
                backup = backup_run / path.relative_to(home)
                backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                if path.is_symlink():
                    backup.symlink_to(os.readlink(path), target_is_directory=path.is_dir())
                    shutil.copystat(path, backup, follow_symlinks=False)
                else:
                    shutil.copy2(path, backup)
                entry["backup"] = str(backup)
                if fingerprint(path) != expected:
                    raise InstallationError(f"Managed path changed while backing up: {path}")

            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.install-{uuid.uuid4().hex}")
            try:
                if entry["kind"] == "symlink":
                    temporary.symlink_to(entry["target"], target_is_directory=Path(entry["target"]).is_dir())
                else:
                    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o755)
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(internal["content"][str(path)])
                    set_permissions(temporary, 0o755)
                if fingerprint(path) != expected:
                    raise InstallationError(f"Managed path changed before replacement: {path}")
                os.replace(temporary, path)
                entry["applied"] = True
            finally:
                if temporary.exists() or temporary.is_symlink():
                    temporary.unlink()
    finally:
        if backup_run:
            write_manifest(backup_run, result)


def installation_state_path(home):
    return home / ".local/state/session-harness/installation.json"


def read_installation_state(home):
    path = installation_state_path(home)
    if WINDOWS:
        windows_security().reject_reparse(path)
    if path.is_symlink():
        raise InstallationError("Installation state must not be a symlink")
    if not path.exists():
        return {}
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise InstallationError("Unknown installation state; preserve and reconcile it first")
    return value


def save_installation_state(home, repo, result, personal_policy, link_mode, include_launcher):
    version_path = repo / "skills/session-harness/VERSION"
    if not version_path.exists():
        version_path = repo / ".claude/skills/session-harness/VERSION"
    state = dict(schema=1, version=version_path.read_text().strip() if version_path.exists() else "unversioned",
                 source="release" if (repo / "RELEASE.json").is_file() else "checkout",
                 source_hash=result["source_hash"], link_mode=link_mode, launcher=include_launcher,
                 personal_policy=str(personal_policy) if personal_policy else None,
                 instructions_sha256=file_digest(home / ".agents/AGENTS.md"))
    path = installation_state_path(home)
    if read_installation_state(home) == state:
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(".installation-" + uuid.uuid4().hex)
    try:
        temporary.write_text(json.dumps(state, indent=2) + "\n")
        set_permissions(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home(), help="Profile home (default: current home)")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1],
                        help="Durable repository checkout containing profile sources")
    parser.add_argument("--apply", action="store_true", help="Apply the previewed links with private backups")
    parser.add_argument("--link-mode", choices=("symlink", "copy"), default="symlink",
                        help="Explicit checked-copy mode supports homes without symlink privileges")
    parser.add_argument("--personal-policy", type=Path, help="Private Markdown addendum, preserved across updates")
    parser.add_argument("--launcher", action="store_true", help="Also install ~/.local/bin/ai-session")
    args = parser.parse_args(argv)
    result = {"mode": "apply" if args.apply else "dry-run"}
    try:
        home = args.home.expanduser().resolve()
        repo = args.repo.expanduser().resolve()
        previous = read_installation_state(home)
        personal_policy = args.personal_policy or previous.get("personal_policy")
        personal_policy = Path(personal_policy).expanduser().absolute() if personal_policy else None
        plan, internal = plan_install(home, repo, args.launcher, args.link_mode, personal_policy)
        result.update(plan)
        if args.apply:
            apply_install(result, internal)
            save_installation_state(home, repo, result, personal_policy, args.link_mode, args.launcher)
    except (InstallationError, OSError, ValueError) as error:
        result["error"] = str(error)
        print(json.dumps(result, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
