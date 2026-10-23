"""Deterministic accounting decomposition of retained, authenticated account facts.

No strategy execution, provider access, classification discovery or causal attribution.
Amounts and quantities remain in the replay's own pricing units.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
import math

from .models import Record
from .replay_audit import ReplayEvidence


DIAGNOSIS_PROTOCOL = "single-long-full-position-v1"


class AccountDiagnosisStatus(StrEnum):
    COMPUTED = "COMPUTED"
    INCOMPARABLE = "INCOMPARABLE"
    UNSUPPORTED = "UNSUPPORTED"
    INVALID_EVIDENCE = "INVALID_EVIDENCE"


@dataclass(frozen=True)
class DailyPnl(Record):
    session: str
    opening_equity: float
    closing_equity: float
    entry: float
    holding: float
    exit: float
    fees: float
    equity_change: float
    residual: float
    cycle_id: str | None
    decision_ids: tuple[str, ...]
    order_ids: tuple[str, ...]
    fill_ids: tuple[str, ...]


@dataclass(frozen=True)
class AnnualPnl(Record):
    year: int
    start_session: str
    end_session: str
    partial_year: bool
    opening_equity: float
    closing_equity: float
    entry: float
    holding: float
    exit: float
    fees: float
    equity_change: float
    residual: float
    entry_contribution: float | None
    holding_contribution: float | None
    exit_contribution: float | None
    fee_contribution: float | None


@dataclass(frozen=True)
class AccountPnl(Record):
    evaluation_id: str
    daily: tuple[DailyPnl, ...]
    annual: tuple[AnnualPnl, ...]


@dataclass(frozen=True)
class DecisionCoverage(Record):
    evaluation_id: str
    population_id: str
    decision_id: str
    session: str
    member: bool | None
    buy_intent: bool
    buy_fill: bool
    holding_decision: bool


@dataclass(frozen=True)
class PopulationCoverageSummary(Record):
    evaluation_id: str
    population_id: str
    category: str
    total: int
    members: int
    nonmembers: int
    unknown: int
    member_fraction: float | None


@dataclass(frozen=True)
class CyclePathComparison(Record):
    symbol: str
    entry_session: str
    baseline_cycle_id: str | None
    alternative_cycle_id: str | None
    baseline_exit_session: str | None
    alternative_exit_session: str | None


@dataclass(frozen=True)
class DailyPathComparison(Record):
    session: str
    baseline_cash: float
    alternative_cash: float
    baseline_quantity: int
    alternative_quantity: int
    baseline_equity: float
    alternative_equity: float
    equity_difference: float


@dataclass(frozen=True)
class AccountDiagnosisCalculation(Record):
    status: AccountDiagnosisStatus
    protocol: str
    issues: tuple[str, ...]
    pnl_breakdown: tuple[AccountPnl, ...] = ()
    path_comparison: tuple[CyclePathComparison, ...] = ()
    daily_paths: tuple[DailyPathComparison, ...] = ()


class _Unsupported(ValueError):
    pass


def _day(value):
    return str(value)[:10]


def _close(left, right):
    # Fixed binary64 precision contract, never supplied by researchers.
    return math.isclose(left, right, rel_tol=1e-10, abs_tol=1e-7)


def _decompose(evaluation_id, replay, start, end):
    if replay.execution_spec.get("mode") == "CORE_EVENT_INTRADAY_ROTATION":
        raise _Unsupported("intraday overlay is outside full-position/cash diagnosis")
    if replay.execution_spec.get("capital_mode") == "signal_cash_fraction":
        raise _Unsupported("signal-owned cycle allocation is outside full-position/cash diagnosis")
    if replay.execution_spec.get("allocation_fraction", 1.0) != 1.0:
        raise _Unsupported("fractional capital allocation is outside full-position/cash diagnosis")
    rows = replay.account_daily
    if not rows or start < _day(rows[0]["date"]) or end > _day(rows[-1]["date"]):
        raise ValueError("diagnostic window is outside retained account coverage")
    by_session = {}
    cycle_fills = {}
    decisions_by_session = {}
    orders_by_session = {}
    for decision in replay.decisions:
        decisions_by_session.setdefault(_day(decision["valid_session"]), []).append(
            decision["decision_id"]
        )
    for order in replay.orders:
        orders_by_session.setdefault(_day(order["execution_date"]), []).append(order["order_id"])
    for fill in replay.fills:
        by_session.setdefault(_day(fill["fill_time"]), []).append(fill)
        cycle_fills.setdefault(fill["cycle_id"], []).append(fill)
    for fills in cycle_fills.values():
        if (
            sum(f["side"] == "BUY" for f in fills) != 1
            or sum(f["side"] == "SELL" for f in fills) > 1
        ):
            raise _Unsupported("scaling or multiple fills in one holding cycle are unsupported")
    previous_close = None
    previous_equity = replay.initial_cash
    active_cycle = None
    daily = []
    all_daily = []
    for row in rows:
        session = _day(row["date"])
        q0, q1 = int(row["quantity_before"]), int(row["quantity"])
        if q0 < 0 or q1 < 0 or float(row["target_position"]) not in (0.0, 1.0):
            raise _Unsupported("only long-only full-position/cash targets are supported")
        fills = by_session.get(session, [])
        if len(fills) > 1:
            raise _Unsupported("multiple or same-session roundtrip fills are unsupported")
        close = float(row["close"])
        entry = holding = exit_pnl = fees = 0.0
        cycle = active_cycle
        if q0 and previous_close is None:
            raise _Unsupported("opening position lacks a retained previous valuation")
        if fills:
            fill = fills[0]
            cycle = fill["cycle_id"]
            q, price = int(fill["quantity"]), float(fill["price"])
            fees = -float(fill["fees"])
            if fill["side"] == "BUY" and q0 == 0 and q1 == q:
                entry = q * (close - price)
                active_cycle = cycle
            elif fill["side"] == "SELL" and q0 == q and q1 == 0:
                exit_pnl = q * (price - previous_close)
                active_cycle = None
            else:
                raise _Unsupported("partial entry, partial exit or scaling is unsupported")
        elif q0 != q1:
            raise _Unsupported("position movement without a supported fill")
        elif q1:
            holding = q1 * (close - previous_close)
        equity = float(row["equity"])
        change = equity - previous_equity
        residual = change - (entry + holding + exit_pnl + fees)
        if not _close(residual, 0.0):
            raise ValueError(f"unreconciled account equity at {session}")
        item = DailyPnl(
            session,
            previous_equity,
            equity,
            entry,
            holding,
            exit_pnl,
            fees,
            change,
            residual,
            cycle,
            tuple(decisions_by_session.get(session, ())),
            tuple(orders_by_session.get(session, ())),
            tuple(f["fill_id"] for f in fills),
        )
        all_daily.append(item)
        if start <= session <= end:
            daily.append(item)
        previous_close, previous_equity = close, equity
    if not daily:
        raise ValueError("diagnostic window has no retained sessions")
    annual = []
    for year in sorted({int(d.session[:4]) for d in daily}):
        selected = [d for d in daily if int(d.session[:4]) == year]
        retained = [d for d in all_daily if int(d.session[:4]) == year]
        # Conservative calendar-bound declaration; no holiday calendar is inferred.
        partial = (
            selected[0] != retained[0]
            or selected[-1] != retained[-1]
            or start > f"{year}-01-01"
            or end < f"{year}-12-31"
        )
        opening, closing = selected[0].opening_equity, selected[-1].closing_equity
        parts = [
            math.fsum(getattr(d, name) for d in selected)
            for name in ("entry", "holding", "exit", "fees")
        ]
        residual = closing - opening - math.fsum(parts)
        if not _close(residual, 0.0):
            raise ValueError(f"unreconciled annual equity at {year}")
        annual.append(
            AnnualPnl(
                year,
                selected[0].session,
                selected[-1].session,
                partial,
                opening,
                closing,
                *parts,
                closing - opening,
                residual,
                *(p / opening if opening > 0 else None for p in parts),
            )
        )
    return AccountPnl(evaluation_id, tuple(daily), tuple(annual))


def diagnose_account_replays(
    baseline: ReplayEvidence,
    baseline_id: str,
    start: date,
    end: date,
    *,
    symbol: str,
    alternative: ReplayEvidence | None = None,
    alternative_id: str | None = None,
) -> AccountDiagnosisCalculation:
    """Pure calculation; TDR authenticates evidence and comparison context first."""
    if type(baseline) is not ReplayEvidence or (
        alternative is not None and type(alternative) is not ReplayEvidence
    ):
        raise TypeError("account diagnosis requires ReplayEvidence")
    if type(start) is not date or type(end) is not date or start > end:
        raise ValueError("account diagnosis requires an ordered date window")
    if (
        not isinstance(baseline_id, str)
        or not baseline_id
        or not isinstance(symbol, str)
        or not symbol
    ):
        raise ValueError("account diagnosis requires evaluation and symbol identities")
    if alternative is not None and (not isinstance(alternative_id, str) or not alternative_id):
        raise ValueError("alternative requires an evaluation identity")
    try:
        left = _decompose(baseline_id, baseline, start.isoformat(), end.isoformat())
        if alternative is None:
            return AccountDiagnosisCalculation(
                AccountDiagnosisStatus.COMPUTED, DIAGNOSIS_PROTOCOL, (), (left,)
            )
        right = _decompose(alternative_id, alternative, start.isoformat(), end.isoformat())
        if tuple(d.session for d in left.daily) != tuple(d.session for d in right.daily):
            return AccountDiagnosisCalculation(
                AccountDiagnosisStatus.INCOMPARABLE,
                DIAGNOSIS_PROTOCOL,
                ("diagnostic sessions differ",),
            )
        cycles = []

        def entries(replay):
            result = {}
            exits = {
                f["cycle_id"]: _day(f["fill_time"]) for f in replay.fills if f["side"] == "SELL"
            }
            for f in replay.fills:
                day = _day(f["fill_time"])
                if f["side"] != "BUY":
                    continue
                if day > end.isoformat() or (
                    exits.get(f["cycle_id"], end.isoformat()) < start.isoformat()
                ):
                    continue
                if day in result:
                    raise _Unsupported("ambiguous entry-session matching key")
                exit_session = exits.get(f["cycle_id"])
                result[day] = (
                    f["cycle_id"],
                    exit_session if exit_session and exit_session <= end.isoformat() else None,
                )
            return result

        le, re = entries(baseline), entries(alternative)
        for day in sorted(le.keys() | re.keys()):
            lc, lx = le.get(day, (None, None))
            rc, rx = re.get(day, (None, None))
            cycles.append(CyclePathComparison(symbol, day, lc, rc, lx, rx))
        lr = {_day(r["date"]): r for r in baseline.account_daily}
        rr = {_day(r["date"]): r for r in alternative.account_daily}
        paths = tuple(
            DailyPathComparison(
                d.session,
                float(lr[d.session]["cash"]),
                float(rr[d.session]["cash"]),
                int(lr[d.session]["quantity"]),
                int(rr[d.session]["quantity"]),
                d.closing_equity,
                other.closing_equity,
                other.closing_equity - d.closing_equity,
            )
            for d, other in zip(left.daily, right.daily, strict=True)
        )
        return AccountDiagnosisCalculation(
            AccountDiagnosisStatus.COMPUTED,
            DIAGNOSIS_PROTOCOL,
            (),
            (left, right),
            tuple(cycles),
            paths,
        )
    except _Unsupported as exc:
        return AccountDiagnosisCalculation(
            AccountDiagnosisStatus.UNSUPPORTED, DIAGNOSIS_PROTOCOL, (str(exc),)
        )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return AccountDiagnosisCalculation(
            AccountDiagnosisStatus.INVALID_EVIDENCE, DIAGNOSIS_PROTOCOL, (str(exc),)
        )
