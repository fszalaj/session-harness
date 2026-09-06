"""Explicit paid text requests with durable monthly budget authorization."""
import argparse
import json
import os
import sqlite3
import sys

from spend import SpendLedger, estimate


def execute(service, model, prompt, max_output_tokens, reserve_cost, *, request_id=None,
            ledger=None, effort=None, timeout=120):
    if os.environ.get("SESSION_HARNESS_LEAF"):
        return {"status": "recursion_blocked"}
    import api_providers
    prepared = api_providers.preflight(service, model, prompt, max_output_tokens, effort)
    ledger = ledger or SpendLedger()
    rates = None
    if service not in {"xai", "openrouter"}:
        rates = ledger.rates(service, model)
        if rates["currency"] != "USD":
            raise ValueError("currency mismatch; API pricing requires USD")
    authorization = ledger.authorize("api:" + service, reserve_cost, "USD", prepared.digest, request_id)
    if not authorization["dispatch"]:
        return {"status": "duplicate_accounting_only", "accounting": ledger.request(authorization["id"])}
    identifier = authorization["id"]
    try:
        result = api_providers.execute(prepared, timeout=timeout)
        actual = result.get("actual_cost_ticks")
        if actual is not None:
            receipt = result.get("response_id") or identifier
            accounting = ledger.settle(identifier, actual, "provider:" + receipt)
        elif rates and result.get("usage_complete"):
            accounting = ledger.settle(identifier, estimate(result["usage"], rates["rates"]),
                                       rates["evidence"], kind="estimated")
        else:
            accounting = ledger.unresolved(identifier)
        valid = result.get("output_valid", False)
        return {"status": "completed" if valid else "output_rejected", "request_id": identifier,
                "model": result.get("model"), "text": result.get("text") if valid else None,
                "accounting": accounting,
                "budget_note": "Observed estimates and reservations cannot guarantee an exact provider charge."}
    except Exception:
        return {"status": "unresolved_dispatch", "request_id": identifier,
                "accounting": ledger.unresolved(identifier),
                "error": "Provider result or cost could not be verified; reservation retained. Do not retry automatically."}


def main(argv=None):
    if os.environ.get("SESSION_HARNESS_LEAF"):
        print(json.dumps({"status": "recursion_blocked"}))
        return 2
    import api_providers
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db")
    sub = parser.add_subparsers(dest="action", required=True)
    models = sub.add_parser("models")
    models.add_argument("service", choices=api_providers.SERVICES)
    run = sub.add_parser("run")
    run.add_argument("service", choices=api_providers.SERVICES)
    run.add_argument("--model", required=True)
    run.add_argument("--max-output-tokens", required=True, type=int)
    run.add_argument("--reserve-cost", required=True, help="Observed liability allowance, not a provider maximum charge")
    run.add_argument("--id")
    run.add_argument("--effort")
    run.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args(argv)
    try:
        if args.action == "models":
            result = api_providers.models(args.service)
        else:
            if not 1 <= args.timeout <= 600:
                raise ValueError("timeout must be between 1 and 600 seconds")
            artifact = sys.stdin.buffer.read(262145)
            if not artifact or len(artifact) > 262144:
                raise ValueError("provide at most 256 KiB text on stdin")
            result = execute(args.service, args.model, artifact.decode("utf-8"), args.max_output_tokens,
                             args.reserve_cost, request_id=args.id, ledger=SpendLedger(args.db),
                             effort=args.effort, timeout=args.timeout)
        print(json.dumps(result, indent=2))
        return 0 if result.get("status") in {"completed", "ok", "available", "catalog_available", "catalog_metadata"} else 2
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error, api_providers.APIError) as exc:
        message = str(exc) if type(exc) is ValueError else "API capability or configuration is unavailable."
        print(json.dumps({"status": "api_error", "error": message}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
