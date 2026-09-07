import os
"""Offline tests of the private native force-refresh endpoint and process lifecycle."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import agy_quota as agy
import native_quota

NOW = 1800000000
RESET = "2030-01-01T15:00:00Z"


def payload():
    return dict(response=dict(description="Native quota group policy", groups=[dict(displayName=group, buckets=[dict(
        bucketId=group + "-" + window, window=window, remainingFraction=0.987654321,
        resetTime=RESET) for window in ("weekly", "5h")]) for group in ("gemini", "3p")]))


class AgyTests(unittest.TestCase):
    def test_full_schema_and_fail_closed(self):
        result = agy.parse_response(json.dumps(payload()), NOW)
        self.assertTrue(result["complete"])
        self.assertEqual(4, len(result["pools"]))
        self.assertEqual(NOW, result["observed_at"])
        mutations = [lambda d: d.update(error="secret"), lambda d: d["response"].update(cache=True),
                     lambda d: d["response"]["groups"].pop(),
                     lambda d: d["response"]["groups"][0]["buckets"].pop(),
                     lambda d: d["response"]["groups"][0]["buckets"][0].update(remainingFraction=-1),
                     lambda d: d["response"]["groups"][0]["buckets"][0].update(extraQuota={}),
                     lambda d: d["response"]["groups"][0]["buckets"][0].pop("resetTime")]
        for mutation in mutations:
            data = payload()
            mutation(data)
            with self.assertRaises(ValueError):
                agy.parse_response(json.dumps(data), NOW)

    def test_force_refresh_fixed_loopback_endpoint_no_auth_or_redirect(self):
        connection = MagicMock()
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = json.dumps(payload()).encode()
        with patch.object(agy.http.client, "HTTPSConnection", return_value=connection) as factory:
            self.assertTrue(agy.refresh_owned_port(12345, 2))
        self.assertEqual(("127.0.0.1", 12345), factory.call_args.args)
        self.assertFalse(factory.call_args.kwargs["context"].check_hostname)
        request = connection.request.call_args
        self.assertEqual(("POST", agy.ENDPOINT), request.args)
        self.assertEqual({"forceRefresh": True, "request": {}}, json.loads(request.kwargs["body"]))
        self.assertEqual({"Content-Type": "application/json", "Connect-Protocol-Version": "1"}, request.kwargs["headers"])
        connection.close.assert_called_once()
        response.read.assert_called_once_with(agy.MAX_RESPONSE + 1)
        for status in (301, 400, 401, 403, 429, 500):
            response.status = status
            with patch.object(agy.http.client, "HTTPSConnection", return_value=connection):
                with self.assertRaises(ValueError):
                    agy.refresh_owned_port(12345, 2)
        response.status = 404
        with patch.object(agy.http.client, "HTTPSConnection", return_value=connection):
            with self.assertRaises(agy.NotQuotaTLS):
                agy.refresh_owned_port(12345, 2)
        response.status = 200
        response.read.return_value = b"x" * (agy.MAX_RESPONSE + 1)
        with patch.object(agy.http.client, "HTTPSConnection", return_value=connection):
            with self.assertRaises(ValueError):
                agy.refresh_owned_port(12345, 2)

    def test_http_handshake_disconnect_allows_other_owned_listener(self):
        for method in ("request", "getresponse"):
            for error in (ConnectionResetError(), agy.ssl.SSLError(), agy.http.client.RemoteDisconnected()):
                connection = MagicMock()
                getattr(connection, method).side_effect = error
                with self.subTest(method=method, error=type(error).__name__), \
                        patch.object(agy.http.client, "HTTPSConnection", return_value=connection):
                    with self.assertRaises(agy.NotQuotaTLS):
                        agy.refresh_owned_port(12345, 2)
                connection.close.assert_called_once()

    @unittest.skipUnless(os.name == "posix", "Native Antigravity quota is unsupported on Windows")
    def test_linux_ports_filter_only_owned_socket_inodes_and_listeners(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "42" / "fd").mkdir(parents=True)
            (root / "42" / "net").mkdir()
            (root / "42" / "fd" / "7").symlink_to("socket:[111]")
            (root / "42" / "fd" / "8").symlink_to("socket:[222]")
            rows = ["header", "0: 0100007F:3039 remote 0A a b c d e 111",
                    "1: 0100007F:303A remote 0A a b c d e 999",
                    "2: 0100007F:303B remote 01 a b c d e 222",
                    "3: 0100000A:303C remote 0A a b c d e 222"]
            (root / "42" / "net" / "tcp").write_text("\n".join(rows))
            with patch.object(agy, "Path", side_effect=lambda _: root):
                self.assertEqual({12345}, agy.linux_ports(42))

    def test_darwin_lsof_pid_restricted_no_shell(self):
        with patch.object(agy.shutil, "which", return_value="/usr/sbin/lsof"), \
                patch.object(agy.harness, "run", return_value=(0, "p42\nn127.0.0.1:12345\nn10.0.0.1:12346\nn[::]:12347\nn[::1]:12348\n", "")) as run:
            self.assertEqual({12345, 12347}, agy.darwin_ports(42, 1))
        self.assertEqual(["/usr/sbin/lsof", "-nP", "-a", "-p", "42", "-iTCP", "-sTCP:LISTEN", "-Fn"], run.call_args.args[0])

    def lifecycle(self, ports, refresh):
        proc = MagicMock()
        proc.pid = 42
        proc._harness_exit.ready.return_value = False
        return proc, [patch.object(agy.subprocess, "Popen", return_value=proc),
            patch.object(agy.harness, "register_process"), patch.object(agy.harness, "stop_group"),
            patch.object(agy.harness, "unregister_process"), patch.object(agy, "owned_ports", side_effect=lambda *_: ports.pop(0) if len(ports) > 1 else ports[0]),
            patch.object(agy, "refresh_owned_port", side_effect=refresh),
            patch.object(agy.time, "time", return_value=NOW)]

    @unittest.skipUnless(os.name == "posix", "Native Antigravity quota is unsupported on Windows")
    def test_private_launch_no_terminal_writes_and_cleanup(self):
        from contextlib import ExitStack
        proc, patches = self.lifecycle([{12345}, {12345}], [json.dumps(payload())])
        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            with patch.object(agy.os, "write", side_effect=AssertionError("No terminal input allowed")):
                self.assertTrue(agy.read_snapshot("/native/agy")["complete"])
        popen, registered, stopped, unregistered, ports, refreshed, _ = mocks
        self.assertEqual(["/native/agy", "--new-project", "--log-file", "/dev/null"], popen.call_args.args[0])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual(subprocess.DEVNULL, popen.call_args.kwargs["stderr"])
        self.assertFalse(Path(popen.call_args.kwargs["cwd"]).exists())
        registered.assert_called_once_with(proc)
        stopped.assert_called_once_with(proc)
        unregistered.assert_called_once_with(proc)
        self.assertTrue(all(call.args[0] == proc.pid for call in ports.call_args_list))
        self.assertLessEqual(refreshed.call_args.args[1], 15)

    @unittest.skipUnless(os.name == "posix", "Native Antigravity quota is unsupported on Windows")
    def test_failures_and_ambiguous_or_lost_ownership_cleanup_without_retry(self):
        from contextlib import ExitStack
        cases = [( [set(range(1, 10))], []), ([{12345}, set()], []),
                 ([{12345}, {12345}], [OSError("credential-secret")]),
                 ([{12345}, {12345}], ["{}"])]
        for ports, refresh in cases:
            proc, patches = self.lifecycle(ports, refresh)
            with ExitStack() as stack:
                mocks = [stack.enter_context(p) for p in patches]
                with self.assertRaises(ValueError) as raised:
                    agy.read_snapshot("/native/agy")
                self.assertNotIn("credential-secret", str(raised.exception))
            mocks[2].assert_called_once_with(proc)
            mocks[3].assert_called_once_with(proc)
            self.assertLessEqual(mocks[5].call_count, 1)

    @unittest.skipUnless(os.name == "posix", "Native Antigravity quota is unsupported on Windows")
    def test_two_owned_ports_tls_discrimination_and_no_backend_retry(self):
        from contextlib import ExitStack
        proc, patches = self.lifecycle([{12344, 12345}] * 3,
                                      [agy.NotQuotaTLS("plain HTTP listener"), json.dumps(payload())])
        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            self.assertTrue(agy.read_snapshot("/native/agy")["complete"])
        self.assertEqual([12344, 12345], [call.args[0] for call in mocks[5].call_args_list])
        proc, patches = self.lifecycle([{12344, 12345}] * 2, [ValueError("Backend HTTP500")])
        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            with self.assertRaises(ValueError):
                agy.read_snapshot("/native/agy")
        self.assertEqual(1, mocks[5].call_count)
        mocks[2].assert_called_once_with(proc)

    @unittest.skipUnless(os.name == "posix", "Native Antigravity quota is unsupported on Windows")
    def test_transient_startup_retry_same_port_and_persistent_failure_blocks(self):
        from contextlib import ExitStack
        for outcomes, succeeds in (([agy.BackendNotReady(), json.dumps(payload())], True),
                                   ([agy.BackendNotReady()] * 5, False)):
            proc, patches = self.lifecycle([{12345}], outcomes)
            with ExitStack() as stack:
                mocks = [stack.enter_context(p) for p in patches]
                if succeeds:
                    self.assertTrue(agy.read_snapshot("/native/agy")["complete"])
                else:
                    with self.assertRaises(ValueError):
                        agy.read_snapshot("/native/agy")
            self.assertEqual(2 if succeeds else 5, mocks[5].call_count)
            self.assertTrue(all(call.args[0] == 12345 for call in mocks[5].call_args_list))
            mocks[2].assert_called_once_with(proc)

    @unittest.skipUnless(os.name == "posix", "Native Antigravity quota is unsupported on Windows")
    def test_late_tls_listener_is_rediscovered(self):
        from contextlib import ExitStack
        proc, patches = self.lifecycle([{12344}] * 3 + [{12344, 12345}],
            [agy.NotQuotaTLS(), agy.NotQuotaTLS(), json.dumps(payload())])
        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            self.assertTrue(agy.read_snapshot("/native/agy")["complete"])
        self.assertEqual([12344, 12344, 12345], [c.args[0] for c in mocks[5].call_args_list])
        mocks[2].assert_called_once_with(proc)

    def test_zero_remaining_bucket_stops_ledger_admission(self):
        from quota import Ledger
        data = payload()
        data["response"]["groups"][0]["buckets"][0]["remainingFraction"] = 0
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "quota.sqlite3")
            ledger.set_mode("observed")
            result = ledger.record(agy.parse_response(json.dumps(data), NOW), now=NOW, initialize=True)
        self.assertFalse(result["allowed"])
        self.assertTrue(any(reason.endswith(":reserve_floor") for reason in result["reasons"]))

    def test_unknown_reset_is_retained(self):
        data = payload()
        data["response"]["groups"][0]["buckets"][0]["resetTime"] = None
        pools = agy.parse_response(json.dumps(data), NOW)["pools"]
        self.assertTrue(any(p["resets_at"] is None for p in pools))

    @unittest.skipUnless(sys.platform == "darwin", "Native macOS socket ownership check")
    def test_real_darwin_owned_listener(self):
        proc = subprocess.Popen([sys.executable, "-c",
            "import socket,sys; s=socket.socket(); s.bind(('127.0.0.1',0)); "
            "s.listen(); print(s.getsockname()[1],flush=True); sys.stdin.read()"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, start_new_session=True)
        agy.harness.register_process(proc)
        try:
            port = int(proc.stdout.readline())
            self.assertIn(port, agy.darwin_ports(proc.pid, 3))
        finally:
            agy.harness.stop_group(proc)
            agy.harness.unregister_process(proc)
            proc.stdin.close()
            proc.stdout.close()

    @unittest.skipUnless(os.name == "posix", "Native Antigravity quota is unsupported on Windows")
    def test_deadline_cleanup_before_request(self):
        from contextlib import ExitStack
        proc, patches = self.lifecycle([], [])
        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in patches]
            with patch.object(agy.time, "monotonic", side_effect=[0, 16]):
                with self.assertRaises(ValueError):
                    agy.read_snapshot("/native/agy")
        mocks[2].assert_called_once_with(proc)
        mocks[5].assert_not_called()


if __name__ == "__main__":
    unittest.main()
