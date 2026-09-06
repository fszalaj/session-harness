"""Real native process/IPC contracts without provider clients or credentials."""
import ctypes
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
import platform_runtime as runtime


class PipeTests(unittest.TestCase):
    def test_reader_delivers_fragmented_bytes_and_eof(self):
        proc = subprocess.Popen([sys.executable, '-c',
                                 "import os,time; os.write(1,b'first'); time.sleep(.03); os.write(1,b'second')"],
                                stdout=subprocess.PIPE)
        reader = runtime.Reader(proc.stdout)
        data = bytearray()
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                chunk = reader.read(.1)
                if chunk == b'': break
                if chunk: data.extend(chunk)
            self.assertEqual(data, b'firstsecond')
            proc.wait(timeout=2)
        finally:
            if proc.poll() is None: proc.kill(); proc.wait()
            reader.close(); proc.stdout.close()

    def test_bounded_reader_backpressure_can_be_cancelled(self):
        proc = subprocess.Popen([sys.executable, '-c', 'import os; os.write(1,b"x"*4000000)'],
                                stdout=subprocess.PIPE)
        reader = runtime.Reader(proc.stdout)
        try:
            time.sleep(.1)
            self.assertLessEqual(reader.queue.qsize(), 16)
        finally:
            proc.kill(); proc.wait(); reader.close(); proc.stdout.close()


@unittest.skipUnless(os.name == 'nt', 'Native Windows Job Object, IPC and ACL contracts')
class WindowsTests(unittest.TestCase):
    def assert_stopped(self, pid):
        from ctypes import wintypes as w
        runtime.kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        runtime.kernel.OpenProcess.restype = w.HANDLE
        handle = runtime.kernel.OpenProcess(0x100000, False, pid)
        if not handle: return
        try: self.assertEqual(runtime.kernel.WaitForSingleObject(handle, 2000), 0)
        finally: runtime.kernel.CloseHandle(handle)

    def test_timeout_kills_actual_descendants_in_runner_job(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'pids.json'
            code = ('import subprocess,sys,time,os,json,pathlib; '
                    'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
                    'pathlib.Path(sys.argv[1]).write_text(json.dumps([os.getpid(),p.pid])); time.sleep(60)')
            with self.assertRaises(harness.HarnessError):
                harness.run([sys.executable, '-c', code, str(marker)], timeout=2)
            self.assertTrue(marker.exists())
            for pid in json.loads(marker.read_text()): self.assert_stopped(pid)

    def test_denied_job_assignment_never_starts_target(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'never-created'
            with patch.object(runtime.kernel, 'AssignProcessToJobObject', return_value=False):
                with self.assertRaisesRegex(OSError, 'assignment denied'):
                    runtime.spawn([sys.executable, '-c', 'import pathlib,sys; pathlib.Path(sys.argv[1]).touch()', str(marker)])
            self.assertFalse(marker.exists())

    def test_breakaway_child_is_denied(self):
        code = ('import subprocess,sys; '
                '\ntry: subprocess.Popen([sys.executable,"-c","pass"],creationflags=subprocess.CREATE_BREAKAWAY_FROM_JOB)'
                '\nexcept OSError: print("denied")')
        result = harness.run([sys.executable, '-c', code])
        self.assertEqual(result[1].strip(), 'denied')

    def test_output_overflow_and_blocked_stdin_have_bounded_cleanup(self):
        for code, stdin, expected in [
            ('import os; os.write(1,b"x"*3000000)', b'', 'output_limit'),
            ('import time; time.sleep(60)', b'x' * 1024 * 1024, 'timeout'),
        ]:
            with self.subTest(expected=expected):
                start = time.monotonic()
                with self.assertRaises(harness.HarnessError) as raised:
                    harness.run([sys.executable, '-c', code], stdin=stdin, timeout=1)
                self.assertEqual(raised.exception.status, expected)
                self.assertLess(time.monotonic() - start, 6)

    def test_job_closes_when_supervising_process_dies(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'target.pid'
            code = ('import sys,time; sys.path.insert(0,sys.argv[1]); import platform_runtime as r; '
                    'r.spawn([sys.executable,"-c",sys.argv[2],sys.argv[3]]); time.sleep(60)')
            target = 'import pathlib,sys,os,time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)'
            supervisor = subprocess.Popen([sys.executable, '-c', code, str(Path(runtime.__file__).parent), target, str(marker)])
            try:
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline: time.sleep(.02)
                self.assertTrue(marker.exists())
                supervisor.kill(); supervisor.wait(timeout=3)
                self.assert_stopped(int(marker.read_text()))
            finally:
                if supervisor.poll() is None: supervisor.kill(); supervisor.wait()

    def test_codex_rpc_fragmented_real_pipe_response(self):
        fixture = ('import sys,json,os,time\n'
                   'for line in sys.stdin:\n'
                   ' row=json.loads(line)\n'
                   ' if "id" not in row: continue\n'
                   ' data=(json.dumps({"id":row["id"],"result":{"ok":True}})+"\\n").encode()\n'
                   ' os.write(1,data[:4]); time.sleep(.02); os.write(1,data[4:])\n')
        original = runtime.spawn
        with patch.object(runtime, 'spawn', side_effect=lambda argv, **kw: original([sys.executable, '-c', fixture], **kw)):
            rpc = harness.CodexRPC(sys.executable)
            try: self.assertEqual(rpc.request('model/list', {}), {'ok': True})
            finally: rpc.close()

    def test_copilot_content_length_real_pipe_response(self):
        import inventory
        fixture = ('import sys,json,os,time\n'
                   'while True:\n'
                   ' line=sys.stdin.buffer.readline()\n'
                   ' if not line: break\n'
                   ' length=int(line.split(b":")[1]); sys.stdin.buffer.readline()\n'
                   ' row=json.loads(sys.stdin.buffer.read(length))\n'
                   ' data=json.dumps({"id":row["id"],"result":{"ok":True}}).encode()\n'
                   ' frame=b"Content-Length: "+str(len(data)).encode()+b"\\r\\n\\r\\n"+data\n'
                   ' os.write(1,frame[:5]); time.sleep(.02); os.write(1,frame[5:])\n')
        original = runtime.spawn
        with patch.object(runtime, 'spawn', side_effect=lambda argv, **kw: original([sys.executable, '-c', fixture], **kw)):
            rpc = inventory.MetadataRPC(sys.executable)
            try: self.assertEqual(rpc.request('status.get'), {'ok': True})
            finally: rpc.close()

    def test_cwd_lookup_and_arbitrary_batch_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            batch = Path(directory) / 'evil.cmd'; batch.write_text('@echo off\necho no')
            with self.assertRaisesRegex(OSError, 'Unsupported batch'):
                runtime.executable_argv([str(batch)])
            with patch.dict(os.environ, {'PATH': directory}), patch.object(Path, 'cwd', return_value=Path(directory)):
                self.assertIsNone(runtime.which('evil'))

    def test_native_antigravity_is_explicitly_unsupported(self):
        import agy_quota
        with self.assertRaisesRegex(ValueError, 'unsupported on Windows'):
            agy_quota.read_snapshot('never-launch')

    def test_private_state_acl_and_timezone(self):
        from quota import Ledger
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'private/ledger.sqlite3'
            ledger = Ledger(path, timezone='Europe/Warsaw')
            self.assertEqual(ledger.policy['timezone'], 'Europe/Warsaw')
            command = "$a=Get-Acl -LiteralPath '" + str(path).replace("'", "''") + "'; [Console]::Write($a.AreAccessRulesProtected)"
            result = subprocess.check_output(['pwsh', '-NoProfile', '-Command', command], text=True)
            self.assertEqual(result.strip(), 'True')

    def test_reparse_ancestor_is_rejected(self):
        import windows_security
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); target = root / 'target'; target.mkdir()
            alias = root / 'junction'
            command = 'mklink /J "' + str(alias) + '" "' + str(target) + '"'
            result = subprocess.run(['cmd.exe', '/d', '/c', command], capture_output=True)
            self.assertEqual(result.returncode, 0, 'Creating an unprivileged directory junction must succeed')
            try:
                with self.assertRaisesRegex(ValueError, 'reparse'):
                    windows_security.prepare_private_file(alias / 'ledger.sqlite3')
                self.assertFalse((target / 'ledger.sqlite3').exists())
            finally:
                alias.rmdir()


if __name__ == '__main__':
    unittest.main()
