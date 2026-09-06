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
for test in tests:
    print(test.relative_to(ROOT), flush=True)
    result = subprocess.run([sys.executable, str(test)], cwd=ROOT)
    if result.returncode:
        raise SystemExit(result.returncode)
