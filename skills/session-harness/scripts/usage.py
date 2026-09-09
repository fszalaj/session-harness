#!/usr/bin/env python3
"""Read native quota metadata, persist observations, and evaluate the private admission policy."""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time

from quota import Ledger
import credits


def epoch(value):
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Reset timestamps require a timezone")
        return parsed.timestamp()
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Invalid reset timestamp")
    return value


def snapshot(service, pools, source, complete=True, now=None):
    return dict(service=service, observed_at=time.time() if now is None else now,
                pools=pools, source=source, complete=complete)


def codex_snapshot(payload, now=None):
    rows = payload.get("rateLimitsByLimitId")
    if not isinstance(rows, dict) or not rows:
        primary = payload.get("rateLimits")
        rows = {primary.get("limitId", "default"): primary} if isinstance(primary, dict) else {}
    pools = []
    complete = bool(rows)
    for key, row in rows.items():
        if not isinstance(row, dict):
            complete = False
            continue
        for name in ("primary", "secondary"):
            window = row.get(name)
            if window is None:
                continue
            pools.append(dict(pool=f"{key}:{name}", used_percent=window["usedPercent"],
                              resets_at=epoch(window["resetsAt"]),
                              window_minutes=window["windowDurationMins"],
                              window_source="codex.windowDurationMins"))
        if row.get("spendControlReached") is True:
            pools.append(dict(pool=f"{key}:spend_control", used_percent=100,
                              resets_at=(time.time() if now is None else now) + 1))
    result = snapshot("codex", pools, "codex.account/rateLimits/read", complete, now)
    result["credit_resources"] = credits.codex_resources(rows)
    return result


def client_snapshot(service, payload, now=None):
    """Accept native fields and an optional trusted-adapter quota_observation envelope.

    The envelope is our contract, not a vendor payload or provenance verification.
    Only a separately verified reader may supply its backend timestamp assertion.
    """
    pools = []
    if service == "claude":
        rows = payload.get("rate_limits", {})
        if not isinstance(rows, dict):
            raise ValueError("Rate limits must be an object")
        for key, row in rows.items():
            if isinstance(row, dict) and "used_percentage" in row and "resets_at" in row:
                pools.append(dict(pool=key, used_percent=row["used_percentage"],
                                  resets_at=epoch(row["resets_at"])))
        complete = {"five_hour", "seven_day"}.issubset({pool["pool"] for pool in pools}) and len(pools) == len(rows)
    elif service == "antigravity":
        rows = payload.get("quota", {})
        complete = isinstance(rows, dict) and bool(rows)
        if not isinstance(rows, dict):
            raise ValueError("Quota must be an object")
        for key, row in rows.items():
            if not isinstance(row, dict) or "remaining_fraction" not in row or "reset_time" not in row:
                complete = False
                continue
            fraction = row["remaining_fraction"]
            if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not 0 <= fraction <= 1:
                raise ValueError("Invalid remaining fraction")
            pools.append(dict(pool=key, used_percent=100 * (1 - fraction),
                              resets_at=epoch(row["reset_time"])))
    else:
        raise ValueError("This client has no verified statusline quota contract")
    result = snapshot(service, pools, f"{service}.native_report", False, now)
    result["credit_resources"] = credits.missing(service)
    result["reported_pools_complete"] = complete
    result["freshness"] = "client_receipt_only_backend_time_unverified"
    metadata = payload.get("quota_observation")
    if metadata is not None:
        if not isinstance(metadata, dict) or metadata.get("provenance") != "backend":
            raise ValueError("Explicit backend quota observation provenance is required")
        observed_at = epoch(metadata.get("observed_at"))
        received_at = time.time() if now is None else now
        if observed_at < 0 or observed_at > received_at:
            raise ValueError("Invalid backend observation timestamp")
        result.update(observed_at=observed_at,
                      complete=complete and metadata.get("complete") is True,
                      source=f"{service}.backend_observation",
                      freshness="backend_observed_at")
    return result


def copilot_snapshot(rows, now=None, complete=False):
    pools, complete = [], complete and bool(rows)
    for row in rows:
        if row.get("entitlementRequests") == -1 or row.get("isUnlimitedEntitlement") is True:
            continue
        if "remainingPercentage" not in row or "resetDate" not in row:
            complete = False
            continue
        remaining = row["remainingPercentage"]
        if isinstance(remaining, bool) or not isinstance(remaining, (int, float)) or not math.isfinite(remaining) or not 0 <= remaining <= 100:
            raise ValueError("Invalid remaining percentage")
        pools.append(dict(pool=row["pool"], used_percent=100 - remaining,
                          resets_at=epoch(row["resetDate"])))
    result = snapshot("copilot", pools, "copilot.account.getQuota", complete, now)
    result["credit_resources"] = credits.copilot_resources(rows)
    return result


def refresh(service, *, ledger=None, initialize=False):
    ledger = ledger or Ledger()
    from quota_refresh import serialized
    with serialized(ledger, service):
        return _refresh(service, ledger=ledger, initialize=initialize)


def _refresh(service, *, ledger, initialize=False):
    if service == "codex":
        import harness
        executable = shutil.which("codex")
        if not executable:
            raise ValueError("Codex is not installed")
        rpc = harness.CodexRPC(executable)
        try:
            rpc.request("initialize", {"clientInfo": {"name": "session_harness_quota", "version": "2"}})
            rpc.notify("initialized")
            observed = codex_snapshot(rpc.request("account/rateLimits/read", {}))
        finally:
            rpc.close()
    elif service == "copilot":
        import inventory
        data = inventory.discover("copilot")
        if data.get("authenticated") is not True:
            raise ValueError("Copilot subscription metadata is unavailable")
        observed = copilot_snapshot(data["quota"], complete=data.get("quota_complete") is True)
    elif service in {"claude", "antigravity"}:
        import native_quota
        observed = native_quota.read_snapshot(service)
    else:
        result = ledger.check(service)
        result["refresh_status"] = "unsupported"
        result["allowed"] = False
        result["allowed_by_observed_threshold"] = False
        result["reasons"].append("unsupported_quota_refresh")
        return result
    if service == "antigravity":
        observed["credit_resources"] = credits.antigravity_resources()
    observed.setdefault("credit_resources", credits.missing(service))
    return credits.gate(ledger.record(observed, initialize=initialize), service)


def context_status(payload):
    window = payload.get("context_window", {})
    value = window.get("used_percentage", payload.get("current_context_used_percentage"))
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
        return {"status": "unknown", "action": "read_native_context_metadata"}
    action = "continue"
    if value >= 85:
        action = "compact"
    elif value >= 75:
        action = "reduce_context"
    elif value >= 60:
        action = "checkpoint"
    return {"status": "observed", "used_percent": value, "action": action, "advisory": True}


def require_admission(service, *, ledger=None, models=None):
    """Refresh metadata and check persisted policy for admission or runtime polling."""
    try:
        active_ledger = ledger or Ledger()
        try:
            active_ledger.require_setup("native", service)
        except ValueError as exc:
            return dict(allowed=False, exact_cap_supported=False,
                        reasons=[str(exc).split(";", 1)[0]], next_step="ai-session setup")
        result = refresh(service, ledger=active_ledger)
        if models is not None:
            scoped = active_ledger.check(service, models=models)
            if ("observed_at" not in result or result.get("observed_at") != scoped.get("observed_at")
                    or result.get("refresh_status") == "unsupported"):
                return dict(allowed=False, reasons=["quota_refresh_failed"])
            result = scoped
        # Recheck policy here even when an adapter supplies an inconsistent result.
        if active_ledger.mode() == "strict":
            result["allowed"] = False
            if "exact_request_bound_unavailable" not in result["reasons"]:
                result["reasons"].append("exact_request_bound_unavailable")
        return credits.gate(result, service)
    except Exception:
        return dict(allowed=False, exact_cap_supported=False, reasons=["quota_refresh_failed"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("refresh", "status", "check", "capture", "context", "hook", "credit-policy"))
    parser.add_argument("service", nargs="?", choices=("codex", "claude", "antigravity", "copilot", "cursor"))
    parser.add_argument("--initialize", action="store_true", help="Explicit prospective first baseline; prior daily use stays unknown")
    parser.add_argument("--model", help="Concrete Claude model for a scoped check or status")
    parser.add_argument("--db")
    parser.add_argument("--timezone", default=None)
    parser.add_argument("--renderer", help="Existing trusted statusline command; forward its original input/output")
    policy = parser.add_mutually_exclusive_group()
    policy.add_argument("--auto-top-up", choices=("disabled",), help="Record the owner's explicit account setting confirmation")
    policy.add_argument("--revoke-credit-policy", action="store_true", help="Remove the account's owner confirmation")
    args = parser.parse_args(argv)
    raw = None
    try:
        if args.model and (args.service != "claude" or args.action not in {"check", "status"}):
            parser.error("--model requires Claude check or status")
        if args.action == "credit-policy":
            if args.service != "codex" or args.db:
                parser.error("credit-policy supports the current Codex account only")
            print(json.dumps(credits.configure_codex_policy(disabled=args.auto_top_up == "disabled",
                                                           revoke=args.revoke_credit_policy), indent=2))
            return 0
        if args.auto_top_up or args.revoke_credit_policy:
            parser.error("credit policy options require the credit-policy action")
        if args.action in {"capture", "context"}:
            raw = sys.stdin.buffer.read(256 * 1024 + 1)
            if len(raw) > 256 * 1024:
                raise ValueError("Telemetry exceeds size bound")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("Telemetry must be an object")
        if args.action == "context":
            result = context_status(payload)
        else:
            if not args.service:
                parser.error("service is required")
            ledger = Ledger(args.db, timezone=args.timezone)
            if args.action == "refresh":
                result = refresh(args.service, ledger=ledger, initialize=args.initialize)
            elif args.action == "capture":
                result = ledger.record(client_snapshot(args.service, payload), initialize=args.initialize)
                result["context"] = context_status(payload)
            else:
                if args.action == "check":
                    import coordination
                    if args.service not in coordination.SERVICES:
                        result = dict(allowed=False, reasons=["unsupported_protected_coordination"])
                    else:
                        result = coordination.dispatch("check", args.service, "usage-preflight", ledger,
                                                       **({"models": [args.model]} if args.model else {}))
                else:
                    result = ledger.check(args.service, **({"models": [args.model]} if args.model else {}))
            credits.gate(result, args.service)
        if args.action == "hook":
            if not result.get("allowed"):
                print(json.dumps({"decision": "block", "reason": "Session harness: " + ", ".join(result["reasons"])}))
            return 0
        if args.renderer and raw is not None:
            return subprocess.run(args.renderer, shell=True, input=raw, timeout=5).returncode
        print(json.dumps(result, indent=2))
        return 2 if args.action == "check" and not result.get("allowed") else 0
    except Exception as exc:
        if args.renderer and raw is not None:
            try:
                return subprocess.run(args.renderer, shell=True, input=raw, timeout=5).returncode
            except Exception:
                return 2
        if args.action == "hook":
            print(json.dumps({"decision": "block", "reason": "Session harness quota evidence is unavailable"}))
            return 0
        print(json.dumps({"allowed": False, "error": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
