"""Inspect and explicitly install published releases without changing quota or setup."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

REPOSITORY = "fszalaj/session-harness"
MAX_DOWNLOAD = 16 * 1024 * 1024
MAX_EXTRACTED = 32 * 1024 * 1024


def version(value):
    if not re.fullmatch(r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise ValueError("Use a stable release version such as 0.1.0")
    return value.removeprefix("v")


def current_version():
    path = Path(__file__).resolve().parent.parent / "VERSION"
    return path.read_text().strip() if path.is_file() else "unversioned"


def fetch(url, limit=MAX_DOWNLOAD):
    request = urllib.request.Request(url, headers={"User-Agent": "session-harness-updater",
                                                   "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if not response.url.startswith("https://"):
            raise ValueError("Release download must use HTTPS")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Release download exceeds its size limit")
    return data


def release_metadata(selected=None):
    endpoint = "latest" if selected is None else "tags/v" + version(selected)
    result = json.loads(fetch(f"https://api.github.com/repos/{REPOSITORY}/releases/{endpoint}", 1024 * 1024))
    if not isinstance(result, dict):
        raise ValueError("Invalid release metadata")
    resolved = version(result["tag_name"])
    if selected and resolved != version(selected):
        raise ValueError("Release tag does not match the requested version")
    if result.get("draft") or result.get("prerelease") or result.get("immutable") is not True:
        raise ValueError("Updates require a published immutable stable release")
    return result


def unpack(data, destination, selected):
    prefix = f"session-harness-{selected}"
    total = 0
    seen = set()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist()) > 10000:
            raise ValueError("Too many archive entries")
        for item in archive.infolist():
            name = item.orig_filename
            parts = PurePosixPath(name).parts
            mode = item.external_attr >> 16
            if (not parts or parts[0] != prefix or len(parts) < 2 or name.startswith("/")
                    or any(part in {".", ".."} for part in name.split("/"))
                    or any(not part or part != part.rstrip(" .") or
                           re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part)
                           for part in name.rstrip("/").split("/"))
                    or "\\" in name or ":" in name or "\x00" in name
                    or (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR})
                    or name.casefold() in seen):
                raise ValueError("Unsafe or duplicate archive entry")
            seen.add(name.casefold())
            total += item.file_size
            if total > MAX_EXTRACTED:
                raise ValueError("Extracted release exceeds its size limit")
            path = destination.joinpath(*parts)
            if item.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(item))
                path.chmod(0o755 if mode & 0o111 else 0o644)
    root = destination / prefix
    marker = json.loads((root / "RELEASE.json").read_text())
    if (not isinstance(marker, dict) or marker.get("version") != selected or marker.get("repository") != REPOSITORY
            or (root / "skills/session-harness/VERSION").read_text().strip() != selected
            or not (root / "scripts/install-agent-profile.py").is_file()):
        raise ValueError("Release contents do not match its metadata")
    return root


def download_release(metadata, destination):
    selected = version(metadata["tag_name"])
    name = f"session-harness-{selected}.zip"
    assets = {asset["name"]: asset for asset in metadata.get("assets", [])}
    if name not in assets or "SHA256SUMS" not in assets:
        raise ValueError("Release archive or checksums are missing")
    base = f"https://github.com/{REPOSITORY}/releases/download/v{selected}/"
    for filename in (name, "SHA256SUMS"):
        if assets[filename].get("browser_download_url") != base + filename:
            raise ValueError("Unexpected release asset URL")
    sums = fetch(base + "SHA256SUMS", 65536).decode("ascii").splitlines()
    matches = [line.split() for line in sums if len(line.split()) == 2 and line.split()[1] == name]
    if len(matches) != 1 or not re.fullmatch(r"[0-9a-f]{64}", matches[0][0]):
        raise ValueError("Invalid release checksum")
    data = fetch(base + name)
    digest = hashlib.sha256(data).hexdigest()
    if digest != matches[0][0]:
        raise ValueError("Release checksum mismatch")
    advertised = assets[name].get("digest")
    if advertised and advertised != "sha256:" + digest:
        raise ValueError("GitHub asset digest mismatch")
    metadata['_verified_archive_sha256'] = digest
    return unpack(data, destination, selected)


def installation(home):
    path = home / ".local/state/session-harness/installation.json"
    if path.is_symlink():
        raise ValueError("Installation metadata must not be a symlink")
    if not path.is_file():
        raise ValueError("Install this version once with scripts/install-agent-profile.py --launcher --apply")
    result = json.loads(path.read_text())
    if (not isinstance(result, dict) or result.get("schema") != 1 or result.get("link_mode") not in {"symlink", "copy"}
            or not re.fullmatch(r"[a-f0-9]{64}", result.get("source_hash", ""))):
        raise ValueError("Invalid installation metadata")
    target = home / ".agents/AGENTS.md"
    if hashlib.sha256(target.read_bytes()).hexdigest() != result.get("instructions_sha256"):
        raise ValueError("Personal instructions changed; reconcile them before updating")
    return result


def update(home, metadata, previous):
    state = home / ".local/state/session-harness"
    lock = state / "update.lock"
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError as error:
        raise ValueError("Another update is active; inspect a stale update.lock before removing it") from error
    try:
        with tempfile.TemporaryDirectory(prefix="harness-update-", dir=state) as directory:
            source = download_release(metadata, Path(directory))
            if installation(home) != previous:
                raise ValueError("Installation changed while downloading; retry after inspecting it")
            command = [sys.executable, str(source / "scripts/install-agent-profile.py"),
                       "--repo", str(source), "--home", str(home), "--link-mode", previous["link_mode"]]
            if previous.get("launcher"):
                command.append("--launcher")
            # The installer reads and preserves the registered private policy itself.
            preview = subprocess.run(command, capture_output=True, text=True, check=True)
            report = json.loads(preview.stdout)
            applied = subprocess.run([*command, "--apply"], capture_output=True, text=True, check=True)
            report = json.loads(applied.stdout)
            return {"version": version(metadata["tag_name"]), "source_hash": report["source_hash"],
                    "changed_paths": len(report["changes"]), "restart_clients": True,
                    "backup_root": report.get("backup_root")}
    finally:
        lock.rmdir()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("version", "update"))
    parser.add_argument("--version", dest="selected", help="Exact release, including an older version for rollback")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="Check only; never install")
    group.add_argument("--apply", action="store_true", help="Explicitly install the selected release")
    args = parser.parse_args(argv)
    try:
        if args.command == "version":
            if args.selected or args.check or args.apply:
                raise ValueError("version takes no update options")
            print(json.dumps({"version": current_version(), "runtime": str(Path(__file__).resolve())}))
            return 0
        if args.apply and not args.selected:
            raise ValueError("Noninteractive installation requires --version X.Y.Z --apply")
        previous = installation(Path.home())
        metadata = release_metadata(args.selected)
        selected = version(metadata["tag_name"])
        print(json.dumps({"installed": previous["version"], "available": selected,
                          "source": previous["source"], "release": metadata["html_url"]}))
        if args.check or (previous["version"] == selected and previous["source"] == "release"):
            return 0
        if not args.apply:
            if not sys.stdin.isatty():
                print(f"To install: ai-session update --version {selected} --apply")
                return 0
            answer = input(f"Install v{selected}, preserving private policy, setup and usage? [y/N] ")
            if answer.strip().lower() not in {"y", "yes"}:
                return 130
        print(json.dumps(update(Path.home(), metadata, previous), indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, EOFError, zipfile.BadZipFile,
            subprocess.CalledProcessError) as error:
        print(json.dumps({"status": "update_failed", "detail": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
