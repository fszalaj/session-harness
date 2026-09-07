#!/usr/bin/env python3
"""Public graph input boundaries, freshness and reproducibility contracts."""
import copy
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

import code_graph as graph


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "--quiet")
        (self.root / "module.py").write_text("import helper\ndef public_symbol():\n    return 1\n", encoding="utf-8")
        (self.root / "helper.py").write_text("def helper():\n    pass\n", encoding="utf-8")
        self.git("add", "module.py", "helper.py")

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def snapshot(self):
        data = {"graph": {"sources": graph.manifest(graph.sources(self.root))},
                "nodes": [], "links": []}
        data["content_sha256"] = graph.digest(data)
        path = self.root / graph.SNAPSHOT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(graph.serialize(data), encoding="utf-8")
        return path

    def test_untracked_and_ignored_sources_are_not_read(self):
        (self.root / "private.py").write_text("PRIVATE_SENTINEL", encoding="utf-8")
        (self.root / ".gitignore").write_text("local/\n", encoding="utf-8")
        (self.root / "local").mkdir()
        (self.root / "local/secret.py").write_text("PRIVATE_SENTINEL", encoding="utf-8")
        self.assertEqual(set(graph.sources(self.root)), {"module.py", "helper.py"})

    def test_stale_edit_add_and_delete_are_detected(self):
        path = self.snapshot()
        original = (self.root / "module.py").read_bytes()
        (self.root / "module.py").write_bytes(original + b"# change\n")
        with self.assertRaisesRegex(ValueError, "Stale"):
            graph.load(self.root)
        (self.root / "module.py").write_bytes(original)
        graph.load(self.root)
        (self.root / "new.py").write_bytes(b"pass\n")
        self.git("add", "new.py")
        with self.assertRaisesRegex(ValueError, "Stale"):
            graph.load(self.root)
        self.snapshot()
        (self.root / "helper.py").unlink()
        with self.assertRaisesRegex(ValueError, "Stale"):
            graph.load(self.root)
        self.assertTrue(path.is_file())

    def test_line_endings_do_not_cause_platform_drift(self):
        self.snapshot()
        path = self.root / "module.py"
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        graph.load(self.root)

    def test_tampered_snapshot_is_rejected(self):
        path = self.snapshot()
        data = graph.load(self.root)
        data["nodes"].append({"id": "invented"})
        path.write_text(graph.serialize(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "content changed"):
            graph.load(self.root)

    def test_symlink_source_is_rejected(self):
        path = self.root / "module.py"
        path.unlink()
        try:
            path.symlink_to(self.root / "helper.py")
        except OSError:
            self.skipTest("Symlinks unavailable for this account")
        with self.assertRaisesRegex(ValueError, "Symlink"):
            graph.sources(self.root)

    def test_queries_and_ambiguous_module(self):
        data = {"nodes": [{"id": "module:a.py", "type": "module", "source_file": "a.py", "label": "a.py"},
                          {"id": "module:sub/a.py", "type": "module", "source_file": "sub/a.py"},
                          {"id": "extmodule:os"}],
                "links": [{"source": "module:a.py", "target": "extmodule:os", "relation": "imports"}]}
        self.assertEqual(graph.query(data, "imports", "a.py"), [{"id": "extmodule:os"}])
        self.assertEqual(len(graph.query(data, "find", "a.py")), 2)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            graph.query(data, "importers", ".py")

    def test_real_extractor_repeatability_and_private_exclusion(self):
        if importlib.util.find_spec("gateway") is None:
            self.skipTest("Optional graph rebuild dependencies are not installed")
        (self.root / "private.py").write_text("def PRIVATE_SENTINEL(): pass\n", encoding="utf-8")
        first = graph.build(self.root)
        self.assertEqual(first, graph.build(self.root))
        self.assertIn("public_symbol", graph.serialize(first))
        self.assertNotIn("PRIVATE_SENTINEL", graph.serialize(first))
        self.assertNotIn(str(self.root), graph.serialize(first))
        self.assertTrue(graph.query(first, "importers", "helper.py"))
        altered = copy.deepcopy(first)
        altered["nodes"].pop()
        self.assertNotEqual(graph.digest(first), graph.digest(altered))

    def test_script_directory_imports_reach_real_files(self):
        if importlib.util.find_spec("gateway") is None:
            self.skipTest("Optional graph rebuild dependencies are not installed")
        scripts = self.root / "skills/session-harness/scripts"
        scripts.mkdir(parents=True)
        (scripts / "entry.py").write_text("from quota import Ledger\n", encoding="utf-8")
        (scripts / "quota.py").write_text("class Ledger: pass\n", encoding="utf-8")
        self.git("add", "skills")
        data = graph.build(self.root)
        matches = graph.query(data, "importers", "skills/session-harness/scripts/quota.py")
        self.assertEqual([n["source_file"] for n in matches], ["skills/session-harness/scripts/entry.py"])
        (scripts / "quota.py").write_text("invalid python !!!\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "invalid Python"):
            graph.build(self.root)


if __name__ == "__main__":
    unittest.main()
