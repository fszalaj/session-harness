#!/usr/bin/env python3
"""Run portable harness contracts without model inference."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
skill = ROOT / "skills/session-harness"
if not skill.is_dir():
    skill = ROOT / ".claude/skills/session-harness"
tests = sorted((skill / "scripts").glob("test_*.py"))
if not tests:
    raise SystemExit("Harness tests are missing")
tests.append(ROOT / "scripts/install-agent-profile.test.py")
if (ROOT / "skills/session-harness").is_dir():
    tests.extend([ROOT / "scripts/code_graph.test.py", ROOT / "scripts/release.test.py"])
failures = []
for test in tests:
    print(test.relative_to(ROOT), flush=True)
    result = subprocess.run([sys.executable, str(test)], cwd=ROOT)
    if result.returncode:
        failures.append(test.relative_to(ROOT))

if (ROOT / "skills/session-harness").is_dir():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/code_graph.py"), "check"], cwd=ROOT)
    if result.returncode:
        failures.append(Path("docs/code-graph.json"))

if failures:
    print("Failed test files:", flush=True)
    for test in failures:
        print(f"  {test}", flush=True)
raise SystemExit(1 if failures else 0)
