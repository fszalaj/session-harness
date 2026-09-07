"""Allowlisted credit metadata; no native paid execution contract is verified."""
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import stat
import re


SERVICES = {"claude", "codex", "copilot", "antigravity"}
FLAGS = ("enabled", "auto_reload", "can_purchase", "has_credits", "unlimited")
AMOUNTS = ("balance", "used", "limit", "cap")
SOURCES = {"claude": "claude.native_usage", "codex": "codex.account/rateLimits/read",
           "copilot": "copilot.account.getQuota", "antigravity": "antigravity.native_usage"}
AGY_SETTINGS_SOURCE = "antigravity.cli_settings"
CONTROLS = {"useG1Credits", "tokenBasedBilling", "hasQuota", "usageAllowedWithExhaustedQuota", "overageAllowedWithExhaustedQuota"}


def decimal_amount(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("Invalid credit amount")
    if isinstance(value, str) and (len(value) > 80 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value)):
        raise ValueError("Invalid credit amount")
    try:
        amount = Decimal(str(value))
        if (not amount.is_finite() or amount < 0 or amount > Decimal("1e24")
                or amount.as_tuple().exponent < -18):
            raise ValueError("Invalid credit amount")
    except InvalidOperation as exc:
        raise ValueError("Invalid credit amount") from exc
    return format(amount, "f")


def flag(value):
    if value is not None and type(value) is not bool:
        raise ValueError("Invalid credit flag")
    return value


def resource(service, source, identity="account", status="reported"):
    return {"resource_id": service + ":" + hashlib.sha256(str(identity).encode()).hexdigest()[:24],
            "service": service, "scope": "extra:" + service, "source": source,
            "unit": "server_defined", **dict.fromkeys(FLAGS), **dict.fromkeys(AMOUNTS),
            "currency": None, "exponent": None, "metadata_status": status,
            "paid_execution_supported": False, "native_controls": {}}


def missing(service):
    if service not in SERVICES:
        return []
    return [resource(service, SOURCES[service], status="missing")]


def validate_resources(rows, service):
    if not isinstance(rows, list) or len(rows) > 128:
        raise ValueError("Invalid credit resources")
    expected = set(resource("claude", "claude.native_usage"))
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != expected or row["service"] != service
                or service not in SERVICES or row["scope"] != "extra:" + service
                or row["source"] not in ({SOURCES[service], AGY_SETTINGS_SOURCE}
                                         if service == "antigravity" else {SOURCES[service]})
                or not isinstance(row["resource_id"], str)
                or not re.fullmatch(re.escape(service) + r":[0-9a-f]{24}", row["resource_id"])
                or row["resource_id"] in seen or row["paid_execution_supported"] is not False
                or row["metadata_status"] not in {"reported", "missing", "invalid"}
                or row["unit"] not in {"server_defined", "provider_credits", "currency_minor"}):
            raise ValueError("Invalid credit resource")
        seen.add(row["resource_id"])
        if (not isinstance(row["native_controls"], dict) or set(row["native_controls"]) - CONTROLS
                or any(type(value) is not bool for value in row["native_controls"].values())):
            raise ValueError("Invalid native credit controls")
        for key in FLAGS:
            flag(row[key])
        for key in AMOUNTS:
            if row[key] is not None and (not isinstance(row[key], str) or decimal_amount(row[key]) != row[key]):
                raise ValueError("Invalid stored credit amount")
        currency, exponent = row["currency"], row["exponent"]
        if currency is not None and (not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency)):
            raise ValueError("Invalid credit currency")
        if exponent is not None and (type(exponent) is not int or not 0 <= exponent <= 9):
            raise ValueError("Invalid credit scale")
        if row["unit"] == "currency_minor" and (currency is None or exponent is None):
            raise ValueError("Missing credit currency or scale")
    return rows


def claude_resources(rates):
    result = resource("claude", "claude.native_usage")
    try:
        if not isinstance(rates, dict):
            raise ValueError("Invalid usage")
        extra, spend = rates.get("extra_usage"), rates.get("spend")
        if extra is None and spend is None:
            return missing("claude")
        if extra is not None and not isinstance(extra, dict) or spend is not None and not isinstance(spend, dict):
            raise ValueError("Invalid usage")
        enabled = [flag(block[key]) for block, key in ((extra, "is_enabled"), (spend, "enabled"))
                   if block is not None and key in block]
        if True in enabled and False in enabled:
            raise ValueError("Conflicting credit enablement")
        result["enabled"] = enabled[0] if enabled and all(value == enabled[0] for value in enabled) else None
        if spend is not None:
            result["can_purchase"] = flag(spend.get("can_purchase_credits"))
            if result["can_purchase"] is None:
                result["metadata_status"] = "missing"
            reload = spend.get("auto_reload")
            result["auto_reload"] = flag(reload.get("enabled")) if isinstance(reload, dict) else flag(reload)
            for key in AMOUNTS:
                value = spend.get(key)
                if value is None:
                    continue
                if not isinstance(value, dict) or not {"amount_minor", "currency", "exponent"}.issubset(value):
                    raise ValueError("Invalid structured money")
                if result["currency"] is not None and (result["currency"], result["exponent"]) != (value["currency"], value["exponent"]):
                    raise ValueError("Conflicting credit currencies")
                result.update(currency=value["currency"], exponent=value["exponent"], unit="currency_minor")
                result[key] = decimal_amount(value["amount_minor"])
        elif extra is not None:
            result.update(unit="provider_credits", currency=extra.get("currency"), exponent=extra.get("decimal_places"))
            for source, target in (("used_credits", "used"), ("monthly_limit", "limit")):
                if extra.get(source) is not None:
                    result[target] = decimal_amount(extra[source])
            if result["currency"] is not None and result["exponent"] is not None:
                result["unit"] = "currency_minor"
        validate_resources([result], "claude")
    except (ValueError, TypeError, KeyError):
        result = resource("claude", "claude.native_usage", status="invalid")
    return [result]


def codex_resources(rows):
    if not isinstance(rows, dict) or not rows:
        return missing("codex")
    results = []
    for identity, row in rows.items():
        result = resource("codex", "codex.account/rateLimits/read", identity)
        try:
            data = row.get("credits") if isinstance(row, dict) else None
            if data is None:
                result["metadata_status"] = "missing"
            elif not isinstance(data, dict):
                raise ValueError("Invalid credits")
            else:
                result.update(unit="provider_credits", has_credits=flag(data.get("hasCredits")),
                              unlimited=flag(data.get("unlimited")))
                if data.get("balance") is not None:
                    result["balance"] = decimal_amount(data["balance"])
            validate_resources([result], "codex")
        except (ValueError, TypeError, KeyError):
            result = resource("codex", "codex.account/rateLimits/read", identity, status="invalid")
        results.append(result)
    return results


def copilot_resources(rows):
    if not isinstance(rows, list) or not rows:
        return missing("copilot")
    results = []
    for index, row in enumerate(rows):
        identity = row.get("pool", index) if isinstance(row, dict) else index
        result = resource("copilot", "copilot.account.getQuota", identity)
        try:
            if not isinstance(row, dict):
                raise ValueError("Invalid overage")
            for key in CONTROLS:
                if key in row:
                    value = flag(row[key])
                    if value is not None:
                        result["native_controls"][key] = value
            result["enabled"] = flag(row.get("overageAllowedWithExhaustedQuota"))
            if row.get("usageAllowedWithExhaustedQuota") is True:
                result["enabled"] = True
            elif "usageAllowedWithExhaustedQuota" in row:
                flag(row["usageAllowedWithExhaustedQuota"])
            if row.get("overage") is not None:
                result["used"] = decimal_amount(row["overage"])
            result["unlimited"] = flag(row.get("isUnlimitedEntitlement"))
            if result["enabled"] is None:
                result["metadata_status"] = "missing"
            validate_resources([result], "copilot")
        except (ValueError, TypeError, KeyError):
            result = resource("copilot", "copilot.account.getQuota", identity, status="invalid")
        results.append(result)
    return results


def antigravity_settings_path():
    return Path.home() / ".gemini" / "antigravity-cli" / "settings.json"


def antigravity_resources():
    """Report the local fallback control without inventing account credit metadata."""
    result = resource("antigravity", AGY_SETTINGS_SOURCE, identity="cli_settings", status="missing")
    try:
        path = antigravity_settings_path()
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("Settings must be a regular file")
        with path.open("rb") as handle:
            raw = handle.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise ValueError("Settings exceed size bound")
        def unique(pairs):
            obj = {}
            for key, value in pairs:
                if key in obj:
                    raise ValueError("Duplicate settings key")
                obj[key] = value
            return obj
        data = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(data, dict):
            raise ValueError("Settings must be an object")
        if "useG1Credits" not in data:
            return [result]
        enabled = data["useG1Credits"]
        if type(enabled) is not bool:
            raise ValueError("Credit control must be boolean")
        result.update(enabled=enabled, metadata_status="reported", native_controls={"useG1Credits": enabled})
    except FileNotFoundError:
        pass
    except (OSError, ValueError, UnicodeError, RecursionError):
        result["metadata_status"] = "invalid"
    return [result]


def native_reasons(service, rows):
    if service not in SERVICES:
        return []
    try:
        validate_resources(rows, service)
    except (ValueError, TypeError):
        return ["credit_metadata_invalid"]
    if service == "antigravity":
        current = antigravity_resources()[0]
        if current["metadata_status"] == "invalid":
            return ["credit_metadata_invalid"]
        if current["metadata_status"] != "reported":
            return ["credit_metadata_unverified"]
        if current["enabled"] is not False:
            return ["native_paid_execution_unsupported"]
        if any(row["source"] != AGY_SETTINGS_SOURCE
               or row["native_controls"] != {"useG1Credits": False} for row in rows):
            return ["credit_metadata_unverified"]
    if not rows or any(row["metadata_status"] != "reported" for row in rows):
        return ["credit_metadata_unverified"]
    if any(row["enabled"] is not False or row["auto_reload"] is True or row["can_purchase"] is True
           for row in rows):
        return ["native_paid_execution_unsupported"]
    return []


def gate(result, service):
    reasons = native_reasons(service, result.get("credit_resources", []))
    if reasons:
        result["allowed"] = False
        result["allowed_by_observed_threshold"] = False
        result.setdefault("reasons", []).extend(reason for reason in reasons if reason not in result.get("reasons", []))
    return result
