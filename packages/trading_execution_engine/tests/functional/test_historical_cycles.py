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


class _EvidenceWithoutDeepcopy:
    def __deepcopy__(self, memo):
        raise AssertionError("numeric replay must not deep-copy source evidence")


def test_numeric_admission_isolates_prices_without_copying_evidence_and_preserves_day_boundaries():
    dates = pd.bdate_range("2026-09-14", periods=4)
    prices = pd.DataFrame({"dt": dates, "open": [10.] * 4, "close": [10., 11., 12., 13.]})
    bars = pd.DataFrame({
        "dt": [dates[3], dates[2] + pd.Timedelta(hours=10, minutes=30),
               dates[1] + pd.Timedelta(hours=23, minutes=59),
               dates[2] + pd.Timedelta(hours=9, minutes=30)],
        "high": [10.] * 4, "low": [1., 8.5, 1., 9.],
    })

    def admitted():
        return HistoricalExecutor(
            strategy_reference="S999-C0001", symbol="588080.SH", execution_daily=prices,
            execution_intraday=bars, evaluation_start=dates[1], evaluation_end=dates[-1],
            initial_cash=20000., execution_policy=ExecutionPolicy("FROZEN_RULE", {"capital": {"fee_rate": .001}}),
            order_types=("MARKET", "LIMIT"),
        )

    baseline = admitted()
    evidence = _EvidenceWithoutDeepcopy()
    prices.attrs["evidence"] = bars.attrs["evidence"] = evidence
    isolated = admitted()
    prices.loc[:, "close"] = 999.
    bars.loc[:, "low"] = 999.
    results = []
    for executor in (baseline, isolated):
        for day, target, orders in (
            (1, 0., ()),
            (2, .5, (PlannedOrder(OrderSide.BUY, 100, OrderType.LIMIT, Decimal("9")),)),
            (3, 0., (PlannedOrder(OrderSide.SELL, 100, OrderType.MARKET, None),)),
        ):
            executor.execute(_plan(executor, dates, day, target, orders, .001))
        results.append(executor.finish())
    for name in ("decisions", "orders", "fills", "trades", "account_daily"):
        pd.testing.assert_frame_equal(getattr(results[0], name), getattr(results[1], name), check_exact=True)
    assert results[1].fills.iloc[0].fill_time == dates[2] + pd.Timedelta(hours=10, minutes=30)
    assert results[1].account_daily.close.tolist() == [11., 12., 13.]
    assert prices.attrs["evidence"] is bars.attrs["evidence"] is evidence


def test_snapshot_refuses_missing_reference_and_uses_last_available_local_session():
    from strategy_runtime import RuntimeContractError

    dates = pd.to_datetime(["2026-09-14", "2026-09-16"])
    prices = pd.DataFrame({"dt": dates, "open": [10., 20.], "close": [10., 20.]})
    executor = HistoricalExecutor(
        strategy_reference="S999-C0001", symbol="588080.SH", execution_daily=prices,
        execution_intraday=pd.DataFrame(columns=["dt", "high", "low"]),
        evaluation_start=dates[1], evaluation_end=dates[1], initial_cash=20000.,
        execution_policy=ExecutionPolicy("FROZEN_RULE", {"capital": {"fee_rate": 0.}}),
        order_types=("MARKET",),
    )
    generated = datetime(2026, 9, 13, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    with pytest.raises(RuntimeContractError, match="no reference close"):
        executor.snapshot(TradingPoint(dates[0].date(), generated))
    executor.execute(_plan(executor, dates, 1, 1., (PlannedOrder(OrderSide.BUY, 100, OrderType.MARKET, None),), 0.))
    # The snapshot API prices the confirmed ledger at the requested date, never a future close.
    earlier = datetime(2026, 9, 15, 20, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    portfolio, _ = executor.snapshot(TradingPoint(dates[1].date(), earlier))
    assert portfolio.total_assets == Decimal("19000.0")


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
    assert first.exit_date == dates[4] + pd.Timedelta(hours=9, minutes=30)
    assert second.cycle_id != first.cycle_id
    assert second.quantity == 100
    assert second.net_return == pytest.approx(900. * (1 - fee) / (800. * (1 + fee)) - 1)
    assert result.account_daily.quantity.iloc[-1] == 0
    assert result.account_daily.equity.iloc[-1] == pytest.approx(
        20000. + (exit_gross + 900.) * (1 - fee) - (entry_gross + 800.) * (1 + fee)
    )
