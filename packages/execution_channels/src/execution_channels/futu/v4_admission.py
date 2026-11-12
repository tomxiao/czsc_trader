"""Futu V4 plan admission and pending account transition without I/O or strategy calls."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping

from ..contracts import AccountExecutionPlan, AccountSnapshot
from ..instruments import TimeInterval
from ..state import AccountStrategyState, CycleState, StateRecord
from .adoption import AdoptionOrder, AdoptionLeg
from .equity_contracts import EquityAccountRules
from .equity_account_state import budget_from_dict, budget_to_dict, validate_document


@dataclass(frozen=True, slots=True)
class V4AccountProposal:
    account: StateRecord
    cycle_values: StateRecord | None
    state_binding: str
    next_event_cursor: int

    def __post_init__(self):
        if type(self.account) is not StateRecord or (self.cycle_values is not None and type(self.cycle_values) is not StateRecord):
            raise TypeError("V4 account proposal requires execution state records")
        if type(self.next_event_cursor) is not int or self.next_event_cursor < 0 or not self.state_binding:
            raise ValueError("V4 account proposal requires event cursor and state binding")


@dataclass(frozen=True, slots=True)
class V4ExecutionContext:
    interval: TimeInterval
    as_of: datetime
    buy_sellable_at: datetime
    v4_constraint: Mapping[str, object]
    data_identity: str
    fee_rate: float

    def __post_init__(self):
        if type(self.interval) is not TimeInterval or type(self.buy_sellable_at) is not datetime or self.buy_sellable_at.utcoffset() is None:
            raise TypeError("V4 execution context requires explicit aware interval and sellability")
        if type(self.as_of) is not datetime or self.as_of.utcoffset() is None:
            raise TypeError("V4 execution context requires an aware observation time")
        if self.as_of > self.interval.start:
            raise ValueError("V4 observation time must not follow execution start")
        if not 0 <= self.fee_rate < 1:
            raise ValueError("V4 execution fee must be between zero and one")
        object.__setattr__(self, "v4_constraint", MappingProxyType(dict(self.v4_constraint)))


@dataclass(frozen=True, slots=True)
class V4DecisionEffects:
    orders: tuple[AdoptionOrder, ...]
    legs: tuple[AdoptionLeg, ...]
    after: dict
    reference: float
    estimated_order_cost: float
    unallocated_cash: float
    action: str


def prepare_v4_adoption(plan: AccountExecutionPlan, snapshot: AccountSnapshot, document: dict,
                        proposal: V4AccountProposal, prepared: V4ExecutionContext,
                        rules: EquityAccountRules) -> V4DecisionEffects:
    """Validate lots, prices, funding and sellability; prepare an uncommitted state transition."""
    if (type(plan) is not AccountExecutionPlan or type(snapshot) is not AccountSnapshot
            or type(proposal) is not V4AccountProposal or type(prepared) is not V4ExecutionContext
            or type(rules) is not EquityAccountRules):
        raise TypeError("V4 admission requires execution-owned plan, account, proposal and context")
    state = validate_document(document)
    actual_quantity, available_cash = snapshot.quantity, float(snapshot.available_cash)
    if (plan.point.execution_start, plan.point.execution_end) != (prepared.interval.start, prepared.interval.end):
        raise ValueError('V4 plan differs from the prepared execution interval')
    interval = {key: getattr(prepared.interval, key).isoformat() for key in ("start", "end")}
    if plan.legs:
        if tuple(leg.sequence for leg in plan.legs) != tuple(range(len(plan.legs))):
            raise ValueError("V4 leg sequences must be contiguous")
        for leg in plan.legs:
            if not prepared.interval.start <= leg.submit_after < leg.submit_before <= prepared.interval.end:
                raise ValueError("V4 leg is outside its declared execution interval")
            if leg.dependency_sequence is not None and leg.dependency_required_status != "FILLED_ALL":
                raise ValueError("V4 dependent legs require confirmed complete execution")
        # Reserve existing inventory and cash. Future entry fills do not finance
        # an exit at adoption; this preserves core-position rotation semantics.
        if sum(leg.order.quantity for leg in plan.legs if leg.order.side.value == "SELL") > snapshot.sellable_quantity:
            raise ValueError("V4 plan sell legs exceed confirmed sellable holdings")
    if plan.orders and len({order.side for order in plan.orders}) > 1:
        raise ValueError("V4 mixed-side orders require supported dependency execution")
    prior_budget = budget_from_dict(document["budget"])
    if plan.capital_mode == "signal_cash_fraction":
        if plan.cycle_before != prior_budget:
            raise ValueError("V4 cycle budget differs from confirmed state")
        if plan.cycle_after is None and plan.target_quantity:
            raise ValueError("V4 cycle allocation requires a declared budget")
        if prior_budget is not None and plan.cycle_after is not None and any(
                getattr(prior_budget, key) != getattr(plan.cycle_after, key)
                for key in ("cycle_id", "target_quantity", "allocation_fraction", "cash_budget", "buy_cost_including_fees")):
            raise ValueError("V4 active cycle budget cannot be rebuilt")
        if plan.cycle_after is not None:
            if plan.target_quantity > plan.cycle_after.target_quantity:
                raise ValueError("V4 plan exceeds its declared cycle target")
            if prior_budget is None and plan.cycle_after.cash_budget > Decimal(str(available_cash))*plan.cycle_after.allocation_fraction:
                raise ValueError("V4 cycle budget exceeds declared available cash allocation")
    orders = tuple(AdoptionOrder(order.side.value, order.quantity, order.order_type.value,
        float(order.limit_price) if order.limit_price is not None else float(plan.evidence["reference_price"]), "DAY")
        for order in plan.orders)
    legs = tuple(AdoptionLeg(leg.sequence, "V4", leg.checkpoint, leg.submit_after, leg.submit_before,
        leg.dependency_sequence, leg.dependency_required_status,
        AdoptionOrder(leg.order.side.value, leg.order.quantity, leg.order.order_type.value,
            float(leg.order.limit_price) if leg.order.limit_price is not None else float(plan.evidence["reference_price"]), "DAY"))
        for leg in plan.legs)
    all_orders = orders or tuple(leg.order for leg in legs)
    if any(order.side == "BUY" and order.order_type != "LIMIT" for order in all_orders):
        raise ValueError("PTE V4 cash reservation requires explicit limit buy orders")
    sellable = snapshot.sellable_quantity
    for order in all_orders:
        if order.side == "BUY" and prepared.buy_sellable_at <= prepared.interval.start:
            sellable += order.quantity
        if order.side == "SELL":
            sellable -= order.quantity
            if sellable < 0:
                raise ValueError("V4 order exceeds currently sellable holdings")
    for order in all_orders:
        if order.quantity % rules.execution.quantity_step:
            # Full liquidation of integer split remainders is allowed only when
            # the dated constraint explicitly permits it (the shared planner checks it).
            if (order.side != "SELL" or order.quantity != actual_quantity
                    or prepared.v4_constraint["SellRemainderPolicy"] != "FULL_LIQUIDATION"):
                raise ValueError("V4 order differs from declared trading lot")
        if order.order_type == "LIMIT":
            price = Decimal(str(order.limit_price))
            if price % Decimal(str(rules.execution.price_tick)):
                raise ValueError("V4 limit price differs from declared tick")
            limits = prepared.v4_constraint
            if limits["PriceLimitPolicy"] == "DATED_LIMITS" and not limits["PriceLimitLower"] <= float(price) <= limits["PriceLimitUpper"]:
                raise ValueError("V4 limit order exceeds dated price limits")
    cycle = None if state.cycle is None else CycleState(state.cycle.cycle_id, state.cycle.entry_at, proposal.cycle_values)
    next_state = AccountStrategyState(state.revision + 1, proposal.account, cycle,
                                     proposal.state_binding, proposal.next_event_cursor)
    after = {**document, "state": next_state.to_dict(),
        "locked_quantity": plan.evidence["locked_quantity"],
        "pending_cycle": None if proposal.cycle_values is None else proposal.cycle_values.to_dict(),
        "budget": budget_to_dict(plan.cycle_after if plan.cycle_after is not None else prior_budget), "last_interval": interval, "last_inputs": prepared.data_identity,
        "buy_locks": [lock for lock in document["buy_locks"] if datetime.fromisoformat(lock["at"]) > prepared.as_of]}
    validate_document(after)
    reference = float(plan.evidence["reference_price"])
    exact_estimate = sum((Decimal(str(order.limit_price))*order.quantity*(1+Decimal(str(prepared.fee_rate)))
                          for order in all_orders if order.side == "BUY"), Decimal(0))
    estimate = float(exact_estimate)
    budget = budget_from_dict(after["budget"])
    if plan.capital_mode == "signal_cash_fraction" and budget is not None and exact_estimate > budget.cash_budget-budget.buy_cost_including_fees:
        raise ValueError("V4 orders exceed remaining cycle budget")
    sides = {order.side for order in all_orders}
    action = ("ROTATE" if len(sides) > 1 else "BUY" if "BUY" in sides else "SELL") if all_orders else ("HOLD" if actual_quantity else "WAIT")
    return V4DecisionEffects(orders, legs, after, reference, estimate, available_cash-estimate, action)


def decision_snapshot(account: Mapping[str, object], document: dict, rules: EquityAccountRules,
                      at: datetime, available_cash: Decimal) -> AccountSnapshot:
    """Read confirmed quantities and sellability locks into the channel account view."""
    from .equity_account_state import position_from_dict
    if type(rules) is not EquityAccountRules or type(available_cash) is not Decimal:
        raise TypeError("snapshot requires execution rules and exact available cash")
    state = validate_document(document)
    active = position_from_dict(document["active"])
    quantity = int(account["quantity"])
    if active is not None and active.quantity != quantity:
        raise ValueError("V4 position feedback differs from confirmed holdings")
    locked = sum(lock["quantity"] for lock in document["buy_locks"]
                 if datetime.fromisoformat(lock["at"]) > at)
    if locked > quantity:
        raise ValueError("V4 locked holdings exceed confirmed quantity")
    return AccountSnapshot(rules.instrument, rules.execution.account.currency, at, state.revision,
        Decimal(account["cash"])+Decimal(account["frozen_cash"]), available_cash,
        Decimal(account["receivable"]), quantity, quantity-locked)
