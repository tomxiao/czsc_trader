"""Private shared RAW equity account ledger and economic-event postings."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal, ROUND_FLOOR
import math

import pandas as pd
from dataflows import MarketId
from strategy_runtime.equity import (EquityClosedCycleFeedback, EquityPortfolio, ResearchExecutionSpec)

from .accounting import (AccountBalances, post_split,
                         accrue_receivable, _settle_confirmed_receivable)


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


@dataclass(frozen=True)
class _CorporateAction:
    Date: datetime
    EventId: str
    Kind: str
    Ratio: float | None
    CashPerShare: float | None
    PayAt: datetime | None


@dataclass
class _TransitionCheckpoint:
    state: dict[str, object]
    pending: list
    lengths: dict[str, int]
    completed_added: list[str]
    applied_added: list[str]


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
    corporate_action_entries: pd.DataFrame
    account_points: pd.DataFrame
    account_daily: pd.DataFrame
    trades: pd.DataFrame
    specification: dict
    initial_cash: float


class _EquityAccount:
    """One account; all monetary changes are recorded as fills or dated events."""

    def __init__(self, *, specification: ResearchExecutionSpec, initial_cash: float,
                 fee_rate: float, actions: pd.DataFrame):
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
        self.actions = actions.copy(deep=True)
        self.actions["_priority"] = self.actions.Kind.map({"SPLIT": 0, "CASH_DIVIDEND": 1, "NONE": 2})
        self.actions = self.actions.sort_values(["Date", "_priority", "EventId"])
        # Retain the independent public frame, but never construct pandas rows on
        # the per-decision path. Optional fields remain unused for NONE events.
        self._action_events = tuple(_CorporateAction(
            event.Date, event.EventId, event.Kind, getattr(event, "Ratio", None),
            getattr(event, "CashPerShare", None), getattr(event, "PayAt", None),
        ) for event in self.actions.itertuples(index=False))
        self._transactions: list[_TransitionCheckpoint] = []
        self.pending = []
        self.applied = set()
        self.completed = {}
        self._neutral_owner = None
        self.last_end = None
        self.last_mark_price = None
        self.last_mark_time = None
        self.rows = {name: [] for name in ("decisions", "orders", "fills", "actions", "points", "trades")}
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
            {name: len(rows) for name, rows in self.rows.items()}, [], [],
        )
        self._transactions.append(checkpoint)
        try:
            yield self
        except BaseException:
            self.__dict__.update(checkpoint.state)
            self.pending = checkpoint.pending
            for key in checkpoint.completed_added:
                self.completed.pop(key, None)
            for key in checkpoint.applied_added:
                self.applied.discard(key)
            for name, length in checkpoint.lengths.items():
                del self.rows[name][length:]
            raise
        finally:
            self._transactions.pop()

    def _mark_applied(self, identity):
        if identity not in self.applied:
            for checkpoint in self._transactions:
                checkpoint.applied_added.append(identity)
            self.applied.add(identity)

    def snapshot(self):
        return EquityPortfolio(self.cash, self.quantity, self.receivable, self.revision,
                               self.cycle_entry, self.cycle_cost,
                               closed_cycle_feedback=self._closed_cycle_feedback)

    def snapshot_at(self, observed_through, decision_at):
        """Apply already-effective events before a formal causal decision."""
        scale = 1.
        for event in self._action_events:
            if event.Kind == 'SPLIT' and observed_through <= _timestamp(event.Date) <= decision_at:
                scale /= float(event.Ratio)
        with self.transaction():
            self._events(decision_at, after=decision_at, plan_quantity=0, limit_price=None)
            return EquityPortfolio(self.cash, self.quantity, self.receivable, self.revision,
                                   self.cycle_entry, self.cycle_cost, reference_price_scale=scale,
                                   closed_cycle_feedback=self._closed_cycle_feedback)

    def _events(self, through, *, after, plan_quantity, limit_price, include_actions=True):
        return self._apply_events(self._action_events, through, after=after,
            plan_quantity=plan_quantity, limit_price=limit_price, include_actions=include_actions)

    def _apply_events(self, events, through, *, after, plan_quantity, limit_price, include_actions=True):
        """Post an ordered event range through the shared economic journal."""
        for event in events:
            if event.Kind == "NONE" or event.EventId in self.applied:
                continue
            stamp = _timestamp(event.Date)
            if stamp > through:
                continue
            if not include_actions and stamp == through:
                continue
            # Events preceding this independent account cannot create entitlements.
            if self.last_end is None and stamp < after:
                self._mark_applied(event.EventId)
                continue
            self._pay(stamp, inclusive=False)
            before = self.quantity
            if event.Kind == "SPLIT":
                # Raw entry facts cannot describe a cycle spanning quantity-unit
                # changes, nor safely carry a pre-split closed cycle forward.
                if self.cycle is not None or (self._closed_cycle_feedback is not None
                                              and self._closed_cycle_feedback.latest is not None):
                    self._cycle_feedback_supported = False
                    self._closed_cycle_feedback = None
                ratio = float(event.Ratio)
                if self.last_mark_price is not None:
                    self.last_mark_price /= ratio
                changed = before * ratio
                planned = plan_quantity * ratio
                if not changed.is_integer() or not planned.is_integer():
                    raise ValueError("CORPORATE_ACTION_UNSUPPORTED: fractional split entitlement")
                self.quantity = post_split(AccountBalances(self.cash, self.quantity, self.receivable), ratio).quantity
                plan_quantity = int(planned)
                if limit_price is not None:
                    tick = Decimal(str(self.spec.price_tick))
                    limit_price = float((Decimal(str(limit_price)) / Decimal(str(ratio)) / tick)
                                        .to_integral_value(rounding=ROUND_FLOOR) * tick)
                    if limit_price <= 0:
                        raise ValueError("CORPORATE_ACTION_UNSUPPORTED: split-adjusted limit below price tick")
                amount = 0.
            elif event.Kind == "CASH_DIVIDEND":
                amount = before * float(event.CashPerShare)
                pay = _timestamp(event.PayAt)
                if pd.isna(pay) or pay.tzinfo is None or pay < stamp:
                    raise ValueError("CORPORATE_ACTION_UNSUPPORTED: payment date missing")
                self.receivable = accrue_receivable(AccountBalances(self.cash, self.quantity, self.receivable), amount).receivable
                self.cycle_income += amount if self.cycle is not None else 0.
                self.pending.append((pay, amount, event.EventId, "DIVIDEND_PAYMENT"))
            else:
                raise ValueError("CORPORATE_ACTION_UNSUPPORTED")
            self._mark_applied(event.EventId)
            self.rows["actions"].append({"event_id": event.EventId, "time": stamp,
                                         "account_revision": self.revision,
                                         "kind": event.Kind, "quantity_before": before,
                                         "quantity_after": self.quantity, "amount": amount,
                                         "cash_delta": 0., "receivable_delta": amount})
        self._pay(through, inclusive=True)
        return plan_quantity, limit_price

    def _pay(self, through, *, inclusive):
        remaining = []
        for stamp, amount, identity, kind in sorted(self.pending, key=lambda item: item[0]):
            if stamp < through or (inclusive and stamp == through):
                self.cash, self.receivable = _settle_confirmed_receivable(self.cash, self.receivable, amount)
                self.rows["actions"].append({"event_id": identity, "time": stamp, "kind": kind,
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
        return EquityExecutionResult(*(pd.DataFrame(self.rows[k]) for k in ("decisions", "orders", "fills", "actions")),
                                     points, daily, pd.DataFrame(self.rows["trades"]), asdict(self.spec), self.initial_cash)
