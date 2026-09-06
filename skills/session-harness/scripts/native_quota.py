"""Metadata-only native quota readers; diagnostics never leave process memory."""
from datetime import datetime
from collections import Counter
import json
import math
import re
import shutil
import tempfile
import time
import uuid

import harness
import credits


class NativeQuotaError(ValueError):
    """A safe, deliberately non-diagnostic metadata failure."""


def invalid():
    raise NativeQuotaError("Native quota metadata could not be verified.")


def number(value, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= maximum:
        invalid()
    return value


def timestamp(value, observed_at):
    if value is None:
        return None
    if not isinstance(value, str):
        invalid()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        result = parsed.timestamp()
    except (ValueError, OverflowError, OSError):
        invalid()
    if parsed.tzinfo is None or not math.isfinite(result):
        invalid()
    return result


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            invalid()
        result[key] = value
    return result


def decode(raw):
    return json.loads(raw, object_pairs_hook=object_pairs,
                      parse_constant=lambda _: invalid())


def add_pool(pools, identity, used, reset, observed_at):
    if not isinstance(identity, str) or not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,128}", identity):
        invalid()
    if any(pool["pool"] == identity for pool in pools):
        invalid()
    pools.append(dict(pool=identity, used_percent=number(used, 100),
                      resets_at=timestamp(reset, observed_at)))


def envelope(service, pools, observed_at):
    if not pools:
        invalid()
    return dict(service=service, pools=pools, observed_at=observed_at,
                source=service + ".native_backend_refresh", complete=True,
                freshness="backend_refresh_request_start")


def validate_native_limit(row, observed_at):
    allowed = {"utilization", "resets_at", "limit_dollars", "used_dollars", "remaining_dollars", "locked_reason"}
    if not isinstance(row, dict) or set(row) - allowed or not {"utilization", "resets_at"}.issubset(row):
        invalid()
    number(row["utilization"], 100)
    if row["resets_at"] is not None:
        timestamp(row["resets_at"], observed_at)
    if any(row.get(key) is not None for key in ("limit_dollars", "used_dollars", "remaining_dollars", "locked_reason")):
        invalid()


def claude_snapshot(stdout, stderr, request_ids, observed_at):
    import hashlib
    markers = ("fetchUtilization: GET /api/oauth/usage (attempt 1)",
               "fetchUtilization: 200 after 1 attempt(s)")
    if any(stderr.count(marker) != 1 for marker in markers) or stderr.index(markers[0]) >= stderr.index(markers[1]):
        invalid()
    responses = {}
    for line in stdout.splitlines():
        if not line.strip():
            continue
        event = decode(line)
        if event.get("type") != "control_response":
            invalid()
        response = event["response"]
        identity = response["request_id"]
        if response.get("subtype") != "success" or identity not in request_ids or identity in responses:
            invalid()
        responses[identity] = response["response"]
    if set(responses) != set(request_ids):
        invalid()
    data = responses[request_ids[1]]
    session = data["session"]
    if (data.get("rate_limits_available") is not True or data.get("behaviors", "missing") is not None
            or session.get("model_usage") != {}):
        invalid()
    for key in ("total_cost_usd", "total_api_duration_ms", "total_lines_added", "total_lines_removed"):
        if number(session[key], 0) != 0:
            invalid()
    number(session["total_duration_ms"], 15000)
    rates = data["rate_limits"]
    allowed = {"five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet", "limits",
               "model_scoped", "extra_usage", "spend", "member_dashboard_available"}
    credit_resources = credits.claude_resources(rates)
    if "member_dashboard_available" in rates and not isinstance(rates["member_dashboard_available"], bool):
        invalid()
    limits, scoped = rates["limits"], rates["model_scoped"]
    if not isinstance(limits, list) or not isinstance(scoped, list):
        invalid()
    pools, globals_seen, projections = [], set(), []
    for row in limits:
        kind = row["kind"]
        if not isinstance(row.get("is_active"), bool):
            invalid()
        if kind in ("session", "weekly_all"):
            if row.get("scope") is not None or row.get("group") != ("session" if kind == "session" else "weekly"):
                invalid()
            globals_seen.add(kind)
            native = rates["five_hour" if kind == "session" else "seven_day"]
            validate_native_limit(native, observed_at)
            if number(native["utilization"], 100) != number(row["percent"], 100) or native["resets_at"] != row["resets_at"]:
                invalid()
            identity = kind
        elif kind == "weekly_scoped":
            scope = row["scope"]
            if row.get("group") != "weekly" or set(scope) != {"model", "surface"} or scope["surface"] is not None:
                invalid()
            model = scope["model"]
            if set(model) != {"id", "display_name"} or not isinstance(model["display_name"], str) or not model["display_name"]:
                invalid()
            if model["id"] is not None and not isinstance(model["id"], str):
                invalid()
            identity = kind + ":" + hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
            projections.append((model["display_name"], row["percent"], row["resets_at"]))
        else:
            invalid()
        add_pool(pools, identity, row["percent"], row["resets_at"], observed_at)
        pools[-1].update(window_minutes=300 if kind == "session" else 10080,
                         window_source="claude.native_limit_kind")
    expected = []
    for row in scoped:
        if set(row) != {"display_name", "utilization", "resets_at"}:
            invalid()
        number(row["utilization"], 100)
        timestamp(row["resets_at"], observed_at)
        expected.append((row["display_name"], row["utilization"], row["resets_at"]))
    if globals_seen != {"session", "weekly_all"} or Counter(projections) != Counter(expected):
        invalid()
    for key in ("seven_day_opus", "seven_day_sonnet"):
        row = rates.get(key)
        if row is None:
            continue
        validate_native_limit(row, observed_at)
        family = key.removeprefix("seven_day_")
        matches = [entry for entry in expected if family in re.findall(r"[a-z]+", entry[0].lower())]
        if len(matches) != 1 or matches[0][1:] != (row["utilization"], row["resets_at"]):
            add_pool(pools, "native:" + key, row["utilization"], row["resets_at"], observed_at)
            pools[-1].update(window_minutes=10080, window_source="claude.native_limit_kind")
    for key in sorted(set(rates) - allowed):
        row = rates[key]
        if row is None:
            continue
        validate_native_limit(row, observed_at)
        add_pool(pools, "native:" + key, row["utilization"], row["resets_at"], observed_at)
    result = envelope("claude", pools, observed_at)
    result["credit_resources"] = credit_resources
    return result


def antigravity_pools(groups, observed_at):
    if not isinstance(groups, list) or not groups:
        invalid()
    pools, group_names = [], set()
    for group in groups:
        name = group["name"]
        if not isinstance(name, str) or not name or name in group_names:
            invalid()
        group_names.add(name)
        buckets = group["buckets"]
        if not isinstance(buckets, list) or not buckets:
            invalid()
        windows = set()
        for bucket in buckets:
            window = bucket["window"]
            if window not in ("5h", "weekly") or window in windows:
                invalid()
            windows.add(window)
            known_windows = {"gemini-weekly": "weekly", "gemini-5h": "5h", "3p-weekly": "weekly", "3p-5h": "5h"}
            if bucket["id"] in known_windows and known_windows[bucket["id"]] != window:
                invalid()
            fraction = number(bucket["remaining_fraction"], 1)
            add_pool(pools, bucket["id"], 100 * (1 - fraction), bucket["reset_time"], observed_at)
            pools[-1].update(window_minutes=300 if window == "5h" else 10080,
                             window_source="antigravity.bucket.window")
        if windows != {"5h", "weekly"}:
            invalid()
    if not {"gemini-weekly", "gemini-5h", "3p-weekly", "3p-5h"}.issubset({pool["pool"] for pool in pools}):
        invalid()
    return pools


def read_snapshot(service):
    """Run only established metadata protocols, without model prompts."""
    try:
        if service not in ("claude", "antigravity"):
            invalid()
        executable = harness.platform_runtime.which("claude" if service == "claude" else "agy")
        if executable is None:
            invalid()
        if service == "antigravity":
            import agy_quota
            return agy_quota.read_snapshot(executable)
        stdin = b""
        request_ids = (uuid.uuid4().hex, uuid.uuid4().hex)
        argv = [executable, "--safe-mode", "--no-session-persistence", "--no-chrome",
                "--strict-mcp-config", "--setting-sources", "", "--tools", "",
                "--permission-mode", "dontAsk", "--input-format", "stream-json",
                "--output-format", "stream-json", "--verbose", "--debug-file", "/dev/stderr", "-p"]
        requests = [dict(type="control_request", request_id=request_ids[0], request=dict(subtype="initialize")),
                    dict(type="control_request", request_id=request_ids[1], request=dict(subtype="get_usage", skip_behaviors=True))]
        stdin = ("\n".join(json.dumps(row) for row in requests) + "\n").encode()
        with tempfile.TemporaryDirectory(prefix="session-harness-quota-") as directory:
            from pathlib import Path
            import os
            debug = Path(directory) / 'native-debug.log'
            if os.name == 'nt':
                from windows_security import prepare_private_file
                prepare_private_file(debug)
                argv[argv.index('--debug-file') + 1] = str(debug)
            observed_at = time.time()
            code, stdout, stderr = harness.run(argv, stdin=stdin, timeout=15, cwd=directory,
                                               env=harness.child_env(leaf=True))
            if os.name == 'nt':
                with debug.open('rb') as stream:
                    diagnostics = stream.read(256 * 1024 + 1)
                if len(diagnostics) > 256 * 1024:
                    invalid()
                stderr += diagnostics.decode('utf-8', 'strict')
        if code or time.time() - observed_at > 15 or time.time() < observed_at:
            invalid()
        return claude_snapshot(stdout, stderr, request_ids, observed_at)
    except (ValueError, TypeError, KeyError, AttributeError, OSError, harness.HarnessError):
        raise NativeQuotaError("Native quota metadata could not be verified.") from None
