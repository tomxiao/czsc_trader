"""Confirmed decision effects, separate from planning and order submission.

COMPLETED describes this decision's executable orders, not exact attainment of
its target weight. Valuation is explicit and never fetches a market price.
"""
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
import math
from .planning.result import PlanningResult, PlanningStatus, PlanningConstraint


class ExecutionEffectStatus(StrEnum):
    WAITING = 'WAITING'
    PARTIAL = 'PARTIAL'
    COMPLETED = 'COMPLETED'
    NOT_EXECUTED = 'NOT_EXECUTED'
    UNKNOWN = 'UNKNOWN'


@dataclass(frozen=True, slots=True)
class OrderExecutionEffect:
    order_id: str
    side: str
    quantity: int
    filled_quantity: int
    status: str
    in_flight: bool
    outcome_unknown: bool = False
    reason: str | None = None

    def __post_init__(self):
        if not self.order_id or self.side not in {'BUY', 'SELL'} or not self.status:
            raise ValueError('execution order effect requires identity, side and status')
        if (type(self.quantity) is not int or self.quantity <= 0
                or type(self.filled_quantity) is not int or not 0 <= self.filled_quantity <= self.quantity):
            raise ValueError('confirmed quantity must be within ordered quantity')
        if type(self.in_flight) is not bool or type(self.outcome_unknown) is not bool:
            raise TypeError('execution order progress requires explicit booleans')
        if self.outcome_unknown and not self.in_flight:
            raise ValueError('unknown execution must remain unresolved')
        if self.reason is not None and (type(self.reason) is not str or not self.reason):
            raise ValueError('execution reason must be nonempty text')


@dataclass(frozen=True, slots=True)
class DecisionExecutionEffect:
    decision_id: str
    as_of: datetime
    status: ExecutionEffectStatus
    terminal: bool
    target_weight: float
    desired_quantity: int
    planned_quantity: int
    actual_quantity: int
    cash: Decimal
    available_cash: Decimal
    receivable: Decimal
    valuation_price: Decimal
    equity: Decimal
    actual_weight: float | None
    weight_deviation: float | None
    planning_status: PlanningStatus
    constraint_reasons: tuple[PlanningConstraint, ...]
    orders: tuple[OrderExecutionEffect, ...]

    def to_dict(self) -> dict:
        """Serialize the confirmed effect without recalculating account values."""
        value = asdict(self)
        value['as_of'] = self.as_of.isoformat()
        value['status'] = self.status.value
        value['planning_status'] = self.planning_status.value
        value['constraint_reasons'] = [item.value for item in self.constraint_reasons]
        value['orders'] = [asdict(item) for item in self.orders]
        for name in ('cash', 'available_cash', 'receivable', 'valuation_price', 'equity'):
            value[name] = str(getattr(self, name))
        return value

    def __post_init__(self):
        if (type(self.decision_id) is not str or not self.decision_id
                or type(self.as_of) is not datetime or self.as_of.utcoffset() is None):
            raise ValueError('execution effect requires decision identity and aware observation time')
        if type(self.status) is not ExecutionEffectStatus or type(self.terminal) is not bool:
            raise TypeError('execution effect requires typed progress')
        if type(self.orders) is not tuple or any(type(x) is not OrderExecutionEffect for x in self.orders):
            raise TypeError('execution effects require immutable typed orders')
        if len({x.order_id for x in self.orders}) != len(self.orders):
            raise ValueError('execution effect contains duplicate orders')
        if self.terminal == any(x.in_flight for x in self.orders):
            raise ValueError('execution terminal flag differs from outstanding orders')
        if (type(self.target_weight) not in (int, float) or not math.isfinite(self.target_weight)
                or not 0 <= self.target_weight <= 1):
            raise ValueError('execution target must be a finite weight')
        for name in ('desired_quantity', 'planned_quantity', 'actual_quantity'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError('execution quantities require nonnegative integers')
        for name in ('cash', 'available_cash', 'receivable', 'valuation_price', 'equity'):
            value = getattr(self, name)
            if type(value) is not Decimal or not value.is_finite() or value < 0:
                raise ValueError('execution values require finite nonnegative Decimal amounts')
        if self.valuation_price <= 0 or self.available_cash > self.cash:
            raise ValueError('execution valuation or available cash is invalid')
        if self.equity != self.cash + self.receivable + self.actual_quantity * self.valuation_price:
            raise ValueError('execution equity differs from confirmed account')
        weight = None if not self.equity else float(self.actual_quantity * self.valuation_price / self.equity)
        deviation = None if weight is None else weight - self.target_weight
        if self.actual_weight != weight or self.weight_deviation != deviation:
            raise ValueError('execution weight differs from confirmed valuation')
        if type(self.planning_status) is not PlanningStatus:
            raise TypeError('execution effect requires typed planning status')
        if (type(self.constraint_reasons) is not tuple
                or any(type(x) is not PlanningConstraint for x in self.constraint_reasons)):
            raise TypeError('execution constraints require immutable typed reason codes')


def decision_execution_effect(*, decision_id, at, target_weight, planning_result,
                              actual_quantity, cash, available_cash, receivable,
                              valuation_price, orders):
    """Project confirmed account/order facts; no new fills or account mutation.

The deviation is actual weight minus target weight. ``cash`` includes reserved
cash, while ``available_cash`` excludes those reservations. A zero-equity
account has undefined weights rather than a fabricated zero achievement.
"""
    planning = PlanningResult.from_dict(planning_result)
    if type(orders) is not tuple or any(type(x) is not OrderExecutionEffect for x in orders):
        raise TypeError('execution effect requires typed order facts')
    if any(x.outcome_unknown for x in orders):
        status = ExecutionEffectStatus.UNKNOWN
    elif any(x.in_flight for x in orders):
        status = ExecutionEffectStatus.PARTIAL if any(x.filled_quantity for x in orders) else ExecutionEffectStatus.WAITING
    elif orders and all(x.filled_quantity == x.quantity for x in orders):
        status = ExecutionEffectStatus.COMPLETED
    elif any(x.filled_quantity for x in orders):
        status = ExecutionEffectStatus.PARTIAL
    elif not orders and planning.status is PlanningStatus.NO_CHANGE:
        status = ExecutionEffectStatus.COMPLETED
    else:
        status = ExecutionEffectStatus.NOT_EXECUTED
    amounts = tuple(Decimal(str(x)) for x in (cash, available_cash, receivable, valuation_price))
    equity = amounts[0] + amounts[2] + actual_quantity * amounts[3]
    weight = None if not equity else float(actual_quantity * amounts[3] / equity)
    return DecisionExecutionEffect(decision_id, at, status, not any(x.in_flight for x in orders),
        target_weight, planning.desired_quantity, planning.planned_quantity, actual_quantity,
        *amounts, equity, weight, None if weight is None else weight-target_weight,
        planning.status, planning.reasons, orders)
