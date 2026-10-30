"""Explicit fact projection for the existing batch and bar execution models."""
from datetime import datetime

from .contracts import ExecutionPlan, OrderSide, OrderType
from .equity import EquityPlan, EquityPortfolio
from .replay_contracts import AccountExecutionPlan, CycleBudget, ReplayLeg, ReplayOrder, ReplayPoint


def _cycle(value):
    return None if value is None else CycleBudget(value.cycle_id, value.target_quantity,
        value.allocation_fraction, value.cash_budget, value.buy_cost_including_fees, value.phase)


def project_window_plan(plan: ExecutionPlan, point: ReplayPoint) -> AccountExecutionPlan:
    """Map existing plan facts without recomputing sizing, cash or prices."""
    if type(plan) is not ExecutionPlan or type(point) is not ReplayPoint:
        raise TypeError("window projection requires ExecutionPlan and ReplayPoint")
    if point.decision_at != plan.generated_at:
        raise ValueError("replay point differs from generated plan time")
    def order(item):
        return ReplayOrder(item.side, item.quantity, item.order_type,
                           item.limit_price if item.order_type is OrderType.LIMIT else None)
    legs = tuple(ReplayLeg(item.sequence, order(item.order), item.checkpoint,
        datetime.combine(plan.trading_date, item.submit_after, tzinfo=point.execution_start.tzinfo),
        datetime.combine(plan.trading_date, item.submit_before, tzinfo=point.execution_start.tzinfo),
        item.dependency_sequence, item.dependency_required_status) for item in plan.legs)
    return AccountExecutionPlan(plan.plan_identity, plan.strategy.reference_id, point,
        plan.expected_portfolio_revision, plan.target_quantity,
        () if legs else tuple(order(item) for item in plan.orders), legs, plan.capital_mode,
        _cycle(plan.entry_cycle_before), _cycle(plan.entry_cycle_after))


def project_bar_plan(plan: EquityPlan, portfolio: EquityPortfolio, point: ReplayPoint,
                     *, owner: str) -> AccountExecutionPlan:
    if type(plan) is not EquityPlan or type(portfolio) is not EquityPortfolio or type(point) is not ReplayPoint:
        raise TypeError("bar projection requires EquityPlan, EquityPortfolio and ReplayPoint")
    native = plan.point
    if (point.observed_through, point.decision_at, point.execution_start, point.execution_end) != (
            native.observed_through, native.decision_at, native.execution_interval.start, native.execution_interval.end):
        raise ValueError("replay point differs from bar plan time")
    orders = ()
    if plan.side == "BUY":
        orders = (ReplayOrder(OrderSide.BUY, plan.quantity, OrderType.LIMIT, plan.limit_price),)
    elif plan.side == "SELL":
        orders = (ReplayOrder(OrderSide.SELL, plan.quantity, OrderType.MARKET),)
    target = portfolio.quantity
    if plan.side == "BUY":
        target += plan.quantity
    elif plan.side == "SELL":
        target -= plan.quantity
    return AccountExecutionPlan(plan.plan_id, owner, point, plan.portfolio_revision, target, orders)
