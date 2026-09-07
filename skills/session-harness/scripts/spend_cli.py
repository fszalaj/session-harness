"""Configure private monthly money caps without enabling provider billing."""
import argparse
from datetime import datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import sys

from spend import SpendLedger, ticks


def main(argv=None):
    if os.environ.get("SESSION_HARNESS_LEAF"):
        print(json.dumps({"status": "recursion_blocked"}))
        return 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    configure = sub.add_parser("set")
    configure.add_argument("scope")
    configure.add_argument("--monthly", required=True)
    configure.add_argument("--currency", default="USD")
    configure.add_argument("--mode", choices=("strict", "observed"), default="strict")
    add = sub.add_parser("add")
    add.add_argument("scope")
    add.add_argument("amount")
    add.add_argument("--id")
    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("id")
    reconcile.add_argument("--actual", required=True)
    reconcile.add_argument("--evidence", required=True)
    record = sub.add_parser("record")
    record.add_argument("scope")
    record.add_argument("--actual", required=True)
    record.add_argument("--currency", default="USD")
    record.add_argument("--evidence", required=True)
    record.add_argument("--id")
    rates = sub.add_parser("rates")
    rates.add_argument("service")
    rates.add_argument("model")
    rates.add_argument("--file", required=True, help="JSON: currency, rates per million tokens, observed_at, expires_at, evidence")
    args = parser.parse_args(argv)
    try:
        ledger = SpendLedger(args.db)
        if args.action == "set":
            result = ledger.configure(args.scope, args.monthly, args.currency, args.mode)
        elif args.action == "add":
            result = ledger.add(args.scope, args.amount, args.id)
        elif args.action == "reconcile":
            result = ledger.settle(args.id, ticks(args.actual), args.evidence, reconcile=True)
        elif args.action == "record":
            result = ledger.record_expense(args.scope, args.actual, args.currency, args.evidence, args.id)
        elif args.action == "rates":
            with Path(args.file).open("rb") as source:
                raw = source.read(65537)
            if len(raw) > 65536:
                raise ValueError("rate file too large")
            def invalid_constant(value):
                raise ValueError("nonfinite rate data")
            data = json.loads(raw, parse_float=Decimal, parse_constant=invalid_constant)
            def timestamp(value):
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("rate timestamps need an offset")
                return parsed.timestamp()
            ledger.set_rates(args.service, args.model, data["rates"], timestamp(data["observed_at"]),
                             timestamp(data["expires_at"]), data["evidence"], data["currency"])
            result = {"status": "rates_saved"}
        else:
            result = ledger.status()
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"status": "money_error", "error": str(exc) if type(exc) is ValueError else "Invalid monetary configuration, evidence or unavailable private storage."}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
