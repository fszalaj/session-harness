# Contributor code graph

[code-graph.json](code-graph.json) is a committed, derived graph of this repository's
tracked Python sources. It contains declarations and static relationships, relative
source paths, line locations and content hashes. It is available after cloning;
reading it does not require a gateway server, account, credentials or model calls.
Use Python 3.11 or newer and Git on Linux, macOS or Windows.

```sh
python scripts/code_graph.py find Ledger
python scripts/code_graph.py imports skills/session-harness/scripts/harness.py
python scripts/code_graph.py importers skills/session-harness/scripts/quota.py
python scripts/code_graph.py check
```

Queries check source freshness and graph integrity before returning results. Output
is bounded to 30 matches. Use an exact repository path when a module name is
ambiguous. The JSON uses node-link format with `nodes`, `links` and `graph` metadata,
so graph tools can read it directly. Avoid pasting the entire snapshot into prompts.

## Rebuild

The optional rebuild environment uses the existing knowledge-gateway Python
extractor. The wrapper also resolves bare sibling imports in this repository's
two CLI script directories, whose execution puts that directory on Python's import
path. Keep rebuild dependencies separate from runtime dependencies:

```sh
python -m venv .venv
# Linux/macOS: . .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-graph.txt
# Stage new Python paths so they are included, for example:
git add scripts/new_helper.py
python scripts/code_graph.py build
python scripts/code_graph.py build --check
python scripts/test.py
```

Replace the example path with files you actually added; omit that step when there
are no new Python files. Stage the changed graph with the corresponding source
change. The builder reads tracked **working-tree contents**, including edits and
deletions. It does not require committing code first. Docs-only changes do not
require a rebuild. It normalizes CRLF/LF for stable cross-platform hashes and omits
timestamps, machine paths and environment-dependent community labels.

`check` uses only the standard library and compares source hashes and graph
integrity. `build --check` also reruns extraction and compares the full artifact;
CI runs both checks on Linux, macOS and Windows. Never edit the JSON manually.

## Scope and privacy

Only tracked regular `.py` files are copied into an isolated temporary input tree.
Untracked and ignored files, home directories, ledgers, transcripts and credentials
are not scanned. Symlink sources are rejected. Exported fields are limited to
declarations, source locations and extracted relationships; code bodies and literal
values are not embedded. Review tracked source paths and identifiers before publishing.

The graph does not cover Markdown links, client settings, shell/subprocess dispatch,
SQL, CI workflows or dynamic Python resolution. Static call coverage is incomplete.
Use targeted source inspection for these blind spots; an empty result does not
prove unused code. This snapshot describes the harness itself. Consumer projects
should maintain a graph of their own source, with their own coverage and rebuild rules.
