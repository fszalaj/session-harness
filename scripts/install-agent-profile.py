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
        f"runtime = {str(runtime)!r}\n"
        "args = sys.argv[1:]\n"
        "if args and args[0] in {'budget', 'inventory', 'usage'}:\n"
        "    forwarded = args\n"
        "else:\n"
        "    forwarded = ['launch', *args[:1], '--execute', *args[1:]]\n"
        "os.execv(sys.executable, [sys.executable, runtime, *forwarded])\n"
    ).encode()


def release_sources(repo: Path) -> tuple[dict, list]:
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
            sources[str(Path("session-harness") / relative)] = path
    legal_names = ("LICENSE", "NOTICE")
    if any((legal_root / name).exists() or (legal_root / name).is_symlink() for name in legal_names):
        for name in legal_names:
            path = legal_root / name
            if path.is_symlink() or not path.is_file():
                raise InstallationError(f"Missing or nonregular licensing artifact: {path}")
            sources[name] = path
            sources[str(Path("session-harness") / name)] = path
    native = []
    for provider, directory, pattern, destination in [
        ("codex", "codex-agents", "*.toml", ".codex/agents"),
        ("claude", "claude-agents", "*.md", ".claude/agents"),
    ]:
        for path in sorted((profile / directory).glob(pattern)):
            relative = str(Path("native") / provider / path.name)
            sources[relative] = path
            native.append((Path(destination) / path.name, relative))
    payload = {}
    for relative, path in sorted(sources.items()):
        if path.is_symlink() or not path.is_file():
            raise InstallationError(f"Snapshot source must be a regular file: {path}")
        mode = 0o555 if path.stat().st_mode & 0o111 else 0o444
        payload[relative] = {"content": path.read_bytes(), "mode": mode}
    return payload, native


def release_hash(payload: dict) -> str:
    digest = hashlib.sha256()
    for relative, item in sorted(payload.items()):
        metadata = json.dumps([relative, item["mode"], len(item["content"])], separators=(",", ":"))
        digest.update(metadata.encode() + b"\0" + item["content"])
    return digest.hexdigest()


def verify_release(release: Path, payload: dict) -> None:
    if release.is_symlink() or not release.is_dir():
        raise InstallationError(f"Release must be an immutable directory: {release}")
    if stat.S_IMODE(release.stat().st_mode) != 0o555:
        raise InstallationError(f"Installed release directory permissions were modified: {release}")
    actual = set()
    for path in release.rglob("*"):
        if path.is_symlink():
            raise InstallationError(f"Unexpected symlink in installed release: {path}")
        if path.is_file():
            actual.add(str(path.relative_to(release)))
        elif path.is_dir() and stat.S_IMODE(path.stat().st_mode) != 0o555:
            raise InstallationError(f"Installed release directory permissions were modified: {path}")
        elif not path.is_dir():
            raise InstallationError(f"Unexpected special file in installed release: {path}")
    if actual != set(payload):
        raise InstallationError(f"Installed release file set differs from its source hash: {release}")
    for relative, item in payload.items():
        path = release / relative
        if path.read_bytes() != item["content"] or stat.S_IMODE(path.stat().st_mode) != item["mode"]:
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
        directory.chmod(0o700)
    staging = release.parent / (".building-" + uuid.uuid4().hex)
    staging.mkdir(mode=0o700)
    try:
        for relative, item in payload.items():
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_bytes(item["content"])
            path.chmod(item["mode"])
        for directory in [path for path in staging.rglob("*") if path.is_dir()]:
            directory.chmod(0o555)
        staging.chmod(0o555)
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
            staging.chmod(0o700)
            for directory in [path for path in staging.rglob("*") if path.is_dir()]:
                directory.chmod(0o700)
            shutil.rmtree(staging)


def plan_install(home: Path, repo: Path, include_launcher: bool) -> tuple[dict, dict]:
    for variable, directory in [("CODEX_HOME", ".codex"), ("CLAUDE_CONFIG_DIR", ".claude"),
                                ("COPILOT_HOME", ".copilot")]:
        override = os.environ.get(variable)
        if override and Path(override).expanduser().resolve() != (home / directory).resolve():
            raise InstallationError(f"Custom {variable} is unsupported by this installer; preserve it and configure its instruction links explicitly")
    payload, native = release_sources(repo)
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
        launcher = str(home / ".local/bin/ai-session")
        content[launcher] = launcher_content(runtime)
        entries.append({"path": launcher, "kind": "launcher", "mode": "0755"})

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
                       and stat.S_IMODE(path.stat().st_mode) == 0o755)
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
        path.chmod(0o700)
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
    home = Path(result["home"])
    changes = result["changes"]
    backup_run = None
    for entry in changes:
        path = Path(entry["path"])
        if fingerprint(path) != internal["snapshots"][str(path)]:
            raise InstallationError(f"Managed path changed after preflight: {path}")
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
                    backup.symlink_to(os.readlink(path))
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
                    temporary.symlink_to(entry["target"])
                else:
                    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o755)
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(internal["content"][str(path)])
                    temporary.chmod(0o755)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home(), help="Profile home (default: current home)")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1],
                        help="Durable repository checkout containing profile sources")
    parser.add_argument("--apply", action="store_true", help="Apply the previewed links with private backups")
    parser.add_argument("--launcher", action="store_true", help="Also install ~/.local/bin/ai-session")
    args = parser.parse_args(argv)
    result = {"mode": "apply" if args.apply else "dry-run"}
    try:
        home = args.home.expanduser().resolve()
        repo = args.repo.expanduser().resolve()
        plan, internal = plan_install(home, repo, args.launcher)
        result.update(plan)
        if args.apply:
            apply_install(result, internal)
    except (InstallationError, OSError) as error:
        result["error"] = str(error)
        print(json.dumps(result, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
