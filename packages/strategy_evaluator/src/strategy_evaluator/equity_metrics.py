"""Summarize TXE observations without re-executing orders or accounting events."""

from dataclasses import dataclass
from datetime import datetime
import math
from statistics import median
from zoneinfo import ZoneInfo

from .models import ValidationError


@dataclass(frozen=True, slots=True)
class EquityAccountMetrics:
    total_return: float
    annualized_return: float
    daily_max_drawdown: float
    bar_max_drawdown: float
    sessions: int
    observations: int
    closed_cycles: int
    fees: float
    rolling_60_closed_cycle_counts: tuple[int, ...]
    rolling_60_closed_cycle_median: float | None


def _finite(value, name, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValidationError(f"equity {name} requires finite {'positive' if positive else 'nonnegative'} values")
    return float(value)


def _stamp(value):
    stamp = datetime.fromisoformat(value)
    if stamp.utcoffset() is None:
        raise ValidationError("equity observations require aware timestamps")
    return stamp


def _drawdown(values, initial):
    peak, maximum = initial, 0.0
    for value in values:
        peak = max(peak, value)
        maximum = max(maximum, 1 - value / peak)
    return float(maximum)


def summarize_equity_ledger(ledger):
    """Calculate metrics from recorded observations, fills and closed cycles.

    Shape, range and chronology checks protect the input contract. This does not
    infer fills, replay cash/holdings, or attest to the source's correctness.
    """
    initial = _finite(ledger["initial_cash"], "initial cash", positive=True)
    market = ledger["specification"]["market"]["rule_version"]
    if market not in {"US_EQUITY_V1", "CN_EQUITY_V1"}:
        raise ValidationError("unsupported equity market")
    zone = ZoneInfo("America/New_York" if market == "US_EQUITY_V1" else "Asia/Shanghai")
    points = ledger["account_points"]
    if not points:
        raise ValidationError("equity account requires observations")
    daily, values, previous = {}, [], None
    for point in points:
        stamp = _stamp(point["time"])
        local_session = stamp.astimezone(zone).date().isoformat()
        if previous is not None and stamp <= previous:
            raise ValidationError("equity observation times must be ordered and unique")
        if point["session"] != local_session:
            raise ValidationError("equity account session differs from market timezone")
        previous = stamp
        for field in ("cash", "receivable", "close"):
            _finite(point[field], field, positive=field == "close")
        if type(point["quantity"]) is not int or point["quantity"] < 0:
            raise ValidationError("equity quantity requires nonnegative integer units")
        value = _finite(point["equity"], "net value")
        values.append(value)
        daily[local_session] = value
    fees = sum(_finite(row["fees"], "fill fees") for row in ledger["fills"])
    counts = dict.fromkeys(daily, 0)
    identities = set()
    for row in ledger["trades"]:
        key = row["cycle_id"]
        entry, exit_at = _stamp(row["entry_at"]), _stamp(row["exit_at"])
        exit_session = exit_at.astimezone(zone).date().isoformat()
        if key in identities or not key or row["status"] != "CLOSED" or entry > exit_at or exit_session not in counts:
            raise ValidationError("equity closed-cycle identity or observation coverage differs")
        identities.add(key)
        counts[exit_session] += 1
    per_session = tuple(counts.values())
    rolling = tuple(sum(per_session[i - 59:i + 1]) for i in range(59, len(per_session)))
    try:
        annual = (values[-1] / initial) ** (252 / len(daily)) - 1
    except OverflowError as exc:
        raise ValidationError("annual return overflow") from exc
    if not math.isfinite(annual) or not math.isfinite(fees):
        raise ValidationError("nonfinite equity metrics")
    return EquityAccountMetrics(float(values[-1] / initial - 1), float(annual),
        _drawdown(daily.values(), initial), _drawdown(values, initial), len(daily), len(values),
        len(identities), float(fees), rolling, float(median(rolling)) if rolling else None)
