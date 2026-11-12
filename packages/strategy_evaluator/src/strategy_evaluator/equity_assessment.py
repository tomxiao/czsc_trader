"""Equity facts for shared SE assessment; no runtime or execution imports."""

from datetime import datetime
from contextvars import ContextVar
from hashlib import sha256
from functools import lru_cache
import inspect
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo
from types import MappingProxyType

from .equity import audit_equity_account
from .models import ValidationError


LEDGER_FIELDS = frozenset({"initial_cash", "specification", "bars", "decisions", "orders",
    "fills", "account_entries", "account_points", "trades", "price_basis", "quantity_basis", "constraints", "fee_rate", "account_contract"})


_active_certification = ContextVar("equity_account_certification", default=None)


class EquityCertificationScope:
    """Own numerical audits for exact immutable ledgers, never caller PASS claims.

    The cache is process-local and cannot be serialized as certification authority.
    Entering a scope again reuses its audits; different scopes independently audit.
    """

    def __init__(self):
        from . import equity_v4
        self.audit_version = sha256(Path(inspect.getsourcefile(audit_equity_account)).read_bytes()
            + Path(equity_v4.__file__).read_bytes()).hexdigest()
        self.__audits = {}
        self.__tokens = []
        self.audit_count = 0
        self.reused_count = 0

    def __enter__(self):
        self.__tokens.append(_active_certification.set(self))
        return self

    def __exit__(self, *exc):
        _active_certification.reset(self.__tokens.pop())

    def __reduce__(self):
        raise TypeError("certification scopes cannot cross process or persistence boundaries")

    def certify(self, ledger, *, decision_contract="FORMAL_V4"):
        content = canonical_ledger(ledger).encode()
        key = (self.audit_version, decision_contract, sha256(content).hexdigest())
        stored = self.__audits.get(key)
        if stored is not None:
            if stored[0] != content:
                raise ValidationError("equity certification content collision")
            self.reused_count += 1
            return stored[1]
        # Audit the serialized snapshot, not a caller's mutable dictionary.
        result = audit_equity_account(**json.loads(content), decision_contract=decision_contract)
        self.__audits[key] = (content, result)
        self.audit_count += 1
        return result


def certify_equity_ledger(ledger, *, decision_contract="FORMAL_V4"):
    """Independently audit, or reuse the current owner's exact prior audit."""
    scope = _active_certification.get()
    if scope is None:
        return audit_equity_account(**ledger, decision_contract=decision_contract)
    return scope.certify(ledger, decision_contract=decision_contract)


def canonical_ledger(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_observations(ledger):
    """Encode only the recorded values needed by deterministic SE metrics.

    Complete journals remain separate evidence. This projection is neither a
    journal audit nor a reconstruction of trading or accounting events.
    """
    return canonical_ledger({
        "observation_contract": 1,
        "initial_cash": ledger["initial_cash"],
        "specification": {
            "market": ledger["specification"]["market"],
            "account": {"currency": ledger["specification"]["account"]["currency"]},
        },
        "account_points": [{name: row[name] for name in ("time", "session", "equity")}
                           for row in ledger["account_points"]],
        "trades": [{name: row[name] for name in ("cycle_id", "exit_at", "net_pnl")}
                   for row in ledger["trades"]],
    })


def _freeze(value):
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


@lru_cache(maxsize=16)
def read_ledger(value):
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValidationError("duplicate equity ledger field")
            result[key] = item
        return result
    ledger = json.loads(value, object_pairs_hook=pairs,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValidationError("nonfinite equity fact")))
    compact = (type(ledger) is dict and type(ledger.get("observation_contract")) is int
               and ledger["observation_contract"] == 1
               and set(ledger) == {"observation_contract", "initial_cash", "specification", "account_points", "trades"})
    if type(ledger) is not dict or (not compact and set(ledger) not in (LEDGER_FIELDS, LEDGER_FIELDS | {"execution_bars"})):
        raise ValidationError("equity observations require full V4 fields or an explicit observation schema")
    if not compact and (type(ledger["account_contract"]) is not int or ledger["account_contract"] != 4):
        raise ValidationError("unknown account ledger contract")
    initial = ledger["initial_cash"]
    if type(initial) not in (int, float) or not math.isfinite(initial) or initial <= 0:
        raise ValidationError("equity observations require positive finite initial cash")
    points = ledger["account_points"]
    if not points:
        raise ValidationError("equity observations require account points")
    market = ledger["specification"]["market"]["rule_version"]
    if market not in {"US_EQUITY_V1", "CN_EQUITY_V1"}:
        raise ValidationError("unsupported equity observation market")
    timezone = "America/New_York" if market == "US_EQUITY_V1" else "Asia/Shanghai"
    previous = None
    for point in points:
        stamp = datetime.fromisoformat(point["time"])
        if stamp.utcoffset() is None or (previous is not None and stamp <= previous):
            raise ValidationError("equity observation times must be aware, ordered and unique")
        if point["session"] != session(point["time"], timezone):
            raise ValidationError("equity observation session differs from market timezone")
        previous = stamp
        equity = point["equity"]
        if type(equity) not in (int, float) or not math.isfinite(equity) or equity < 0:
            raise ValidationError("equity observations require finite nonnegative equity")
    cycles, dates = set(), {row["session"] for row in points}
    for row in ledger["trades"]:
        if type(row["cycle_id"]) is not str or not row["cycle_id"] or row["cycle_id"] in cycles:
            raise ValidationError("equity cycles require unique nonempty identities")
        if session(row["exit_at"], timezone) not in dates:
            raise ValidationError("equity cycle exit outside observation calendar")
        cycles.add(row["cycle_id"])
        if type(row["net_pnl"]) not in (int, float) or not math.isfinite(row["net_pnl"]):
            raise ValidationError("equity cycles require finite net profit")
    return _freeze(ledger)


def _assessment_ledgers(facts):
    candidate = read_ledger(facts.candidate_ledger)
    benchmark = None if facts.benchmark_ledger is None else read_ledger(facts.benchmark_ledger)
    return candidate, benchmark


def session(stamp, timezone):
    value = datetime.fromisoformat(stamp)
    if value.utcoffset() is None:
        raise ValidationError("equity facts require aware timestamps")
    return value.astimezone(ZoneInfo(timezone)).date().isoformat()


def daily_points(ledger):
    result = {}
    for row in ledger["account_points"]:
        result[row["session"]] = row
    return tuple(result.values())


def validate_equity_facts(facts):
    if (facts.market, facts.timezone, facts.currency) not in {("US", "America/New_York", "USD"), ("CN", "Asia/Shanghai", "CNY")}:
        raise ValidationError("unsupported equity assessment market identity")
    if facts.drawdown_basis not in {"SESSION_CLOSE", "BAR_CLOSE"}:
        raise ValidationError("equity assessment requires explicit drawdown basis")
    if facts.concentration_basis not in {"TOP_DECILE", "MAX_SINGLE"}:
        raise ValidationError("equity assessment requires explicit concentration basis")
    candidate, benchmark = _assessment_ledgers(facts)
    for ledger in ((candidate,) if benchmark is None else (candidate, benchmark)):
        if ledger["specification"]["market"] != {"rule_version": facts.market + "_EQUITY_V1"}:
            raise ValidationError("equity ledger market differs")
        if ledger["specification"]["account"]["currency"] != facts.currency:
            raise ValidationError("equity ledger currency differs")
    if benchmark is None:
        return
    for key in ("initial_cash", "specification"):
        if candidate[key] != benchmark[key]:
            raise ValidationError("equity benchmark execution facts differ")
    if [p["time"] for p in candidate["account_points"]] != [p["time"] for p in benchmark["account_points"]]:
        raise ValidationError("equity benchmark observation calendar differs")


def validate_equity_assessment(evidence):
    facts = evidence.equity
    present = facts.benchmark_ledger is not None
    if present != bool(evidence.benchmark_equity) or present != (evidence.scenario_context.benchmark_id is not None):
        raise ValidationError("equity assessment benchmark presence differs")
    if evidence.opening_cash != evidence.initial_cash or evidence.opening_quantity:
        raise ValidationError("equity assessment opening identity differs")
    expected_version = f"equity-assessment-v4:{facts.drawdown_basis}:{facts.concentration_basis}"
    if evidence.metric_version != expected_version:
        raise ValidationError("equity metric semantics differ")


def equity_performance(evidence, *, benchmark=False):
    facts = evidence.equity
    ledger = read_ledger(facts.benchmark_ledger if benchmark else facts.candidate_ledger)
    daily = daily_points(ledger)
    annual = (daily[-1]["equity"] / evidence.initial_cash) ** (252 / len(daily)) - 1
    if not math.isfinite(annual):
        raise ValidationError("annual return overflow")
    curve = ledger["account_points"] if facts.drawdown_basis == "BAR_CLOSE" else daily
    peak, drawdown = evidence.initial_cash, 0.0
    for point in curve:
        peak = max(peak, point["equity"])
        drawdown = max(drawdown, 1 - point["equity"] / peak)
    return float(annual), float(drawdown)


def _equity_concentration_parts(evidence):
    ledger = read_ledger(evidence.equity.candidate_ledger)
    winners = sorted((row["net_pnl"] for row in ledger["trades"] if row["net_pnl"] > 0), reverse=True)
    count = 1 if evidence.equity.concentration_basis == "MAX_SINGLE" else math.ceil(0.1 * len(winners))
    return len(winners), min(count, len(winners)), float(sum(winners[:count])), float(sum(winners))


def equity_concentration(evidence):
    _, _, selected, total = _equity_concentration_parts(evidence)
    return selected / total if total else None
