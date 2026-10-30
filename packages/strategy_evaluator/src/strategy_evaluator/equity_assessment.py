"""Equity facts for shared SE assessment; no runtime or execution imports."""

from datetime import datetime
from contextvars import ContextVar
from hashlib import sha256
import inspect
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

from .equity import audit_equity_account
from .models import ValidationError


LEDGER_FIELDS = frozenset({"initial_cash", "specification", "bars", "decisions", "orders",
    "fills", "actions", "account_points", "trades", "action_facts", "constraints", "fee_rate"})


_active_certification = ContextVar("equity_account_certification", default=None)


class EquityCertificationScope:
    """Own numerical audits for exact immutable ledgers, never caller PASS claims.

    The cache is process-local and cannot be serialized as certification authority.
    Entering a scope again reuses its audits; different scopes independently audit.
    """

    def __init__(self):
        self.audit_version = sha256(Path(inspect.getsourcefile(audit_equity_account)).read_bytes()).hexdigest()
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

    def certify(self, ledger, *, decision_contract="FORMAL_V2"):
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


def certify_equity_ledger(ledger, *, decision_contract="FORMAL_V2"):
    """Independently audit, or reuse the current owner's exact prior audit."""
    scope = _active_certification.get()
    if scope is None:
        return audit_equity_account(**ledger, decision_contract=decision_contract)
    return scope.certify(ledger, decision_contract=decision_contract)


def canonical_ledger(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


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
    if type(ledger) is not dict or set(ledger) != LEDGER_FIELDS or canonical_ledger(ledger) != value:
        raise ValidationError("equity ledger schema or canonical encoding differs")
    return ledger


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
    if (facts.market, facts.timezone, facts.currency) != ("US", "America/New_York", "USD"):
        raise ValidationError("unsupported equity assessment market identity")
    if facts.drawdown_basis not in {"SESSION_CLOSE", "BAR_CLOSE"}:
        raise ValidationError("equity assessment requires explicit drawdown basis")
    if facts.concentration_basis not in {"TOP_DECILE", "MAX_SINGLE"}:
        raise ValidationError("equity assessment requires explicit concentration basis")
    candidate, benchmark = (read_ledger(value) for value in (facts.candidate_ledger, facts.benchmark_ledger))
    for ledger in (candidate, benchmark):
        if ledger["specification"]["market"] != {"rule_version": "US_EQUITY_V1"}:
            raise ValidationError("equity ledger market differs")
        if ledger["specification"]["account"]["currency"] != facts.currency:
            raise ValidationError("equity ledger currency differs")
        certify_equity_ledger(ledger, decision_contract="FORMAL_V2")
        for point in ledger["account_points"]:
            if point["session"] != session(point["time"], facts.timezone):
                raise ValidationError("equity account session differs from market timezone")
    for key in ("initial_cash", "specification", "bars", "action_facts", "constraints", "fee_rate"):
        if candidate[key] != benchmark[key]:
            raise ValidationError("equity benchmark execution facts differ")
    if [p["time"] for p in candidate["account_points"]] != [p["time"] for p in benchmark["account_points"]]:
        raise ValidationError("equity benchmark observation calendar differs")


def validate_equity_assessment(evidence):
    facts = evidence.equity
    candidate, benchmark = read_ledger(facts.candidate_ledger), read_ledger(facts.benchmark_ledger)
    if evidence.initial_cash != candidate["initial_cash"] or evidence.opening_cash != evidence.initial_cash or evidence.opening_quantity:
        raise ValidationError("equity assessment opening identity differs")
    expected = tuple((r["session"], float(r["cash"]), int(r["quantity"]), float(r["close"]), float(r["equity"]))
                     for r in daily_points(candidate))
    actual = tuple((r.session, r.cash, r.quantity, r.close, r.equity) for r in evidence.account)
    if actual != expected:
        raise ValidationError("equity assessment daily account differs from audited journal")
    expected_fills = tuple((r["cycle_id"], session(r["interval_end"], facts.timezone), r["side"],
                            int(r["quantity"]), float(r["price"]), float(r["fees"])) for r in candidate["fills"])
    actual_fills = tuple((r.cycle_id, r.session, r.side.value, r.quantity, r.price, r.fees) for r in evidence.fills)
    if expected_fills != actual_fills:
        raise ValidationError("equity assessment fills differ from audited journal")
    expected_cycles = tuple((r["cycle_id"], session(r["exit_at"], facts.timezone)) for r in candidate["trades"])
    if expected_cycles != tuple((r.cycle_id, r.exit_session) for r in evidence.closed_cycles):
        raise ValidationError("equity assessment cycles differ from audited journal")
    if evidence.benchmark_equity != tuple(float(r["equity"]) for r in daily_points(benchmark)):
        raise ValidationError("equity assessment benchmark differs from audited journal")
    if evidence.scenario_context.one_way_cost != candidate["fee_rate"]:
        raise ValidationError("equity assessment fee differs from audited journal")
    expected_version = f"equity-assessment-v2:{facts.drawdown_basis}:{facts.concentration_basis}"
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


def equity_concentration(evidence):
    ledger = read_ledger(evidence.equity.candidate_ledger)
    winners = sorted((row["net_pnl"] for row in ledger["trades"] if row["net_pnl"] > 0), reverse=True)
    if not winners:
        return None
    count = 1 if evidence.equity.concentration_basis == "MAX_SINGLE" else math.ceil(0.1 * len(winners))
    return float(sum(winners[:count]) / sum(winners))
