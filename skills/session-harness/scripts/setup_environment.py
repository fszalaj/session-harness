"""Configure private environment authorization without inference or account changes."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import re
import coordination
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from api_providers import SERVICES
from budget_policy import WEEKDAYS, parse_workdays, validate_calendar
from quota import Ledger, default_path
from spend import SpendLedger, amount, ticks

NATIVE_SERVICES = coordination.SERVICES


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--ledger", "--db", dest="ledger", help="Private shared ledger path")
    result.add_argument("--services", help="Comma-separated " + ','.join(NATIVE_SERVICES) + "; empty selects none")
    result.add_argument("--api-services", help="Comma-separated API services; empty selects none")
    result.add_argument("--timezone", help="IANA timezone; existing ledger timezone must match")
    result.add_argument("--workdays", help="all, weekdays, or comma-separated weekdays")
    result.add_argument("--cutoff", help="Reset cutoff HH:MM")
    result.add_argument("--mode", choices=("strict", "observed"))
    result.add_argument("--authority", help="local for one machine, or trusted SSH user@host for a shared quota authority")
    result.add_argument("--max-sessions", type=int, help="Concurrent sessions per service, 1..32; existing value is preserved")
    result.add_argument("--monthly-budget", help="Positive monthly total API budget")
    result.add_argument("--currency", choices=("USD",), default="USD")
    result.add_argument("--money-mode", choices=("strict", "observed"))
    result.add_argument("--yes", action="store_true", help="Confirm the displayed settings without prompting")
    operations = result.add_mutually_exclusive_group()
    operations.add_argument("--status", action="store_true")
    operations.add_argument("--reset", action="store_true", help="Clear setup authorization only")
    return result


def _services(value, allowed):
    selected = [part.strip() for part in value.split(",")] if value.strip() else []
    if len(selected) != len(set(selected)) or any(part not in allowed for part in selected):
        raise ValueError("services must be unique names from: " + ",".join(allowed))
    return selected


def _ask(stream, output, label, default=None):
    suffix = "" if default is None else f" [{default}]"
    output.write(f"{label}{suffix}: ")
    output.flush()
    answer = stream.readline()
    if not answer:
        raise EOFError
    answer = answer.strip()
    return answer if answer else default if default is not None else ""


def _confirm(args, stream, output):
    if args.yes:
        return True
    return _ask(stream, output, "Apply these private settings? Type yes", "no").lower() == "yes"


def _money_defaults(ledger):
    if ledger is None:
        return None
    with ledger._connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='money_caps'").fetchone():
            return None
        row = db.execute("SELECT cap,currency,mode FROM money_caps WHERE scope='total'").fetchone()
    return dict(monthly=amount(row[0]), currency=row[1], mode=row[2]) if row else None


def main(argv=None, *, input_stream=None, output_stream=None):
    stream = sys.stdin if input_stream is None else input_stream
    output = sys.stdout if output_stream is None else output_stream
    args = parser().parse_args(argv)
    try:
        path = Path(args.ledger) if args.ledger else default_path()
        ledger = Ledger(path) if path.exists() else None
        status = {"complete": False, "services": [], "api_services": []}
        if ledger and not args.reset:
            status = ledger.setup_status()
        changes = (args.services, args.api_services, args.timezone, args.workdays, args.cutoff,
                   args.mode, args.monthly_budget, args.money_mode, args.authority, args.max_sessions)
        if (args.status or args.reset) and any(value is not None for value in changes):
            raise ValueError("status/reset cannot be combined with configuration changes")
        if args.status:
            output.write(json.dumps(status, sort_keys=True) + "\n")
            return 0
        interactive = bool(stream.isatty())
        if not interactive and not args.yes:
            raise ValueError("noninteractive setup requires --yes")
        if args.reset:
            output.write("Clear setup authorization; retain budgets, balances and history.\n")
            if not _confirm(args, stream, output):
                return 130
            result = ledger.reset_setup() if ledger else status
            output.write(json.dumps(result, sort_keys=True) + "\n")
            return 0

        calendar = ledger.budget_calendar()["calendar"] if ledger else {
            "workdays": list(range(7)), "reset_cutoff": "08:30"}
        defaults = {
            "services": ",".join(status.get("services", [])),
            "api_services": ",".join(status.get("api_services", [])),
            "timezone": ledger.policy["timezone"] if ledger else "UTC",
            "workdays": ",".join(WEEKDAYS[day] for day in calendar["workdays"]),
            "cutoff": calendar["reset_cutoff"], "mode": ledger.mode() if ledger else "strict",
            "authority": coordination.settings(ledger)["authority"] if ledger else "local",
            "max_sessions": coordination.settings(ledger)["max_sessions"] if ledger else coordination.DEFAULT_MAX_SESSIONS,
        }
        output.write("Setup authorizes selected routes only; keys and model catalogs do not authorize spending.\n"
                     "Strict native mode requires enforceable bounds. Observed mode permits in-flight overshoot.\n")
        labels = {"services": "Native services (" + ",".join(NATIVE_SERVICES) + "; none to clear)",
                  "api_services": "API services (" + ",".join(SERVICES) + "; none to clear)",
                  "timezone": "Timezone", "workdays": "Workdays", "cutoff": "Reset cutoff",
                  "mode": "Native quota mode (strict/observed)",
                  "authority": "Quota authority (local for one machine, or trusted SSH user@host)",
                  "max_sessions": "Concurrent sessions per service (1..32, shared quota budget)"}
        values = {}
        for key, fallback in defaults.items():
            value = getattr(args, key)
            if value is None and interactive:
                value = _ask(stream, output, labels[key], fallback)
            if value is None:
                if key == "mode":
                    raise ValueError("noninteractive setup requires explicit --mode")
                value = fallback
            values[key] = value
        native = _services("" if values["services"] == "none" else values["services"], NATIVE_SERVICES)
        apis = _services("" if values["api_services"] == "none" else values["api_services"], SERVICES)
        if not native and not apis:
            raise ValueError("select at least one native or API service")
        ZoneInfo(values["timezone"])
        if ledger and values["timezone"] != ledger.policy["timezone"]:
            raise ValueError("existing ledger timezone cannot be changed by setup")
        schedule = validate_calendar({"workdays": parse_workdays(values["workdays"]),
                                      "reset_cutoff": values["cutoff"]})
        if values["mode"] not in {"strict", "observed"}:
            raise ValueError("native mode must be strict or observed")
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]{0,252}', values["authority"]):
            raise ValueError("invalid quota authority")
        values['max_sessions'] = int(values['max_sessions'])
        coordination.validate_settings({'authority': values['authority'], 'max_sessions': values['max_sessions']})
        if apis and values["authority"] != "local":
            raise ValueError("API money dispatch must run on the authority machine; remote money admission is unsupported")
        monthly, money_mode = args.monthly_budget, args.money_mode
        if apis:
            previous = _money_defaults(ledger)
            if previous and previous["currency"] != args.currency:
                raise ValueError("existing monetary currency cannot be changed by setup")
            output.write("API strict mode currently blocks dispatch: per-request costs cannot be proven in advance.\n"
                         "API observed mode accepts possible cost overruns; select it explicitly.\n")
            if interactive:
                if monthly is None:
                    monthly = _ask(stream, output, "Monthly total API budget (USD)", previous["monthly"] if previous else None)
                if money_mode is None:
                    money_mode = _ask(stream, output, "API money mode (strict/observed)", previous["mode"] if previous else None)
            if monthly is None or ticks(monthly) <= 0:
                raise ValueError("API setup requires a positive --monthly-budget")
            if money_mode not in {"strict", "observed"}:
                raise ValueError("API setup requires explicit --money-mode")
        elif monthly is not None or money_mode is not None:
            raise ValueError("money options require selected API services")
        preview = dict(services=native, api_services=apis, timezone=values["timezone"],
                       calendar=schedule, mode=values["mode"], authority=values["authority"],
                       max_sessions=values['max_sessions'])
        if apis:
            preview["money"] = dict(monthly_budget=monthly, currency=args.currency, mode=money_mode)
        output.write(json.dumps(preview, sort_keys=True) + "\n")
        if not _confirm(args, stream, output):
            output.write("Setup cancelled; authorization was not changed.\n")
            return 130
        if values['authority'] != 'local':
            output.write('The remote authority enforces its own session capacity; configure capacity there.\n')
        ledger = ledger or Ledger(path, timezone=values["timezone"])
        coordination.configure(ledger, values["authority"], values['max_sessions'])
        ledger.reset_setup()
        ledger.budget_calendar(workdays=schedule["workdays"], reset_cutoff=schedule["reset_cutoff"])
        ledger.set_mode(values["mode"])
        if apis:
            SpendLedger(ledger=ledger).configure("total", monthly, code=args.currency, mode=money_mode)
        result = ledger.complete_setup(services=native, api_services=apis,
                                       source="interactive" if interactive else "cli")
        output.write(json.dumps(result, sort_keys=True) + "\n")
        if apis:
            output.write(json.dumps(SpendLedger(ledger=ledger).status(), sort_keys=True) + "\n")
        return 0
    except (EOFError, KeyboardInterrupt):
        output.write("Setup cancelled; no new completion was recorded.\n")
        return 130
    except (ValueError, ZoneInfoNotFoundError, sqlite3.Error, OSError) as exc:
        output.write("Setup failed: " + str(exc) + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
