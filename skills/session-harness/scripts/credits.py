"""Allowlisted credit metadata; no native paid execution contract is verified."""
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import stat
import re
import tempfile
import time


SERVICES = {"claude", "codex", "copilot", "antigravity"}
FLAGS = ("enabled", "auto_reload", "can_purchase", "has_credits", "unlimited")
AMOUNTS = ("balance", "used", "limit", "cap")
SOURCES = {"claude": "claude.native_usage", "codex": "codex.account/rateLimits/read",
           "copilot": "copilot.account.getQuota", "antigravity": "antigravity.native_usage"}
AGY_SETTINGS_SOURCE = "antigravity.cli_settings"
AGY_DEFAULTS_SOURCE = "antigravity.cli_defaults"
CONTROLS = {"useG1Credits", "tokenBasedBilling", "hasQuota", "usageAllowedWithExhaustedQuota", "overageAllowedWithExhaustedQuota"}


def credit_policy_path():
    root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return root / "session-harness/native-credit-policy/codex.json"


def private_json(path):
    original = path.lstat()
    if not stat.S_ISREG(original.st_mode):
        raise ValueError("Credit evidence must be a regular file")
    if os.name != "nt" and (original.st_uid != os.getuid() or original.st_mode & 0o077):
        raise ValueError("Credit evidence must be private to its owner")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (original.st_dev, original.st_ino):
            raise ValueError("Credit evidence changed during read")
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("Credit evidence is too large")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate credit evidence key")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("Credit evidence must be an object")
    return value


def codex_account_fingerprint():
    path = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "auth.json"
    data = private_json(path)
    account = data.get("tokens", {}).get("account_id")
    if (data.get("auth_mode") != "chatgpt" or data.get("OPENAI_API_KEY")
            or not isinstance(account, str) or not account or len(account) > 512):
        raise ValueError("A current ChatGPT account is required")
    return hashlib.sha256(("codex-account:" + account).encode()).hexdigest()


def codex_owner_policy():
    if os.name == "nt":
        return None
    try:
        value = private_json(credit_policy_path())
        if (set(value) != {"version", "service", "source", "account_fingerprint", "auto_top_up", "confirmed_at"}
                or type(value["version"]) is not int or value["version"] != 1
                or value["service"] != "codex" or value["source"] != "owner_confirmation"
                or value["auto_top_up"] is not False
                or type(value["confirmed_at"]) not in (int, float)
                or not 0 < value["confirmed_at"] <= time.time() + 60
                or value["account_fingerprint"] != codex_account_fingerprint()):
            raise ValueError("Invalid or account-mismatched credit policy")
        return value
    except (OSError, ValueError, TypeError, AttributeError, UnicodeError, RecursionError):
        return None


def configure_codex_policy(*, disabled=False, revoke=False):
    if disabled and revoke:
        raise ValueError("Choose confirmation or revocation")
    path = credit_policy_path()
    if revoke:
        path.unlink(missing_ok=True)
    elif disabled:
        if os.name == "nt":
            raise ValueError("Owner confirmation requires a POSIX file-backed account authority")
        value = dict(version=1, service="codex", source="owner_confirmation",
                     account_fingerprint=codex_account_fingerprint(), auto_top_up=False,
                     confirmed_at=time.time())
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            os.chmod(path.parent, 0o700)
        fd, temporary = tempfile.mkstemp(prefix=".policy-", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(value, stream)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    value = codex_owner_policy()
    return {"service": "codex", "source": "owner_confirmation" if value else None,
            "auto_top_up": False if value else None,
            "confirmed_at": value["confirmed_at"] if value else None,
            "account_matches": bool(value), "paid_execution_supported": False}


def codex_subscription_only(rows):
    if not codex_owner_policy() or not rows:
        return False
    reported = [row for row in rows if row["metadata_status"] == "reported"]
    if not reported:
        return False
    for row in rows:
        if (row["metadata_status"] == "invalid" or row["native_controls"]
                or any(row[key] is True for key in ("enabled", "auto_reload", "can_purchase"))):
            return False
        if row["metadata_status"] == "reported":
            if (row["has_credits"] is not False or row["unlimited"] is not False
                    or row["balance"] is None or Decimal(row["balance"]) != 0):
                return False
        elif any(row[key] is not None for key in FLAGS + AMOUNTS):
            return False
    return True


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
                or row["source"] not in ({SOURCES[service], AGY_SETTINGS_SOURCE, AGY_DEFAULTS_SOURCE}
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
    """Resolve the sparse CLI setting without inventing account credit metadata."""
    result = resource("antigravity", AGY_SETTINGS_SOURCE, identity="cli_settings", status="missing")
    try:
        path = antigravity_settings_path()
        try:
            original = path.lstat()
        except FileNotFoundError:
            for parent in path.parents:
                try:
                    ancestor = parent.stat()
                except FileNotFoundError:
                    continue
                if not stat.S_ISDIR(ancestor.st_mode):
                    raise ValueError("Settings parent must be a directory")
                break
            result.update(source=AGY_DEFAULTS_SOURCE, enabled=False, metadata_status="reported",
                          native_controls={"useG1Credits": False})
            return [result]
        if not stat.S_ISREG(original.st_mode):
            raise ValueError("Settings must be a regular file")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if (not stat.S_ISREG(opened.st_mode)
                    or (opened.st_dev, opened.st_ino) != (original.st_dev, original.st_ino)):
                raise ValueError("Settings changed during read")
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
            result["source"] = AGY_DEFAULTS_SOURCE
        enabled = data.get("useG1Credits", False)
        if type(enabled) is not bool:
            raise ValueError("Credit control must be boolean")
        result.update(enabled=enabled, metadata_status="reported", native_controls={"useG1Credits": enabled})
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
    if service == "codex" and codex_subscription_only(rows):
        return []
    if service == "antigravity":
        current = antigravity_resources()[0]
        if current["metadata_status"] == "invalid":
            return ["credit_metadata_invalid"]
        if current["metadata_status"] != "reported":
            return ["credit_metadata_unverified"]
        if current["enabled"] is not False:
            return ["native_paid_execution_unsupported"]
        if any(row["source"] not in {AGY_SETTINGS_SOURCE, AGY_DEFAULTS_SOURCE}
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
    elif service == "codex":
        result["credit_policy"] = configure_codex_policy()
    return result
