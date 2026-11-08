"""Market-neutral account facts. Market rules validate legal quantities/prices."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from decimal import Decimal
from enum import StrEnum
import math

from .instruments import InstrumentId, TimeInterval, utc

from .session_contracts import OrderSide, OrderType
from .entry_cycle import EntryCyclePhase
from .policy import _positive


def _aware(value, name):
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError(f"{name} requires an aware datetime")


def _amount(value, name):
    if type(value) not in (int, float, Decimal):
        raise TypeError(f"{name} requires a numeric amount")
    finite = value.is_finite() if type(value) is Decimal else (True if type(value) is int else math.isfinite(value))
    if not finite or value < 0:
        raise ValueError(f"{name} requires a finite nonnegative amount")


def _quantity(value, name, *, positive=False):
    if type(value) is not int or value < int(positive):
        raise ValueError(f"{name} requires {'positive' if positive else 'nonnegative'} integer units")


class StrategyComputation(StrEnum):
    BATCH_HISTORY = "BATCH_HISTORY"
    STATEFUL_STEP = "STATEFUL_STEP"


class ExecutionPrecision(StrEnum):
    SESSION = "SESSION"
    BAR_INTERVAL = "BAR_INTERVAL"
    CHECKPOINT = "CHECKPOINT"


@dataclass(frozen=True, slots=True)
class ReplayPoint:
    observed_through: datetime
    decision_at: datetime
    execution_start: datetime
    execution_end: datetime
    session_id: str
    precision: ExecutionPrecision

    def __post_init__(self):
        for name in ("observed_through", "decision_at", "execution_start", "execution_end"):
            _aware(getattr(self, name), name)
        observed, decision, start, end = (getattr(self, name).astimezone(UTC) for name in
            ("observed_through", "decision_at", "execution_start", "execution_end"))
        if not observed <= decision <= start < end:
            raise ValueError("replay point violates causal execution order")
        if type(self.session_id) is not str or not self.session_id.strip():
            raise ValueError("replay point requires a declared session identity")
        if type(self.precision) is not ExecutionPrecision:
            raise TypeError("execution precision requires ExecutionPrecision")


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    instrument: InstrumentId
    currency: str
    as_of: datetime
    revision: int
    cash: float | Decimal
    available_cash: float | Decimal
    receivable: float | Decimal
    quantity: int
    sellable_quantity: int

    def __post_init__(self):
        if type(self.instrument) is not InstrumentId:
            raise TypeError("account requires InstrumentId")
        if type(self.currency) is not str or not self.currency.strip():
            raise ValueError("account requires currency")
        _aware(self.as_of, "account as_of")
        for name in ("revision", "quantity", "sellable_quantity"):
            _quantity(getattr(self, name), name)
        for name in ("cash", "available_cash", "receivable"):
            _amount(getattr(self, name), name)
        if self.available_cash > self.cash or self.sellable_quantity > self.quantity:
            raise ValueError("available assets exceed confirmed account assets")


@dataclass(frozen=True, slots=True)
class ReplayOrder:
    side: OrderSide
    quantity: int
    order_type: OrderType
    limit_price: float | Decimal | None = None

    def __post_init__(self):
        if type(self.side) is not OrderSide or type(self.order_type) is not OrderType:
            raise TypeError("order requires typed side and order type")
        _quantity(self.quantity, "order quantity", positive=True)
        if self.order_type is OrderType.LIMIT:
            if self.limit_price is None:
                raise ValueError("limit order requires price")
            _amount(self.limit_price, "limit price")
            if self.limit_price <= 0:
                raise ValueError("limit price must be positive")
        elif self.limit_price is not None:
            raise ValueError("market order cannot declare a limit price")


@dataclass(frozen=True, slots=True)
class ReplayLeg:
    sequence: int
    order: ReplayOrder
    checkpoint: str
    submit_after: datetime
    submit_before: datetime
    dependency_sequence: int | None = None
    dependency_required_status: str | None = None

    def __post_init__(self):
        _quantity(self.sequence, "leg sequence")
        if type(self.order) is not ReplayOrder:
            raise TypeError("leg requires ReplayOrder")
        if type(self.checkpoint) is not str or not self.checkpoint.strip():
            raise ValueError("leg requires checkpoint")
        _aware(self.submit_after, "leg start")
        _aware(self.submit_before, "leg end")
        if self.submit_after.astimezone(UTC) >= self.submit_before.astimezone(UTC):
            raise ValueError("leg submission interval must be positive")
        if (self.dependency_sequence is None) != (self.dependency_required_status is None):
            raise ValueError("dependency sequence and required status must be supplied together")
        if self.dependency_sequence is not None:
            _quantity(self.dependency_sequence, "leg dependency")
            if (self.dependency_sequence >= self.sequence
                    or type(self.dependency_required_status) is not str
                    or self.dependency_required_status != "FILLED_ALL"):
                raise ValueError("leg dependency requires FILLED_ALL from an earlier confirmed leg")


@dataclass(frozen=True, slots=True)
class CycleBudget:
    cycle_id: str
    target_quantity: int
    allocation_fraction: Decimal
    cash_budget: Decimal
    buy_cost_including_fees: Decimal
    phase: EntryCyclePhase

    def __post_init__(self):
        if type(self.cycle_id) is not str or not self.cycle_id.strip():
            raise ValueError("cycle budget requires identity")
        _quantity(self.target_quantity, "cycle target", positive=True)
        for name in ("allocation_fraction", "cash_budget", "buy_cost_including_fees"):
            if type(getattr(self, name)) is not Decimal:
                raise TypeError("cycle budgets preserve Decimal calculation units")
            _amount(getattr(self, name), name)
        if not 0 < self.allocation_fraction <= 1 or self.cash_budget <= 0:
            raise ValueError("cycle budget requires positive cash and valid allocation fraction")
        if type(self.phase) is not EntryCyclePhase:
            raise TypeError("cycle budget requires EntryCyclePhase")


@dataclass(frozen=True, slots=True)
class AccountExecutionPlan:
    plan_identity: str
    owner: str
    point: ReplayPoint
    expected_revision: int
    target_quantity: int
    orders: tuple[ReplayOrder, ...] = ()
    legs: tuple[ReplayLeg, ...] = ()
    capital_mode: str = "full_available_cash"
    cycle_before: CycleBudget | None = None
    cycle_after: CycleBudget | None = None
    evidence: object = field(default_factory=dict)

    def __post_init__(self):
        from .identity import freeze as _freeze
        from collections.abc import Mapping
        import json
        if not isinstance(self.evidence, Mapping):
            raise TypeError('plan evidence requires mapping')
        # Evidence is immutable JSON facts, never arbitrary model objects.
        json.dumps(dict(self.evidence), allow_nan=False)
        object.__setattr__(self, 'evidence', _freeze(dict(self.evidence)))
        import re
        if type(self.plan_identity) is not str or re.fullmatch(r"[0-9a-f]{64}", self.plan_identity) is None:
            raise ValueError("plan requires content identity")
        if type(self.owner) is not str or not self.owner.strip():
            raise ValueError("plan requires owner identity")
        if type(self.point) is not ReplayPoint:
            raise TypeError("plan requires ReplayPoint")
        _quantity(self.expected_revision, "plan revision")
        _quantity(self.target_quantity, "target quantity")
        if type(self.orders) is not tuple or any(type(x) is not ReplayOrder for x in self.orders):
            raise TypeError("plan requires immutable orders")
        if type(self.legs) is not tuple or any(type(x) is not ReplayLeg for x in self.legs):
            raise TypeError("plan requires immutable execution legs")
        if self.orders and self.legs:
            raise ValueError("plan declares direct orders or dependency legs, not both")
        sequences = [leg.sequence for leg in self.legs]
        if sequences != sorted(set(sequences)):
            raise ValueError("plan leg sequences must be unique and increasing")
        if any(leg.dependency_sequence is not None and leg.dependency_sequence not in sequences for leg in self.legs):
            raise ValueError("plan leg dependency is absent")
        if type(self.capital_mode) is not str or not self.capital_mode.strip():
            raise ValueError("plan requires capital mode")
        for value in (self.cycle_before, self.cycle_after):
            if value is not None and type(value) is not CycleBudget:
                raise TypeError("plan cycle facts require CycleBudget")
        if self.capital_mode != "signal_cash_fraction" and any(x is not None for x in (self.cycle_before, self.cycle_after)):
            raise ValueError("cycle budgets require signal_cash_fraction mode")



@dataclass(frozen=True, slots=True)
class DecisionPoint:
    observed_through: datetime
    decision_at: datetime
    execution_interval: TimeInterval

    def __post_init__(self):
        object.__setattr__(self, "observed_through", utc(self.observed_through))
        object.__setattr__(self, "decision_at", utc(self.decision_at))
        if type(self.execution_interval) is not TimeInterval:
            raise TypeError("decision requires an execution interval")
        if self.observed_through > self.decision_at or self.decision_at > self.execution_interval.start:
            raise ValueError("CAUSAL_TIME_VIOLATION")


@dataclass(frozen=True, slots=True)
class EquityClosedCycle:
    """Confirmed one-entry/full-exit facts, in original entry quantity units."""

    cycle_id: str
    entry_interval: TimeInterval
    exit_interval: TimeInterval
    entry_quantity: int
    entry_cost: float
    exit_observed_through: datetime

    def __post_init__(self):
        if type(self.cycle_id) is not str or not self.cycle_id.strip() or self.cycle_id != self.cycle_id.strip():
            raise ValueError("closed cycle requires a nonblank identity")
        if type(self.entry_interval) is not TimeInterval or type(self.exit_interval) is not TimeInterval:
            raise TypeError("closed cycle requires typed entry and exit intervals")
        if type(self.entry_quantity) is not int or self.entry_quantity <= 0:
            raise ValueError("closed cycle entry quantity must be a positive integer")
        _positive(self.entry_cost, "closed cycle entry cost")
        object.__setattr__(self, "exit_observed_through", utc(self.exit_observed_through))
        if not self.entry_interval.end <= self.exit_observed_through <= self.exit_interval.start:
            raise ValueError("CAUSAL_TIME_VIOLATION: closed cycle observation boundary")


@dataclass(frozen=True, slots=True)
class EquityClosedCycleFeedback:
    """Available closed-cycle feedback; latest=None means no cycle has closed."""

    latest: EquityClosedCycle | None = None

    def __post_init__(self):
        if self.latest is not None and type(self.latest) is not EquityClosedCycle:
            raise TypeError("closed cycle feedback requires a typed latest cycle")


@dataclass(frozen=True, slots=True)
class EquityPortfolio:
    cash: float
    quantity: int
    receivable: float
    revision: int
    cycle_entry: datetime | None = None
    cycle_cost: float = 0.
    feedback_source: str = "BAR_INTERVAL"
    closed_cycle_feedback: EquityClosedCycleFeedback | None = None

    def __post_init__(self):
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < -1e-8 for v in (self.cash, self.receivable)):
            raise ValueError("invalid cash or receivable")
        if any(type(v) is not int or v < 0 for v in (self.quantity, self.revision)):
            raise ValueError("invalid quantity or portfolio revision")
        if type(self.cycle_cost) not in (float, int) or not math.isfinite(self.cycle_cost) or self.cycle_cost < 0:
            raise ValueError("invalid cycle cost")
        if self.cycle_entry is not None:
            object.__setattr__(self, "cycle_entry", utc(self.cycle_entry))
        if self.closed_cycle_feedback is not None and type(self.closed_cycle_feedback) is not EquityClosedCycleFeedback:
            raise TypeError("portfolio requires typed closed cycle feedback or unavailable None")


@dataclass(frozen=True, slots=True)
class EquityPlan:
    plan_id: str
    point: DecisionPoint
    target: float
    quantity: int
    side: str
    limit_price: float | None
    portfolio_revision: int
    reference_price: float
    specification_hash: str
    explanation: dict | None = None
    signal_status: str = "EVALUATED"

    def __post_init__(self):
        if self.signal_status not in {"EVALUATED", "SUPPRESSED_UNOBSERVED_BAR"}:
            raise ValueError("invalid equity signal status")
        if self.signal_status == "SUPPRESSED_UNOBSERVED_BAR" and (self.side != "WAIT" or self.quantity != 0):
            raise ValueError("suppressed signal cannot submit an order")
        if type(self.point) is not DecisionPoint or self.target not in (0., 1.):
            raise ValueError("invalid decision point or target")
        if type(self.quantity) is not int or self.quantity < 0 or type(self.portfolio_revision) is not int or self.portfolio_revision < 0:
            raise ValueError("invalid plan quantity or revision")
        if self.side not in {"BUY", "SELL", "HOLD", "WAIT"} or ((self.side in {"BUY", "SELL"}) != (self.quantity > 0)):
            raise ValueError("plan side differs from quantity")
        if self.side == "BUY":
            _positive(self.limit_price, "buy limit")
        elif self.side == "SELL" and self.limit_price is not None:
            raise ValueError("sell must be a market order")
        _positive(self.reference_price, "reference price")


class RecognizedEventKind(StrEnum):
    POSITION_ADJUSTMENT = 'POSITION_ADJUSTMENT'
    SALE_SETTLEMENT = 'SALE_SETTLEMENT'


@dataclass(frozen=True, slots=True)
class RecognizedAccountEvent:
    event_id: str
    kind: RecognizedEventKind
    effective_at: datetime
    quantity_before: int
    quantity_after: int
    cash_delta: float
    receivable_delta: float
    reason: str = 'UNKNOWN'

    def __post_init__(self):
        if type(self.event_id) is not str or not self.event_id or type(self.kind) is not RecognizedEventKind:
            raise TypeError('recognized account event requires identity and typed kind')
        if type(self.effective_at) is not datetime or self.effective_at.tzinfo is None:
            raise TypeError('recognized event requires an aware effective time')
        for name in ('quantity_before','quantity_after'):
            if type(getattr(self,name)) is not int or getattr(self,name)<0:
                raise ValueError('recognized quantities require nonnegative integer units')
        for name in ('cash_delta','receivable_delta'):
            value=getattr(self,name)
            if type(value) not in (int,float) or not math.isfinite(value):
                raise ValueError('recognized event deltas must be finite')
        if self.reason not in {'UNKNOWN', 'TRADE_SETTLEMENT'}:
            raise ValueError('recognized event requires an explicit supported reason')
        if self.kind is RecognizedEventKind.POSITION_ADJUSTMENT and self.reason != 'UNKNOWN':
            raise ValueError('position adjustment cannot infer its cause')


class SellRemainderPolicy(StrEnum):
    STRICT_STEP = 'STRICT_STEP'
    FULL_LIQUIDATION = 'FULL_LIQUIDATION'


@dataclass(frozen=True, slots=True)
class PositionCycle:
    cycle_id: str
    entry_interval: TimeInterval
    last_fill_interval: TimeInterval
    quantity: int
    buy_cost: float
    sell_income: float
    fees: float
    buy_fills: int
    sell_fills: int

    def __post_init__(self):
        if type(self.cycle_id) is not str or not self.cycle_id:
            raise ValueError('position cycle requires identity')
        if any(type(getattr(self, name)) is not TimeInterval for name in ('entry_interval', 'last_fill_interval')):
            raise TypeError('position cycle requires confirmed intervals')
        if self.entry_interval.start > self.last_fill_interval.start:
            raise ValueError('position fills are out of order')
        for name in ('quantity', 'buy_fills', 'sell_fills'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError('position counts must be nonnegative integers')
        for name in ('buy_cost', 'sell_income', 'fees'):
            value = getattr(self, name)
            if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
                raise ValueError('position amounts must be finite nonnegative numbers')


@dataclass(frozen=True, slots=True)
class PositionFeedback:
    active: PositionCycle | None = None
    latest_closed: PositionCycle | None = None

    def __post_init__(self):
        if any(value is not None and type(value) is not PositionCycle for value in (self.active, self.latest_closed)):
            raise TypeError('position feedback requires typed cycles')
        if self.active is not None and self.active.quantity <= 0:
            raise ValueError('active cycle requires a holding')
        if self.latest_closed is not None and self.latest_closed.quantity != 0:
            raise ValueError('closed cycle must be flat')
