"""Observe quota admission and supervise an owned POSIX terminal process group."""
import errno
import math
import os
import select
import signal
import struct
import subprocess
import tempfile
import sys
import time
import uuid

if os.name == "posix":
    import pty
    import termios
    import tty
    import fcntl


class Stop(RuntimeError):
    """A quota stop containing reason codes only, never adapter payloads."""

    def __init__(self, service, reasons):
        self.service = service
        known = {"missing_snapshot", "stale_or_future_snapshot", "incomplete_pools",
                 "new_day_needs_observation", "unknown_daily_consumption", "daily_limit",
                 "reserve_floor", "reset_needs_fresh_evidence", "stale_pool",
                 "exact_request_bound_unavailable", "invalid_ledger", "quota_refresh_failed",
                 "quota_admission_denied", "unsupported_quota_refresh",
                 "account_session_busy", "coordination_unavailable", "environment_setup_required", "service_not_configured",
                 "unknown_adaptive_reset", "unknown_window", "budget_anchor_missing", "native_growth_limit", "not_work_day", "credit_metadata_invalid", "credit_metadata_unverified", "native_paid_execution_unsupported"}
        self.reasons = tuple(dict.fromkeys(reason.rsplit(":", 1)[-1] for reason in reasons
                                         if isinstance(reason, str) and reason.rsplit(":", 1)[-1] in known)) or ("quota_admission_denied",)
        super().__init__("Quota supervision stopped: " + ", ".join(self.reasons))


class Watch:
    def __init__(self, service, check=None, interval=15, clock=time.monotonic):
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("Polling interval must be positive and finite")
        self.service, self.check = service, check
        self.interval, self.clock = interval, clock
        self.next_check = None
        self.owner = uuid.uuid4().hex

    def _check(self):
        try:
            if self.check is None:
                from coordination import dispatch
                result = dispatch('admit', self.service, self.owner)
            else:
                result = self.check(self.service)
        except Exception:
            raise Stop(self.service, ["quota_refresh_failed"]) from None
        if not isinstance(result, dict) or result.get("allowed") is not True:
            reasons = result.get("reasons", []) if isinstance(result, dict) else []
            raise Stop(self.service, reasons if isinstance(reasons, (list, tuple)) else [])
        self.next_check = self.clock() + self.interval
        return result

    def start(self):
        return self._check()

    def tick(self):
        if self.next_check is None or self.clock() >= self.next_check:
            return self._check()
        return None

    def finish(self):
        try:
            return self._check()
        finally:
            self.close()

    def close(self):
        if self.check is None:
            from coordination import dispatch
            try:
                dispatch('release', self.service, self.owner)
            except Exception:
                pass


class ChildExit:
    """Observe child exit without releasing its PID before group cleanup."""

    def __init__(self, pid):
        self.pid, self.queue, self.exited = pid, None, False
        if not hasattr(os, "waitid"):
            self.queue = select.kqueue()
            try:
                self.queue.control([select.kevent(pid, filter=select.KQ_FILTER_PROC,
                                                 flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE,
                                                 fflags=select.KQ_NOTE_EXIT)], 0, 0)
            except ProcessLookupError:
                self.exited = True

    def ready(self):
        if not self.exited:
            if self.queue is not None:
                self.exited = bool(self.queue.control([], 1, 0))
            else:
                self.exited = bool(os.waitid(os.P_PID, self.pid,
                                            os.WEXITED | os.WNOHANG | os.WNOWAIT))
        return self.exited

    def close(self):
        if self.queue is not None:
            self.queue.close()
            self.queue = None


class _SignalStop(BaseException):
    def __init__(self, signum):
        self.signum = signum


def _zombie_only_group(pid):
    """Read only group IDs and process states; unknown evidence stays denied."""
    try:
        with tempfile.TemporaryFile() as output:
            result = subprocess.run(["/bin/ps", "-A", "-o", "pgid=", "-o", "stat="],
                                    stdin=subprocess.DEVNULL, stdout=output,
                                    stderr=subprocess.DEVNULL, timeout=2)
            if result.returncode or output.tell() > 4 * 1024 * 1024:
                return False
            output.seek(0)
            rows = output.read().decode("ascii").splitlines()
        found = False
        for row in rows:
            group, state = row.split()
            if int(group) == pid:
                found = True
                if not state.startswith("Z"):
                    return False
        return found
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def signal_group(pid, signum, observer):
    """Darwin can return EPERM when an owned group contains only zombies."""
    try:
        os.killpg(pid, signum)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        if sys.platform != "darwin" or not _zombie_only_group(pid):
            raise
        deadline = time.monotonic() + 0.1
        while not observer.ready():
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.005)
        return False


def _cleanup(pid, grace, observer=None):
    # Preserve one exit observer and keep the leader unreaped until group cleanup.
    owned_observer = observer is None
    if owned_observer:
        observer = ChildExit(pid)
    try:
        signal_group(pid, signal.SIGTERM, observer)
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            if not signal_group(pid, 0, observer):
                break
            time.sleep(min(0.02, max(0, deadline - time.monotonic())))
        signal_group(pid, signal.SIGKILL, observer)
        try:
            _, status = os.waitpid(pid, 0)
            return os.waitstatus_to_exitcode(status)
        except ChildProcessError:
            return 0
    finally:
        if owned_observer:
            observer.close()


def run_terminal(argv, env, service, *, check=None, interval=15, grace=1.0):
    """Relay a PTY and stop its entire owned group when observation denies work."""
    if not math.isfinite(grace) or grace < 0:
        raise ValueError("Cleanup grace must be nonnegative and finite")
    if os.name == 'nt':
        from platform_runtime import terminal
        return terminal(argv, env, service, check=check, interval=interval, grace=grace)
    watch = Watch(service, check=check, interval=interval)
    watch.start()
    env = dict(env, SESSION_HARNESS_OWNER=watch.owner)
    stdin, stdout = sys.stdin.fileno(), sys.stdout.fileno()
    saved_tty = termios.tcgetattr(stdin) if os.isatty(stdin) else None
    saved_handlers = {}
    pid = master = None
    status = None
    exit_observer = None
    saved_flags = {}

    def interrupted(signum, _frame):
        raise _SignalStop(signum)

    def resize(_signum=None, _frame=None):
        if master is not None and saved_tty is not None:
            size = fcntl.ioctl(stdin, termios.TIOCGWINSZ, struct.pack("HHHH", 0, 0, 0, 0))
            fcntl.ioctl(master, termios.TIOCSWINSZ, size)

    try:
        for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT, signal.SIGWINCH):
            saved_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, resize if signum == signal.SIGWINCH else interrupted)
        pid, master = pty.fork()
        if pid == 0:
            try:
                for signum in saved_handlers:
                    signal.signal(signum, signal.SIG_DFL)
                os.execvpe(argv[0], argv, env)
            except BaseException:
                os._exit(127)
        exit_observer = ChildExit(pid)
        resize()
        if saved_tty is not None:
            tty.setraw(stdin)
        saved_flags = {fd: fcntl.fcntl(fd, fcntl.F_GETFL) for fd in {stdin, stdout}}
        for fd, flags in saved_flags.items():
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        os.set_blocking(master, False)
        to_child, to_stdout = bytearray(), bytearray()
        capacity, chunk = 256 * 1024, 16384
        input_open, master_open = True, True
        exit_deadline = None
        while True:
            watch.tick()
            readers = ([master] if master_open and len(to_stdout) < capacity else [])
            if input_open and len(to_child) < capacity and exit_deadline is None:
                readers.append(stdin)
            writers = ([stdout] if to_stdout else [])
            if master_open and to_child and exit_deadline is None:
                writers.append(master)
            ready, writable, _ = select.select(readers, writers, [], min(0.1, interval))
            if master in ready:
                try:
                    data = os.read(master, min(chunk, capacity - len(to_stdout)))
                except BlockingIOError:
                    data = None
                except OSError as exc:
                    if exc.errno != errno.EIO:
                        raise
                    data = b""
                if data is not None:
                    if data:
                        to_stdout.extend(data)
                    else:
                        master_open = False
            if stdin in ready:
                try:
                    data = os.read(stdin, min(chunk, capacity - len(to_child)))
                except BlockingIOError:
                    data = None
                if data is not None:
                    if data:
                        to_child.extend(data)
                    else:
                        input_open = False
            for fd, pending in ((stdout, to_stdout), (master, to_child)):
                if fd in writable and pending:
                    try:
                        written = os.write(fd, pending[:chunk])
                        del pending[:written]
                    except BlockingIOError:
                        pass
                    except OSError as exc:
                        if fd != master or exc.errno != errno.EIO:
                            raise
                        master_open = False
            # Keep the leader unreaped, and bound output draining after its exit.
            if exit_deadline is None:
                exited = exit_observer.ready()
                if exited or not master_open:
                    exit_deadline = time.monotonic() + 0.1
            if not master_open and not to_stdout:
                break
            if exit_deadline is not None and time.monotonic() >= exit_deadline:
                break
    except _SignalStop as exc:
        status = 128 + exc.signum
    except KeyboardInterrupt:
        status = 130
    finally:
        stopped = pid is None
        try:
            for signum in saved_handlers:
                signal.signal(signum, signal.SIG_IGN)
            if pid:
                child_status = _cleanup(pid, grace, exit_observer)
                stopped = True
                if status is None:
                    status = child_status if child_status >= 0 else 128 - child_status
        finally:
            if stopped:
                watch.close()
            if exit_observer is not None:
                exit_observer.close()
            if master is not None:
                os.close(master)
            for fd, flags in saved_flags.items():
                fcntl.fcntl(fd, fcntl.F_SETFL, flags)
            if saved_tty is not None:
                termios.tcsetattr(stdin, termios.TCSANOW, saved_tty)
            for signum, handler in saved_handlers.items():
                signal.signal(signum, handler)
    watch.finish()
    return status
