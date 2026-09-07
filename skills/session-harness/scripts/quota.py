#!/usr/bin/env python3
"""Conservative subscription quota accounting; never promises an exact cap."""
import argparse
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

import budget_policy as budgets
import credits


def default_path():
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "session-harness/quota/ledger.sqlite3"


def number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite numeric data")
    return float(value)


class Ledger:
    def __init__(self, path=None, *, timezone=None, daily_limit=None,
                 reserve=None, max_age=None, max_gap=None):
        supplied = dict(timezone=timezone, daily_limit=daily_limit, reserve=reserve,
                        max_age=max_age, max_gap=max_gap)
        defaults = dict(timezone="UTC", daily_limit=20, reserve=0,
                        max_age=120, max_gap=300)
        self.path = Path(path or default_path())
        if os.name == 'nt':
            from windows_security import prepare_private_file
            prepare_private_file(self.path)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.path.parent, 0o700)
            if self.path.is_symlink():
                raise ValueError("ledger must not be a symlink")
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            os.chmod(self.path, 0o600)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM state WHERE key='policy'").fetchone()
            policy = json.loads(row[0]) if row else defaults
            if not isinstance(policy, dict) or set(policy) != set(defaults):
                raise ValueError("invalid persisted quota policy")
            for key, value in supplied.items():
                if value is not None:
                    if row and value != policy[key]:
                        raise ValueError("persisted quota policy differs; explicit migration required")
                    policy[key] = value
            try:
                ZoneInfo(policy["timezone"])
            except (KeyError, TypeError) as exc:
                raise ValueError("invalid quota timezone") from exc
            for key in ("daily_limit", "reserve", "max_age", "max_gap"):
                policy[key] = number(policy[key], key)
            if (not 0 < policy["daily_limit"] <= 100 or not 0 <= policy["reserve"] < 100
                    or policy["max_age"] <= 0 or policy["max_gap"] <= 0):
                raise ValueError("invalid quota policy")
            self.policy = policy
            db.execute("INSERT OR IGNORE INTO state VALUES ('policy', ?)", (json.dumps(policy),))
            if row is None:
                config = budgets.empty_state()
                config["default_strategy"] = "adaptive"
                self._save_budgets(db, config)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute("PRAGMA journal_mode=DELETE")
            with db:
                yield db
        finally:
            db.close()

    def set_mode(self, mode):
        """Persist the owner's opt-in privately without replacing accounting history."""
        if mode not in {"strict", "observed"}:
            raise ValueError("invalid admission mode")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR REPLACE INTO state VALUES ('admission_mode', ?)",
                       (json.dumps(mode),))

    def _setup(self, db):
        row = db.execute("SELECT value FROM state WHERE key='setup_v1'").fetchone()
        if row is None:
            return {"complete": False, "services": [], "api_services": []}
        try:
            value = json.loads(row[0])
            if (not isinstance(value, dict) or type(value.get("version")) is not int or value.get("version") != 1
                    or value.get("complete") is not True
                    or value.get("source") not in {"interactive", "cli", "test"}):
                raise ValueError("invalid setup")
            for key in ("services", "api_services"):
                items = value[key]
                if not isinstance(items, list) or len(items) > 100 or len(set(items)) != len(items):
                    raise ValueError("invalid setup services")
                for item in items:
                    budgets.label(item, "service")
            number(value["completed_at"], "setup completion")
            if not value["services"] and not value["api_services"]:
                raise ValueError("empty setup")
            return value
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ValueError("invalid environment setup; run ai-session setup") from exc

    def setup_status(self):
        with self._connect() as db:
            return self._setup(db)

    def _require_setup(self, db, route, service):
        value = self._setup(db)
        if not value["complete"]:
            raise ValueError("environment_setup_required; run ai-session setup")
        key = {"native": "services", "api": "api_services"}.get(route)
        if key is None or service not in value[key]:
            raise ValueError("service_not_configured; run ai-session setup")
        return value

    def require_setup(self, route, service):
        with self._connect() as db:
            return self._require_setup(db, route, service)

    def complete_setup(self, *, services, api_services, source):
        value = {"version": 1, "complete": True, "services": services,
                 "api_services": api_services, "source": source, "completed_at": time.time()}
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR REPLACE INTO state VALUES ('setup_v1', ?)", (json.dumps(value),))
            return self._setup(db)

    def reset_setup(self):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM state WHERE key='setup_v1'")
        return {"complete": False, "services": [], "api_services": []}

    def _mode(self, db):
        row = db.execute("SELECT value FROM state WHERE key='admission_mode'").fetchone()
        mode = json.loads(row[0]) if row else "strict"
        if mode not in {"strict", "observed"}:
            raise ValueError("invalid persisted admission mode")
        return mode

    def mode(self):
        with self._connect() as db:
            db.execute("BEGIN DEFERRED")
            return self._mode(db)

    def _budgets(self, db):
        row = db.execute("SELECT value FROM state WHERE key='budget_v1'").fetchone()
        try:
            return budgets.validate_state(json.loads(row[0])) if row else budgets.empty_state()
        except (KeyError, TypeError, AttributeError, OverflowError) as exc:
            raise ValueError("invalid persisted budget state") from exc

    def _save_budgets(self, db, config):
        budgets.validate_state(config)
        db.execute("INSERT OR REPLACE INTO state VALUES ('budget_v1', ?)", (json.dumps(config),))

    def _service(self, db, service):
        budgets.label(service, "service")
        row = db.execute("SELECT value FROM state WHERE key=?", ("service:" + service,)).fetchone()
        if not row:
            return None
        try:
            state = json.loads(row[0])
            self._validate_accounting(state)
            return state
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("invalid stored accounting") from exc

    def _fresh(self, state, now):
        return bool(state and state["complete"] and not state["missing_pools"]
                    and self._day(state["observed_at"]) == self._day(now)
                    and 0 <= now - state["observed_at"] <= self.policy["max_age"]
                    and all(0 <= now - p["observed_at"] <= self.policy["max_age"]
                            and (p["resets_at"] is None or p["resets_at"] > now)
                            for p in state["pools"].values()))

    def budget_services(self):
        with self._connect() as db:
            db.execute("BEGIN DEFERRED")
            config = self._budgets(db)
            services = {row[0][8:] for row in db.execute("SELECT key FROM state WHERE key LIKE 'service:%'")}
            return sorted(services | set(config["services"]))

    def _reanchor_fresh(self, db, config, now):
        day = self._day(now)
        for row in db.execute("SELECT key FROM state WHERE key LIKE 'service:%'").fetchall():
            service = row[0][8:]
            state = self._service(db, service)
            if self._fresh(state, now):
                for pool, value in state["pools"].items():
                    budgets.anchor_pool(config, service, pool, value, state["days"][day][pool],
                                        self.policy, now, day)
                    budgets.audit_deadline(config, service, pool, value, self.policy, now)

    def budget_calendar(self, workdays=None, reset_cutoff=None, now=None):
        now = number(time.time() if now is None else now, "now")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE" if workdays is not None or reset_cutoff is not None else "BEGIN DEFERRED")
            config = self._budgets(db)
            old = budgets.calendar(config)
            new = budgets.validate_calendar({"workdays": old["workdays"] if workdays is None else workdays,
                "reset_cutoff": old["reset_cutoff"] if reset_cutoff is None else reset_cutoff})
            if new != old:
                config["calendar"] = new
                config["revision"] += 1
                config["audit"].append({"action": "calendar", "at": now, "calendar": new,
                                        "revision": config["revision"]})
                self._reanchor_fresh(db, config, now)
                self._save_budgets(db, config)
            return {"calendar": new, "timezone": self.policy["timezone"], "revision": config["revision"]}

    def budget_defaults(self, reserve=None, now=None, strategy=None, daily_limit=None):
        now = number(time.time() if now is None else now, "now")
        changed = any(value is not None for value in (reserve, strategy, daily_limit))
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE" if changed else "BEGIN DEFERRED")
            config = self._budgets(db)
            old = budgets.fallback_policy(config, self.policy)
            new = budgets.validate_policy({"strategy": old["strategy"] if strategy is None else strategy,
                "reserve": old["reserve"] if reserve is None else reserve,
                "daily_limit": old["daily_limit"] if daily_limit is None else daily_limit})
            if new != old:
                config.update({"default_" + key: value for key, value in new.items()})
                config["revision"] += 1
                config["audit"].append({"action": "defaults", "at": now, **new,
                                        "revision": config["revision"]})
                self._reanchor_fresh(db, config, now)
                self._save_budgets(db, config)
            return {**{"default_" + key: value for key, value in new.items()}, "revision": config["revision"]}

    def budget_set(self, service, strategy, reserve=None, daily_limit=None, pool=None, now=None):
        return self._budget_configure(service, strategy, reserve, daily_limit, pool, now)

    def budget_reset(self, service, pool=None, now=None):
        return self._budget_configure(service, None, None, None, pool, now)

    def _budget_configure(self, service, strategy, reserve, daily_limit, pool, now):
        budgets.label(service, "service")
        if pool is not None:
            budgets.label(pool, "pool")
        now = number(time.time() if now is None else now, "now")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            config = self._budgets(db)
            state = self._service(db, service)
            settings = config["services"].setdefault(service, {"pools": {}})
            old = settings.get("pools", {}).get(pool, settings.get("default", budgets.fallback_policy(config, self.policy)))
            if strategy is None:
                if pool is None:
                    settings.pop("default", None)
                else:
                    settings.setdefault("pools", {}).pop(pool, None)
                policy = None
            else:
                policy = budgets.validate_policy({"strategy": strategy,
                    "reserve": old["reserve"] if reserve is None else number(reserve, "reserve"),
                    "daily_limit": old["daily_limit"] if daily_limit is None else number(daily_limit, "daily_limit")})
                if pool is None:
                    settings["default"] = policy
                else:
                    settings.setdefault("pools", {})[pool] = policy
            config["revision"] += 1
            config["audit"].append({"action": "reset" if strategy is None else "set", "service": service,
                                    "pool": pool, "at": now, "policy": policy, "revision": config["revision"]})
            if self._fresh(state, now):
                day = self._day(now)
                for name, value in state["pools"].items():
                    if pool is None or name == pool:
                        budgets.anchor_pool(config, service, name, value, state["days"][day][name],
                                            self.policy, now, day)
                        budgets.audit_deadline(config, service, name, value, self.policy, now)
            self._save_budgets(db, config)
            revision = config["revision"]
        return {"action": "reset" if strategy is None else "set", "service": service, "pool": pool,
                "budget_policy": policy, "revision": revision, "status": self.check(service, now=now)}

    def budget_add(self, service, points, pool=None, grant_id=None, now=None):
        points = number(points, "points")
        if not 0 < points <= 100:
            raise ValueError("grant must be greater than zero and at most 100 percentage points")
        return self._budget_grant(service, "add", points, pool, grant_id, now)

    def budget_use_rest(self, service, grant_id=None, now=None):
        return self._budget_grant(service, "use-rest", None, None, grant_id, now)

    def _budget_grant(self, service, kind, points, pool, grant_id, now):
        budgets.label(service, "service")
        if pool is not None:
            budgets.label(pool, "pool")
        grant_id = budgets.label(str(uuid.uuid4()) if grant_id is None else grant_id, "grant id")
        now = number(time.time() if now is None else now, "now")
        day = self._day(now)
        payload = {"kind": kind, "service": service, "pool": pool, "day": day, "points": points}
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            config = self._budgets(db)
            prior = next((g for g in config["grants"] if g["id"] == grant_id), None)
            if prior:
                if prior["payload"] != payload:
                    raise ValueError("grant id already belongs to a different payload")
                grant = prior
            else:
                state = self._service(db, service)
                if not self._fresh(state, now):
                    raise ValueError("grant requires a fresh complete observation from today with a future or unknown reset")
                if pool is not None and pool not in state["pools"]:
                    raise ValueError("requested pool is absent from the fresh snapshot")
                targets = [pool] if pool is not None else sorted(state["pools"])
                grant = {"id": grant_id, "kind": kind, "service": service, "day": day,
                         "created_at": now, "expires_at": budgets.midnight_after(now, self.policy["timezone"]),
                         "payload": payload, "pools": {}}
                for name in targets:
                    adds, rest = budgets.active_grants(config, service, name, now, day)
                    if kind == "add":
                        if adds + points > 100 + 1e-9:
                            raise ValueError("combined grants exceed 100 percentage points for a pool today")
                        grant["pools"][name] = {"points": points}
                    else:
                        ceiling = state["days"][day][name]["consumed"] + 100 - state["pools"][name]["used_percent"]
                        if rest:
                            ceiling = min(ceiling, rest["ceiling"] + max(0, adds - rest["prior_adds"]))
                        grant["pools"][name] = {"ceiling": ceiling, "prior_adds": adds}
                config["grants"].append(grant)
                config["audit"].append({"action": kind, "service": service, "grant_id": grant_id, "at": now})
                self._save_budgets(db, config)
        return {"action": kind, "service": service, "pool": pool, "grant_id": grant_id,
                "expires_at": grant["expires_at"], "idempotent": prior is not None,
                "grant": grant, "status": self.check(service, now=now)}

    def _day(self, timestamp):
        return datetime.fromtimestamp(timestamp, ZoneInfo(self.policy["timezone"])).date().isoformat()

    def _validate_accounting(self, state):
        """Every persisted pool observation must retain its matching daily counter."""
        if (type(state["complete"]) is not bool or not isinstance(state["missing_pools"], list)
                or not isinstance(state["resets"], list) or not state["pools"]):
            raise ValueError("invalid stored accounting")
        latest = number(state["observed_at"], "stored observation")
        budgets.label(state["source"], "stored source")
        for day, entries in state["days"].items():
            datetime.fromisoformat(day)
            for pool, entry in entries.items():
                budgets.label(pool, "stored pool")
                if (number(entry["consumed"], "stored consumption") < 0
                        or type(entry["unknown"]) is not bool
                        or type(entry["history_partial"]) is not bool):
                    raise ValueError("invalid stored accounting")
        for pool, value in state["pools"].items():
            budgets.label(pool, "stored pool")
            observed = number(value["observed_at"], "stored pool observation")
            state["days"][self._day(observed)][pool]
            if not 0 <= observed <= latest or not 0 <= number(value["used_percent"], "stored usage") <= 100:
                raise ValueError("invalid stored accounting")
            if value["resets_at"] is not None and number(value["resets_at"], "stored reset") < 0:
                raise ValueError("invalid stored reset")
            if "window_minutes" in value and number(value["window_minutes"], "window minutes") <= 0:
                raise ValueError("invalid stored window")
            if "window_source" in value and (value["window_source"] not in budgets.WINDOW_SOURCES
                                             or "window_minutes" not in value):
                raise ValueError("invalid stored window provenance")

    def record(self, snapshot, *, now=None, initialize=False):
        """Record allowlisted metadata. initialize explicitly accepts a prospective baseline."""
        if not isinstance(snapshot, dict):
            raise ValueError("snapshot must be an object")
        now = number(time.time() if now is None else now, "now")
        observed = number(snapshot.get("observed_at"), "observed_at")
        if observed > now or observed < 0:
            raise ValueError("invalid observation time")
        service = snapshot.get("service")
        source = snapshot.get("source")
        if not isinstance(service, str) or not service or len(service) > 128:
            raise ValueError("service must be a nonempty pseudonymous key")
        if not isinstance(source, str) or not source or len(source) > 128:
            raise ValueError("source must be a short adapter label")
        if type(snapshot.get("complete")) is not bool:
            raise ValueError("complete must be explicit boolean")
        pools = snapshot.get("pools")
        if not isinstance(pools, list) or not pools:
            raise ValueError("nonempty pools required")
        clean = {}
        for item in pools:
            if not isinstance(item, dict):
                raise ValueError("pool must be an object")
            pool = item.get("pool")
            if not isinstance(pool, str) or not pool or len(pool) > 128 or pool in clean:
                raise ValueError("invalid or duplicate pool")
            used = number(item.get("used_percent"), "used_percent")
            if "resets_at" not in item:
                raise ValueError("reset schedule must be explicit")
            resets = None if item["resets_at"] is None else number(item["resets_at"], "resets_at")
            if not 0 <= used <= 100 or (resets is not None and resets < 0):
                raise ValueError("invalid quota percentage or reset")
            clean[pool] = dict(used_percent=used, resets_at=resets)
            if "window_minutes" in item:
                window = number(item["window_minutes"], "window_minutes")
                if window <= 0:
                    raise ValueError("invalid window duration")
                clean[pool]["window_minutes"] = window
            if "window_source" in item:
                if (not isinstance(item["window_source"], str)
                        or item["window_source"] not in budgets.WINDOW_SOURCES or "window_minutes" not in item):
                    raise ValueError("invalid native window provenance")
                clean[pool]["window_source"] = item["window_source"]
        resources = credits.validate_resources(snapshot.get("credit_resources", credits.missing(service)), service)
        day = self._day(observed)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            key = "service:" + service
            row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
            state = json.loads(row[0]) if row else {"pools": {}, "days": {}, "resets": []}
            if row:
                try:
                    self._validate_accounting(state)
                except (KeyError, TypeError, AttributeError) as exc:
                    raise ValueError("invalid stored accounting") from exc
            previous_time = state.get("observed_at")
            if previous_time is not None and observed <= previous_time:
                raise ValueError("observations must be strictly ordered")
            config = self._budgets(db)
            recoveries = set()
            daily = state["days"].setdefault(day, {})
            for pool, current in clean.items():
                old = state["pools"].get(pool)
                entry = daily.setdefault(pool, {"consumed": 0.0, "unknown": False,
                                                "history_partial": old is None})
                if old is None:
                    entry["unknown"] = not initialize
                else:
                    gap = observed - old["observed_at"]
                    delta = current["used_percent"] - old["used_percent"]
                    entry["consumed"] += current["used_percent"] if delta < 0 else delta
                    changed_reset = current["resets_at"] != old["resets_at"]
                    crossed_reset = old["resets_at"] is not None and old["resets_at"] <= observed
                    if delta < 0 or changed_reset or crossed_reset or gap > self.policy["max_gap"]:
                        entry["unknown"] = True
                        entry["history_partial"] = True
                    if delta < 0:
                        recoveries.add(pool)
                        state["resets"].append(dict(pool=pool, observed_at=observed,
                                                    prior_reset=old["resets_at"],
                                                    resets_at=current["resets_at"],
                                                    usage_drop=delta < 0))
                state["pools"][pool] = dict(current, observed_at=observed)
            missing = sorted(set(state["pools"]) - set(clean))
            state.update(observed_at=observed, source=source,
                         complete=snapshot["complete"], missing_pools=missing, credit_resources=resources)
            if self._fresh(state, now):
                for pool, value in clean.items():
                    budgets.anchor_pool(config, service, pool, state["pools"][pool], daily[pool],
                                        self.policy, now, day, recovery=pool in recoveries)
                    budgets.audit_deadline(config, service, pool, state["pools"][pool], self.policy, now)
            self._save_budgets(db, config)
            db.execute("INSERT OR REPLACE INTO state VALUES (?, ?)", (key, json.dumps(state)))
        return self.check(service, now=now)

    def check(self, service, *, now=None, strict=None):
        """Observed-threshold admission is separate from strict (unsupported) admission."""
        now = number(time.time() if now is None else now, "now")
        reasons = []
        result = dict(service=service, allowed=False, allowed_by_observed_threshold=False,
                      exact_cap_supported=False, reasons=reasons, pools=[], policy=self.policy)
        try:
            with self._connect() as db:
                db.execute("BEGIN DEFERRED")
                mode = self._mode(db)
                config = self._budgets(db)
                row = db.execute("SELECT value FROM state WHERE key=?", ("service:" + service,)).fetchone()
                try:
                    self._require_setup(db, "native", service)
                except ValueError as exc:
                    reasons.append(str(exc).split(";", 1)[0])
            result["budget_config"] = config["services"].get(service, {})
            result["budget_revision"] = config["revision"]
            result["calendar"] = budgets.calendar(config)
            result["default_reserve"] = budgets.fallback_policy(config, self.policy)["reserve"]
            result["grants"] = [g for g in config["grants"] if g["service"] == service]
            result["mode"] = mode
            result["in_flight_overshoot_possible"] = mode == "observed"
            if strict is None:
                strict = mode == "strict"
            if row is None:
                reasons.append("missing_snapshot")
                return result
            state = json.loads(row[0])
            self._validate_accounting(state)
            observed = number(state["observed_at"], "stored observation")
            if type(state["complete"]) is not bool or not state["pools"]:
                raise ValueError("invalid stored completeness")
            result.update(observed_at=observed, source=state["source"], reset_history=state["resets"])
            result["credit_resources"] = credits.validate_resources(state.get("credit_resources", credits.missing(service)), service)
            reasons.extend(credits.native_reasons(service, result["credit_resources"]))
            if now < observed or now - observed > self.policy["max_age"]:
                reasons.append("stale_or_future_snapshot")
            if not state["complete"] or state["missing_pools"]:
                reasons.append("incomplete_pools")
            day = self._day(now)
            result["day"] = day
            if self._day(observed) != day:
                reasons.append("new_day_needs_observation")
            daily = state["days"].get(day, {})
            for pool, value in sorted(state["pools"].items()):
                if self._day(observed) == day and pool not in state["missing_pools"]:
                    entry = daily[pool]
                else:
                    entry = daily.get(pool, {"consumed": 0, "unknown": True, "history_partial": True})
                used = number(value["used_percent"], "stored percentage")
                consumed = number(entry["consumed"], "stored consumption")
                if value["resets_at"] is not None and number(value["resets_at"], "stored reset") < 0:
                    raise ValueError("invalid stored reset")
                number(value["observed_at"], "stored pool observation")
                if not 0 <= used <= 100 or consumed < 0 or type(entry["unknown"]) is not bool:
                    raise ValueError("invalid stored quota")
                remaining = 100 - value["used_percent"]
                pool_reasons = []
                if entry["unknown"] and mode != "observed":
                    pool_reasons.append("unknown_daily_consumption")
                budget = budgets.pool_budget(config, service, pool, value, entry, self.policy, now, day,
                                             fresh=self._fresh(state, now))
                pool_reasons.extend(budget.pop("budget_reasons"))
                if value["resets_at"] is not None and value["resets_at"] <= now:
                    pool_reasons.append("reset_needs_fresh_evidence")
                if now - value["observed_at"] > self.policy["max_age"]:
                    pool_reasons.append("stale_pool")
                result["pools"].append(dict(**budget, pool=pool, remaining_percent=remaining,
                                             daily_consumed=entry["consumed"],
                                             history_partial=bool(entry["history_partial"] or entry["unknown"]),
                                             daily_consumption_lower_bound=bool(entry["history_partial"] or entry["unknown"]),
                                             resets_at=value["resets_at"],
                                             reset_schedule_known=value["resets_at"] is not None,
                                             reasons=pool_reasons))
                reasons.extend(f"{pool}:{reason}" for reason in pool_reasons)
            result["allowed_by_observed_threshold"] = not reasons
            if strict:
                reasons.append("exact_request_bound_unavailable")
            result["allowed"] = not reasons
        except (sqlite3.Error, ValueError, KeyError, TypeError, AttributeError, OverflowError):
            reasons.append("invalid_ledger")
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["record", "check", "status", "configure"])
    parser.add_argument("--service")
    parser.add_argument("--mode", choices=["strict", "observed"])
    parser.add_argument("--db")
    parser.add_argument("--timezone")
    parser.add_argument("--initialize", action="store_true")
    parser.add_argument("--observed-only", action="store_true")
    args = parser.parse_args()
    if args.observed_only and args.action != "status":
        parser.error("--observed-only is diagnostic and requires the status action")
    try:
        ledger = Ledger(args.db, timezone=args.timezone)
        if args.action == "configure":
            if not args.mode:
                parser.error("--mode is required")
            ledger.set_mode(args.mode)
            print(json.dumps({"mode": ledger.mode()}))
            return 0
        if args.action == "record":
            output = ledger.record(json.load(sys.stdin), initialize=args.initialize)
        else:
            if not args.service:
                parser.error("--service is required")
            output = ledger.check(args.service, strict=False if args.observed_only else None)
        print(json.dumps(output, sort_keys=True))
        return 0 if args.action in ("record", "status") or output["allowed"] else 2
    except (ValueError, sqlite3.Error, OSError, TypeError) as exc:
        print(json.dumps({"allowed": False, "error": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
