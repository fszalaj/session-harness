#!/usr/bin/env python3
"""Exercise profile installation against isolated homes and repository fixtures."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest


INSTALLER = Path(__file__).with_name("install-agent-profile.py")
SPEC = importlib.util.spec_from_file_location("install_agent_profile", INSTALLER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@unittest.skipUnless(os.name == "posix", "POSIX symlink/mode contract; checked-copy tests run on Windows")
class ProfileInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="agent-profile-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.repo = self.root / "repo with spaces"
        self.home.mkdir()
        self.instructions = self.repo / "infra/host/agent-profile/AGENTS.md"
        self.skill = self.repo / ".claude/skills/session-harness"
        self.write(self.instructions, "# Shared profile\n")
        self.write(self.skill / "SKILL.md", "---\nname: session-harness\n---\n")
        self.write(self.skill / "scripts/harness.py", "import json, sys\nprint(json.dumps(sys.argv[1:]))\n")

    def write(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def run_installer(self, *args, expected=0):
        completed = subprocess.run(
            [sys.executable, str(INSTALLER), "--home", str(self.home),
             "--repo", str(self.repo), *args], capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, expected, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def test_custom_client_homes_fail_before_profile_mutation(self):
        for variable in ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "COPILOT_HOME"):
            with self.subTest(variable=variable):
                env = dict(os.environ, **{variable: str(self.home / "custom-client")})
                result = subprocess.run([sys.executable, str(INSTALLER), "--home", str(self.home),
                                         "--repo", str(self.repo), "--apply"], env=env,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 1)
                self.assertIn(variable, result.stdout)
                self.assertEqual(list(self.home.iterdir()), [])

    def test_dry_run_preserves_files_and_creates_nothing(self):
        original = self.home / ".codex/AGENTS.md"
        self.write(original, "Keep this exact existing profile.\n")
        before = sorted(str(path.relative_to(self.home)) for path in self.home.rglob("*"))
        result = self.run_installer("--launcher")
        after = sorted(str(path.relative_to(self.home)) for path in self.home.rglob("*"))
        self.assertEqual(before, after)
        self.assertEqual(original.read_text(), "Keep this exact existing profile.\n")
        self.assertEqual(result["mode"], "dry-run")
        self.assertEqual(len(result["changes"]), 12)
        self.assertFalse(any(entry["applied"] for entry in result["changes"]))

    def test_apply_links_canonical_files_and_preserves_unrelated_configuration(self):
        unrelated = self.home / ".codex/config.toml"
        plugin = self.home / ".claude/skills/existing-plugin/SKILL.md"
        self.write(unrelated, 'model = "unchanged-local-choice"\n')
        self.write(plugin, "Unrelated skill\n")
        result = self.run_installer("--apply")
        self.assertEqual(len(result["changes"]), 11)
        release = Path(result["release_root"])
        self.assertTrue(result["release_created"])
        for relative in [".agents/AGENTS.md", ".codex/AGENTS.md", ".claude/CLAUDE.md", ".gemini/GEMINI.md"]:
            path = self.home / relative
            self.assertTrue(path.is_symlink())
            self.assertEqual(path.resolve(), release / "AGENTS.md")
        for relative in [".agents/skills/session-harness", ".codex/skills/session-harness",
                         ".claude/skills/session-harness", ".gemini/config/skills/session-harness"]:
            self.assertEqual((self.home / relative).resolve(), release / "session-harness")
        self.assertEqual(os.readlink(self.home / ".codex/AGENTS.md"), str(self.home.resolve() / ".agents/AGENTS.md"))
        self.assertEqual(unrelated.read_text(), 'model = "unchanged-local-choice"\n')
        self.assertEqual(plugin.read_text(), "Unrelated skill\n")
        self.assertNotIn("backup_root", result)

    def test_exact_file_backup_is_private_and_repeat_is_idempotent(self):
        previous = self.home / ".codex/AGENTS.md"
        self.write(previous, "Original\nwith unusual spacing.  \n")
        previous.chmod(0o640)
        first = self.run_installer("--apply", "--launcher")
        backup_root = Path(first["backup_root"])
        backup = backup_root / ".codex/AGENTS.md"
        self.assertEqual(backup.read_bytes(), b"Original\nwith unusual spacing.  \n")
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(backup_root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(backup_root.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((backup_root / "manifest.json").stat().st_mode), 0o600)
        snapshots = {path: path.lstat().st_mtime_ns for path in self.home.rglob("*")}
        second = self.run_installer("--apply", "--launcher")
        self.assertEqual(second["changes"], [])
        self.assertEqual(len(second["unchanged"]), 12)
        self.assertFalse(second["release_created"])
        self.assertEqual(first["source_hash"], second["source_hash"])
        self.assertNotIn("backup_root", second)
        self.assertEqual(snapshots, {path: path.lstat().st_mtime_ns for path in self.home.rglob("*")})

    def test_broken_and_live_symlinks_keep_their_literal_backup_targets(self):
        broken = self.home / ".claude/CLAUDE.md"
        broken.parent.mkdir()
        broken.symlink_to("../missing-profile.md")
        live = self.home / ".gemini/GEMINI.md"
        self.write(self.home / "old-profile.md", "Previous source\n")
        live.parent.mkdir()
        live.symlink_to("../old-profile.md")
        result = self.run_installer("--apply")
        backup = Path(result["backup_root"])
        self.assertEqual(os.readlink(backup / ".claude/CLAUDE.md"), "../missing-profile.md")
        self.assertEqual(os.readlink(backup / ".gemini/GEMINI.md"), "../old-profile.md")
        self.assertEqual(broken.resolve(), Path(result["release_root"]) / "AGENTS.md")
        self.assertEqual(live.resolve(), Path(result["release_root"]) / "AGENTS.md")
        self.assertEqual((self.home / "old-profile.md").read_text(), "Previous source\n")

    def test_new_conflict_uses_a_distinct_backup_without_overwriting_history(self):
        previous = self.home / ".codex/AGENTS.md"
        self.write(previous, "First profile\n")
        first = self.run_installer("--apply")
        previous.unlink()
        self.write(previous, "Later profile\n")
        second = self.run_installer("--apply")
        self.assertNotEqual(first["backup_root"], second["backup_root"])
        self.assertEqual((Path(first["backup_root"]) / ".codex/AGENTS.md").read_text(), "First profile\n")
        self.assertEqual((Path(second["backup_root"]) / ".codex/AGENTS.md").read_text(), "Later profile\n")

    def test_real_directory_conflict_fails_before_any_managed_change(self):
        existing = self.home / ".claude/skills/session-harness/SKILL.md"
        self.write(existing, "An existing user-maintained directory\n")
        result = self.run_installer("--apply", expected=1)
        self.assertIn("Managed leaf is a directory", result["error"])
        self.assertFalse((self.home / ".agents").exists())
        self.assertFalse((self.home / ".local").exists())
        self.assertEqual(existing.read_text(), "An existing user-maintained directory\n")

    def test_inaccessible_parent_and_missing_source_fail_without_mutation(self):
        self.write(self.home / ".codex", "A conflicting regular file\n")
        result = self.run_installer("--apply", expected=1)
        self.assertIn("Parent is not an accessible directory", result["error"])
        self.assertFalse((self.home / ".agents").exists())
        (self.home / ".codex").unlink()
        self.instructions.unlink()
        result = self.run_installer("--apply", expected=1)
        self.assertIn("Missing profile instructions", result["error"])
        self.assertEqual(list(self.home.iterdir()), [])

    def test_native_definitions_and_launcher_forward_arguments_without_a_shell(self):
        definition_root = self.repo / "infra/host/agent-profile"
        self.write(definition_root / "codex-agents/worker.toml", 'name = "Worker"\n')
        self.write(definition_root / "claude-agents/reviewer.md", "Reviewer\n")
        result = self.run_installer("--apply", "--launcher")
        self.assertEqual(len(result["changes"]), 14)
        release = Path(result["release_root"])
        self.assertEqual((self.home / ".codex/agents/worker.toml").resolve(), release / "native/codex/worker.toml")
        self.assertEqual((self.home / ".claude/agents/reviewer.md").resolve(), release / "native/claude/reviewer.md")
        launcher = self.home / ".local/bin/ai-session"
        self.assertEqual(stat.S_IMODE(launcher.stat().st_mode), 0o755)
        payload = "Prompt with spaces, '$HOME', `touch forbidden`, and $(commands)."
        completed = subprocess.run(
            [str(launcher), "claude", "--role", "worker", "--", payload],
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(json.loads(completed.stdout), ["launch", "claude", "--execute", "--role", "worker", "--", payload])
        completed = subprocess.run([str(launcher), "codex", "--", "resume", "--last"],
                                   capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(completed.stdout), ["launch", "codex", "--execute", "--", "resume", "--last"])
        for arguments in (["inventory"], ["budget", "add", "codex", "5", "--id", payload],
                          ["usage", "status", "claude"]):
            completed = subprocess.run([str(launcher), *arguments], capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(completed.stdout), arguments)

    def test_concurrent_managed_change_is_preserved(self):
        target = self.home / ".codex/AGENTS.md"
        self.write(target, "Before preflight\n")
        result, internal = MODULE.plan_install(self.home, self.repo, False)
        target.write_text("Another session changed this\n")
        with self.assertRaisesRegex(MODULE.InstallationError, "changed after preflight"):
            MODULE.apply_install(result, internal)
        self.assertEqual(target.read_text(), "Another session changed this\n")
        self.assertFalse((self.home / ".agents").exists())
        self.assertFalse((self.home / ".local").exists())


    def test_release_survives_source_removal_and_excludes_unrelated_files(self):
        legal_names = ("LICENSE", "NOTICE")
        for name in legal_names:
            self.write(self.skill / name, "Harness legal artifact: " + name)
        self.write(self.repo / "LICENSE", "Unrelated application license")
        self.write(self.repo / "private-project-context.md", "Never install unrelated files\n")
        self.write(self.repo / "infra/host/agent-profile/other.md", "Not a canonical profile source\n")
        self.write(self.skill / "scripts/__pycache__/harness.cpython-313.pyc", "bytecode cache")
        self.write(self.skill / "scripts/orphan.pyc", "orphan bytecode")
        self.write(self.skill / "references/client.md", "Retain useful harness reference\n")
        result = self.run_installer("--apply", "--launcher")
        release = Path(result["release_root"])
        self.assertEqual(release.name, result["source_hash"])
        self.assertEqual(len(result["source_hash"]), 64)
        files = {str(path.relative_to(release)) for path in release.rglob("*") if path.is_file()}
        self.assertEqual(files, {"AGENTS.md", "session-harness/SKILL.md",
                                 "session-harness/scripts/harness.py", "session-harness/references/client.md"}
                         | set(legal_names) | {"session-harness/" + name for name in legal_names})
        self.assertFalse(release.stat().st_mode & 0o222)
        self.assertFalse((release / "AGENTS.md").stat().st_mode & 0o222)
        shutil.rmtree(self.repo)
        for name in legal_names:
            for path in (release / name, release / "session-harness" / name):
                self.assertEqual(path.read_text(), "Harness legal artifact: " + name)
        self.assertEqual((self.home / ".claude/CLAUDE.md").read_text(), "# Shared profile\n")
        self.assertTrue((self.home / ".codex/skills/session-harness/SKILL.md").is_file())
        completed = subprocess.run([str(self.home / ".local/bin/ai-session"), "codex", "--", "resume", "--last"],
                                   capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(completed.stdout), ["launch", "codex", "--execute", "--", "resume", "--last"])

    def test_standalone_legal_artifacts_and_incomplete_source_protection(self):
        self.write(self.repo / "profile/AGENTS.md", "# Standalone profile\n")
        shutil.copytree(self.skill, self.repo / "skills/session-harness")
        for name in ("LICENSE", "NOTICE"):
            self.write(self.repo / name, "Standalone legal artifact: " + name)
        result = self.run_installer("--apply")
        release = Path(result["release_root"])
        for name in ("LICENSE", "NOTICE"):
            for path in (release / name, release / "session-harness" / name):
                self.assertEqual(path.read_text(), "Standalone legal artifact: " + name)
        (self.repo / "NOTICE").unlink()
        denied = self.run_installer("--apply", expected=1)
        self.assertIn("licensing artifact", denied["error"])
        self.assertEqual((self.home / ".agents/AGENTS.md").resolve(), release / "AGENTS.md")

    def test_source_change_creates_a_new_release_and_preserves_the_old_release(self):
        first = self.run_installer("--apply", "--launcher")
        self.instructions.write_text("# Revised profile\n")
        second = self.run_installer("--apply", "--launcher")
        self.assertNotEqual(first["source_hash"], second["source_hash"])
        self.assertEqual((Path(first["release_root"]) / "AGENTS.md").read_text(), "# Shared profile\n")
        self.assertEqual((Path(second["release_root"]) / "AGENTS.md").read_text(), "# Revised profile\n")
        backup = Path(second["backup_root"]) / ".agents/AGENTS.md"
        self.assertEqual(os.readlink(backup), str(Path(first["release_root"]) / "AGENTS.md"))

    def test_corrupted_existing_release_is_not_overwritten_or_relinked(self):
        first = self.run_installer("--apply")
        corrupted = Path(first["release_root"]) / "AGENTS.md"
        corrupted.chmod(0o644)
        corrupted.write_text("Unexpected changed release\n")
        result = self.run_installer("--apply", expected=1)
        self.assertIn("Installed release was modified", result["error"])
        self.assertEqual(corrupted.read_text(), "Unexpected changed release\n")
        self.assertFalse((self.home / ".local/state/session-harness").exists())


class RepositoryProfileContractTests(unittest.TestCase):
    def test_shared_entrypoints_and_native_roles_keep_the_profile_contract(self):
        repo = INSTALLER.resolve().parents[1]
        canonical = repo / "AGENTS.md"
        instructions = canonical.read_text()
        self.assertLess(len(instructions.splitlines()), 200, "Move operational detail into linked procedures")
        self.assertLess(len(instructions), 12_000, "Keep the session entrypoint within its context budget")
        for name in ("CLAUDE.md", "GEMINI.md"):
            entrypoint = repo / name
            with self.subTest(entrypoint=name):
                if os.name == 'nt' and not entrypoint.is_symlink():
                    self.assertEqual(entrypoint.read_text().strip(), 'AGENTS.md')
                    continue
                self.assertTrue(entrypoint.is_symlink(), "Edit AGENTS.md without replacing the client symlink")
                self.assertFalse(Path(os.readlink(entrypoint)).is_absolute(), "Repository links must survive relocation")
                self.assertEqual(entrypoint.resolve(strict=True), canonical.resolve(strict=True))
        skill_link = repo / ".agents/skills"
        if os.name == 'nt' and not skill_link.is_symlink():
            self.assertIn(skill_link.read_text().strip(), {'../.claude/skills', '../skills'})
        else:
            self.assertTrue(skill_link.is_symlink())
            self.assertEqual(skill_link.resolve(strict=True), (repo / ".claude/skills").resolve(strict=True))
        profile = repo / "profile"
        if not profile.is_dir():
            profile = repo / "infra/host/agent-profile"
        skill = repo / 'skills/session-harness'
        if not skill.is_dir(): skill = repo / '.claude/skills/session-harness'
        for source in (profile / "AGENTS.md", skill / "SKILL.md"):
            self.assertTrue(source.is_file(), f"Missing canonical installation source: {source}")
            self.assertTrue(source.read_text().strip(), f"Empty canonical installation source: {source}")

        codex_roles = sorted((profile / "codex-agents").glob("*.toml"))
        claude_roles = sorted((profile / "claude-agents").glob("*.md"))
        self.assertTrue(codex_roles, "Codex native worker roles are missing")
        self.assertTrue(claude_roles, "Claude native worker roles are missing")
        for role in codex_roles:
            with self.subTest(role=role.name):
                config = tomllib.loads(role.read_text())
                self.assertNotIn("model", config, "Inherit the runtime-selected model instead of pinning it")
                self.assertIn(config.get("model_reasoning_effort"), {"low", "medium", "high"})
        for role in claude_roles:
            with self.subTest(role=role.name):
                sections = role.read_text().split("---", 2)
                self.assertEqual(len(sections), 3, "Native Claude roles require YAML frontmatter")
                self.assertFalse(sections[0].strip())
                metadata = dict(line.split(":", 1) for line in sections[1].splitlines() if ":" in line)
                model = metadata.get("model", "inherit").strip().strip("\"'")
                effort = metadata.get("effort", "").strip().strip("\"'")
                self.assertEqual(model, "inherit", "Inherit the runtime-selected model instead of pinning it")
                self.assertIn(effort, {"low", "medium", "high"})


class CheckedCopyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='profile copy ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / 'home'; self.home.mkdir()
        self.repo = self.root / 'source'
        (self.repo / 'profile').mkdir(parents=True)
        (self.repo / 'profile/AGENTS.md').write_text('# User rules\n')
        self.skill = self.repo / 'skills/session-harness'
        (self.skill / 'scripts').mkdir(parents=True)
        (self.skill / 'SKILL.md').write_text('name: session-harness\n')
        (self.skill / 'scripts/harness.py').write_text('import json,sys; print(json.dumps(sys.argv[1:]))')
        (self.repo / 'LICENSE').write_text('Apache License 2.0')
        (self.repo / 'NOTICE').write_text('Copyright Example')

    def install(self):
        result, internal = MODULE.plan_install(self.home, self.repo, True, 'copy')
        MODULE.apply_install(result, internal)
        return result

    def test_real_copy_install_idempotence_legal_and_source_removal(self):
        result = self.install()
        self.assertTrue(result['changes'])
        target = self.home / '.codex/skills/session-harness'
        self.assertFalse(target.is_symlink())
        self.assertEqual((target / 'LICENSE').read_text(), 'Apache License 2.0')
        self.assertEqual((self.home / '.codex/AGENTS.md').read_text(), '# User rules\n')
        again, _ = MODULE.plan_install(self.home, self.repo, True, 'copy')
        self.assertEqual(again['changes'], [])
        backups = list((self.home / '.local/state/session-harness/backups').iterdir())
        self.install()
        self.assertEqual(list((self.home / '.local/state/session-harness/backups').iterdir()), backups)
        shutil.rmtree(self.repo)
        entry = self.home / ('.local/bin/ai-session.py' if os.name == 'nt' else '.local/bin/ai-session')
        args = ['', 'a b', 'λ', '"quotes"', '&|<>%!', '`literal`']
        output = subprocess.check_output([sys.executable, str(entry), 'inventory', *args], text=True)
        self.assertEqual(json.loads(output), ['inventory', *args])

    def test_launcher_in_process_path_preserves_output_imports_and_exit_status(self):
        runtime = self.skill / 'scripts/harness.py'
        (runtime.parent / 'sibling.py').write_text('MESSAGE = "from sibling"')
        runtime.write_text('import sibling,sys; print(sibling.MESSAGE,flush=True); raise SystemExit(7)')
        launcher = self.root / 'portable-launcher.py'
        content = MODULE.launcher_content(runtime).decode().replace("if os.name == 'nt':", 'if True:')
        launcher.write_text(content)
        result = subprocess.run([sys.executable, str(launcher), 'inventory'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout.strip(), 'from sibling')

    def test_modified_copy_is_preserved(self):
        self.install()
        target = self.home / '.codex/AGENTS.md'; target.write_text('local edit')
        with self.assertRaisesRegex(MODULE.InstallationError, 'modified'):
            MODULE.plan_install(self.home, self.repo, True, 'copy')
        self.assertEqual(target.read_text(), 'local edit')

    def test_source_upgrade_removes_only_unchanged_managed_files(self):
        obsolete = self.skill / 'old.txt'; obsolete.write_text('old')
        self.install(); obsolete.unlink()
        result = self.install()
        self.assertTrue(any(row['action'] == 'delete' for row in result['changes']))
        self.assertFalse((self.home / '.agents/skills/session-harness/old.txt').exists())

    def test_preview_race_preserves_modified_destination(self):
        result, internal = MODULE.plan_install(self.home, self.repo, True, 'copy')
        path = self.home / '.codex/AGENTS.md'; path.parent.mkdir(); path.write_text('racing edit')
        with self.assertRaises(MODULE.InstallationError): MODULE.apply_install(result, internal)
        self.assertEqual(path.read_text(), 'racing edit')

    @unittest.skipUnless(os.name == 'nt', 'Native PowerShell argument preservation')
    def test_powershell_launcher_preserves_empty_quotes_and_metacharacters(self):
        self.install()
        pwsh = shutil.which('pwsh')
        self.assertIsNotNone(pwsh, 'Windows CI must provide PowerShell 7.3+')
        launcher = self.home / '.local/bin/ai-session.ps1'
        output = subprocess.check_output([pwsh, '-NoProfile', '-File', str(launcher), 'inventory',
                                          '', 'a b', '"quoted"', '&|<>%!', 'λ'], text=True, encoding='utf-8')
        self.assertEqual(json.loads(output), ['inventory', '', 'a b', '"quoted"', '&|<>%!', 'λ'])


if __name__ == "__main__":
    unittest.main()
