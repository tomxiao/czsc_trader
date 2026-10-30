"""Typed adapter for the existing dated-session execution model.

Model adapters retain existing sizing/budget and fill precision semantics. They
share monetary postings; they never own a second account replay loop.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from strategy_runtime.contracts import ExecutionPlan, OrderType
from strategy_runtime.replay_contracts import AccountExecutionPlan, ExecutionPrecision


if TYPE_CHECKING:
    from .historical import HistoricalExecutor


_SESSION_ZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class SessionExecution:
    executor: HistoricalExecutor
    source: ExecutionPlan


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


def execute_plan(plan: AccountExecutionPlan, model: SessionExecution):
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
    raise TypeError('execution requires SessionExecution')
