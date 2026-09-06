"""Private monetary caps and durable dispatch liabilities, separate from quotas."""
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json
import re
import time
import uuid
from zoneinfo import ZoneInfo

from quota import Ledger

SCALE = 10_000_000_000
MAX_TICKS = 9_000_000_000_000_000_000


def ticks(value):
    if isinstance(value, (bool, float)) or len(str(value)) > 256:
        raise ValueError("money must be an exact decimal string")
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount < 0 or amount > Decimal(MAX_TICKS) / SCALE:
            raise ValueError("invalid money amount")
        parts = amount.as_tuple()
        shifted = Decimal((parts.sign, parts.digits, parts.exponent + 10))
        return int(shifted.to_integral_value(rounding=ROUND_CEILING))
    except (InvalidOperation, TypeError, OverflowError) as exc:
        raise ValueError("invalid money amount") from exc


def amount(value):
    return format(Decimal(value) / SCALE, ".10f")


def identifier(value, kind="identifier"):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}", value):
        raise ValueError(f"invalid {kind}")
    return value


def currency(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}", value):
        raise ValueError("currency must be an uppercase ISO code")
    return value


def scope_name(value):
    if value != "total" and not re.fullmatch(r"(?:api|extra):[a-z][a-z0-9_-]{0,63}", value):
        raise ValueError("scope must be total, api:SERVICE or extra:SERVICE")
    return value


class SpendLedger:
    def __init__(self, path=None, *, ledger=None):
        self.ledger = ledger or Ledger(path)
        with self.ledger._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS money_caps (
                    scope TEXT PRIMARY KEY, currency TEXT NOT NULL, cap INTEGER NOT NULL,
                    mode TEXT NOT NULL CHECK(mode IN ('strict','observed')));
                CREATE TABLE IF NOT EXISTS money_additions (
                    id TEXT PRIMARY KEY, scope TEXT NOT NULL, month TEXT NOT NULL,
                    ticks INTEGER NOT NULL, digest TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS money_requests (
                    id TEXT PRIMARY KEY, scope TEXT NOT NULL, month TEXT NOT NULL,
                    currency TEXT NOT NULL, digest TEXT NOT NULL, reserved INTEGER NOT NULL,
                    charged INTEGER, status TEXT NOT NULL, kind TEXT, evidence TEXT,
                    review_required INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS money_rates (
                    service TEXT NOT NULL, model TEXT NOT NULL, currency TEXT NOT NULL,
                    rates TEXT NOT NULL, observed REAL NOT NULL, expires REAL NOT NULL,
                    evidence TEXT NOT NULL, PRIMARY KEY(service,model));
                CREATE TABLE IF NOT EXISTS money_audit (
                    id INTEGER PRIMARY KEY, at REAL NOT NULL, action TEXT NOT NULL, data TEXT NOT NULL);
            """)

    def month(self, now=None):
        return datetime.fromtimestamp(time.time() if now is None else now,
                                      ZoneInfo(self.ledger.policy["timezone"])).strftime("%Y-%m")

    def _audit(self, db, action, data):
        db.execute("INSERT INTO money_audit(at,action,data) VALUES (?,?,?)",
                   (time.time(), action, json.dumps(data, sort_keys=True)))

    def configure(self, scope, monthly, code="USD", mode="strict"):
        scope_name(scope)
        currency(code)
        cap = ticks(monthly)
        if mode not in {"strict", "observed"}:
            raise ValueError("invalid monetary mode")
        with self.ledger._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            other = db.execute("SELECT currency FROM money_caps WHERE scope<>?", (scope,)).fetchall()
            history = db.execute("SELECT DISTINCT currency FROM money_requests").fetchall()
            previous = db.execute("SELECT currency FROM money_caps WHERE scope=?", (scope,)).fetchone()
            if any(row[0] != code for row in other + history) or previous and previous[0] != code:
                raise ValueError("currency mismatch; conversion is not supported")
            db.execute("INSERT OR REPLACE INTO money_caps VALUES (?,?,?,?)", (scope, code, cap, mode))
            self._audit(db, "configure", dict(scope=scope, cap=cap, currency=code, mode=mode))
        return self.status()

    def add(self, scope, value, grant_id=None, now=None):
        scope_name(scope)
        value = ticks(value)
        if value <= 0:
            raise ValueError("addition must be positive")
        grant_id = identifier(grant_id or str(uuid.uuid4()))
        with self.ledger._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            month = self.month(now)
            digest = hashlib.sha256(f"{scope}:{month}:{value}".encode()).hexdigest()
            prior = db.execute("SELECT digest FROM money_additions WHERE id=?", (grant_id,)).fetchone()
            if prior:
                if prior[0] != digest:
                    raise ValueError("addition ID already has a different payload")
            else:
                if not db.execute("SELECT 1 FROM money_caps WHERE scope=?", (scope,)).fetchone():
                    raise ValueError("configure scope before adding money")
                total = db.execute("SELECT COALESCE(SUM(ticks),0) FROM money_additions WHERE scope=? AND month=?",
                                   (scope, month)).fetchone()[0]
                if total + value > MAX_TICKS:
                    raise ValueError("addition overflow")
                db.execute("INSERT INTO money_additions VALUES (?,?,?,?,?)", (grant_id, scope, month, value, digest))
                self._audit(db, "add", dict(id=grant_id, scope=scope, month=month, ticks=value))
        return dict(id=grant_id, **self.status(now=now))

    def _status(self, db, month, scope=None):
        caps = []
        for name, code, cap, mode in db.execute("SELECT scope,currency,cap,mode FROM money_caps ORDER BY scope"):
            if scope and name not in {"total", scope}:
                continue
            extra = db.execute("SELECT COALESCE(SUM(ticks),0) FROM money_additions WHERE scope=? AND month=?",
                               (name, month)).fetchone()[0]
            rows = db.execute("SELECT month,reserved,charged,status,review_required FROM money_requests" +
                              (" WHERE scope=?" if name != "total" else ""), (name,) if name != "total" else ()).fetchall()
            charged = sum(row[2] or 0 for row in rows if row[0] == month and row[3] == "SETTLED")
            pending = sum(row[1] for row in rows if row[3] != "SETTLED")
            blocked = any(row[4] for row in rows)
            caps.append(dict(scope=name, currency=code, mode=mode, cap=amount(cap + extra),
                             charged=amount(charged), pending=amount(pending),
                             available=amount(max(0, cap + extra - charged - pending)), cap_ticks=cap + extra,
                             charged_ticks=charged, pending_ticks=pending,
                             available_ticks=max(0, cap + extra - charged - pending), review_required=blocked))
        return caps

    def status(self, now=None):
        with self.ledger._connect() as db:
            db.execute("BEGIN DEFERRED")
            return dict(month=self.month(now), timezone=self.ledger.policy["timezone"],
                        caps=self._status(db, self.month(now)),
                        unfinished=[dict(id=r[0], scope=r[1], month=r[2], status=r[3], reserved_ticks=r[4])
                                    for r in db.execute("SELECT id,scope,month,status,reserved FROM money_requests WHERE status<>'SETTLED'")],
                        note="Unfinished dispatches retain liability across months; no automatic expiry or refund.")

    def request(self, request_id):
        identifier(request_id)
        with self.ledger._connect() as db:
            row = db.execute("SELECT id,scope,month,currency,digest,reserved,charged,status,kind,evidence,review_required FROM money_requests WHERE id=?", (request_id,)).fetchone()
            return dict(zip(("id", "scope", "month", "currency", "digest", "reserved_ticks", "charged_ticks", "status", "kind", "evidence", "review_required"), row)) if row else None

    def authorize(self, scope, reserve, code, digest, request_id=None, now=None):
        scope_name(scope)
        currency(code)
        if scope == "total" or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("invalid dispatch scope or digest")
        reservation = ticks(reserve)
        if reservation <= 0:
            raise ValueError("positive per-request reservation required")
        request_id = identifier(request_id or str(uuid.uuid4()))
        with self.ledger._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT scope,currency,digest,reserved FROM money_requests WHERE id=?", (request_id,)).fetchone()
            if prior:
                if prior != (scope, code, digest, reservation):
                    raise ValueError("request ID already has a different payload")
                return dict(id=request_id, dispatch=False, status="duplicate_accounting_only")
            instant = time.time() if now is None else now
            month = self.month(instant)
            caps = self._status(db, month, scope)
            if not any(cap["scope"] == "total" for cap in caps):
                raise ValueError("configure a total monthly monetary cap first")
            for cap in caps:
                if cap["currency"] != code:
                    raise ValueError("currency mismatch; conversion is not supported")
                if cap["mode"] != "observed":
                    raise ValueError("strict monetary mode blocks providers without enforceable cost bounds")
                if cap["review_required"]:
                    raise ValueError("unreconciled overrun blocks dispatch; additions do not clear it")
                if reservation > cap["available_ticks"]:
                    raise ValueError("monthly monetary cap reached")
            db.execute("INSERT INTO money_requests(id,scope,month,currency,digest,reserved,status,created) VALUES (?,?,?,?,?,?,'DISPATCHED',?)",
                       (request_id, scope, month, code, digest, reservation, instant))
            self._audit(db, "dispatch", dict(id=request_id, scope=scope, month=month, reserved=reservation))
        return dict(id=request_id, dispatch=True, status="DISPATCHED")

    def unresolved(self, request_id):
        with self.ledger._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE money_requests SET status='UNRESOLVED' WHERE id=? AND status='DISPATCHED'", (identifier(request_id),))
        return self.request(request_id)

    def settle(self, request_id, charged_ticks, evidence, kind="actual", *, reconcile=False):
        identifier(request_id)
        identifier(evidence, "evidence reference")
        if type(charged_ticks) is not int or not 0 <= charged_ticks <= MAX_TICKS or kind not in {"actual", "estimated"}:
            raise ValueError("invalid settlement")
        with self.ledger._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT reserved,charged,status,kind,evidence,review_required FROM money_requests WHERE id=?", (request_id,)).fetchone()
            if not row:
                raise ValueError("request not found")
            if row[2] == "SETTLED":
                if row[3] == "actual" and (kind != "actual" or charged_ticks < row[1]):
                    raise ValueError("cannot reduce evidenced actual consumption")
                if not reconcile:
                    if (charged_ticks, kind, evidence) != (row[1], row[3], row[4]):
                        raise ValueError("settlement already exists; reconcile explicitly")
                    return dict(id=request_id, status="SETTLED", charged_ticks=row[1])
            latch = 0 if reconcile else int(bool(row[5]) or charged_ticks > row[0])
            db.execute("UPDATE money_requests SET charged=?,status='SETTLED',kind=?,evidence=?,review_required=? WHERE id=?",
                       (charged_ticks, kind, evidence, latch, request_id))
            self._audit(db, "reconcile" if reconcile else "settle", dict(id=request_id, ticks=charged_ticks, kind=kind, evidence=evidence))
        return self.request(request_id)

    def record_expense(self, scope, value, code, evidence, request_id=None, now=None):
        """Import a verified charge; recording consumption never dispatches inference."""
        scope_name(scope)
        currency(code)
        identifier(evidence, "evidence reference")
        if scope == "total":
            raise ValueError("expense needs an api or extra service scope")
        charged = ticks(value)
        request_id = identifier(request_id or str(uuid.uuid4()))
        with self.ledger._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            instant = time.time() if now is None else now
            month = self.month(instant)
            digest = hashlib.sha256(f"receipt:{scope}:{code}:{charged}:{evidence}".encode()).hexdigest()
            prior = db.execute("SELECT digest FROM money_requests WHERE id=?", (request_id,)).fetchone()
            if prior:
                if prior[0] != digest:
                    raise ValueError("receipt ID already has a different payload")
                return {"id": request_id, "status": "duplicate_accounting_only"}
            caps = self._status(db, month, scope)
            if not any(cap["scope"] == "total" for cap in caps):
                raise ValueError("configure total before importing expenses")
            if any(cap["currency"] != code for cap in caps):
                raise ValueError("currency mismatch; conversion is not supported")
            latch = int(any(charged > cap["available_ticks"] for cap in caps))
            db.execute("INSERT INTO money_requests VALUES (?,?,?,?,?,?,?,'SETTLED','actual',?,?,?)",
                       (request_id, scope, month, code, digest, 0, charged, evidence, latch, instant))
            self._audit(db, "expense", dict(id=request_id, scope=scope, month=month, ticks=charged, evidence=evidence))
        return self.request(request_id)

    def set_rates(self, service, model, rates, observed, expires, evidence, code="USD"):
        identifier(service)
        identifier(model)
        identifier(evidence, "evidence reference")
        currency(code)
        if not isinstance(rates, dict) or not rates:
            raise ValueError("nonempty per-million token rates required")
        converted = {identifier(key): ticks(value) for key, value in rates.items()}
        if not isinstance(observed, (int, float)) or not isinstance(expires, (int, float)) or not 0 <= observed < expires < 1e12:
            raise ValueError("invalid rate validity interval")
        with self.ledger._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR REPLACE INTO money_rates VALUES (?,?,?,?,?,?,?)",
                       (service, model, code, json.dumps(converted), observed, expires, evidence))
            self._audit(db, "rates", dict(service=service, model=model, currency=code, observed=observed, expires=expires, evidence=evidence))

    def rates(self, service, model, now=None):
        now = time.time() if now is None else now
        with self.ledger._connect() as db:
            row = db.execute("SELECT currency,rates,observed,expires,evidence FROM money_rates WHERE service=? AND model=?", (service, model)).fetchone()
            if not row or not row[2] <= now < row[3]:
                raise ValueError("missing or stale explicit model rates")
            return dict(currency=row[0], rates=json.loads(row[1]), observed_at=row[2], expires_at=row[3], evidence=row[4])


def estimate(usage, rates):
    if not isinstance(usage, dict) or not usage:
        raise ValueError("missing token usage")
    total = 0
    for key, count in usage.items():
        if type(count) is not int or count < 0 or count > MAX_TICKS:
            raise ValueError("invalid billed token class")
        if count and key not in rates:
            raise ValueError("unknown billed token class; liability retained")
        total += count * rates.get(key, 0)
    result = (total + 999_999) // 1_000_000
    if result > MAX_TICKS:
        raise ValueError("cost overflow")
    return result
