"""SRT-34: public facts remain typed; no account execution is involved."""

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
import pytest
from dataflows import AssetClass, InstrumentId, MarketId
from strategy_runtime import (
    AccountExecutionPlan,
    AccountSnapshot,
    ExecutionPrecision,
    ReplayOrder,
    ReplayPoint,
    ReplayLeg,
    CycleBudget,
    EntryCyclePhase,
    OrderSide,
    OrderType,
)


def point():
    stamp = datetime(2026, 10, 1, 10, tzinfo=ZoneInfo("America/New_York"))
    return ReplayPoint(
        stamp,
        stamp,
        stamp,
        stamp + timedelta(minutes=30),
        "2026-10-01",
        ExecutionPrecision.BAR_INTERVAL,
    )


def account():
    return AccountSnapshot(
        InstrumentId(MarketId.US, AssetClass.STOCK, "LITE"),
        "USD",
        point().decision_at,
        0,
        20.0,
        10.0,
        50.0,
        1,
        0,
    )


def test_SRT_34_C01_single_share_plan_and_separate_receivable():
    order = ReplayOrder(OrderSide.BUY, 1, OrderType.LIMIT, Decimal("10.01"))
    plan = AccountExecutionPlan("a" * 64, "candidate:S999:C0001", point(), 0, 1, (order,))
    assert plan.orders == (order,) and plan.orders[0].quantity == 1
    assert (account().available_cash, account().receivable) == (10.0, 50.0)


@pytest.mark.parametrize(
    "change",
    [
        {"available_cash": 70.0},
        {"sellable_quantity": 2},
    ],
    ids=["SRT-34-C02", "SRT-34-C03"],
)
def test_available_assets_cannot_exceed_confirmed_assets(change):
    with pytest.raises(ValueError, match="exceed"):
        replace(account(), **change)


@pytest.mark.parametrize(
    "field,delta",
    [
        ("observed_through", timedelta(seconds=1)),
        ("execution_start", timedelta(seconds=-1)),
        ("execution_end", timedelta(minutes=-30)),
    ],
    ids=["SRT-34-C04", "SRT-34-C05", "SRT-34-C06"],
)
def test_replay_clock_causal_order(field, delta):
    value = point()
    with pytest.raises(ValueError, match="causal"):
        replace(value, **{field: getattr(value, field) + delta})


def test_SRT_34_C07_clock_orders_absolute_instants_at_dst_fold():
    zone = ZoneInfo("America/New_York")
    first = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    second = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
    tick = ReplayPoint(
        first, first, first, second, "declared-session", ExecutionPrecision.BAR_INTERVAL
    )
    assert tick.execution_end.fold == 1
    with pytest.raises(ValueError, match="causal"):
        replace(tick, observed_through=second)


@pytest.mark.parametrize(
    "quantity",
    [
        True,
        0,
        1.5,
    ],
    ids=["SRT-34-C08", "SRT-34-C09", "SRT-34-C10"],
)
def test_order_requires_positive_integer_units(quantity):
    with pytest.raises(ValueError, match="integer units"):
        ReplayOrder(OrderSide.BUY, quantity, OrderType.MARKET)


def test_SRT_34_C11_limit_order_requires_price():
    with pytest.raises(ValueError, match="requires price"):
        ReplayOrder(OrderSide.BUY, 1, OrderType.LIMIT)


def test_SRT_34_C12_market_order_cannot_declare_limit():
    with pytest.raises(ValueError, match="cannot declare"):
        ReplayOrder(OrderSide.BUY, 1, OrderType.MARKET, Decimal("10"))


def test_SRT_34_C13_plan_cannot_mix_direct_orders_and_legs():
    tick = point()
    order = ReplayOrder(OrderSide.BUY, 1, OrderType.MARKET)
    leg = ReplayLeg(0, order, "entry", tick.execution_start, tick.execution_end)
    with pytest.raises(ValueError, match="not both"):
        AccountExecutionPlan("a" * 64, "candidate:S999:C0001", tick, 0, 1, (order,), (leg,))


def test_SRT_34_C14_cycle_budget_preserves_decimal_units():
    with pytest.raises(TypeError, match="Decimal"):
        CycleBudget("cycle-1", 1, Decimal("1"), 10.0, Decimal("0"), next(iter(EntryCyclePhase)))
