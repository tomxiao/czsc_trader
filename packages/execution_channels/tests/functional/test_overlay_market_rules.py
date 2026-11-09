"""Real market contracts for checkpoint-only ETF core rotations."""

from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from execution_channels.policy import ExecutionPolicy
from execution_channels.session_contracts import OrderSide
from execution_channels.session_contracts import OrderType
from execution_channels.session_contracts import PlanLeg
from execution_channels.session_contracts import PlannedOrder
from execution_channels.errors import RuntimeExecutionError
from execution_channels.session_contracts import TradingPoint
from execution_channels.historical import (
    HistoricalExecutor, MarketExecutionRules, SessionPriceLimits, SuspensionInformation,
)

from test_historical_execution_plans import _execution_plan, _rotation_plan


FEE = .00012


def _setup(*, market=True, fault=None):
    dates = pd.to_datetime(["2026-09-16", "2026-09-17", "2026-09-18"])
    daily = pd.DataFrame({"dt": dates, "open": 10., "high": 10.3,
                          "low": 9.9, "close": [10., 10.1, 10.2]})
    five = pd.DataFrame([
        {"dt": pd.Timestamp(f"{day} {clock}"), "open": opened, "high": high,
         "low": low, "close": closed}
        for day in ("2026-09-17", "2026-09-18")
        for clock, opened, high, low, closed in (
            ("09:35", 10., 10.1, 9.9, 10.), ("11:30", 10.1, 10.3, 10., 10.2))
    ])
    if fault == "locked_upper_entry":
        five.loc[five.dt.dt.normalize().eq(dates[-1]), ["open", "high", "low", "close"]] = 11.
        daily.loc[daily.dt.eq(dates[-1]), ["open", "high", "low", "close"]] = 11.
    elif fault == "locked_lower_exit":
        five.loc[five.dt.eq(pd.Timestamp("2026-09-18 11:30")), ["open", "high", "low", "close"]] = 9.
        daily.loc[daily.dt.eq(dates[-1]), ["low", "close"]] = 9.
    elif fault == "bad_ohlc":
        five.loc[0, "high"] = 9.95
    elif fault == "outside_limits":
        five.loc[0, "high"] = 12.
    elif fault == "missing_ohlc":
        five = five.drop(columns="high")
    elif fault == "missing_checkpoint":
        five = five.iloc[:-1].copy()
    elif fault == "duplicate_checkpoint":
        five = pd.concat([five, five.iloc[[-1]]], ignore_index=True)
    elif fault == "wrong_open":
        five.loc[0, "open"] = 10.05
    elif fault == "not_a_5m_timestamp":
        five.loc[0, "dt"] += pd.Timedelta(seconds=1)
    rules = MarketExecutionRules("510500.SH", tuple(
        SessionPriceLimits(day.date(), 9., 11., .001) for day in dates[1:]
    ), (), SuspensionInformation.NOT_PROVIDED) if market else None
    policy = ExecutionPolicy("INTRADAY_OVERLAY", {
        "core_fraction": .5, "event_fraction": .5, "lot_size": 100,
        "one_way_cost": FEE,
    })
    channel = HistoricalExecutor(
        strategy_reference="S003-v1", symbol="510500.SH",
        execution_daily=daily,
        execution_intraday=pd.DataFrame(columns=["dt", "open", "high", "low", "close"]),
        execution_five_minute=five, evaluation_start=dates[1], evaluation_end=dates[-1],
        initial_cash=100000., execution_policy=policy,
        order_types=("LIMIT", "MARKET"), checkpoints=("OPEN", "11:30_CLOSE"),
        market_rules=rules,
    )
    generated = datetime(2026, 9, 16, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    point = TradingPoint(dates[1].date(), generated)
    portfolio, state = channel.snapshot(point)
    core = _execution_plan(
        reference="S003-v1", symbol="510500.SH", signal_date="2026-09-16",
        valid_date="2026-09-17", generated_at=generated, portfolio=portfolio, state=state,
        target_position=.5, target_quantity=4900, cycle_target_quantity=4900,
        plan_mode="CORE_SETUP", fee_rate=FEE,
        legs=(PlanLeg(0, "CORE_SETUP", "OPEN", time(9, 30), time(9, 35),
                      PlannedOrder(OrderSide.BUY, 4900, OrderType.LIMIT, Decimal("10"))),),
    )
    return channel, core


# Independent risk: EC28; responsibility-level assertions.
def test_locked_upper_checkpoint_buy_does_not_fill_or_sell_core():
    channel, core = _setup(fault="locked_upper_entry")
    channel.execute(core)
    rotation, point = _rotation_plan(channel, FEE, buy_limit=Decimal("11"))
    before = channel.snapshot(point)[0]
    result = channel.execute(rotation)
    assert result.portfolio.position_quantity == before.position_quantity == 4900
    assert result.portfolio.available_cash == before.available_cash
    ledger = channel.finish()
    assert ledger.fills.side.tolist() == ["BUY"]
    assert ledger.orders.status.tolist() == ["FILLED", "UNFILLED"]
    assert ledger.orders.reason.iloc[-1] == "OPEN_UP_LIMIT_BUY_BLOCKED"
    assert ledger.trades.empty


# Independent risk: EC28; responsibility-level assertions.
def test_locked_lower_exit_retains_partial_buy_and_permanently_rejects_success():
    channel, core = _setup(fault="locked_lower_exit")
    channel.execute(core)
    rotation, point = _rotation_plan(channel, FEE)
    before = channel.snapshot(point)[0]
    with pytest.raises(RuntimeExecutionError, match="confirmed fills in failed plan=1.*restore its sellable core"):
        channel.execute(rotation)
    actual, _ = channel.snapshot(point)
    assert actual.position_quantity == 9500
    assert actual.available_cash < before.available_cash
    assert actual.revision == before.revision + 1
    with pytest.raises(RuntimeExecutionError, match="partial execution facts are retained"):
        channel.finish()
    with pytest.raises(RuntimeExecutionError, match="confirmed fills in failed plan=1"):
        channel.execute(rotation)
    # A failed account cannot poison a separate executor.
    independent, independent_core = _setup()
    assert independent.execute(independent_core).status == "SETTLED"
