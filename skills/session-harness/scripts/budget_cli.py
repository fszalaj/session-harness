"""Inspect and adjust private subscription budgets without model inference."""
import argparse
from datetime import datetime, timezone
import json
import sqlite3
from zoneinfo import ZoneInfo

from quota import Ledger
from budget_policy import WEEKDAYS, parse_workdays


def display(result):
    """Show percentages per pool, never sum unlike allowances."""
    settings = result["calendar"]
    schedule = settings["calendar"]
    days = ",".join(WEEKDAYS[d] for d in schedule["workdays"])
    print(f"Calendar: {settings['timezone']} | workdays {days} | reset cutoff {schedule['reset_cutoff']}")
    print(f"Default strategy: {result['defaults']['default_strategy']} | fixed daily limit: {result['defaults']['default_daily_limit']:g} pp")
    print(f"Default reserve: {result['defaults']['default_reserve']:g}% (explicit service/pool settings take precedence)")
    for status in result["services"]:
        zone = ZoneInfo(status["policy"]["timezone"])
        print(f"{status['service']} | {status.get('day', 'no observation')} | "
              f"{status.get('mode', 'strict')} | {zone.key}")
        for row in status.get("pools", []):
            def percent(key):
                value = row.get(key)
                return "unknown" if value is None else f"{value:.2f}"
            lower = ">=" if row.get("daily_consumption_lower_bound") else ""
            print(f"  {row['pool']} [{row.get('strategy', 'fixed')}]")
            print(f"    native left {percent('remaining_percent')}% | spent today "
                  f"{lower}{percent('daily_consumed')} pp | available today "
                  f"{percent('spendable_percent')} pp")
            print(f"    daily ceiling {percent('daily_ceiling')} pp | added "
                  f"{percent('granted_percent')} pp | reserve {percent('reserve_percent')}%")
            reset = row.get("resets_at")
            if reset is None:
                print("    reset unknown")
                if row.get("strategy") == "adaptive" and row.get("pacing_source") == "native_window_duration":
                    print(f"    conservative pacing: full native window across {row['pacing_workdays']} workdays "
                          "(not a reset prediction)")
            else:
                instant = datetime.fromtimestamp(reset, timezone.utc)
                print(f"    reset {instant.isoformat()} / {instant.astimezone(zone).isoformat()} "
                      f"| workdays left {row.get('workdays_remaining')}")
            if row.get("deadline_release"):
                print("    before-cutoff reset: full current headroom available today")
        print("  admission: " + ("allowed (observed thresholds)" if status.get("allowed")
                                   else ", ".join(status.get("reasons", [])) or "denied"))
    change = result.get("change") or {}
    if change.get("grant_id"):
        print(f"Grant ID: {change['grant_id']} (reuse --id when retrying this grant)")
    if change.get("expires_at") is not None:
        print("Expires: " + datetime.fromtimestamp(change["expires_at"], timezone.utc).isoformat())
    if result.get("warning"):
        print(result["warning"])
    if not result["services"]:
        print("No recorded services. Initialize native quota observation through harness.py usage refresh.")


def parser_for(action):
    parser = argparse.ArgumentParser(description=__doc__)
    if action not in {"calendar", "defaults"}:
        parser.add_argument("service", nargs="?" if action == "status" else None)
    else:
        parser.set_defaults(service=None)
    parser.add_argument("--db", help="Private ledger path; defaults to the shared user ledger")
    parser.add_argument("--json", action="store_true", help="Machine-readable result")
    if action == "calendar":
        parser.add_argument("--workdays", type=parse_workdays, help="all, weekdays, or mon,tue,wed,thu,fri,sat,sun")
        parser.add_argument("--reset-cutoff", help="Inclusive next-day reset cutoff, HH:MM in the ledger timezone")
        parser.add_argument("--timezone", help="IANA zone for a new ledger; an existing ledger must already match")
    if action == "defaults":
        parser.add_argument("--strategy", choices=("adaptive", "fixed", "window"))
        parser.add_argument("--daily-limit", type=float)
        parser.add_argument("--reserve", type=float, help="Shared fallback reserve; explicit service/pool settings win")
    if action in {"set", "reset", "add"}:
        parser.add_argument("--pool", help="Exact pool ID; omitted means current service scope")
    if action == "set":
        parser.add_argument("--strategy", required=True, choices=("fixed", "adaptive", "window"))
        parser.add_argument("--reserve", type=float, help="Remaining percentage to retain; 0 targets full use")
        parser.add_argument("--daily-limit", type=float, help="Percentage points per day for fixed strategy")
    if action == "add":
        parser.add_argument("points", type=float, help="Extra percentage points for today, at most 100")
    if action in {"add", "use-rest"}:
        parser.add_argument("--id", dest="grant_id", help="Reuse this ID for an idempotent retry")
    return parser


def main(argv=None):
    import sys
    import usage
    arguments = list(sys.argv[1:] if argv is None else argv)
    actions = {"status", "set", "reset", "add", "use-rest", "calendar", "defaults"}
    if arguments and arguments[0] in {"-h", "--help"}:
        print("ai-session budget [SERVICE] [--json]\n"
              "ai-session budget set SERVICE --strategy adaptive --reserve 0 [--pool ID]\n"
              "ai-session budget set SERVICE --strategy fixed --daily-limit 20 --reserve 0\n"
              "ai-session budget calendar --workdays all --reset-cutoff 08:30 [--timezone IANA_ZONE]\n"
              "ai-session budget defaults --strategy adaptive --reserve 0 [--daily-limit 20]\n"
              "ai-session budget add SERVICE 5 [--pool ID] [--id RETRY_ID]\n"
              "ai-session budget use-rest SERVICE [--id RETRY_ID]\n"
              "ai-session budget reset SERVICE [--pool ID]\n\n"
              "Local budget changes preserve provider balances, history and admission mode.\n"
              "Today's grants expire at midnight in the ledger timezone. Strict mode still blocks inference.")
        return 0
    action = arguments.pop(0) if arguments and arguments[0] in actions else "status"
    args = parser_for(action).parse_args(arguments)
    try:
        ledger = Ledger(args.db, timezone=getattr(args, "timezone", None))
        change = None
        refresh_failures = set()
        if (action == "calendar" and (args.workdays is not None or args.reset_cutoff is not None)
                or action == "defaults" and any(v is not None for v in (args.reserve, args.strategy, args.daily_limit))):
            for service in ledger.budget_services():
                try:
                    refreshed = usage.refresh(service, ledger=ledger)
                    if refreshed.get("refresh_status") == "unsupported":
                        refresh_failures.add(service)
                except Exception:
                    refresh_failures.add(service)
        if action == "calendar":
            change = ledger.budget_calendar(workdays=args.workdays, reset_cutoff=args.reset_cutoff)
        elif action == "defaults":
            change = ledger.budget_defaults(reserve=args.reserve, strategy=args.strategy, daily_limit=args.daily_limit)
        elif action == "set":
            change = ledger.budget_set(args.service, args.strategy, reserve=args.reserve,
                                       daily_limit=args.daily_limit, pool=args.pool)
        elif action == "reset":
            change = ledger.budget_reset(args.service, pool=args.pool)
        elif action in {"add", "use-rest"}:
            refreshed = usage.refresh(args.service, ledger=ledger)
            if refreshed.get("refresh_status") == "unsupported":
                raise ValueError("A verified native quota refresh adapter is required for grants")
            if action == "add":
                change = ledger.budget_add(args.service, args.points, pool=args.pool, grant_id=args.grant_id)
            else:
                change = ledger.budget_use_rest(args.service, grant_id=args.grant_id)
        services = [args.service] if args.service else ledger.budget_services()
        statuses = []
        for service in services:
            if action == "status":
                try:
                    status = usage.refresh(service, ledger=ledger)
                except Exception:
                    status = ledger.check(service)
                    status["allowed"] = False
                    status["reasons"].append("quota_refresh_failed")
            else:
                status = ledger.check(service)
            if service in refresh_failures:
                status["allowed"] = False
                status["reasons"].append("quota_refresh_failed")
            statuses.append(status)
        result = dict(action=action, change=change, services=statuses,
                      calendar=ledger.budget_calendar(), defaults=ledger.budget_defaults())
        if ledger.mode() == "strict":
            result["warning"] = "Strict mode blocks inference: current clients cannot enforce exact request-cost bounds."
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            display(result)
        return 0
    except (ValueError, sqlite3.Error, OSError, TypeError) as exc:
        # Native reader failures are deliberately sanitized by their adapters.
        message = str(exc) if type(exc) is ValueError else "Budget metadata or storage is unavailable"
        print(json.dumps({"error": type(exc).__name__, "message": message}) if args.json else message)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
