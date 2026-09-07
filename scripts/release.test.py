"""Verify release archives use committed public files and stable bytes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

SPEC = importlib.util.spec_from_file_location("release_builder", Path(__file__).with_name("release.py"))
MODULE = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(MODULE)


class BuildTests(unittest.TestCase):
    def test_committed_only_portable_and_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); repo = root / "repo"; repo.mkdir()
            def git(*args):
                return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL)
            git("init"); git("config", "user.name", "Release Test"); git("config", "user.email", "release@example.invalid")
            for name, content in {"skills/session-harness/VERSION": "0.1.0\n", "profile/AGENTS.md": "# Public\n"}.items():
                p = repo / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content)
            git("add", "."); git("commit", "-m", "Fixture")
            (repo / "private-setup.json").write_text("not for publication")
            (repo / "profile/AGENTS.md").write_text("uncommitted owner rules")
            first = MODULE.build(repo, "HEAD", root / "first")
            second = MODULE.build(repo, "HEAD", root / "second")
            self.assertEqual(first["sha256"], second["sha256"])
            with zipfile.ZipFile(first["archive"]) as bundle:
                self.assertFalse(any("private" in name for name in bundle.namelist()))
                self.assertEqual(bundle.read("session-harness-0.1.0/profile/AGENTS.md"), b"# Public\n")
                self.assertEqual(json.loads(bundle.read("session-harness-0.1.0/RELEASE.json"))["commit"], first["commit"])


if __name__ == "__main__":
    unittest.main()
