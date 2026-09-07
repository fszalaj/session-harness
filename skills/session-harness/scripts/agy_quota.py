"""Force-refresh quota through a private native CLI process, without terminal input."""
import http.client
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import ssl
import socket
import subprocess
import sys
import tempfile
import time
import threading

import harness

if os.name == "posix":
    import pty

MAX_RESPONSE = 256 * 1024
ENDPOINT = "/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary"


class BackendNotReady(ValueError):
    """The owned native server returned a transient server error."""


class NotQuotaTLS(ValueError):
    """The owned listener does not yet expose the native quota endpoint."""


def fail():
    raise ValueError("Native Antigravity quota refresh could not be verified.")


def linux_ports(pid):
    root = Path("/proc") / str(pid)
    inodes = set()
    for entry in (root / "fd").iterdir():
        try:
            target = os.readlink(entry)
        except FileNotFoundError:
            continue
        match = re.fullmatch(r"socket:\[(\d+)\]", target)
        if match:
            inodes.add(match[1])
    ports = set()
    for table in ("tcp", "tcp6"):
        try:
            lines = (root / "net" / table).read_text().splitlines()[1:]
        except FileNotFoundError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 10 or fields[3] != "0A" or fields[9] not in inodes:
                continue
            address, port = fields[1].split(":")
            if address in ("0100007F", "00000000", "00000000000000000000000000000000"):
                ports.add(int(port, 16))
    return ports


def darwin_ports(pid, timeout):
    executable = shutil.which("lsof")
    if not executable:
        fail()
    code, stdout, _ = harness.run([executable, "-nP", "-a", "-p", str(pid), "-iTCP",
                                   "-sTCP:LISTEN", "-Fn"], timeout=min(timeout, 3))
    if code not in (0, 1):
        fail()
    ports = set()
    for line in stdout.splitlines():
        match = re.fullmatch(r"n(?:127\.0\.0\.1|\*|\[::\]):(\d+)", line)
        if match:
            ports.add(int(match[1]))
    return ports


def owned_ports(pid, timeout):
    if sys.platform.startswith("linux"):
        return linux_ports(pid)
    if sys.platform == "darwin":
        return darwin_ports(pid, timeout)
    fail()


def refresh_owned_port(port, timeout):
    if type(port) is not int or not 1 <= port <= 65535 or timeout <= 0:
        fail()
    # Only the selected owned loopback socket uses its native self-signed TLS certificate.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    connection = http.client.HTTPSConnection("127.0.0.1", port, timeout=min(timeout, 1), context=context)
    watchdog = None
    deadline = time.monotonic() + timeout
    try:
        try:
            connection.connect()
        except (ssl.SSLError, ConnectionError, TimeoutError):
            raise NotQuotaTLS("Owned listener did not establish TLS.") from None
        owned_socket = connection.sock
        def expire():
            try:
                owned_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            fail()
        owned_socket.settimeout(remaining)
        watchdog = threading.Timer(remaining, expire)
        watchdog.daemon = True
        watchdog.start()
        try:
            connection.request("POST", ENDPOINT, body=json.dumps({"forceRefresh": True, "request": {}}),
                               headers={"Content-Type": "application/json", "Connect-Protocol-Version": "1"})
            response = connection.getresponse()
        except (ssl.SSLError, ConnectionError, http.client.HTTPException):
            raise NotQuotaTLS("Owned listener did not establish native HTTP.") from None
        if response.status == 404:
            raise NotQuotaTLS("Owned TLS listener does not expose the quota endpoint.")
        if 500 <= response.status <= 599:
            raise BackendNotReady("Native quota backend is not ready.")
        if response.status != 200:
            fail()
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            fail()
        return raw.decode("utf-8")
    finally:
        if watchdog is not None:
            watchdog.cancel()
        connection.close()


def parse_response(raw, observed_at):
    import native_quota as native
    data = native.decode(raw)
    if not isinstance(data, dict) or set(data) != {"response"} or not isinstance(data["response"], dict) or "groups" not in data["response"] or set(data["response"]) - {"groups", "description"}:
        fail()
    groups = data["response"]["groups"]
    if not isinstance(groups, list):
        fail()
    normalized = []
    for group in groups:
        if (not isinstance(group, dict) or set(group) - {"displayName", "description", "buckets"}
                or not isinstance(group.get("displayName"), str)
                or not isinstance(group.get("buckets"), list)):
            fail()
        buckets = []
        for bucket in group["buckets"]:
            if (not isinstance(bucket, dict)
                    or not {"bucketId", "window", "remainingFraction", "resetTime"} <= set(bucket)
                    or set(bucket) - {"bucketId", "displayName", "description", "window", "remainingFraction", "resetTime"}):
                fail()
            buckets.append(dict(id=bucket["bucketId"], window=bucket["window"],
                                remaining_fraction=bucket["remainingFraction"], reset_time=bucket["resetTime"]))
        normalized.append(dict(name=group["displayName"], buckets=buckets))
    pools = native.antigravity_pools(normalized, observed_at)
    result = native.envelope("antigravity", pools, observed_at)
    result.update(source="antigravity.native_owned_server.forceRefresh",
                  freshness="forced_backend_refresh_request_start")
    return result


def drain_terminal(master, stop, overflow):
    total = 0
    with selectors.DefaultSelector() as selector:
        selector.register(master, selectors.EVENT_READ)
        while not stop.is_set():
            for _, _ in selector.select(0.05):
                try:
                    chunk = os.read(master, 65536)
                except BlockingIOError:
                    continue
                except OSError:
                    return
                if not chunk:
                    return
                total += len(chunk)
                if total > harness.MAX_OUTPUT:
                    overflow.set()


def read_snapshot(executable):
    if os.name == 'nt':
        raise ValueError('Native Antigravity quota is unsupported on Windows')
    """Never reuse another process, send terminal input, or fall back to cached usage."""
    proc = None
    registered = False
    master = slave = None
    directory = None
    drainer = None
    stop, overflow = threading.Event(), threading.Event()
    try:
        deadline = time.monotonic() + 15
        directory = tempfile.TemporaryDirectory(prefix="session-harness-agy-quota-")
        master, slave = pty.openpty()
        proc = subprocess.Popen([executable, "--new-project", "--log-file", "/dev/null"],
                                stdin=slave, stdout=slave, stderr=subprocess.DEVNULL,
                                cwd=directory.name, env=harness.child_env(leaf=True),
                                start_new_session=True, close_fds=True)
        harness.register_process(proc)
        registered = True
        os.close(slave)
        slave = None
        os.set_blocking(master, False)
        drainer = threading.Thread(target=drain_terminal, args=(master, stop, overflow), daemon=True)
        drainer.start()
        raw = None
        while raw is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or proc._harness_exit.ready() or overflow.is_set():
                fail()
            ports = owned_ports(proc.pid, remaining)
            if len(ports) > 8:
                fail()
            for selected in sorted(ports):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or proc._harness_exit.ready() or overflow.is_set():
                    fail()
                if selected not in owned_ports(proc.pid, remaining):
                    fail()
                try:
                    delays = (0.2, 0.5, 1, 2)
                    for attempt in range(len(delays) + 1):
                        remaining = deadline - time.monotonic()
                        if (remaining <= 0 or proc._harness_exit.ready() or overflow.is_set()
                                or selected not in owned_ports(proc.pid, remaining)):
                            fail()
                        observed_at = time.time()
                        try:
                            raw = refresh_owned_port(selected, deadline - time.monotonic())
                            break
                        except BackendNotReady:
                            if attempt == len(delays) or deadline - time.monotonic() <= delays[attempt]:
                                fail()
                            stop.wait(delays[attempt])
                    break
                except NotQuotaTLS:
                    continue
            if raw is None:
                stop.wait(min(max(0, deadline - time.monotonic()), 0.05))
        if time.monotonic() >= deadline or proc._harness_exit.ready() or overflow.is_set():
            fail()
        return parse_response(raw, observed_at)
    except (ValueError, TypeError, KeyError, AttributeError, OSError, http.client.HTTPException, harness.HarnessError):
        raise ValueError("Native Antigravity quota refresh could not be verified.") from None
    finally:
        try:
            if proc is not None:
                harness.stop_group(proc)
        finally:
            if registered:
                harness.unregister_process(proc)
            stop.set()
            if drainer is not None:
                drainer.join(timeout=1)
            for fd in (master, slave):
                if fd is not None:
                    os.close(fd)
            if directory is not None:
                directory.cleanup()
