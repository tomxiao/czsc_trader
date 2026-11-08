"""Private HFQ simulated-unit account ledger and trade settlements."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from collections.abc import Iterator
from contextlib import contextmanager
import math

import pandas as pd
from ..instruments import MarketId
from ..contracts import EquityClosedCycleFeedback, EquityPortfolio
from ..policy import ResearchExecutionSpec

from .accounting import _settle_confirmed_receivable


_SESSION_ZONES = {
    MarketId.US: pd.Timestamp('2000-01-01', tz='America/New_York').tzinfo,
    MarketId.CN: pd.Timestamp('2000-01-01', tz='Asia/Shanghai').tzinfo,
}


def _timestamp(value):
    # Local datetime equality at a DST fold differs from Timestamp equality.
    # Only UTC datetimes can skip the original normalization unconditionally.
    if type(value) is pd.Timestamp or (type(value) is datetime and value.tzinfo is timezone.utc):
        return value
    return pd.Timestamp(value)


def _bar_identity_value(value):
    """The existing JSON payload, avoiding pandas dispatch for ordinary scalars."""
    kind = type(value)
    if value is None or (kind is float and math.isnan(value)):
        return None
    if kind in (float, int, bool, str):
        return value
    if kind is datetime:
        return value.isoformat()
    return (None if pd.isna(value) else value.isoformat()
            if isinstance(value, (datetime, pd.Timestamp)) else value)


@dataclass
class _TransitionCheckpoint:
    state: dict[str, object]
    pending: list
    lengths: dict[str, int]
    completed_added: list[str]


_ACCOUNT_STATE = (
    "cash", "quantity", "receivable", "revision", "last_end", "last_mark_price",
    "last_mark_time", "cycle", "cycle_cost", "cycle_income", "cycle_entry",
    "_cycle_entry_interval", "_cycle_entry_quantity", "_cycle_feedback_supported",
    "_closed_cycle_feedback", "_neutral_owner",
)


@dataclass(frozen=True)
class EquityExecutionResult:
    decisions: pd.DataFrame
    orders: pd.DataFrame
    fills: pd.DataFrame
    account_entries: pd.DataFrame
    account_points: pd.DataFrame
    account_daily: pd.DataFrame
    trades: pd.DataFrame
    specification: dict
    initial_cash: float
    price_basis: str = "HFQ"
    quantity_basis: str = "SIMULATED_INTEGER_UNITS"


class _EquityAccount:
    """One account; all monetary changes are recorded as fills or dated events."""

    def __init__(self, *, specification: ResearchExecutionSpec, initial_cash: float,
                 fee_rate: float):
        if type(specification) is not ResearchExecutionSpec:
            raise TypeError("typed execution specification required")
        if type(initial_cash) not in (int, float) or not math.isfinite(initial_cash) or initial_cash <= 0:
            raise ValueError("initial cash must be positive and finite")
        if type(fee_rate) not in (int, float) or not math.isfinite(fee_rate) or not 0 <= fee_rate < 1:
            raise ValueError("fee rate must be finite in [0, 1)")
        self.spec = specification
        self.initial_cash = float(initial_cash)
        self.cash, self.quantity, self.receivable = float(initial_cash), 0, 0.
        self.fee_rate, self.revision = float(fee_rate), 0
        self._transactions: list[_TransitionCheckpoint] = []
        self.pending = []
        self.completed = {}
        self._neutral_owner = None
        self.last_end = None
        self.last_mark_price = None
        self.last_mark_time = None
        self.rows = {name: [] for name in ("decisions", "orders", "fills", "entries", "points", "trades")}
        self.cycle = None
        self.cycle_cost = self.cycle_income = 0.
        self.cycle_entry = None
        self._cycle_entry_interval = None
        self._cycle_entry_quantity = 0
        self._cycle_feedback_supported = True
        self._closed_cycle_feedback = EquityClosedCycleFeedback()

    @contextmanager
    def transaction(self) -> Iterator["_EquityAccount"]:
        """Atomically apply one decision, execution and caller-side validation.

        Nesting provides savepoints. Failure restores this account's state and
        removes only journal entries and idempotency keys added in this scope.
        The caller owns strategy state and commits it only after success. Existing
        journal rows must not be mutated by callers inside the scope.
        """
        checkpoint = _TransitionCheckpoint(
            {key: getattr(self, key) for key in _ACCOUNT_STATE}, list(self.pending),
            {name: len(rows) for name, rows in self.rows.items()}, [],
        )
        self._transactions.append(checkpoint)
        try:
            yield self
        except BaseException:
            self.__dict__.update(checkpoint.state)
            self.pending = checkpoint.pending
            for key in checkpoint.completed_added:
                self.completed.pop(key, None)
            for name, length in checkpoint.lengths.items():
                del self.rows[name][length:]
            raise
        finally:
            self._transactions.pop()

    def snapshot(self):
        return EquityPortfolio(self.cash, self.quantity, self.receivable, self.revision,
                               self.cycle_entry, self.cycle_cost,
                               closed_cycle_feedback=self._closed_cycle_feedback)

    def snapshot_at(self, observed_through, decision_at):
        """Settle confirmed trade proceeds visible at the decision clock."""
        with self.transaction():
            self._pay(decision_at, inclusive=True)
            return self.snapshot()

    def _pay(self, through, *, inclusive):
        remaining = []
        for stamp, amount, identity, kind in sorted(self.pending, key=lambda item: item[0]):
            if stamp < through or (inclusive and stamp == through):
                self.cash, self.receivable = _settle_confirmed_receivable(self.cash, self.receivable, amount)
                self.rows["entries"].append({"event_id": identity, "time": stamp, "kind": kind,
                                             "account_revision": self.revision,
                                             "quantity_before": self.quantity, "quantity_after": self.quantity,
                                             "amount": amount, "cash_delta": amount, "receivable_delta": -amount})
            else:
                remaining.append((stamp, amount, identity, kind))
        self.pending = remaining

    def finish(self):
        points = pd.DataFrame(self.rows["points"])
        if points.empty:
            raise ValueError("execution produced no account points")
        daily = points.groupby("session", sort=True).tail(1).reset_index(drop=True)
        return EquityExecutionResult(*(pd.DataFrame(self.rows[k]) for k in ("decisions", "orders", "fills", "entries")),
                                     points, daily, pd.DataFrame(self.rows["trades"]), asdict(self.spec), self.initial_cash)
