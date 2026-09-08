#!/usr/bin/env python3
"""Contract tests use synthetic future model IDs and never invoke paid inference."""

import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import harness
from quota import Ledger


def model(ident, rank=0, description="", efforts=None):
    return {"id": ident, "rank": rank, "description": description,
            "efforts": efforts or ["low", "medium", "high", "max"]}


class SessionTests(unittest.TestCase):
    def test_explicit_session_overrides_inherited_markers(self):
        result = harness.detect_session("claude", {"CODEX_THREAD_ID": "redacted"})
        self.assertEqual(result["provider"], "claude")

    def test_ambiguous_environment_is_not_guessed(self):
        result = harness.detect_session(env={"CODEX_THREAD_ID": "redacted", "CLAUDECODE": "1"}, ancestry=["codex"])
        self.assertEqual(result["status"], "ambiguous")
        self.assertIsNone(result["provider"])

    def test_launcher_identity_survives_cross_provider_ancestry(self):
        result = harness.detect_session(env={harness.SESSION_MARKER: "claude", "CODEX_THREAD_ID": "redacted", "CLAUDECODE": "1"})
        self.assertEqual(result["provider"], "claude")
        self.assertEqual(result["status"], "verified")

    def test_no_identity_from_installed_clis_or_generic_node(self):
        self.assertEqual(harness.detect_session(env={}, ancestry=["python3", "node", "zsh"])["status"], "unknown")

    def test_nearest_known_ancestor(self):
        self.assertEqual(harness.detect_session(env={}, ancestry=["zsh", "agy", "codex"])["provider"], "antigravity")

    def test_values_are_never_in_identity_evidence(self):
        result = harness.detect_session(env={"CODEX_THREAD_ID": "private-session"})
        self.assertNotIn("private-session", json.dumps(result))


class ModelTests(unittest.TestCase):
    def test_numeric_generation_beats_lexical_order_and_cheap_old_models(self):
        models = [model("gpt-99.9-budget", 0, "Fast and affordable"), model("gpt-99.10-leader", 1, "Most capable")]
        planner, worker = harness.select_models(models, "gpt")
        self.assertEqual(planner["model"], "gpt-99.10-leader")
        self.assertEqual(worker["model"], planner["model"])
        self.assertEqual(worker["effort"], "medium")

    def test_current_generation_affordable_variant(self):
        models = [model("gpt-99.10-leader", 0, "Most capable"), model("gpt-99.10-scout", 1, "Fast and affordable")]
        self.assertEqual(harness.select_models(models, "gpt")[1]["model"], "gpt-99.10-scout")

    def test_infeasible_budget_variant_uses_current_flagship_worker(self):
        models = [model("gpt-99.10-leader", 0, "Most capable"), model("gpt-99.10-budget", 1, "Affordable", ["high"])]
        self.assertEqual(harness.select_models(models, "gpt")[1]["model"], "gpt-99.10-leader")

    def test_catalog_order_does_not_establish_planner_capability(self):
        models = [model("gpt-99.10-first", 0), model("gpt-99.10-second", 1)]
        with self.assertRaises(harness.HarnessError) as raised:
            harness.select_models(models, "gpt")
        self.assertEqual(raised.exception.status, "capability_unverified")
        self.assertIn("manager", str(raised.exception))

    def test_unique_current_candidate_does_not_claim_superiority_over_older_tier(self):
        planner, worker = harness.select_models([model("gpt-99.9-flagship", description="Most capable"), model("gpt-99.10-new-tier")], "gpt")
        self.assertEqual(planner["model"], "gpt-99.10-new-tier")
        self.assertIn("no superiority", planner["basis"])
        self.assertEqual(worker["selection_status"], "task_fit_verification_required")

    def test_maximum_advertised_effort(self):
        self.assertEqual(harness.select_effort(["low", "high", "ultra"], "planner"), "high")

    def test_codex_launch_keeps_delegation_with_harness_manager(self):
        planner, worker = harness.select_models([model("gpt-99.10-test", efforts=["low", "medium", "high", "max", "ultra"])], "gpt")
        result = harness.launch_plan("codex", "planner", {"executable": "codex", "planner": planner})
        self.assertIn('model_reasoning_effort="max"', result["argv"])
        self.assertIn('plan_mode_reasoning_effort="max"', result["argv"])
        self.assertEqual(worker["effort"], "medium")

    def test_orchestration_mode_alone_cannot_establish_reasoning_effort(self):
        with self.assertRaises(harness.HarnessError) as raised:
            harness.select_effort(["ultra"], "planner")
        self.assertEqual(raised.exception.status, "unsupported_capability")

    def test_unknown_effort_does_not_silently_downgrade(self):
        with self.assertRaises(harness.HarnessError) as raised:
            harness.select_effort(["medium", "future-effort"], "planner")
        self.assertEqual(raised.exception.status, "unsupported_capability")

    def test_single_effort_does_not_claim_nonmax_worker(self):
        with self.assertRaises(harness.HarnessError):
            harness.select_effort(["high"], "worker")

    def test_undocumented_generation_does_not_get_invented(self):
        with self.assertRaises(harness.HarnessError):
            harness.select_models([model("gpt-future-alias")], "gpt")

    def test_newer_flash_precedes_older_pro_and_other_vendors(self):
        raw = "Fetching available models...\ngemini-99.10-flash-high\tNewest Flash\ngemini-99.10-flash-medium\tNewest Flash\ngemini-99.9-pro-high\tOlder Pro\ngemini-99.9-pro-low\tOlder Pro\nclaude-unknown\tOther vendor\n"
        planner, worker = harness.select_models(harness.parse_agy_catalog(raw), "gemini")
        self.assertEqual(planner["model"], "gemini-99.10-flash-high")
        self.assertEqual(worker["model"], "gemini-99.10-flash-medium")

    def test_hidden_cache_models_excluded(self):
        raw = [{"slug": "gpt-100-hidden", "visibility": "hide"},
               {"slug": "gpt-99-visible", "visibility": "list", "supported_reasoning_levels": [{"effort": "high"}]}]
        self.assertEqual([item["id"] for item in harness.codex_models(raw, cache=True)], ["gpt-99-visible"])


class DiscoveryTests(unittest.TestCase):
    def cache(self, stamp):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "catalog.json"
        path.write_text(json.dumps({"fetched_at": stamp, "models": []}))
        return path

    def test_stale_cache_rejected_even_when_file_mtime_is_current(self):
        now = dt.datetime(2099, 1, 3, tzinfo=dt.timezone.utc)
        path = self.cache("2099-01-01T00:00:00Z")
        with self.assertRaises(harness.HarnessError) as raised:
            harness.cached_codex(path, now)
        self.assertEqual(raised.exception.status, "stale_catalog")

    def test_future_cache_rejected(self):
        with self.assertRaises(harness.HarnessError):
            harness.cached_codex(self.cache("2099-01-04T00:00:00Z"), dt.datetime(2099, 1, 3, tzinfo=dt.timezone.utc))

    def test_fresh_cache_accepts_nanosecond_timestamp(self):
        now = dt.datetime(2099, 1, 3, tzinfo=dt.timezone.utc)
        self.assertEqual(harness.cached_codex(self.cache("2099-01-02T23:00:00.123456789Z"), now)[0], [])

    def test_missing_cli_has_no_models_or_successful_review(self):
        with patch.object(harness.shutil, "which", return_value=None):
            result = harness.discover_provider("antigravity")
        self.assertEqual(result["status"], "missing_cli")
        self.assertNotIn("planner", result)
        self.assertEqual(result["review"]["status"], "missing_cli")

    def test_live_codex_catalog_pagination(self):
        def entry(ident):
            return {"model": ident, "supportedReasoningEfforts": [{"reasoningEffort": level} for level in ("low", "medium", "high")]}
        class RPC:
            calls = []
            def __init__(self, executable):
                pass
            def notify(self, method):
                self.calls.append((method, None))
            def request(self, method, params):
                self.calls.append((method, params))
                if method == "initialize":
                    return {}
                if method == "account/read":
                    return {"account": {"type": "chatgpt", "planType": "pro"}}
                if params.get("cursor"):
                    return {"data": [entry("gpt-99.10-leader")], "nextCursor": None}
                return {"data": [entry("gpt-99.9-leader")], "nextCursor": "page-two"}
            def close(self):
                pass
        with patch.object(harness, "CodexRPC", RPC), patch.object(harness, "codex_review_capability", return_value={"status": "available"}):
            result = harness.discover_codex("mock-codex")
        self.assertEqual(result["planner"]["model"], "gpt-99.10-leader")
        self.assertIn(("model/list", {"includeHidden": False, "limit": 100, "cursor": "page-two"}), RPC.calls)

    def test_claude_auth_output_excludes_personal_account_fields(self):
        help_text = "--effort <level> Effort (low, medium, high, max)\n--safe-mode --tools --strict-mcp-config --disable-slash-commands --no-session-persistence --permission-mode --mcp-config"
        auth = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "max", "email": "private@example.test", "orgName": "private"}
        with patch.object(harness, "checked", side_effect=[help_text, json.dumps(auth)]), \
                patch("claude_models.discover", return_value={"models": [], "status": "client_selectable_metadata"}):
            result = harness.discover_claude("mock-claude")
        self.assertEqual(result["auth"]["status"], "subscription")
        self.assertNotIn("private", json.dumps(result))
        self.assertIsNone(result["resolved_model"])
        self.assertFalse(result["entitlement_verified"])

    def test_claude_truthy_auth_does_not_probe_models(self):
        auth = {"loggedIn": "true", "authMethod": "private", "apiProvider": "firstParty",
                "subscriptionType": "private"}
        with patch.object(harness, "checked", side_effect=["--effort <level> Effort (low, high)", json.dumps(auth)]), \
                patch("claude_models.discover") as probe:
            result = harness.discover_claude("mock-claude")
        self.assertEqual(result["auth"]["status"], "auth_required")
        self.assertNotIn("private", json.dumps(result))
        probe.assert_not_called()

    def test_claude_concrete_catalog_supersedes_unresolved_aliases(self):
        help_text = "--effort <level> Effort (low, medium, high, max)\n--safe-mode --tools --strict-mcp-config --disable-slash-commands --no-session-persistence --permission-mode --mcp-config"
        auth = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "max"}
        models = [{"id": name, "account_selectable": True,
                   "native_controls": {"reasoning_efforts": ["low", "medium", "high", "max"]}}
                  for name in ["best", "sonnet", "claude-opus-99-9", "claude-fable-99-10[1m]"]]
        with patch.object(harness, "checked", side_effect=[help_text, json.dumps(auth)]), \
                patch("claude_models.discover", return_value={"models": models, "status": "client_selectable_metadata"}):
            result = harness.discover_claude("mock-claude")
        self.assertEqual("claude-fable-99-10[1m]", result["planner"]["model"])
        self.assertEqual("max", result["planner"]["effort"])
        self.assertEqual("claude-fable-99-10[1m]", result["worker"]["model"])
        self.assertEqual("medium", result["worker"]["effort"])
        self.assertFalse(result["entitlement_verified"])


class ExecutionTests(unittest.TestCase):
    def test_bounded_slow_quota_poll_resumes_pipe_drain(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "ready"
            def tick():
                if not marker.exists():
                    marker.touch()
                    time.sleep(0.3)
            child = ("import pathlib,sys,time; "
                     "p=pathlib.Path(sys.argv[1]); "
                     "exec('while not p.exists(): time.sleep(.001)'); "
                     "sys.stdout.write('x'*262144); sys.stdout.flush(); "
                     "sys.stderr.write('y'*262144); sys.stderr.flush()")
            with patch.object(harness.supervision, "Watch") as watch:
                watch.return_value.owner = "fixture-owner"
                watch.return_value.tick.side_effect = tick
                result = harness.run([sys.executable, "-c", child, str(marker)],
                                     quota_service="codex", timeout=4)
            self.assertEqual((0, "x" * 262144, "y" * 262144), result)
            watch.return_value.finish.assert_called_once()

    @unittest.skipUnless(os.name == "posix", "POSIX process/link contract; Windows equivalents are separate")
    def test_final_quota_check_runs_after_cleanup_and_unregister(self):
        events = []
        original_killpg = os.killpg
        def killpg(pid, signum):
            events.append(("signal", signum))
            return original_killpg(pid, signum)
        def finish():
            self.assertFalse(harness._OWNED_PROCESSES)
            events.append(("finish", None))
        with patch.object(harness.supervision, "Watch") as watch, patch.object(harness.os, "killpg", side_effect=killpg):
            watch.return_value.finish.side_effect = finish
            result = harness.run([sys.executable, "-c", "print('complete'); raise SystemExit(7)"],
                                 quota_service="codex")
        self.assertEqual(result, (7, "complete\n", ""))
        self.assertEqual(events[-1], ("finish", None))
        self.assertTrue(any(event[0] == "signal" for event in events))

    @unittest.skipUnless(os.name == "posix", "POSIX process/link contract; Windows equivalents are separate")
    def test_group_signals_precede_reaping(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                start_new_session=True)
        harness.register_process(proc)
        events = []
        original_wait, original_killpg = proc.wait, os.killpg
        def killpg(pid, signum):
            self.assertIsNone(proc.returncode)
            events.append(signum)
            return original_killpg(pid, signum)
        def wait(*args, **kwargs):
            self.assertEqual(events, [harness.signal.SIGTERM, harness.signal.SIGKILL])
            return original_wait(*args, **kwargs)
        try:
            with patch.object(harness.os, "killpg", side_effect=killpg), patch.object(proc, "wait", side_effect=wait):
                code = harness.stop_group(proc)
            self.assertLess(code, 0)
            with patch.object(harness.os, "killpg") as kill:
                self.assertEqual(harness.stop_group(proc), code)
                kill.assert_not_called()
        finally:
            harness.stop_group(proc)
            harness.unregister_process(proc)

    def test_env_preserves_auth_paths_and_removes_api_overrides(self):
        original = {"HOME": "/original", "CODEX_HOME": "/codex", "PATH": "/bin", "OPENAI_API_KEY": "secret", "ANTHROPIC_BASE_URL": "override", "GEMINI_API_KEY": "secret", "CLAUDECODE": "1", "CLAUDE_CODE_EFFORT_LEVEL": "max"}
        clean = harness.child_env(original, leaf=True)
        self.assertEqual(clean["HOME"], "/original")
        self.assertEqual(clean["CODEX_HOME"], "/codex")
        self.assertEqual(clean[harness.LEAF_MARKER], "1")
        self.assertNotIn("OPENAI_API_KEY", clean)
        self.assertNotIn("ANTHROPIC_BASE_URL", clean)
        self.assertNotIn("CLAUDECODE", clean)
        self.assertNotIn("CLAUDE_CODE_EFFORT_LEVEL", clean)

    def test_vertex_adc_overrides_removed_without_redirecting_audited_profiles(self):
        source = {"GOOGLE_GENAI_USE_VERTEXAI": "true", "GOOGLE_CLOUD_PROJECT": "billing-project",
                  "GOOGLE_APPLICATION_CREDENTIALS": "/private/adc.json", "ANTHROPIC_SMALL_FAST_MODEL": "old-model",
                  "HOME": "/audited-home", "CODEX_HOME": "/audited-codex", "CLAUDE_CONFIG_DIR": "/audited-claude"}
        clean = harness.child_env(source)
        self.assertEqual(clean, {"HOME": "/audited-home", "CODEX_HOME": "/audited-codex", "CLAUDE_CONFIG_DIR": "/audited-claude"})

    def test_recursion_guard_precedes_discovery(self):
        with patch.dict(os.environ, {harness.LEAF_MARKER: "1"}), patch.object(harness, "discover_provider") as discover, patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.assertEqual(harness.main(["discover"]), 2)
            self.assertEqual(json.loads(stdout.getvalue())["status"], "recursion_blocked")
        discover.assert_not_called()

    def test_real_subprocess_timeout_reaps_process(self):
        start = time.monotonic()
        with self.assertRaises(harness.HarnessError) as raised:
            harness.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.1)
        self.assertEqual(raised.exception.status, "timeout")
        self.assertLess(time.monotonic() - start, 4)

    @unittest.skipUnless(os.name == "posix", "POSIX process/link contract; Windows equivalents are separate")
    def test_timeout_terminates_descendants_in_exact_process_group(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pids.json"
            script = ("import json,os,pathlib,subprocess,sys,time; "
                      "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
                      "pathlib.Path(sys.argv[1]).write_text(json.dumps([os.getpid(),child.pid])); time.sleep(30)")
            with self.assertRaises(harness.HarnessError):
                harness.run([sys.executable, "-c", script, str(path)], timeout=0.5)
            parent_pid, descendant_pid = json.loads(path.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(parent_pid, 0)
            for _ in range(20):
                status = subprocess.run(["ps", "-p", str(descendant_pid), "-o", "stat="], capture_output=True, text=True).stdout.strip()
                if not status or status.startswith("Z"):
                    break
                time.sleep(0.05)
            self.assertTrue(not status or status.startswith("Z"), "Descendant is still running after timeout")

    def test_literal_stdin_is_not_shell_code(self):
        payload = b"$(touch /tmp/not-created-by-harness) `printf shell`\n"
        result = harness.run([sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"], stdin=payload)
        self.assertEqual(result[1].encode(), payload)

    def test_stdout_callback_receives_final_line_without_newline(self):
        lines = []
        result = harness.run([sys.executable, "-c", "import sys; sys.stdout.write('final event')"], on_stdout_line=lines.append)
        self.assertEqual(lines, ["final event"])
        self.assertEqual(result[1], "final event")

    @unittest.skipUnless(os.name == "posix", "POSIX process/link contract; Windows equivalents are separate")
    def test_sigterm_and_sighup_cleanup_detached_children(self):
        import signal
        for signum in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signum=signum), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "child.pid"
                child = "import os,pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
                code = ("import sys; sys.path.insert(0,sys.argv[1]); import harness\n"
                        "try: harness.run([sys.executable,'-c',sys.argv[2],sys.argv[3]],timeout=30)\n"
                        "except harness.HarnessError: sys.exit(2)\n")
                parent = subprocess.Popen([sys.executable, "-c", code, str(Path(harness.__file__).parent), child, str(path)])
                try:
                    deadline = time.monotonic() + 3
                    while not path.exists() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(path.exists())
                    child_pid = int(path.read_text())
                    parent.send_signal(signum)
                    self.assertEqual(parent.wait(timeout=4), 2)
                    with self.assertRaises(ProcessLookupError):
                        os.kill(child_pid, 0)
                finally:
                    if parent.poll() is None:
                        parent.kill()
                        parent.wait()

    def test_failure_classification_never_becomes_review_approval(self):
        for text, expected in [("quota exceeded", "quota_exhausted"), ("authentication failed", "auth_required"), ("unknown model", "model_unavailable"), ("unknown option", "unsupported_capability"), ("service down", "provider_error")]:
            with self.subTest(text=text):
                self.assertEqual(harness.classify_failure(text), expected)

    def test_unsupported_provider_cannot_launch_leaf(self):
        with self.assertRaises(harness.HarnessError) as raised:
            harness.review("antigravity", b"plan", 1, {"review": {"status": "unsupported_capability"}})
        self.assertEqual(raised.exception.status, "unsupported_capability")

    def test_input_size_is_bounded(self):
        with self.assertRaises(harness.HarnessError) as raised:
            harness.review("claude", b"x" * (harness.MAX_INPUT + 1), 1, {})
        self.assertEqual(raised.exception.status, "input_limit")

    def test_invalid_utf8_is_rejected_before_provider_dispatch(self):
        for provider in harness.PROVIDERS:
            with self.subTest(provider=provider), patch.object(harness, "checked") as checked, self.assertRaises(harness.HarnessError) as raised:
                harness.review(provider, b"invalid \xff", 1, {})
            self.assertEqual(raised.exception.status, "invalid_encoding")
            checked.assert_not_called()

    def test_catalog_access_is_not_subscription_proof_for_codex_or_claude(self):
        capability = {"review": {"status": "available"}, "auth": {"status": "catalog_access"}}
        for provider in ("codex", "claude"):
            with self.subTest(provider=provider), self.assertRaises(harness.HarnessError) as raised:
                harness.review(provider, b"Review artifact", 1, capability)
            self.assertEqual(raised.exception.status, "auth_required")

    def test_launch_forwards_resume_arguments_as_argv(self):
        capability = {"executable": "codex", "planner": {"model": "gpt-99.10-test", "effort": "max"}}
        plan = harness.launch_plan("codex", "planner", capability, ["resume", "--last"])
        self.assertEqual(plan["argv"][-2:], ["resume", "--last"])

    def test_launch_rejects_forwarded_selection_overrides(self):
        capability = {"executable": "codex", "planner": {"model": "gpt-99.10-test", "effort": "max"}}
        for forwarded in (["--model=older"], ["-c", "model=older"], ["--effort", "low"], ["-p"], ["--settings", "{}"]):
            with self.subTest(forwarded=forwarded), self.assertRaises(harness.HarnessError) as raised:
                harness.launch_plan("codex", "planner", capability, forwarded)
            self.assertEqual(raised.exception.status, "conflicting_override")


class ReviewTests(unittest.TestCase):
    def stream(self, **init_changes):
        init = {"type": "system", "subtype": "init", "tools": [], "mcp_servers": [], "model": "claude-current-fixture"}
        init.update(init_changes)
        result = {"type": "result", "subtype": "success", "is_error": False, "result": "One concrete finding."}
        return "\n".join(json.dumps(event) for event in (init, result))

    def test_accepts_only_substantive_isolated_result(self):
        result = harness.validate_claude_review(self.stream())
        self.assertEqual(result["status"], "reviewed")
        self.assertIn("manager", result["verdict"])

    def test_claude_artifact_boundary_and_transmitted_prompt_hashes(self):
        capability = {"review": {"status": "available"}, "auth": {"status": "subscription"},
                      "planner": {"model": "best", "effort": "high"}, "supported_efforts": ["low", "medium", "high"], "executable": "mock-claude"}
        artifact = "Review this plan with UTF-8: zażółć.".encode()
        with patch.object(harness, "checked", return_value=self.stream()) as checked, \
                patch.object(harness, "require_quota"), patch.object(harness, 'require_role', return_value={}):
            result = harness.review("claude", artifact, 1, capability)
        transmitted = checked.call_args.kwargs["stdin"]
        self.assertEqual(transmitted, b"<review-artifact>\n" + artifact + b"\n</review-artifact>")
        self.assertEqual(result["artifact_sha256"], hashlib.sha256(artifact).hexdigest())
        self.assertEqual(result["stdin_sha256"], hashlib.sha256(transmitted).hexdigest())
        self.assertEqual(result["prompt_sha256"], result["stdin_sha256"])

    def test_tools_or_mcp_reject_review(self):
        for change in ({"tools": ["Bash"]}, {"mcp_servers": [{"name": "external"}]}, {"tools": None}):
            with self.subTest(change=change), self.assertRaises(harness.HarnessError) as raised:
                harness.validate_claude_review(self.stream(**change))
            self.assertEqual(raised.exception.status, "isolation_unverified")

    def test_tool_event_rejects_even_with_empty_init(self):
        event = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}}
        with self.assertRaises(harness.HarnessError) as raised:
            harness.validate_claude_review(self.stream() + "\n" + json.dumps(event))
        self.assertEqual(raised.exception.status, "isolation_violation")

    def test_truncated_stream_is_schema_error(self):
        with self.assertRaises(harness.HarnessError) as raised:
            harness.validate_claude_review('{"type":')
        self.assertEqual(raised.exception.status, "schema_error")

    def test_final_error_is_not_success(self):
        events = self.stream().splitlines()
        events[-1] = json.dumps({"type": "result", "subtype": "error", "is_error": True, "result": "Usage limit"})
        with self.assertRaises(harness.HarnessError) as raised:
            harness.validate_claude_review("\n".join(events))
        self.assertEqual(raised.exception.status, "quota_exhausted")

    def test_codex_restricted_arguments_preserve_sandbox_and_disable_integrations(self):
        capability = {"executable": "codex", "planner": {"model": "gpt-99.10-fixture", "effort": "max"}}
        argv = harness.codex_review_argv(capability, "/tmp/fixture")
        self.assertIn("--ignore-user-config", argv)
        self.assertIn("--ignore-rules", argv)
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
        for setting in ("mcp_servers={}", "features.shell_tool=false", "features.multi_agent=false", "features.apps=false", "features.hooks=false", "project_doc_max_bytes=0"):
            self.assertIn(setting, argv)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", argv)

    def test_codex_review_distinguishes_requested_and_observed_model(self):
        stream = '\n'.join(json.dumps(event) for event in (
            {"type": "thread.started", "thread_id": "fixture"}, {"type": "turn.started"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "A concrete finding."}},
            {"type": "turn.completed", "usage": {}}))
        result = harness.validate_codex_review(stream)
        self.assertEqual(result["status"], "reviewed")
        self.assertIsNone(result["actual_model"])
        self.assertIn("residual", result["isolation"])

    def test_codex_tool_events_and_unknown_events_fail_closed(self):
        for event in ({"type": "item.started", "item": {"type": "command_execution"}}, {"type": "future-event"}):
            with self.subTest(event=event), self.assertRaises(harness.HarnessError):
                harness.validate_codex_review(json.dumps(event))

    def test_codex_error_item_is_diagnostic_not_tool_use(self):
        line = json.dumps({"type": "item.completed", "item": {"type": "error", "message": "Under-development features enabled: fixture."}})
        with self.assertRaises(harness.HarnessError) as raised:
            harness.check_codex_line(line)
        self.assertEqual(raised.exception.status, "provider_error")
        self.assertIn("Under-development", str(raised.exception))

    def test_codex_error_diagnostic_redacts_credentials(self):
        line = json.dumps({"type": "item.completed", "item": {"type": "error", "message": "authentication failed Authorization: Bearer private-token"}})
        with self.assertRaises(harness.HarnessError) as raised:
            harness.check_codex_line(line)
        self.assertNotIn("private-token", str(raised.exception))

    def test_expected_codex_restriction_notice_is_not_review_success(self):
        notice = {"type": "item.completed", "item": {"type": "error", "message": "Code Mode is unavailable because code-mode host is disabled. Code mode will fail closed; enable features.code_mode_host."}}
        harness.check_codex_line(json.dumps(notice))
        with self.assertRaises(harness.HarnessError):
            harness.validate_codex_review(json.dumps(notice))

    def test_agy_restricted_review_requires_exact_model_leaf_and_response(self):
        events = [{"event": "init", "init": {"model": "gemini-99.10-flash-high", "agent": harness.AGY_LEAF,
                   "cwd": "/tmp/fixture", "permission_mode": "request-review", "tools": ["run_command"]}},
                  {"event": "step_update", "step_update": {"step_type": "agent_response"}},
                  {"event": "result", "result": {"status": "SUCCESS", "response": "Concrete finding."}}]
        stream = "\n".join(json.dumps(event) for event in events)
        result = harness.validate_agy_review(stream, "", "gemini-99.10-flash-high", "/tmp/fixture")
        self.assertEqual(result["status"], "reviewed")
        self.assertIn("not full filesystem", result["isolation_limit"])
        with self.assertRaises(harness.HarnessError):
            harness.validate_agy_review(stream, "Agent not found, falling back", "gemini-99.10-flash-high", "/tmp/fixture")
        with self.assertRaises(harness.HarnessError):
            harness.validate_agy_review(stream, "", "gemini-99.11-flash-high", "/tmp/fixture")

    def test_agy_tool_step_aborts_before_final_response(self):
        with self.assertRaises(harness.HarnessError) as raised:
            harness.check_agy_event(json.dumps({"event": "step_update", "step_update": {"step_type": "run_command"}}), "gemini-99.10-flash-high", "/tmp/fixture")
        self.assertEqual(raised.exception.status, "isolation_violation")

    @unittest.skipUnless(os.name == "posix", "POSIX process/link contract; Windows equivalents are separate")
    def test_agy_cwd_accepts_same_directory_through_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory) / "private-var"
            real.mkdir()
            alias = Path(directory) / "var"
            alias.symlink_to(real, target_is_directory=True)
            event = {"event": "init", "init": {"model": "gemini-99.10-flash-high", "agent": harness.AGY_LEAF,
                     "cwd": str(real), "permission_mode": "request-review"}}
            harness.check_agy_event(json.dumps(event), "gemini-99.10-flash-high", str(alias))


class QuotaProcessIntegrationTests(unittest.TestCase):
    def setUp(self):
        from quota import Ledger
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'ledger.db'
        Ledger(path).complete_setup(services=['codex'], api_services=[], source='test')
        default = patch('quota.default_path', return_value=path)
        default.start(); self.addCleanup(default.stop)

    def test_review_process_checks_quota_before_and_after_execution(self):
        with patch('usage.require_admission', return_value={'allowed': True}) as admission:
            code, stdout, _ = harness.run([sys.executable, '-c', 'print("finished")'],
                                          quota_service='codex')
        self.assertEqual(code, 0)
        self.assertEqual(stdout.strip(), 'finished')
        self.assertEqual(admission.call_count, 2)

    def test_denial_never_starts_review_process(self):
        with patch('usage.require_admission', return_value={'allowed': False,
                   'reasons': ['reserve_floor']}), patch.object(harness.subprocess, 'Popen') as process:
            with self.assertRaises(harness.supervision.Stop):
                harness.run(['must-not-execute'], quota_service='codex')
        process.assert_not_called()

    def test_closed_output_does_not_disable_running_quota_checks(self):
        original = harness.supervision.Watch
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / 'pid'
            child = ('import os,time,pathlib,subprocess,sys,json; '
                     'grandchild=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"],'
                     'stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); '
                     'pathlib.Path(' + repr(str(pid_file)) +
                     ').write_text(json.dumps([os.getpid(),grandchild.pid])); '
                     'os.close(1); os.close(2); time.sleep(30)')
            with patch('usage.require_admission', side_effect=[{'allowed': True},
                        {'allowed': False, 'reasons': ['daily_limit']}]), \
                    patch.object(harness.supervision, 'Watch', side_effect=lambda service: original(service, interval=.25)):
                with self.assertRaises(harness.supervision.Stop):
                    harness.run([sys.executable, '-c', child], timeout=5, quota_service='codex')
            parent_pid, grandchild_pid = json.loads(pid_file.read_text())
            if os.name == 'nt':
                import ctypes
                from ctypes import wintypes
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                kernel.OpenProcess.restype = wintypes.HANDLE
                kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                kernel.WaitForSingleObject.restype = wintypes.DWORD
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel.CloseHandle.restype = wintypes.BOOL
                for pid in (parent_pid, grandchild_pid):
                    handle = kernel.OpenProcess(0x100000, False, pid)
                    if not handle:
                        self.assertEqual(ctypes.get_last_error(), 87, 'Cannot verify process exit')
                        continue
                    try:
                        self.assertEqual(kernel.WaitForSingleObject(handle, 2000), 0)
                    finally:
                        kernel.CloseHandle(handle)
            else:
                with self.assertRaises(ProcessLookupError):
                    os.kill(parent_pid, 0)
                status = subprocess.run(['ps', '-p', str(grandchild_pid), '-o', 'stat='],
                                        capture_output=True, text=True).stdout.strip()
                self.assertTrue(not status or status.startswith('Z'), 'Grandchild survived quota denial')

    def test_terminal_launch_uses_supervisor(self):
        capability = {'executable': 'never-run', 'auth': {'status': 'subscription'},
                      'planner': {'model': 'future-fixture', 'effort': 'high'}}
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        ledger = Ledger(Path(directory.name) / 'ledger.db')
        ledger.complete_setup(services=['codex', 'claude', 'antigravity'], api_services=[], source='test')
        for provider in ('codex', 'claude', 'antigravity'):
            with self.subTest(provider=provider), patch.dict(harness.os.environ, {}, clear=True), \
                    patch('quota.default_path', return_value=ledger.path), \
                    patch.object(harness, 'discover_provider', return_value=capability), \
                    patch.object(harness.sys.stdin, 'isatty', return_value=True), \
                    patch('usage.require_admission', return_value={'allowed': True}), \
                    patch.object(harness.supervision, 'run_terminal', return_value=0) as terminal:
                self.assertEqual(harness.main(['launch', provider, '--execute']), 0)
            self.assertEqual(terminal.call_args.args[2], provider)
            self.assertEqual(terminal.call_args.args[1][harness.SESSION_MARKER], provider)


if __name__ == "__main__":
    unittest.main()
