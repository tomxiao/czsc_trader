"""One typed plan boundary for session and interval execution models.

Model adapters retain existing sizing/budget and fill precision semantics. They
share monetary postings; they never own a second account replay loop.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Mapping, TYPE_CHECKING
from zoneinfo import ZoneInfo

import pandas as pd
from strategy_runtime.contracts import ExecutionPlan, OrderSide, OrderType
from strategy_runtime.equity import EquityPlan
from strategy_runtime.replay_contracts import AccountExecutionPlan, ExecutionPrecision


if TYPE_CHECKING:
    from .historical import HistoricalExecutor
    from .equity import EquityHistoricalExecutor


_SESSION_ZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class SessionExecution:
    executor: HistoricalExecutor
    source: ExecutionPlan


@dataclass(frozen=True, slots=True)
class BarExecution:
    executor: EquityHistoricalExecutor
    source: EquityPlan
    bar: Mapping | pd.Series
    constraint: Mapping | pd.Series


def _orders(actual, expected):
    return len(actual) == len(expected) and all(
        (a.side, a.quantity, a.order_type, a.limit_price) ==
        (b.side, b.quantity, b.order_type, b.limit_price if b.order_type is OrderType.LIMIT else None)
        for a, b in zip(actual, expected, strict=True))


def _cycle(actual, expected):
    if actual is None or expected is None:
        return actual is expected
    return all(getattr(actual, name) == getattr(expected, name) for name in (
        'cycle_id', 'target_quantity', 'allocation_fraction', 'cash_budget',
        'buy_cost_including_fees', 'phase'))


def execute_plan(plan: AccountExecutionPlan, model: SessionExecution | BarExecution):
    """Reject changed projections before executing authenticated model facts."""
    if type(plan) is not AccountExecutionPlan:
        raise TypeError('execution requires AccountExecutionPlan')
    if type(model) is SessionExecution:
        from .historical import HistoricalExecutor
        if not isinstance(model.executor, HistoricalExecutor) or type(model.source) is not ExecutionPlan:
            raise TypeError('session execution requires its typed executor and source plan')
        source, point = model.source, plan.point
        day = source.trading_date
        if (plan.plan_identity != source.plan_identity or plan.owner != source.strategy.reference_id
                or plan.expected_revision != source.expected_portfolio_revision
                or plan.target_quantity != source.target_quantity or plan.capital_mode != source.capital_mode
                or point.precision is not ExecutionPrecision.SESSION
                or point.decision_at != source.generated_at or point.session_id != day.isoformat()
                or point.observed_through != datetime.combine(source.signal_date, time(15), _SESSION_ZONE)
                or point.execution_start != datetime.combine(day, time.min, _SESSION_ZONE)
                or point.execution_end != datetime.combine(day + timedelta(days=1), time.min, _SESSION_ZONE)
                or not _cycle(plan.cycle_before, source.entry_cycle_before)
                or not _cycle(plan.cycle_after, source.entry_cycle_after)):
            raise ValueError('session neutral plan differs from model facts')
        if source.legs:
            if plan.orders or len(plan.legs) != len(source.legs):
                raise ValueError('session execution legs differ from model facts')
            for actual, expected in zip(plan.legs, source.legs, strict=True):
                if ((actual.sequence, actual.checkpoint, actual.dependency_sequence,
                        actual.dependency_required_status) != (expected.sequence, expected.checkpoint,
                        expected.dependency_sequence, expected.dependency_required_status)
                        or not _orders((actual.order,), (expected.order,))
                        or actual.submit_after != datetime.combine(day, expected.submit_after, tzinfo=_SESSION_ZONE)
                        or actual.submit_before != datetime.combine(day, expected.submit_before, tzinfo=_SESSION_ZONE)):
                    raise ValueError('session execution legs differ from model facts')
        elif plan.legs or not _orders(plan.orders, source.orders):
            raise ValueError('session orders differ from model facts')
        return model.executor.execute(source)
    if type(model) is BarExecution:
        from .equity import EquityHistoricalExecutor, _SESSION_ZONES
        if not isinstance(model.executor, EquityHistoricalExecutor) or type(model.source) is not EquityPlan:
            raise TypeError('bar execution requires its typed executor and source plan')
        source, point, executor = model.source, plan.point, model.executor
        native = source.point
        if (plan.plan_identity != source.plan_id or plan.expected_revision != source.portfolio_revision
                or plan.legs or plan.capital_mode != 'full_available_cash'
                or plan.cycle_before is not None or plan.cycle_after is not None
                or point.precision is not ExecutionPrecision.BAR_INTERVAL
                or (point.observed_through, point.decision_at, point.execution_start, point.execution_end) != (
                    native.observed_through, native.decision_at, native.execution_interval.start, native.execution_interval.end)
                or point.session_id != point.execution_start.astimezone(_SESSION_ZONES[executor.spec.market_id]).date().isoformat()):
            raise ValueError('bar neutral plan differs from model facts')
        if source.side in ('BUY', 'SELL'):
            if len(plan.orders) != 1:
                raise ValueError('bar order differs from model facts')
            order = plan.orders[0]
            if (order.side, order.quantity, order.order_type, order.limit_price) != (
                    OrderSide(source.side), source.quantity,
                    OrderType.LIMIT if source.side == 'BUY' else OrderType.MARKET, source.limit_price):
                raise ValueError('bar order differs from model facts')
        elif plan.orders:
            raise ValueError('waiting bar cannot submit orders')
        prior = executor._neutral_targets.get(source.plan_id)
        target = (executor.quantity + source.quantity if source.side == 'BUY' else
                  executor.quantity - source.quantity if source.side == 'SELL' else executor.quantity)
        if prior is None:
            if source.portfolio_revision != executor.revision or plan.target_quantity != target:
                raise ValueError('bar neutral target differs from confirmed holdings')
        elif prior != plan.target_quantity:
            raise ValueError('bar neutral target changed on retry')
        if executor._neutral_owner is not None and executor._neutral_owner != plan.owner:
            raise ValueError('bar neutral owner differs from account owner')
        result = executor.execute(source, model.bar, constraint=model.constraint)
        executor._neutral_targets[source.plan_id] = plan.target_quantity
        executor._neutral_owner = plan.owner
        return result
    raise TypeError('execution requires SessionExecution or BarExecution')
