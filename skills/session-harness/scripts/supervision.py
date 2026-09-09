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

    def __init__(self, service, reasons, *, receipt=None):
        import model_scope
        self.model_scope_stop = model_scope.scope_only_denial(receipt)
        self.service = service
        known = {"missing_snapshot", "stale_or_future_snapshot", "incomplete_pools",
                 "new_day_needs_observation", "unknown_daily_consumption", "daily_limit",
                 "reserve_floor", "reset_needs_fresh_evidence", "stale_pool",
                 "exact_request_bound_unavailable", "invalid_ledger", "quota_refresh_failed",
                 "quota_admission_denied", "unsupported_quota_refresh",
                 "account_session_busy", "account_maintenance", "coordination_unavailable", "environment_setup_required", "service_not_configured",
                 "unknown_adaptive_reset", "unknown_window", "budget_anchor_missing", "native_growth_limit", "not_work_day", "credit_metadata_invalid", "credit_metadata_unverified", "native_paid_execution_unsupported"}
        self.reasons = tuple(dict.fromkeys(reason.rsplit(":", 1)[-1] for reason in reasons
                                         if isinstance(reason, str) and reason.rsplit(":", 1)[-1] in known)) or ("quota_admission_denied",)
        super().__init__("Quota supervision stopped: " + ", ".join(self.reasons))

    def explanation(self):
        if "daily_limit" in self.reasons or "native_growth_limit" in self.reasons:
            return "Today's harness allowance has been reached."
        if "account_session_busy" in self.reasons:
            return "All protected session slots are occupied."
        if "account_maintenance" in self.reasons:
            return "The shared account is undergoing maintenance."
        if "reserve_floor" in self.reasons:
            return "The configured remaining-usage reserve has been reached."
        if "exact_request_bound_unavailable" in self.reasons:
            return "Strict mode cannot verify an enforceable request bound."
        if "environment_setup_required" in self.reasons or "service_not_configured" in self.reasons:
            return "This service is not authorized by the current setup."
        return "Quota supervision could not authorize further work."


class Watch:
    def __init__(self, service, check=None, interval=15, clock=time.monotonic, models=None):
        self.models = models
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
                models = self.models() if callable(self.models) else self.models
                result = dispatch('admit', self.service, self.owner, **({'models': models} if models is not None else {}))
            else:
                result = self.check(self.service)
        except Exception:
            raise Stop(self.service, ["quota_refresh_failed"]) from None
        if not isinstance(result, dict) or result.get("allowed") is not True:
            reasons = result.get("reasons", []) if isinstance(result, dict) else []
            raise Stop(self.service, reasons if isinstance(reasons, (list, tuple)) else [], receipt=result)
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
        deadline = time.monotonic() + 2
        try:
            while True:
                reaped, status = os.waitpid(pid, os.WNOHANG)
                if reaped == pid:
                    return os.waitstatus_to_exitcode(status)
                if time.monotonic() >= deadline:
                    raise OSError(errno.ETIMEDOUT, "Owned child exit could not be confirmed")
                time.sleep(0.01)
        except ChildProcessError:
            raise OSError(errno.ECHILD, "Owned child exit could not be confirmed") from None
    finally:
        if owned_observer:
            observer.close()


def run_terminal(argv, env, service, *, check=None, interval=15, grace=1.0, models=None, on_stop=None, input_ready=None):
    """Relay a PTY and stop its entire owned group when observation denies work."""
    if not math.isfinite(grace) or grace < 0:
        raise ValueError("Cleanup grace must be nonnegative and finite")
    if os.name == 'nt':
        if models is not None:
            raise ValueError('Model-scoped interactive supervision requires POSIX')
        from platform_runtime import terminal
        return terminal(argv, env, service, check=check, interval=interval, grace=grace)
    watch = Watch(service, check=check, interval=interval, models=models)
    watch.start()
    env = dict(env, SESSION_HARNESS_OWNER=watch.owner)
    stdin, stdout = sys.stdin.fileno(), sys.stdout.fileno()
    saved_tty = termios.tcgetattr(stdin) if os.isatty(stdin) else None
    saved_handlers = {}
    pid = master = None
    status = None
    exit_observer = None
    saved_flags = {}
    primary_error = None
    tearing_down, deferred_signals = False, []

    def interrupted(signum, _frame):
        if tearing_down or isinstance(sys.exc_info()[1], (Stop, _SignalStop, KeyboardInterrupt)):
            deferred_signals.append(signum)
            return
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
            if exit_deadline is None and not exit_observer.ready():
                watch.tick()
            readers = ([master] if master_open and len(to_stdout) < capacity else [])
            if input_open and len(to_child) < capacity and exit_deadline is None and (input_ready is None or input_ready()):
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
    except BaseException as exc:
        primary_error = exc
        if isinstance(exc, Stop):
            exc.inference_interrupted = pid is not None and not exit_observer.ready()
            if on_stop is not None:
                try:
                    on_stop(exc)
                except Exception:
                    exc.inference_interrupted = False
        raise
    finally:
        tearing_down = True
        stopped = pid is None
        errors = []

        def restore(stage, operation, *args):
            try:
                return operation(*args)
            except BaseException as exc:
                errors.append((stage, exc))
                return None

        def reset_screen():
            data = b"\x1b[?1049l\x1b[?25h\x1b[0m\x1b[?2004l\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?1004l"
            if os.write(stdout, data) != len(data):
                raise OSError(errno.EIO, "Terminal reset was incomplete")

        for signum in saved_handlers:
            restore("ignore_signal", signal.signal, signum, signal.SIG_IGN)
        if pid:
            child_status = restore("process_group", _cleanup, pid, grace, exit_observer)
            stopped = child_status is not None
            if stopped and status is None:
                status = child_status if child_status >= 0 else 128 - child_status
        if stopped:
            restore("owner_release", watch.close)
        if exit_observer is not None:
            restore("exit_observer", exit_observer.close)
        if master is not None:
            restore("pty_close", os.close, master)
        for fd, flags in saved_flags.items():
            restore("descriptor_flags", fcntl.fcntl, fd, fcntl.F_SETFL, flags)
        if saved_tty is not None:
            restore("terminal_attributes", termios.tcsetattr, stdin, termios.TCSANOW, saved_tty)
        if pid and os.isatty(stdout):
            restore("terminal_screen", reset_screen)
        for signum, handler in saved_handlers.items():
            restore("signal_handler", signal.signal, signum, handler)
        if deferred_signals:
            errors.extend(("teardown_signal", _SignalStop(signum)) for signum in deferred_signals)
        if isinstance(primary_error, Stop):
            primary_error.session_cleanup = {"state": "stopped" if stopped else "unknown",
                                             "owner_retained": not stopped, "errors": []}
        if errors:
            error = primary_error if primary_error is not None else errors[0][1]
            if primary_error is None and not isinstance(error, (Stop, OSError)):
                error = OSError(errno.EIO, "Session cleanup failed")
            error.session_cleanup = {
                "state": "not_started" if pid is None else "stopped" if stopped else "unknown",
                "owner_retained": not stopped,
                "errors": [{"stage": stage, "errno": exc.errno if isinstance(exc, OSError) else None}
                           for stage, exc in errors],
            }
            if not stopped:
                error.session_cleanup["owner"] = watch.owner
            if primary_error is None:
                raise error from None
    watch.finish()
    return status
