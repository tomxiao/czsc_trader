"""Market-neutral account facts. Market rules validate legal quantities/prices."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from decimal import Decimal
from enum import StrEnum
import math
from typing import Protocol, runtime_checkable

from dataflows import InstrumentId

from .contracts import OrderSide, OrderType, WindowExecutor, ExecutionPlan, ExecutionOutcome
from .entry_cycle import EntryCyclePhase


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
                    or not self.dependency_required_status.strip()):
                raise ValueError("leg dependency must name an earlier confirmed leg")


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
        from .equity_definition import _freeze
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


@runtime_checkable
class AccountPlanExecutor(WindowExecutor, Protocol):
    """The session model accepts neutral facts plus its explicit native model."""
    def execute_plan(self, plan: AccountExecutionPlan, model_plan: ExecutionPlan) -> ExecutionOutcome: ...
