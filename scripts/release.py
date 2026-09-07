#!/usr/bin/env python3
"""Build deterministic release assets from a committed Git revision."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import posixpath
import stat
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(repo, revision, output):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args])
    commit = git("rev-parse", "--verify", revision + "^{commit}").decode().strip()
    version = git("show", commit + ":skills/session-harness/VERSION").decode().strip()
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        raise ValueError("Invalid stable version")
    files = {}
    for row in git("ls-tree", "-rz", commit).split(b"\0"):
        if not row:
            continue
        metadata, raw_path = row.split(b"\t", 1)
        mode, kind, object_id = metadata.split()
        path = raw_path.decode()
        if kind != b"blob" or mode not in {b"100644", b"100755", b"120000"}:
            raise ValueError("Unsupported release tree entry")
        files[path] = (mode, git("cat-file", "blob", object_id.decode()))
    # Materialize file aliases; skill directory aliases are created by the installer.
    for path, (mode, content) in list(files.items()):
        if mode == b"120000":
            target = posixpath.normpath(posixpath.join(posixpath.dirname(path), content.decode()))
            if target in files and files[target][0] != b"120000":
                files[path] = files[target]
            elif any(name.startswith(target + "/") for name in files):
                del files[path]
            else:
                raise ValueError("Unsupported release alias")
    files["RELEASE.json"] = (b"100644", (json.dumps(dict(repository="fszalaj/session-harness",
                                      version=version, commit=commit), sort_keys=True) + "\n").encode())
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"session-harness-{version}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path, (mode, content) in sorted(files.items()):
            item = zipfile.ZipInfo(f"session-harness-{version}/{path}", (1980, 1, 1, 0, 0, 0))
            item.create_system = 3
            item.external_attr = (stat.S_IFREG | (0o755 if mode == b"100755" else 0o644)) << 16
            item.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(item, content)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n")
    return dict(version=version, commit=commit, archive=str(archive), sha256=digest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD", help="Committed revision; working tree edits are excluded")
    parser.add_argument("--output", type=Path, required=True, help="Artifact directory outside the checkout")
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(ROOT):
        parser.error("Keep built artifacts outside the checkout")
    print(json.dumps(build(ROOT, args.ref, args.output), indent=2))


if __name__ == "__main__":
    main()
