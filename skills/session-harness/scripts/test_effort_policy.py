"""Preference and rendered native profiles agree without changing public sources."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import effort_policy
import harness
import auto_install


class EffortPolicyTests(unittest.TestCase):
    def test_runtime_precedence_validation_and_capability_ceiling(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            home = Path(directory)
            path = home / effort_policy.RELATIVE_PATH
            path.parent.mkdir(parents=True)
            with patch.object(Path, 'home', return_value=home):
                self.assertEqual(effort_policy.preference(), 'high')
                for value in ('low', 'medium', 'high'):
                    temporary = path.with_suffix('.tmp')
                    temporary.write_text(value + '\n')
                    os.replace(temporary, path)
                    for role in ('planner', 'worker', 'reviewer'):
                        self.assertEqual(harness.select_effort(['low', 'medium', 'high', 'max'], role), value)
                path.write_text('medium\n')
                self.assertEqual(harness.select_effort(['low', 'high'], 'worker'), 'low')
                with self.assertRaises(harness.HarnessError):
                    harness.select_effort(['high'], 'planner')
                with patch.dict(os.environ, {effort_policy.ENV: 'high'}):
                    self.assertEqual(effort_policy.preference(), 'high')
                    self.assertEqual(effort_policy.preference(home), 'medium')
                for invalid in ('', ' ', 'xhigh', 'medium\nhigh', 'MEDIUM'):
                    path.write_text(invalid)
                    with self.assertRaises(harness.HarnessError):
                        harness.select_effort(['medium', 'high'], 'worker')
                    with patch.dict(os.environ, {effort_policy.ENV: invalid}):
                        with self.assertRaises(ValueError):
                            effort_policy.preference()
                path.unlink()
                path.mkdir()
                with self.assertRaises(ValueError):
                    effort_policy.preference(home)

    def test_render_is_idempotent_and_preserves_prose(self):
        for provider, source in [('codex', b'model_reasoning_effort = "high"\n# medium high low\n'),
                                 ('claude', b'---\neffort: high\n---\nChoose high explicitly.\n')]:
            rendered = effort_policy.render_profile(source, provider, 'medium')
            self.assertEqual(effort_policy.render_profile(rendered, provider, 'medium'), rendered)
            self.assertEqual(source.splitlines()[-1], rendered.splitlines()[-1])
            for bad in (b'', source + source):
                with self.assertRaises(ValueError):
                    effort_policy.render_profile(bad, provider, 'medium')

    def test_install_baseline_and_preflight_use_target_home(self):
        root = Path(__file__).resolve().parents[3]
        spec = importlib.util.spec_from_file_location('effort_installer', root / 'scripts/install-agent-profile.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {effort_policy.ENV: 'low'}):
            home = Path(directory)
            path = home / effort_policy.RELATIVE_PATH
            path.parent.mkdir(parents=True)
            path.write_text('medium\n')
            public, _ = installer.release_sources(root)
            local, _ = installer.release_sources(root, home=home)
            for name in public:
                if name.startswith(('native/codex/', 'native/claude/')):
                    self.assertEqual(local[name]['content'], effort_policy.render_profile(public[name]['content'], name.split('/')[1], 'medium'))
                else:
                    self.assertEqual(public[name], local[name])
            with patch.object(auto_install, 'read_json', return_value={'repository': auto_install.releases.REPOSITORY, 'version': 'fixture'}), \
                    patch.object(auto_install, 'installer', return_value=installer), \
                    patch.object(installer, 'install_release'):
                _, baseline, digest = auto_install.baseline(home, root, {'version': 'fixture'})
            self.assertEqual(baseline, local)
            self.assertEqual(digest, installer.release_hash(local))
            preview, internal = installer.plan_install(home, root, False)
            self.assertEqual(preview['source_hash'], installer.release_hash(local))
            path.write_text('low\n')
            with self.assertRaises(installer.InstallationError):
                installer.apply_install(preview, internal)
            self.assertFalse((home / '.agents/AGENTS.md').exists())


if __name__ == '__main__':
    unittest.main()
