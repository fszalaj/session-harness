import os
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

if os.name == "posix":
    import fcntl
    import pty
    import termios

import supervision

from supervision import Stop, Watch


class WatchTests(unittest.TestCase):
    def test_schedule_and_final_observation(self):
        clock, calls = [0], []
        watch = Watch("codex", lambda service: calls.append(service) or {"allowed": True},
                      interval=2, clock=lambda: clock[0])
        watch.start()
        watch.tick()
        self.assertEqual(len(calls), 1)
        clock[0] = 2
        watch.tick()
        watch.finish()
        self.assertEqual(calls, ["codex"] * 3)

    def test_pool_identifiers_are_removed(self):
        with self.assertRaises(Stop) as caught:
            Watch("codex", lambda _: {"allowed": False,
                                      "reasons": ["codex:private-pool:daily_limit"]}).start()
        self.assertEqual(caught.exception.reasons, ("daily_limit",))
        self.assertNotIn("private-pool", str(caught.exception))

    def test_fail_closed_and_safe_metadata(self):
        for result in (None, {}, {"allowed": 1}, {"allowed": False, "reasons": ["secret value", "daily_limit"]}):
            with self.assertRaises(Stop) as caught:
                Watch("codex", lambda _: result).start()
            self.assertNotIn("secret value", str(caught.exception))
        def broken(_):
            raise RuntimeError("private credential")
        with self.assertRaisesRegex(Stop, "quota_refresh_failed"):
            Watch("codex", broken).start()

    def test_explanations_distinguish_capacity_maintenance_and_missing_evidence(self):
        for reason, phrase in [('account_session_busy', 'slots'), ('account_maintenance', 'maintenance'),
                               ('quota_refresh_failed', 'could not authorize'), ('reserve_floor', 'reserve')]:
            self.assertIn(phrase, Stop('codex', [reason]).explanation())


@unittest.skipUnless(os.name == "posix", "POSIX terminal/kernel contract; Windows has native job tests")
class DarwinSignalTests(unittest.TestCase):
    def test_eperm_is_ignored_only_for_verified_zombie_group(self):
        for platform, exited, zombies, allowed in (("darwin", True, True, True),
                                                   ("darwin", False, True, False),
                                                   ("darwin", True, False, False),
                                                   ("linux", True, True, False)):
            with self.subTest(platform=platform, exited=exited, zombies=zombies):
                observer = Mock()
                observer.ready.return_value = exited
                with patch.object(supervision.sys, "platform", platform), \
                        patch.object(supervision.os, "killpg", side_effect=PermissionError(1, "denied")), \
                        patch.object(supervision, "_zombie_only_group", return_value=zombies):
                    if allowed:
                        self.assertFalse(supervision.signal_group(123, signal.SIGKILL, observer))
                    else:
                        with self.assertRaises(PermissionError):
                            supervision.signal_group(123, signal.SIGKILL, observer)

    def test_darwin_exit_event_can_arrive_after_zombie_snapshot(self):
        observer = Mock()
        observer.ready.side_effect = [False, True]
        with patch.object(supervision.sys, "platform", "darwin"), \
                patch.object(supervision.os, "killpg", side_effect=PermissionError(1, "denied")), \
                patch.object(supervision, "_zombie_only_group", return_value=True):
            self.assertFalse(supervision.signal_group(123, 0, observer))
        self.assertEqual(2, observer.ready.call_count)

    def test_cleanup_preserves_exit_observer_until_reap(self):
        observer = Mock()
        observer.ready.return_value = True
        with patch.object(supervision, "ChildExit", side_effect=AssertionError("Do not reregister exit events")), \
                patch.object(supervision, "signal_group", return_value=False) as send, \
                patch.object(supervision.os, "waitpid", return_value=(123, 0)) as reap:
            self.assertEqual(0, supervision._cleanup(123, 1, observer))
        self.assertEqual([signal.SIGTERM, 0, signal.SIGKILL], [c.args[1] for c in send.call_args_list])
        self.assertTrue(all(c.args[2] is observer for c in send.call_args_list))
        reap.assert_called_once_with(123, os.WNOHANG)
        observer.close.assert_not_called()

    def test_reaped_leader_is_not_reported_as_confirmed_cleanup(self):
        with patch.object(supervision, 'signal_group', return_value=False), \
                patch.object(supervision.os, 'waitpid', side_effect=ChildProcessError):
            with self.assertRaises(OSError) as caught:
                supervision._cleanup(123, 0, Mock())
        self.assertEqual(caught.exception.errno, supervision.errno.ECHILD)

    def test_unreaped_child_has_bounded_cleanup_and_no_false_confirmation(self):
        with patch.object(supervision, 'signal_group', return_value=False), \
                patch.object(supervision.os, 'waitpid', return_value=(0, 0)), \
                patch.object(supervision.time, 'monotonic', side_effect=[0, 1, 2, 10]):
            with self.assertRaises(OSError) as caught:
                supervision._cleanup(123, 0, Mock())
        self.assertEqual(caught.exception.errno, supervision.errno.ETIMEDOUT)

    def test_group_snapshot_rejects_live_missing_and_invalid_evidence(self):
        for rows, expected in ((b"123 Z\n123 Z+\n456 R\n", True),
                               (b"123 Z\n123 S\n", False), (b"456 Z\n", False),
                               (b"invalid\n", False)):
            def listing(*args, **kwargs):
                kwargs["stdout"].write(rows)
                return Mock(returncode=0)
            with self.subTest(rows=rows), patch.object(supervision.subprocess, "run", side_effect=listing):
                self.assertEqual(supervision._zombie_only_group(123), expected)


@unittest.skipUnless(os.name == "posix", "POSIX terminal/kernel contract; Windows has native job tests")
class TerminalTests(unittest.TestCase):
    def test_cleanup_error_preserves_quota_reason_and_retains_owner(self):
        script = '''import json,supervision
from unittest.mock import patch
original=supervision._cleanup
def failing(*args):
 original(*args)
 raise PermissionError(1,'private diagnostic','/private/credential')
closed=[]
patch.object(supervision,'_cleanup',failing).start()
patch.object(supervision.Watch,'close',lambda self: closed.append(True)).start()
'''
        check = "calls=0\ndef check(_):\n global calls\n calls+=1\n return {'allowed':calls<3,'reasons':['daily_limit']}"
        body = self.wrapper("import time; time.sleep(30)", check).replace(
            "except Stop:\n code=77", "except Stop as exc:\n code=77\n print(json.dumps(exc.session_cleanup))\n assert not closed")
        result = self.run_wrapper(script + body, stdin=subprocess.DEVNULL, capture_output=True)
        self.assertEqual(result.returncode, 77, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['state'], 'unknown')
        self.assertTrue(data['owner_retained'])
        self.assertEqual(data['errors'], [{'stage': 'process_group', 'errno': 1}])
        self.assertNotIn(b'private', result.stdout + result.stderr)

    def test_nonquota_primary_survives_cleanup_error(self):
        script = '''import os,sys,supervision
from unittest.mock import patch
original=supervision._cleanup
def cleanup(*args):
 original(*args)
 raise PermissionError(1,'cleanup')
try:
 with patch.object(supervision,'_cleanup',cleanup), patch.object(supervision.select,'select',side_effect=ValueError('primary')):
  supervision.run_terminal([sys.executable,'-c','import time;time.sleep(30)'],dict(os.environ),'codex',check=lambda _: {'allowed':True},grace=.01)
except ValueError as exc:
 assert str(exc)=='primary'
 assert exc.session_cleanup['state']=='unknown'
else: raise AssertionError('Primary error lost')
'''
        result = self.run_wrapper(script, stdin=subprocess.DEVNULL, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cleanup_only_non_os_errors_are_normalized_without_private_text(self):
        for error in ('RuntimeError', 'KeyboardInterrupt'):
            with self.subTest(error=error):
                script = """import os,sys,supervision
from unittest.mock import patch
try:
 with patch.object(supervision.Watch,'close',side_effect=ERROR('private diagnostic')):
  supervision.run_terminal([sys.executable,'-c','pass'],dict(os.environ),'codex',check=lambda _: {'allowed':True},grace=.01)
except OSError as exc:
 assert exc.errno==supervision.errno.EIO
 assert 'private' not in str(exc)
 assert exc.session_cleanup['state']=='stopped'
 assert exc.session_cleanup['errors']==[{'stage':'owner_release','errno':None}]
else: raise AssertionError('Missing cleanup error')
""".replace('ERROR', error)
                result = self.run_wrapper(script, stdin=subprocess.DEVNULL, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_short_screen_reset_is_diagnosed_without_masking_stop(self):
        script = """import supervision
from unittest.mock import patch
original_write=supervision.os.write
def short_reset(fd,data):
 if data.startswith(b'\\x1b[?1049l'): return len(data)-1
 return original_write(fd,data)
patch.object(supervision.os,'write',short_reset).start()
"""
        check = "calls=0\ndef check(_):\n global calls\n calls+=1\n return {'allowed':calls<3,'reasons':['daily_limit']}"
        body = self.wrapper("import time;time.sleep(30)", check).replace(
            'except Stop:\n code=77', "except Stop as exc:\n code=77\n assert exc.session_cleanup['errors']==[{'stage':'terminal_screen','errno':supervision.errno.EIO}]")
        master, slave = pty.openpty()
        try:
            result = self.run_wrapper(script + body, stdin=slave, stdout=slave, stderr=subprocess.PIPE)
            self.assertEqual(result.returncode, 77, result.stderr)
        finally:
            os.close(master)
            os.close(slave)

    def test_restoration_failures_do_not_skip_other_steps_or_mask_stop(self):
        for target in ('ignore_signal', 'descriptor_flags', 'terminal_attributes', 'interrupt'):
            with self.subTest(target=target):
                script = '''import json,supervision
from unittest.mock import patch
target=TARGET
events=[]
fired=False
original_signal=supervision.signal.signal
original_fcntl=supervision.fcntl.fcntl
original_tty=supervision.termios.tcsetattr
def on_signal(number,handler):
 global fired
 if handler==supervision.signal.SIG_IGN and not fired and target in ('ignore_signal','interrupt'):
  fired=True
  if target=='interrupt': os.kill(os.getpid(),supervision.signal.SIGINT)
  else: raise PermissionError(1,'private')
 events.append('signal')
 return original_signal(number,handler)
def on_flags(fd,command,*args):
 global fired
 if command==supervision.fcntl.F_SETFL and args and not args[0]&os.O_NONBLOCK:
  events.append('flags')
  if target=='descriptor_flags' and not fired:
   fired=True
   raise PermissionError(1,'private')
 return original_fcntl(fd,command,*args)
def on_tty(fd,when,attrs):
 global fired
 if when==supervision.termios.TCSANOW:
  events.append('tty')
  if target=='terminal_attributes' and not fired:
   fired=True
   raise PermissionError(1,'private')
 return original_tty(fd,when,attrs)
patch.object(supervision.signal,'signal',on_signal).start()
patch.object(supervision.fcntl,'fcntl',on_flags).start()
patch.object(supervision.termios,'tcsetattr',on_tty).start()
'''.replace('TARGET', repr(target))
                check = "calls=0\ndef check(_):\n global calls\n calls+=1\n return {'allowed':calls<3,'reasons':['daily_limit']}"
                body = self.wrapper("import time;time.sleep(30)", check).replace(
                    'except Stop:\n code=77', "except Stop as exc:\n code=77\n assert exc.reasons==('daily_limit',)\n assert exc.session_cleanup['state']=='stopped'\n assert not exc.session_cleanup['owner_retained']\n assert 'flags' in events and 'tty' in events and events[-1]=='signal'")
                master, slave = pty.openpty()
                before = termios.tcgetattr(slave)
                try:
                    result = self.run_wrapper(script + body, stdin=slave, capture_output=True)
                    self.assertEqual(result.returncode, 77, result.stderr)
                finally:
                    termios.tcsetattr(slave, termios.TCSANOW, before)
                    os.close(master)
                    os.close(slave)

    def test_alternate_screen_is_restored_on_output_terminal_before_stop_notice(self):
        check = "calls=0\ndef check(_):\n global calls\n calls+=1\n return {'allowed':calls<5,'reasons':['daily_limit']}"
        child = "import sys,time;sys.stdout.write('\\x1b[?1049h');sys.stdout.flush();time.sleep(30)"
        script = self.wrapper(child, check).replace('except Stop:\n code=77',
            'except Stop as exc:\n code=77\n import harness\n harness.explain_terminal_stop(exc)')
        master, slave = pty.openpty()
        before = termios.tcgetattr(slave)
        try:
            result = self.run_wrapper(script, stdin=slave, stdout=slave, stderr=slave)
            self.assertEqual(result.returncode, 77)
            self.assert_terminal_restored(slave, before)
            data = os.read(master, 8192)
            self.assertLess(data.index(b'\x1b[?1049h'), data.index(b'\x1b[?1049l'))
            self.assertLess(data.index(b'\x1b[?1049l'), data.index(b"Today's harness allowance"))
            self.assertIn(b'\r\n', data)
        finally:
            os.close(master)
            os.close(slave)

    def test_screen_reset_follows_stdout_and_never_escapes_into_redirected_streams(self):
        check = "calls=0\ndef check(_):\n global calls\n calls+=1\n return {'allowed':calls<3,'reasons':['daily_limit']}"
        script = self.wrapper("import time;time.sleep(30)", check)
        for output_terminal in (True, False):
            with self.subTest(output_terminal=output_terminal):
                master, slave = pty.openpty()
                try:
                    result = self.run_wrapper(script, stdin=slave,
                        stdout=slave if output_terminal else subprocess.PIPE,
                        stderr=subprocess.PIPE if output_terminal else slave)
                    self.assertEqual(result.returncode, 77)
                    redirected = result.stderr if output_terminal else result.stdout
                    self.assertNotIn(b'\x1b', redirected)
                    if output_terminal:
                        self.assertIn(b'\x1b[?1049l', os.read(master, 8192))
                finally:
                    os.close(master)
                    os.close(slave)

    def assert_descriptor_flags_restored(self, fd, before):
        after = fcntl.fcntl(fd, fcntl.F_GETFL)
        self.assertEqual(after & os.O_NONBLOCK, before & os.O_NONBLOCK)
        # Darwin FWASWRITTEN records kernel write history (xnu/bsd/sys/fcntl.h).
        transient = 0x00010000 if sys.platform == "darwin" else 0
        self.assertEqual(after & ~transient, before & ~transient)

    def assert_terminal_restored(self, fd, before):
        after = termios.tcgetattr(fd)
        before = list(before)
        if sys.platform == "darwin":
            # Darwin PENDIN records pending retype state (xnu/bsd/sys/termios.h).
            after[3] &= ~termios.PENDIN
            before[3] &= ~termios.PENDIN
        self.assertEqual(after, before)

    def wrapper(self, child, check, extra=""):
        return ("import os,sys\nfrom supervision import run_terminal, Stop\n" + check + "\n" +
                "try:\n code=run_terminal([sys.executable, '-c', " + repr(child) +
                "], dict(os.environ), 'codex', check=check, interval=.03, grace=.05)\n" +
                "except Stop:\n code=77\n" + extra + "\nsys.exit(code)\n")

    def run_wrapper(self, script, **kwargs):
        return subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).parent,
                              timeout=5, **kwargs)

    def test_initial_denial_never_starts_child(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = str(Path(directory) / "started")
            script = self.wrapper(f"open({marker!r},'w').close()", "def check(_): return {'allowed': False}")
            result = self.run_wrapper(script, stdin=subprocess.DEVNULL, capture_output=True)
            self.assertEqual(result.returncode, 77, result.stderr)
            self.assertFalse(Path(marker).exists())

    def test_normal_exit_and_final_check(self):
        check = "calls=0\ndef check(_):\n global calls\n calls+=1\n return {'allowed': True}"
        script = self.wrapper("print('child-output', flush=True); raise SystemExit(7)", check,
                              "assert calls >= 2\n")
        result = self.run_wrapper(script, stdin=subprocess.DEVNULL, capture_output=True)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn(b"child-output", result.stdout)

    def test_stop_restores_terminal_and_removes_group(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = str(Path(directory) / "pid")
            child = ("import os,signal,time\n"
                     "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                     f"open({marker!r},'w').write(str(os.getpid()))\n"
                     "time.sleep(30)")
            check = ("import time\nstart=time.monotonic()\n"
                     "def check(_): return {'allowed': time.monotonic()-start < .25, 'reasons':['daily_limit']}")
            script = self.wrapper(child, check)
            master, slave = pty.openpty()
            before = termios.tcgetattr(slave)
            try:
                result = self.run_wrapper(script, stdin=slave, stdout=slave, stderr=subprocess.PIPE)
                self.assertEqual(result.returncode, 77, result.stderr)
                self.assert_terminal_restored(slave, before)
                pid = int(Path(marker).read_text())
                with self.assertRaises(ProcessLookupError):
                    os.killpg(pid, 0)
            finally:
                os.close(master)
                os.close(slave)

    def test_quota_stop_terminates_descendant(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "heartbeat"
            descendant = ("import signal,time\n"
                          "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                          f"f=open({str(marker)!r},'w')\n"
                          "while True:\n f.write('x'); f.flush(); time.sleep(.01)")
            child = ("import subprocess,sys,time\n"
                     f"subprocess.Popen([sys.executable, '-c', {descendant!r}])\n"
                     "time.sleep(30)")
            check = ("import time\nstart=time.monotonic()\n"
                     "def check(_): return {'allowed': time.monotonic()-start < .25}")
            result = self.run_wrapper(self.wrapper(child, check),
                                      stdin=subprocess.DEVNULL, capture_output=True)
            self.assertEqual(result.returncode, 77, result.stderr)
            self.assertTrue(marker.exists())
            size = marker.stat().st_size
            time.sleep(.08)
            self.assertEqual(marker.stat().st_size, size)

    def test_stalled_relay_still_stops_and_restores_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "pid"
            child = ("import os,signal\n"
                     "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                     f"open({str(marker)!r},'w').write(str(os.getpid()))\n"
                     "while True: os.write(1,b'x'*16384)")
            check = ("import time\nstart=time.monotonic()\n"
                     "def check(_): return {'allowed': time.monotonic()-start < .4}")
            read_fd, write_fd = os.pipe()
            with tempfile.TemporaryFile() as source:
                source.write(b'i' * (2 * 1024 * 1024))
                source.seek(0)
                original_output = fcntl.fcntl(write_fd, fcntl.F_GETFL)
                original_input = fcntl.fcntl(source.fileno(), fcntl.F_GETFL)
                proc = subprocess.Popen([sys.executable, "-c", self.wrapper(child, check)],
                                        cwd=Path(__file__).parent, stdin=source,
                                        stdout=write_fd, stderr=subprocess.PIPE)
                try:
                    self.assertEqual(proc.wait(timeout=4), 77)
                    self.assert_descriptor_flags_restored(write_fd, original_output)
                    self.assert_descriptor_flags_restored(source.fileno(), original_input)
                    self.assertTrue(marker.exists())
                    with self.assertRaises(ProcessLookupError):
                        os.killpg(int(marker.read_text()), 0)
                    self.assertTrue(os.read(read_fd, 1024))
                finally:
                    if proc.poll() is None:
                        proc.kill()
                    proc.communicate()
                    os.close(write_fd)
                    os.close(read_fd)

    @unittest.skipUnless(sys.platform == "darwin", "Repeat Darwin exit-event race coverage")
    def test_repeated_darwin_parent_sigterm_cleanup(self):
        for attempt in range(5):
            with self.subTest(attempt=attempt):
                self.test_parent_sigterm_cleans_child()

    def test_parent_sigterm_cleans_child(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "pid"
            child = (f"import os,time; from pathlib import Path; marker=Path({str(marker)!r}); "
                     "temporary=marker.with_suffix('.tmp'); temporary.write_text(str(os.getpid())); "
                     "temporary.replace(marker); time.sleep(30)")
            script = self.wrapper(child, "def check(_): return {'allowed': True}")
            proc = subprocess.Popen([sys.executable, "-c", script], cwd=Path(__file__).parent,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 3
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(marker.exists())
                pid = int(marker.read_text())
                proc.send_signal(signal.SIGTERM)
                _, err = proc.communicate(timeout=3)
                self.assertEqual(proc.returncode, 143, err)
                with self.assertRaises(ProcessLookupError):
                    os.killpg(pid, 0)
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.communicate()


if __name__ == "__main__":
    unittest.main()
