"""Neutral clocks/orders preserve same-session and single-unit capabilities."""
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from dataflows import AssetClass, InstrumentId, MarketId
from strategy_runtime import (AccountExecutionPlan, AccountSnapshot, ExecutionPrecision,
    ReplayOrder, ReplayPoint, OrderSide, OrderType)


def point():
    stamp = datetime(2026, 10, 1, 10, tzinfo=ZoneInfo("America/New_York"))
    return ReplayPoint(stamp, stamp, stamp, stamp + timedelta(minutes=30),
                       "2026-10-01", ExecutionPrecision.BAR_INTERVAL)


def test_same_session_single_share_order_and_cash_receivable_are_separate():
    tick = point()
    order = ReplayOrder(OrderSide.BUY, 1, OrderType.LIMIT, Decimal("10.01"))
    plan = AccountExecutionPlan("a" * 64, "candidate:S999:C0001", tick, 0, 1, (order,))
    assert plan.orders[0].quantity == 1
    account = AccountSnapshot(InstrumentId(MarketId.US, AssetClass.STOCK, "LITE"), "USD",
        tick.decision_at, 0, 20., 10., 50., 1, 0)
    assert account.available_cash == 10. and account.receivable == 50.
    with pytest.raises(ValueError, match="exceed"):
        replace(account, available_cash=70.)
    with pytest.raises(ValueError, match="exceed"):
        replace(account, sellable_quantity=2)


@pytest.mark.parametrize("field,change", [
    ("observed_through", timedelta(seconds=1)),
    ("execution_start", timedelta(seconds=-1)),
    ("execution_end", timedelta(minutes=-30)),
])
def test_clock_rejects_future_visibility_and_nonpositive_execution(field, change):
    tick = point()
    with pytest.raises(ValueError, match="causal"):
        replace(tick, **{field: getattr(tick, field) + change})


def test_clock_compares_absolute_instants_across_dst_fold():
    zone = ZoneInfo("America/New_York")
    first = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    second = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
    tick = ReplayPoint(first, first, first, second, "declared-session", ExecutionPrecision.BAR_INTERVAL)
    assert tick.execution_end.fold == 1
    with pytest.raises(ValueError, match="causal"):
        replace(tick, observed_through=second)


@pytest.mark.parametrize("quantity", [True, 0, -1, 1.5])
def test_order_quantity_rejects_invalid_units(quantity):
    with pytest.raises(ValueError, match="integer units"):
        ReplayOrder(OrderSide.BUY, quantity, OrderType.MARKET)
