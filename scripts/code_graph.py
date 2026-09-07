#!/usr/bin/env python3
"""Build and query the public graph without reading private or untracked files."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = Path("docs/code-graph.json")
EXTRACTOR = "knowledge-gateway==0.11.0"
SCRIPT_ROOTS = {"scripts", "skills/session-harness/scripts"}
BLIND_SPOTS = (
    "Python declarations and static imports/calls only; dynamic dispatch, CLI "
    "subprocesses, configuration, SQL and Markdown links need source inspection. "
    "An empty result does not prove unused code."
)


def sources(root: Path) -> dict[str, bytes]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "-z", "--", "*.py"],
        cwd=root, check=True, capture_output=True,
    )
    files = {}
    for raw in sorted(set(result.stdout.split(b"\0")) - {b""}):
        name = raw.decode("utf-8")
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe tracked source path")
        path = root / name
        if any((root / Path(*relative.parts[:i])).is_symlink()
               for i in range(1, len(relative.parts) + 1)):
            raise ValueError(f"Symlink source is not exportable: {name}")
        if path.exists():
            files[name] = path.read_bytes().replace(b"\r\n", b"\n")
    if not files:
        raise ValueError("No tracked Python sources; stage new files before building")
    return files


def manifest(files: dict[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}


def digest(data: dict) -> str:
    content = {key: value for key, value in data.items() if key != "content_sha256"}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def script_imports(extracted: dict, tree: Path, files: dict[str, bytes]) -> None:
    from gateway.codegraph.extract_python import extract
    from gateway.codegraph.resolve import ImportResolver

    class ScriptResolver(ImportResolver):
        directory = PurePosixPath(".")

        def resolve_py_abs(self, dotted):
            if dotted:
                base = (self.directory / dotted.replace(".", "/")).as_posix()
                for candidate in (base + ".py", base + "/__init__.py"):
                    if candidate in files:
                        return candidate
            return super().resolve_py_abs(dotted)

    resolver = ScriptResolver(tree, files)
    for name in files:
        directory = PurePosixPath(name).parent
        if directory.as_posix() not in SCRIPT_ROOTS:
            continue
        resolver.directory = directory
        module = "module:" + name
        extracted["links"] = [e for e in extracted["links"]
                              if not (e["source"] == module and e.get("relation") == "imports")]
        extracted["links"].extend(e for e in extract(tree / name, name, resolver)["edges"]
                                  if e["relation"] == "imports")
    referenced = {e[k] for e in extracted["links"] for k in ("source", "target")}
    extracted["nodes"] = [n for n in extracted["nodes"]
                          if not n["id"].startswith("extmodule:") or n["id"] in referenced]


def build(root: Path) -> dict:
    from importlib.metadata import version
    try:
        from gateway.codegraph.build import build_graph
    except ImportError as exc:
        raise ValueError("Install rebuild dependencies: python -m pip install -r requirements-graph.txt") from exc
    if version("knowledge-gateway") != "0.11.0" or version("networkx") != "3.6.1":
        raise ValueError("Use the versions pinned in requirements-graph.txt")
    files = sources(root)
    for name, content in files.items():
        try:
            ast.parse(content, filename=name)
        except SyntaxError as exc:
            raise ValueError(f"Cannot graph invalid Python: {name}:{exc.lineno}") from exc
    with tempfile.TemporaryDirectory(prefix="harness-graph-") as directory:
        tree = Path(directory) / "session-harness"
        for name, content in files.items():
            target = tree / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        extracted = build_graph(tree)
        script_imports(extracted, tree, files)
    node_fields = {"id", "label", "type", "file_type", "source_file", "source_location"}
    edge_fields = {"source", "target", "relation", "confidence"}
    nodes = sorted(({k: v for k, v in n.items() if k in node_fields}
                    for n in extracted["nodes"]), key=lambda n: n["id"])
    unique_edges = {(e["source"], e["target"], e["relation"]): e for e in extracted["links"]}
    links = sorted(({k: v for k, v in e.items() if k in edge_fields}
                    for e in unique_edges.values()),
                   key=lambda e: (e["source"], e["target"], e.get("relation", "")))
    for node in nodes:
        if node.get("source_file") and node["source_file"] not in files:
            raise ValueError("Extractor emitted a source outside the tracked input")
    data = {"directed": True, "multigraph": False,
            "graph": {"schema_version": 1, "root": "session-harness",
                      "extractor": EXTRACTOR, "sources": manifest(files),
                      "node_count": len(nodes), "edge_count": len(links),
                      "coverage": BLIND_SPOTS}, "nodes": nodes, "links": links}
    data["content_sha256"] = digest(data)
    return data


def serialize(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def load(root: Path) -> dict:
    path = root / SNAPSHOT
    if not path.is_file():
        raise ValueError("Missing graph; run python scripts/code_graph.py build")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("content_sha256") != digest(data):
        raise ValueError("Graph content changed; rebuild instead of editing the snapshot")
    if data.get("graph", {}).get("sources") != manifest(sources(root)):
        raise ValueError("Stale graph; run python scripts/code_graph.py build")
    return data


def query(data: dict, command: str, term: str) -> list[dict]:
    nodes = data["nodes"]
    if command == "find":
        return [n for n in nodes if term.lower() in n.get("label", n["id"]).lower()]
    modules = [n for n in nodes if n.get("type") == "module"]
    selected = [n for n in modules if n.get("source_file") == term]
    if not selected:
        selected = [n for n in modules if term in n.get("source_file", "")]
    if len(selected) != 1:
        raise ValueError("Module missing or ambiguous; provide its full repository path")
    source, target = ("source", "target") if command == "imports" else ("target", "source")
    ids = {e[target] for e in data["links"]
           if e.get("relation") == "imports" and e[source] == selected[0]["id"]}
    return [n for n in nodes if n["id"] in ids]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    rebuild = commands.add_parser("build", help="Rebuild from tracked working-tree Python files")
    rebuild.add_argument("--check", action="store_true", help="Compare a full rebuild without writing")
    commands.add_parser("check", help="Verify source hashes and graph integrity without dependencies")
    for name in ("find", "imports", "importers"):
        commands.add_parser(name).add_argument("term")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            data = build(ROOT)
            content = serialize(data)
            destination = ROOT / SNAPSHOT
            if args.check:
                if not destination.is_file() or destination.read_text(encoding="utf-8") != content:
                    raise ValueError("Graph differs from rebuild; run python scripts/code_graph.py build")
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8", newline="\n")
        else:
            data = load(ROOT)
        if args.command in {"check", "build"}:
            print(f"Graph current: {len(data['nodes'])} nodes, {len(data['links'])} edges")
        else:
            matches = query(data, args.command, args.term)
            for node in matches[:30]:
                location = node.get("source_file", "external dependency")
                if node.get("source_location"):
                    location += ":" + node["source_location"]
                print(f"{node.get('type', 'external')}: {node.get('label', node['id'])} ({location})")
            print(f"{len(matches)} matches" + ("; showing 30" if len(matches) > 30 else ""))
            print(BLIND_SPOTS)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
