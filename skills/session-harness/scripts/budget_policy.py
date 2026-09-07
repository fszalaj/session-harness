"""Pure allocation rules for persisted subscription budgets."""
import math
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

WINDOW_SOURCES = {"codex.windowDurationMins", "claude.native_limit_kind", "antigravity.bucket.window"}
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def validate_calendar(value):
    if not isinstance(value, dict) or set(value) != {"workdays", "reset_cutoff"}:
        raise ValueError("invalid budget calendar")
    days = value["workdays"]
    if (not isinstance(days, list) or not days or any(type(d) is not int or not 0 <= d <= 6 for d in days)
            or days != sorted(set(days))):
        raise ValueError("workdays must be a nonempty sorted set of weekdays")
    cutoff = value["reset_cutoff"]
    if not isinstance(cutoff, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", cutoff):
        raise ValueError("reset cutoff must be HH:MM")
    return {"workdays": list(days), "reset_cutoff": cutoff}


def calendar(config):
    return validate_calendar(config.get("calendar", {"workdays": list(range(7)), "reset_cutoff": "08:30"}))


def parse_workdays(value):
    if value in {"all", "daily"}:
        return list(range(7))
    if value == "weekdays":
        return list(range(5))
    parts = value.lower().split(",")
    if not parts or any(p.strip() not in WEEKDAYS for p in parts):
        raise ValueError("use all, weekdays, or comma-separated mon,tue,wed,thu,fri,sat,sun")
    return sorted({WEEKDAYS.index(p.strip()) for p in parts})


def fallback_policy(config, base):
    return {"strategy": config.get("default_strategy", "fixed"),
            "reserve": config.get("default_reserve", base["reserve"]),
            "daily_limit": config.get("default_daily_limit", base["daily_limit"])}


def numeric(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"invalid {name}")
    return float(value)


def label(value, name):
    if not isinstance(value, str) or not value or len(value) > 128 or any(ord(c) < 32 for c in value):
        raise ValueError(f"invalid {name}")
    return value


def validate_policy(policy):
    if not isinstance(policy, dict) or set(policy) != {"strategy", "reserve", "daily_limit"}:
        raise ValueError("invalid budget policy")
    if policy["strategy"] not in {"fixed", "adaptive", "window"}:
        raise ValueError("invalid budget strategy")
    if not 0 <= numeric(policy["reserve"], "reserve") < 100:
        raise ValueError("invalid reserve")
    if not 0 < numeric(policy["daily_limit"], "daily_limit") <= 100:
        raise ValueError("invalid daily limit")
    return policy


def midnight_after(now, timezone):
    zone = ZoneInfo(timezone)
    day = datetime.fromtimestamp(now, zone).date() + timedelta(days=1)
    return datetime.combine(day, time.min, zone).timestamp()


def forecast_days(now, reset, timezone, schedule=None):
    if reset is None or reset <= now:
        return None
    zone = ZoneInfo(timezone)
    start = datetime.fromtimestamp(now, zone).date()
    end = datetime.fromtimestamp(reset, zone)
    schedule = validate_calendar(schedule) if schedule is not None else calendar({})
    last = end.date() - timedelta(days=int(end.time() <= time.fromisoformat(schedule["reset_cutoff"])))
    count = (max(start, last) - start).days + 1
    weeks, remainder = divmod(count, 7)
    days = schedule["workdays"]
    return weeks * len(days) + sum((start.weekday() + offset) % 7 in days for offset in range(remainder))


def scheduled_today(now, timezone, schedule):
    return datetime.fromtimestamp(now, ZoneInfo(timezone)).weekday() in schedule["workdays"]


def pacing_forecast(value, now, timezone, schedule):
    if value["resets_at"] is not None:
        return "reported_reset", forecast_days(now, value["resets_at"], timezone, schedule)
    minutes = value.get("window_minutes", 0)
    if value.get("window_source") in WINDOW_SOURCES and 1440 < minutes <= 527040:
        # A full-duration horizon is a pacing fallback, never a reset prediction.
        horizon = now + minutes * 60
        conservative = {**schedule, "reset_cutoff": "00:00"}
        return "native_window_duration", forecast_days(now, horizon, timezone, conservative)
    return "unknown", None


def deadline_release(value, now, timezone, schedule):
    reset = value["resets_at"]
    if reset is None or reset <= now or not scheduled_today(now, timezone, schedule):
        return False
    zone = ZoneInfo(timezone)
    tomorrow = datetime.fromtimestamp(now, zone).date() + timedelta(days=1)
    end = datetime.fromtimestamp(reset, zone)
    return end.date() < tomorrow or (end.date() == tomorrow and end.time() <= time.fromisoformat(schedule["reset_cutoff"]))


def effective_policy(config, service, pool, base, value):
    settings = config["services"].get(service, {})
    policy = settings.get("pools", {}).get(pool, settings.get("default"))
    if policy is None:
        policy = fallback_policy(config, base)
    policy = dict(policy)
    if (policy["strategy"] == "adaptive" and value.get("window_source") in WINDOW_SOURCES
            and 0 < value.get("window_minutes", 0) <= 1440):
        policy["strategy"] = "window"
    return validate_policy(policy)


def empty_state():
    return {"version": 1, "revision": 0, "services": {}, "anchors": {}, "grants": [], "audit": []}


def validate_state(state):
    if type(state["version"]) is not int or state["version"] != 1 or type(state["revision"]) is not int or state["revision"] < 0:
        raise ValueError("invalid budget version")
    calendar(state)
    validate_policy(fallback_policy(state, {"reserve": 0, "daily_limit": 20}))
    if "default_reserve" in state and not 0 <= numeric(state["default_reserve"], "default reserve") < 100:
        raise ValueError("invalid default reserve")
    for service, pools in state.get("deadline_states", {}).items():
        label(service, "service")
        for pool, active in pools.items():
            label(pool, "pool")
            if type(active) is not bool:
                raise ValueError("invalid deadline state")
    for service, settings in state["services"].items():
        label(service, "service")
        if "default" in settings:
            validate_policy(settings["default"])
        for pool, policy in settings.get("pools", {}).items():
            label(pool, "pool")
            validate_policy(policy)
    for service, anchors in state["anchors"].items():
        label(service, "service")
        for pool, anchor in anchors.items():
            label(pool, "pool")
            validate_policy(anchor["policy"])
            if "calendar" in anchor:
                validate_calendar(anchor["calendar"])
            if type(anchor.get("deadline_origin", False)) is not bool:
                raise ValueError("invalid anchor deadline origin")
            if anchor.get("pacing_source", "reported_reset") not in {"reported_reset", "native_window_duration", "unknown"}:
                raise ValueError("invalid anchor pacing source")
            if anchor.get("pacing_source") == "native_window_duration":
                if not 1440 < numeric(anchor.get("pacing_window_minutes"), "pacing window") <= 527040:
                    raise ValueError("invalid anchor pacing window")
            datetime.fromisoformat(anchor["day"])
            for field in ("consumed", "used", "allocation", "ceiling", "grant_spent", "observed_at"):
                if numeric(anchor[field], field) < 0:
                    raise ValueError("invalid budget anchor")
            if (anchor["used"] > 100 or anchor["allocation"] > 100 or anchor["grant_spent"] > 100
                    or type(anchor["lower_bound"]) is not bool):
                raise ValueError("invalid budget anchor")
            expected = (anchor["policy"]["daily_limit"] if anchor["policy"]["strategy"] == "fixed"
                        else anchor["consumed"] + anchor["allocation"])
            if abs(anchor["ceiling"] - expected) > 1e-9:
                raise ValueError("inconsistent budget anchor ceiling")
    seen = set()
    for grant in state["grants"]:
        label(grant["id"], "grant id")
        if grant["id"] in seen or grant["kind"] not in {"add", "use-rest"}:
            raise ValueError("invalid grant")
        seen.add(grant["id"])
        label(grant["service"], "service")
        datetime.fromisoformat(grant["day"])
        if numeric(grant["expires_at"], "grant expiry") <= numeric(grant["created_at"], "grant creation"):
            raise ValueError("invalid grant expiry")
        if not isinstance(grant["payload"], dict) or not grant["pools"]:
            raise ValueError("invalid grant payload")
        for pool, data in grant["pools"].items():
            label(pool, "pool")
            if grant["kind"] == "add":
                if not 0 < numeric(data["points"], "grant points") <= 100:
                    raise ValueError("invalid grant points")
            elif (numeric(data["ceiling"], "rest ceiling") < 0
                  or not 0 <= numeric(data["prior_adds"], "prior adds") <= 100):
                raise ValueError("invalid rest ceiling")
    if not isinstance(state["audit"], list):
        raise ValueError("invalid budget audit")
    return state


def active_grants(config, service, pool, now, day):
    adds, rest = 0.0, None
    for grant in config["grants"]:
        if grant["service"] != service or grant["day"] != day or now >= grant["expires_at"] or now < grant["created_at"]:
            continue
        data = grant["pools"].get(pool)
        if data is None:
            continue
        if grant["kind"] == "add":
            adds += data["points"]
        else:
            rest = data
    if adds > 100 + 1e-9:
        raise ValueError("daily grants exceed 100")
    return adds, rest


def allocation(policy, value, now, timezone, schedule):
    _, days = pacing_forecast(value, now, timezone, schedule)
    available = max(0, 100 - value["used_percent"] - policy["reserve"])
    if policy["strategy"] == "fixed":
        return policy["daily_limit"]
    if policy["strategy"] == "window":
        return available
    if days is None:
        return None
    if not scheduled_today(now, timezone, schedule) or days == 0:
        return 0.0
    return available / days


def anchor_pool(config, service, pool, value, entry, base, now, day, *, recovery=False, force=False):
    policy = effective_policy(config, service, pool, base, value)
    schedule = calendar(config)
    anchors = config["anchors"].setdefault(service, {})
    prior = anchors.get(pool)
    source, _ = pacing_forecast(value, now, base["timezone"], schedule)
    fallback_changed = policy["strategy"] == "adaptive" and source == "native_window_duration" and prior and (
        prior.get("pacing_source") != source or prior.get("pacing_window_minutes") != value["window_minutes"])
    origin = policy["strategy"] == "adaptive" and deadline_release(value, now, base["timezone"], schedule)
    withdrawn = prior and prior.get("deadline_origin", False) and not origin
    if (prior and prior["day"] == day and prior["policy"] == policy and prior.get("calendar") == schedule
            and not recovery and not force and not withdrawn and not fallback_changed):
        return
    alloc = allocation(policy, value, now, base["timezone"], schedule)
    if alloc is None:
        return
    if (fallback_changed and prior["day"] == day and prior["policy"] == policy
            and prior.get("calendar") == schedule and not recovery and not force):
        alloc = min(alloc, max(0, prior["ceiling"] - entry["consumed"]))
    adds, _ = active_grants(config, service, pool, now, day)
    spent = 0.0
    if prior and prior["day"] == day:
        excess = max(0, entry["consumed"] - prior["ceiling"])
        spent = min(adds, max(prior["grant_spent"], excess) if prior["policy"]["strategy"] == "fixed"
                    else prior["grant_spent"] + excess)
    ceiling = policy["daily_limit"] if policy["strategy"] == "fixed" else entry["consumed"] + alloc
    anchors[pool] = {"day": day, "policy": policy, "consumed": entry["consumed"],
                    "used": value["used_percent"], "allocation": alloc, "ceiling": ceiling,
                    "grant_spent": spent, "observed_at": value["observed_at"],
                    "lower_bound": bool(entry["history_partial"] or entry["unknown"]), "calendar": schedule,
                    "deadline_origin": origin, "pacing_source": source,
                    "pacing_window_minutes": value.get("window_minutes") if source == "native_window_duration" else None}
    config["audit"].append({"action": "anchor", "service": service, "pool": pool, "at": now,
                            "recovery": recovery, "anchor": dict(anchors[pool])})


def audit_deadline(config, service, pool, value, base, now):
    policy = effective_policy(config, service, pool, base, value)
    active = policy["strategy"] == "adaptive" and deadline_release(value, now, base["timezone"], calendar(config))
    previous = config.setdefault("deadline_states", {}).setdefault(service, {}).get(pool)
    if previous != active:
        config["deadline_states"][service][pool] = active
        config["audit"].append({"action": "deadline_release", "service": service, "pool": pool,
                                "at": now, "active": active, "resets_at": value["resets_at"]})


def pool_budget(config, service, pool, value, entry, base, now, day, fresh=False):
    policy = effective_policy(config, service, pool, base, value)
    schedule = calendar(config)
    strategy = policy["strategy"]
    consumed = entry["consumed"]
    remaining = 100 - value["used_percent"]
    adds, rest = active_grants(config, service, pool, now, day)
    source, days = pacing_forecast(value, now, base["timezone"], schedule)
    anchor = config["anchors"].get(service, {}).get(pool)
    if anchor and (anchor["day"] != day or anchor["policy"] != policy or anchor.get("calendar") != schedule
                   or strategy == "adaptive" and source == "native_window_duration" and (anchor.get("pacing_source") != source
                       or anchor.get("pacing_window_minutes") != value["window_minutes"])
                   or anchor.get("deadline_origin", False) and not deadline_release(value, now, base["timezone"], schedule)):
        anchor = None
    reasons = []
    reserve = 0 if rest else policy["reserve"]
    native = max(0, remaining - reserve)
    alloc = allocation(policy, value, now, base["timezone"], schedule)
    base_ceiling = policy["daily_limit"] if strategy == "fixed" else None
    epoch_remaining = native
    if strategy == "adaptive":
        if source == "unknown":
            reasons.append("unknown_adaptive_reset")
        elif value["resets_at"] is not None and value["resets_at"] <= now:
            reasons.append("reset_needs_fresh_evidence")
        if anchor:
            alloc = anchor["allocation"]
            base_ceiling = anchor["ceiling"]
            epoch_remaining = anchor["used"] + alloc + max(0, adds - anchor["grant_spent"]) - value["used_percent"]
        else:
            reasons.append("budget_anchor_missing")
    if strategy == "window":
        base_ceiling = consumed + native
    grant_remaining = max(0, adds - (anchor["grant_spent"] if anchor and strategy == "adaptive" else 0))
    ceiling = base_ceiling + grant_remaining if base_ceiling is not None else None
    release = bool(strategy == "adaptive" and fresh and anchor and not rest
                   and deadline_release(value, now, base["timezone"], schedule))
    if release:
        ceiling = consumed + native
        epoch_remaining = native
    if rest:
        ceiling = rest["ceiling"] + max(0, adds - rest["prior_adds"])
        epoch_remaining = ceiling - consumed
    daily_remaining = max(0, ceiling - consumed) if ceiling is not None else 0
    spendable = max(0, min(daily_remaining, epoch_remaining, native))
    if ceiling is not None and daily_remaining <= 1e-9:
        reasons.append("daily_limit")
        if strategy == "adaptive" and not scheduled_today(now, base["timezone"], schedule):
            reasons.append("not_work_day")
    if strategy == "adaptive" and epoch_remaining <= 1e-9 and "daily_limit" not in reasons:
        reasons.append("native_growth_limit")
    if remaining <= reserve:
        reasons.append("reserve_floor")
    return {"strategy": strategy, "budget_policy": policy, "reserve_percent": reserve,
            "daily_ceiling": ceiling, "base_allocation": alloc, "granted_percent": adds,
            "grant_remaining_percent": grant_remaining, "spendable_percent": spendable,
            "forecast_days": forecast_days(now, value["resets_at"], base["timezone"], schedule),
            "workdays_remaining": forecast_days(now, value["resets_at"], base["timezone"], schedule),
            "pacing_source": source, "pacing_workdays": days,
            "scheduled_workday": scheduled_today(now, base["timezone"], schedule),
            "deadline_release": release, "calendar": schedule,
            "window_minutes": value.get("window_minutes"), "window_source": value.get("window_source"),
            "anchor_lower_bound": anchor["lower_bound"] if anchor else bool(entry["history_partial"] or entry["unknown"]),
            "anchor": anchor, "use_rest": rest is not None, "budget_reasons": reasons}
