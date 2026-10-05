"""Cycle accounting across partial exits, further entries, and later cycles."""

from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from strategy_runtime import (
    ExecutionCapabilities, ExecutionPlan, ExecutionPolicy, OrderSide, OrderType,
    PlannedOrder, PriceReference, StrategyIdentity, TradingPoint,
)
from strategy_runtime.contracts import plan_identity_for, signal_identity_for
from trading_execution_engine import HistoricalExecutor


def _plan(executor, dates, day, target, orders, fee):
    signal, trading = dates[day - 1].date(), dates[day].date()
    generated = datetime.combine(signal, time(20, 30), ZoneInfo("Asia/Shanghai"))
    portfolio, state = executor.snapshot(TradingPoint(trading, generated))
    identity = StrategyIdentity("S999", "S999-C0001", "a" * 64, "b" * 64, "588080.SH")
    inputs = {"price": "c" * 64}
    signal_identity = signal_identity_for(
        strategy=identity, signal_date=signal, target_position=target,
        input_identities=inputs, price_identities=inputs,
    )
    quantities = dict(
        signal_identity=signal_identity, actual_quantity=portfolio.position_quantity,
        target_quantity=1000 if target else 0, cycle_target_quantity=1000,
        plan_mode="TARGET_POSITION", capital_mode="full_available_cash",
        allocation_fraction=Decimal(1), orders=orders, legs=(),
    )
    return ExecutionPlan(
        strategy=identity, plan_identity=plan_identity_for(**quantities),
        symbol=identity.symbol, signal_date=signal, trading_date=trading,
        generated_at=generated, expected_portfolio_revision=portfolio.revision,
        expected_state_revision=state.revision, target_position=target,
        action="BUY" if target else "SELL", available_cash=portfolio.available_cash,
        fee_rate=Decimal(str(fee)), estimated_order_cost=Decimal(0),
        unallocated_cash=Decimal(0),
        references=PriceReference(Decimal(10), Decimal(10), "ADJUSTED_CLOSE", "UNADJUSTED_CLOSE"),
        required_capabilities=executor.capabilities, input_identities=inputs,
        price_identities=inputs, **quantities,
    )


@pytest.mark.parametrize("reentry", [0, 200])
@pytest.mark.parametrize("fee", [0., .001])
def test_cycle_retains_all_exit_cashflows_across_sessions_and_reentry(reentry, fee):
    dates = pd.bdate_range("2026-09-14", periods=7)
    prices = pd.DataFrame({"dt": dates, "open": [10., 10., 11., 9., 12., 8., 9.]})
    prices["close"] = prices["open"]
    executor = HistoricalExecutor(
        strategy_reference="S999-C0001", symbol="588080.SH", execution_daily=prices,
        execution_intraday=pd.DataFrame(columns=["dt", "high", "low"]),
        evaluation_start=dates[1], evaluation_end=dates[-1], initial_cash=20000.,
        execution_policy=ExecutionPolicy("FROZEN_RULE", {"capital": {"fee_rate": fee}}),
        order_types=("MARKET", "LIMIT"),
    )
    assert executor.capabilities == ExecutionCapabilities((OrderType.MARKET, OrderType.LIMIT))

    def order(side, quantity, limit=None):
        return PlannedOrder(
            side, quantity, OrderType.MARKET if limit is None else OrderType.LIMIT,
            None if limit is None else Decimal(str(limit)),
        )

    steps = (
        (1, (order(OrderSide.BUY, 1000),)),
        (0, (order(OrderSide.SELL, 500), order(OrderSide.SELL, 500, 20.))),
        (1 if reentry else 0, (order(OrderSide.BUY, reentry),) if reentry else ()),
        (0, (order(OrderSide.SELL, 500 + reentry),)),
        (1, (order(OrderSide.BUY, 100),)),
        (0, (order(OrderSide.SELL, 100),)),
    )
    for day, (target, orders) in enumerate(steps, 1):
        plan = _plan(executor, dates, day, target, orders, fee)
        outcome = executor.execute(plan)
        assert executor.execute(plan) == outcome  # A retry must not count an exit twice.
    result = executor.finish()
    assert result.orders.status.tolist().count("UNFILLED") == 1
    assert len(result.trades) == 2
    first, second = result.trades.iloc[0], result.trades.iloc[1]
    entry_gross = 10000. + reentry * 9.
    exit_gross = 5500. + (500 + reentry) * 12.
    assert first.quantity == 1000 + reentry
    assert first.entry_price == pytest.approx(entry_gross / first.quantity)
    assert first.exit_price == pytest.approx(exit_gross / first.quantity)
    assert first.net_return == pytest.approx(exit_gross * (1 - fee) / (entry_gross * (1 + fee)) - 1)
    assert first.exit_date == dates[4]
    assert second.cycle_id != first.cycle_id
    assert second.quantity == 100
    assert second.net_return == pytest.approx(900. * (1 - fee) / (800. * (1 + fee)) - 1)
    assert result.account_daily.quantity.iloc[-1] == 0
    assert result.account_daily.equity.iloc[-1] == pytest.approx(
        20000. + (exit_gross + 900.) * (1 - fee) - (entry_gross + 800.) * (1 + fee)
    )
