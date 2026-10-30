"""Independent equity account audit over serialized facts (no runtime imports)."""
from dataclasses import dataclass
from datetime import datetime
import math


@dataclass(frozen=True, slots=True)
class EquityAuditResult:
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


def _time(value):
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(stamp, datetime) or stamp.tzinfo is None:
        raise ValueError("audit requires aware timestamps")
    return stamp


def _same(actual, expected, label):
    if not math.isfinite(float(actual)) or not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-7):
        raise ValueError(f"equity audit mismatch: {label}")


def _drawdown(values, initial):
    peak, result = initial, 0.
    for value in values:
        peak = max(peak, value)
        result = max(result, 1 - value / peak)
    return result


def audit_equity_account(*, initial_cash, specification, bars, decisions, orders,
                         fills, actions, account_points, trades, action_facts, constraints, fee_rate,
                         decision_contract="FORMAL_V4", account_contract=None, execution_bars=None):
    """Independently audit the current explicit V4 RAW account facts only."""
    if type(account_contract) is not int or account_contract != 4:
        raise ValueError('account audit requires explicit V4 contract marker')
    if decision_contract != 'FORMAL_V4':
        raise ValueError('account audit requires FORMAL_V4 decision contract')
    from .equity_v4 import audit_account_v4
    return audit_account_v4(initial_cash=initial_cash, specification=specification, bars=bars,
        decisions=decisions, orders=orders, fills=fills, actions=actions,
        account_points=account_points, trades=trades, action_facts=action_facts,
        constraints=constraints, fee_rate=fee_rate, execution_bars=execution_bars)
