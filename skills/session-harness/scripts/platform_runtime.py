"""Owned Windows processes and bounded pipe transport; POSIX callers stay native."""
import ctypes
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import time

WINDOWS = os.name == 'nt'


def which(name):
    if not WINDOWS:
        return shutil.which(name)
    paths = [p for p in os.environ.get('PATH', '').split(os.pathsep)
             if p and Path(p).is_absolute() and Path(p).resolve() != Path.cwd()]
    # Python's Windows which can prepend CWD even with an explicit PATH.
    for directory in paths:
        for suffix in ('', '.exe', '.cmd'):
            candidate = Path(directory) / (name + suffix)
            if candidate.is_file(): return str(candidate)
    return None


def executable_argv(argv):
    """Resolve without searching the working directory or invoking a batch shell."""
    if not WINDOWS:
        return argv
    candidate = Path(argv[0])
    if not candidate.is_absolute():
        found = which(str(candidate))
        if not found:
            raise OSError('Executable unavailable on trusted PATH; use an absolute executable path')
        candidate = Path(found)
    if candidate.suffix.lower() in {'.cmd', '.bat'}:
        text = candidate.read_text(encoding='utf-8')
        # Only the standard npm shim's final node invocation is accepted.
        match = re.search(r'^endLocal & goto #_undefined_# 2>NUL \|\| title %COMSPEC% & "%_prog%"\s+"%dp0%\\([^"\r\n]+\.js)" %\*\s*$', text, re.M)
        if (not match or 'SET "_prog=node.exe"' not in text or
                'SET "_prog=%dp0%\\node.exe"' not in text or len(text) > 8192):
            raise OSError('Unsupported batch shim; use the absolute native executable or node script')
        script = (candidate.parent / match[1]).resolve()
        if not script.is_relative_to(candidate.parent.resolve()) or not script.is_file():
            raise OSError('Invalid npm shim target')
        node = candidate.parent / 'node.exe'
        prefix = executable_argv([str(node)]) if node.is_file() else executable_argv(['node.exe'])
        return [*prefix, str(script), *argv[1:]]
    if candidate.suffix.lower() != '.exe' or not candidate.is_file():
        raise OSError('Windows execution requires a native executable')
    return [str(candidate.resolve()), *argv[1:]]


if WINDOWS:
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    for name, args, result in [
        ('CreateJobObjectW', [ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
        ('SetInformationJobObject', [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
        ('AssignProcessToJobObject', [w.HANDLE, w.HANDLE], w.BOOL),
        ('TerminateJobObject', [w.HANDLE, w.UINT], w.BOOL),
        ('CreateEventW', [ctypes.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR], w.HANDLE),
        ('SetHandleInformation', [w.HANDLE, w.DWORD, w.DWORD], w.BOOL),
        ('SetEvent', [w.HANDLE], w.BOOL),
        ('CloseHandle', [w.HANDLE], w.BOOL),
        ('WaitForSingleObject', [w.HANDLE, w.DWORD], w.DWORD),
    ]:
        fn = getattr(kernel, name); fn.argtypes = args; fn.restype = result

    class BasicLimits(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                    ('flags', w.DWORD), ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t),
                    ('active', w.DWORD), ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [('basic', BasicLimits), ('io', ctypes.c_uint64 * 6),
                    ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                    ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]


def spawn(argv, **kwargs):
    if not WINDOWS:
        return subprocess.Popen(argv, **kwargs)
    argv = executable_argv(argv)
    kwargs.pop('start_new_session', None)
    job = kernel.CreateJobObjectW(None, None)
    event = kernel.CreateEventW(None, True, False, None)
    proc = None
    try:
        if not job or not event:
            raise OSError('Windows process ownership initialization failed')
        limits = ExtendedLimits(); limits.basic.flags = 0x2000
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise OSError('Windows kill-on-close job configuration failed')
        if not kernel.SetHandleInformation(event, 1, 1):
            raise OSError('Windows process gate initialization failed')
        startup = subprocess.STARTUPINFO()
        startup.lpAttributeList = {'handle_list': [event]}
        proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--gate', str(event), json.dumps(argv)],
                                startupinfo=startup, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                                close_fds=True, **kwargs)
        if not kernel.AssignProcessToJobObject(job, int(proc._handle)):
            raise OSError('Windows job assignment denied (including incompatible nested job); execution blocked')
        proc._harness_job = job
        if not kernel.SetEvent(event):
            raise OSError('Windows process gate release failed')
        job = None
        return proc
    except BaseException:
        if proc is not None:
            proc.kill(); proc.wait(timeout=2)
        raise
    finally:
        if event: kernel.CloseHandle(event)
        if job: kernel.CloseHandle(job)


def stop(proc):
    job = getattr(proc, '_harness_job', None)
    if job:
        if not kernel.TerminateJobObject(job, 1):
            raise OSError('Windows owned job termination failed')
        return proc.wait(timeout=3)
    raise OSError('Windows process has no owned job; unsafe cleanup refused')


def close(proc):
    job = getattr(proc, '_harness_job', None)
    for pipe in (proc.stdin, proc.stdout, proc.stderr):
        for thread in getattr(pipe, '_harness_writers', []):
            thread.join(timeout=1)
            if thread.is_alive():
                raise OSError('Windows pipe writer did not stop after process cleanup')
    if job:
        kernel.CloseHandle(job)
        proc._harness_job = None


class Reader:
    def __init__(self, pipe):
        self.pipe = pipe
        self.queue = queue.Queue(maxsize=16)
        self.cancel = threading.Event()
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        try:
            while not self.cancel.is_set():
                data = os.read(self.pipe.fileno(), 65536)
                while not self.cancel.is_set():
                    try:
                        self.queue.put(data, timeout=.05); break
                    except queue.Full:
                        pass
                if not data: break
        except (OSError, ValueError):
            if not self.cancel.is_set():
                try: self.queue.put(b'', timeout=.1)
                except queue.Full: pass

    def read(self, timeout=.1):
        try: return self.queue.get(timeout=timeout)
        except queue.Empty: return None

    def close(self):
        self.cancel.set()
        self.thread.join(timeout=1)
        if self.thread.is_alive():
            raise OSError('Windows pipe reader did not stop after owned process cleanup')


def write(pipe, data, timeout):
    done = threading.Event(); errors = []
    def worker():
        try:
            pending = memoryview(data)
            while pending:
                count = os.write(pipe.fileno(), pending[:4096]); pending = pending[count:]
        except (OSError, ValueError) as error:
            errors.append(error)
        finally: done.set()
    thread = threading.Thread(target=worker, daemon=True)
    threads = getattr(pipe, '_harness_writers', [])
    pipe._harness_writers = [item for item in threads if item.is_alive()] + [thread]
    thread.start()
    if not done.wait(timeout):
        raise TimeoutError('Windows pipe write deadline exceeded')
    if errors: raise errors[0]


def terminal(argv, env, service, check=None, interval=15, grace=1):
    from supervision import Watch
    watch = Watch(service, check=check, interval=interval); watch.start()
    proc = spawn(argv, env=env)
    code = None
    try:
        while proc.poll() is None:
            watch.tick(); time.sleep(min(.1, interval))
        code = proc.returncode
    finally:
        stop(proc); close(proc)
    watch.finish()
    return code


def run(argv, *, stdin=b'', timeout=15, cwd=None, env=None, on_stdout_line=None, quota_service=None):
    import harness
    from supervision import Watch
    watch = Watch(quota_service) if quota_service else None
    if watch: watch.start()
    proc = spawn(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                 cwd=cwd, env=harness.child_env(env), bufsize=0)
    harness.register_process(proc)
    readers = {name: Reader(getattr(proc, name)) for name in ('stdout', 'stderr')}
    result = {'stdout': bytearray(), 'stderr': bytearray()}
    pending = b''; deadline = time.monotonic() + timeout
    input_errors = []
    def send():
        try:
            write(proc.stdin, stdin, timeout)
        except (OSError, ValueError, TimeoutError) as error:
            input_errors.append(error)
        finally:
            proc.stdin.close()
    sender = threading.Thread(target=send, daemon=True); sender.start()
    active = set(readers)
    try:
        while active or proc.poll() is None:
            if watch: watch.tick()
            if time.monotonic() >= deadline:
                raise harness.HarnessError('timeout', 'CLI exceeded the bounded timeout.')
            for name in tuple(active):
                chunk = readers[name].read(.02)
                if chunk is None: continue
                if not chunk:
                    active.remove(name)
                    if name == 'stdout' and on_stdout_line and pending.strip():
                        on_stdout_line(pending.decode('utf-8', 'replace')); pending = b''
                    continue
                result[name].extend(chunk)
                if sum(map(len, result.values())) > harness.MAX_OUTPUT:
                    raise harness.HarnessError('output_limit', 'CLI exceeded the output limit.')
                if name == 'stdout' and on_stdout_line:
                    pending += chunk
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1)
                        if line.strip(): on_stdout_line(line.decode('utf-8', 'replace'))
        code = proc.returncode
    finally:
        try: stop(proc)
        finally:
            harness.unregister_process(proc)
            sender.join(timeout=1)
            for reader in readers.values(): reader.close()
            for pipe in (proc.stdout, proc.stderr): pipe.close()
    if sender.is_alive():
        raise harness.HarnessError('cleanup_failed', 'Windows input writer did not stop')
    if watch: watch.finish()
    return code, result['stdout'].decode('utf-8', 'replace'), result['stderr'].decode('utf-8', 'replace')


if __name__ == '__main__':
    if not WINDOWS or len(sys.argv) != 4 or sys.argv[1] != '--gate':
        raise SystemExit(2)
    gate = int(sys.argv[2])
    if kernel.WaitForSingleObject(gate, 10000) != 0:
        raise SystemExit(2)
    kernel.CloseHandle(gate)
    child = subprocess.Popen(json.loads(sys.argv[3]))
    raise SystemExit(child.wait())
