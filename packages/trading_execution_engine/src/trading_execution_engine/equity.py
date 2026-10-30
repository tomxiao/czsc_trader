"""Sequential equity bar execution, sharing canonical order fill resolution."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from decimal import Decimal, ROUND_FLOOR
import math

import pandas as pd
import numpy as np
from dataflows import MarketId
from strategy_runtime.equity import (CashAvailabilityPolicy, EquityClosedCycle, EquityClosedCycleFeedback,
                                    EquityPlan, EquityPortfolio, ResearchExecutionSpec, equity_hash)

from .fills import OrderSpec, resolve_fill


EquityRow = pd.Series | Mapping[str, object]
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
    "_closed_cycle_feedback",
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


class EquityHistoricalExecutor:
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
    def transaction(self) -> Iterator["EquityHistoricalExecutor"]:
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
        for event in self._action_events:
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
                self.quantity, plan_quantity = int(changed), int(planned)
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
                self.receivable += amount
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
                self.cash += amount
                self.receivable -= amount
                self.rows["actions"].append({"event_id": identity, "time": stamp, "kind": kind,
                                             "account_revision": self.revision,
                                             "quantity_before": self.quantity, "quantity_after": self.quantity,
                                             "amount": amount, "cash_delta": amount, "receivable_delta": -amount})
            else:
                remaining.append((stamp, amount, identity, kind))
        self.pending = remaining

    def execute(self, plan: EquityPlan, bar: EquityRow, *, constraint: EquityRow):
        """Execute a Series or immutable mapping row through the same fill kernel."""
        if not isinstance(bar, (pd.Series, Mapping)) or not isinstance(constraint, (pd.Series, Mapping)):
            raise TypeError("execution bar and constraint must be Series or Mapping rows")
        with self.transaction():
            return self._execute(plan, bar, constraint=constraint)

    def _execute(self, plan: EquityPlan, bar: EquityRow, *, constraint: EquityRow):
        if type(plan) is not EquityPlan or plan.specification_hash != self.spec.fingerprint:
            raise ValueError("MARKET_CONTRACT_MISMATCH: execution plan")
        interval = plan.point.execution_interval
        status = bar.get("BarStatus", "OBSERVED")
        if status not in {"OBSERVED", "MISSING", "ZERO_VOLUME"}:
            raise ValueError("invalid execution bar status")
        blocked = bar.get("ExecutionBlocked", False)
        if type(blocked) not in (bool, np.bool_):
            raise ValueError("invalid execution block flag")
        stale = status != "OBSERVED"
        if status == "MISSING":
            if not all(pd.isna(bar[name]) for name in ("Open", "High", "Low", "Close", "Volume", "Amount")):
                raise ValueError("missing bar must not contain fabricated prices or volume")
        else:
            prices = [float(bar[name]) for name in ("Open", "High", "Low", "Close")]
            opening, high, low, close = prices
            if (any(not math.isfinite(value) or value <= 0 for value in prices)
                or not low <= min(opening, close) or not high >= max(opening, close)):
                raise ValueError("invalid execution OHLCV")
            volume = float(bar['Volume'])
            if not math.isfinite(volume) or volume < 0:
                raise ValueError("invalid execution OHLCV")
            if "BarStatus" in bar and ((status == "ZERO_VOLUME") != (volume == 0)):
                raise ValueError("bar status differs from observed volume")
        bar_hash = equity_hash({"bar": {k: _bar_identity_value(v) for k, v in bar.items()},
                                "constraints": {k: (v.isoformat() if isinstance(v, (datetime, pd.Timestamp)) else v)
                                                for k, v in constraint.items()}})
        if plan.plan_id in self.completed:
            if self.completed[plan.plan_id] != bar_hash:
                raise ValueError("same plan was resubmitted with different execution facts")
            return self.snapshot()
        if plan.portfolio_revision != self.revision or (self.last_end is not None and interval.start < self.last_end):
            raise ValueError("stale portfolio revision or unordered execution")
        if _timestamp(bar["BarStart"]) != interval.start or _timestamp(bar["Date"]) != interval.end:
            raise ValueError("execution bar does not match plan interval")
        if (int(constraint["QuantityStep"]), float(constraint["PriceTick"])) != (self.spec.quantity_step, self.spec.price_tick):
            raise ValueError("dated quantity/price rules differ from declared execution specification")
        if _timestamp(constraint["Date"]) != interval.start or _timestamp(constraint["AvailableDate"]) > interval.start:
            raise ValueError("CAUSAL_TIME_VIOLATION: constraints must belong to this execution interval")
        if self.spec.market_id is MarketId.CN:
            # Existing CN engine owns exchange-bound execution. Do not execute CN
            # bars without its price limits and sellability semantics.
            raise ValueError("UNSUPPORTED_EXECUTION_COMBINATION: CN bar execution is not admitted")
        for event in self._action_events:
            if event.Kind != "NONE" and interval.start < _timestamp(event.Date) < interval.end:
                raise ValueError("CORPORATE_ACTION_UNSUPPORTED: event inside execution bar")
        quantity, limit = self._events(interval.start, after=plan.point.decision_at,
                                       plan_quantity=plan.quantity, limit_price=plan.limit_price)
        decision = {"decision_id": plan.plan_id, "observed_through": plan.point.observed_through,
                    "decision_at": plan.point.decision_at, "execution_start": interval.start,
                    "execution_end": interval.end, "target": plan.target, "reference_price": plan.reference_price,
                    "quantity": plan.quantity, "side": plan.side, "limit_price": plan.limit_price,
                    "portfolio_revision": plan.portfolio_revision, "signal_status": plan.signal_status}
        self.rows["decisions"].append(decision)
        if plan.explanation is not None:
            decision["explanation"] = plan.explanation
        if quantity:
            reason, fill_price, precision = "NOT_TRADABLE", None, None
            if status == "MISSING":
                reason = "MISSING_BAR"
            elif status == "ZERO_VOLUME":
                reason = "ZERO_VOLUME"
            elif blocked:
                reason = "KNOWN_INTERRUPTION"
            elif bool(constraint["Tradable"]) and (volume <= 0 or quantity > volume):
                reason = "INSUFFICIENT_BAR_VOLUME"
            elif bool(constraint["Tradable"]):
                fill = resolve_fill(OrderSpec(plan.side, "LIMIT" if plan.side == "BUY" else "MARKET",
                                               quantity, limit),
                                    session_open=opening, session_time=interval.start,
                                    intraday_touches=((interval.end, low if plan.side == "BUY" else high),),
                                    slippage_bp=self.spec.slippage_bp, inclusive_touch=self.spec.inclusive_touch)
                reason = fill.reason or "FILLED"
                if fill.filled:
                    price = float(fill.price)
                    if plan.side == "BUY" and price > limit:
                        reason = "SLIPPAGE_EXCEEDS_LIMIT"
                    elif plan.side == "BUY" and quantity * price * (1 + self.fee_rate) > self.cash + 1e-9:
                        reason = "INSUFFICIENT_CASH"
                    elif plan.side == "SELL" and quantity > self.quantity:
                        raise ValueError("sell quantity exceeds holdings")
                    else:
                        fill_price = price
                        precision = "BAR_INTERVAL" if fill.trigger == "INTRADAY_LIMIT" else "MODEL_BAR_OPEN"
            order = {"order_id": plan.plan_id, "decision_id": plan.plan_id,
                     "side": plan.side, "quantity": quantity, "limit_price": limit,
                     "valid_start": interval.start, "valid_end": interval.end,
                     "status": "FILLED" if fill_price is not None else "EXPIRED", "reason": reason}
            self.rows["orders"].append(order)
            if fill_price is not None:
                gross = quantity * fill_price
                fees = gross * self.fee_rate
                if plan.side == "BUY":
                    self.cash -= gross + fees
                    self.quantity += quantity
                    if self.cycle is None:
                        self.cycle = plan.plan_id
                        self.cycle_entry = interval.start
                        self.cycle_cost = self.cycle_income = 0.
                        self._cycle_entry_interval = interval
                        self._cycle_entry_quantity = quantity
                        self._cycle_feedback_supported = True
                    else:
                        self._cycle_feedback_supported = False
                        self._closed_cycle_feedback = None
                    self.cycle_cost += gross + fees
                else:
                    self.quantity -= quantity
                    if self.quantity:
                        self._cycle_feedback_supported = False
                        self._closed_cycle_feedback = None
                    proceeds = gross - fees
                    self.cycle_income += proceeds
                    if self.spec.account.cash_availability is CashAvailabilityPolicy.IMMEDIATE_RESEARCH:
                        self.cash += proceeds
                    else:
                        settle = _timestamp(constraint["SettlementAt"])
                        if pd.isna(settle) or settle.tzinfo is None or settle < interval.end:
                            raise ValueError("missing or invalid settlement time")
                        self.receivable += proceeds
                        self.pending.append((settle, proceeds, plan.plan_id, "SALE_SETTLEMENT"))
                self.rows["fills"].append({"fill_id": plan.plan_id, "order_id": plan.plan_id,
                                           "account_revision": self.revision,
                                           "cycle_id": self.cycle, "side": plan.side,
                                           "quantity": quantity, "price": fill_price, "fees": fees,
                                           "interval_start": interval.start, "interval_end": interval.end,
                                           "time_precision": precision})
                if self.quantity == 0 and self.cycle is not None:
                    # Preserve the old execution path even for manually supplied
                    # plans whose observation boundary cannot express this contract.
                    if (self._cycle_feedback_supported
                        and self._cycle_entry_interval.end <= plan.point.observed_through):
                        self._closed_cycle_feedback = EquityClosedCycleFeedback(EquityClosedCycle(
                            self.cycle, self._cycle_entry_interval, interval,
                            self._cycle_entry_quantity, self.cycle_cost, plan.point.observed_through))
                    else:
                        self._closed_cycle_feedback = None
                    self.rows["trades"].append({"cycle_id": self.cycle, "entry_at": self.cycle_entry,
                                               "exit_at": interval.end, "cost": self.cycle_cost,
                                               "income": self.cycle_income, "net_pnl": self.cycle_income - self.cycle_cost,
                                               "net_return": self.cycle_income / self.cycle_cost - 1,
                                               "status": "CLOSED"})
                    self.cycle = None
        self._events(interval.end, after=interval.start, plan_quantity=0, limit_price=None, include_actions=False)
        if self.cash < -1e-8 or self.quantity < 0:
            raise ValueError("unlevered long-only account invariant violated")
        self.revision += 1
        self.last_end = interval.end
        if not stale:
            self.last_mark_price, self.last_mark_time = close, interval.end
        elif self.last_mark_price is None:
            self.last_mark_price, self.last_mark_time = plan.reference_price, plan.point.observed_through
        self.rows["points"].append({"time": interval.end,
                                    "account_revision": self.revision - 1,
                                    "session": interval.end.astimezone(_SESSION_ZONES[self.spec.market_id]).date().isoformat(),
                                    "cash": self.cash, "quantity": self.quantity, "receivable": self.receivable,
                                    "close": self.last_mark_price,
                                    "equity": self.cash + self.receivable + self.quantity * self.last_mark_price,
                                    "bar_status": status, "valuation_stale": stale,
                                    "valuation_price_at": self.last_mark_time, "execution_blocked": bool(blocked),
                                    "cycle_id": self.cycle, "decision_id": plan.plan_id})
        for checkpoint in self._transactions:
            checkpoint.completed_added.append(plan.plan_id)
        self.completed[plan.plan_id] = bar_hash
        return self.snapshot()

    def finish(self):
        points = pd.DataFrame(self.rows["points"])
        if points.empty:
            raise ValueError("execution produced no account points")
        daily = points.groupby("session", sort=True).tail(1).reset_index(drop=True)
        return EquityExecutionResult(*(pd.DataFrame(self.rows[k]) for k in ("decisions", "orders", "fills", "actions")),
                                     points, daily, pd.DataFrame(self.rows["trades"]), asdict(self.spec), self.initial_cash)
