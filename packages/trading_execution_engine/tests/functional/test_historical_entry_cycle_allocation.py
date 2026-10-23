"""Real SRT sizing and TXE accounting for signal-owned entry-cycle budgets."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, time
from decimal import Decimal
import json
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from strategy_runtime import (
    CycleTarget, EntryCyclePhase, EntryCyclePlanStatus, ExecutionPlan, ExecutionPolicy, OrderSide,
    OrderType, PlannedOrder, PriceReference, RuntimeContractError, StrategyIdentity, TradingPoint,
)
from strategy_runtime.contracts import plan_identity_for, signal_identity_for
from strategy_runtime.execution_planner import build_execution_plan
from trading_execution_engine import HistoricalExecutor


SETTINGS = {
    "capital": {"fee_rate": .001, "mode": "signal_cash_fraction", "target_scope": "entry_cycle"},
    "entry": {"limit_parameter": .01, "order_type": "LIMIT"},
    "exit": {"limit_ratio": .1, "order_type": "MARKET"},
    "instrument": {"lot_size": 100, "maximum_order_quantity": 1000,
                   "price_limit_ratio": .1, "price_tick": .001},
}
IDENTITY = StrategyIdentity("S999", "S999-C0001", "a" * 64, "b" * 64, "588080.SH")


def _account(prices, cash=100000., settings=None, account_id="backtest-account"):
    policy = ExecutionPolicy("FROZEN_RULE", SETTINGS if settings is None else settings)
    executor = HistoricalExecutor(
        strategy_reference=IDENTITY.reference_id, symbol=IDENTITY.symbol,
        execution_daily=prices, execution_intraday=pd.DataFrame(columns=["dt", "high", "low"]),
        evaluation_start=prices.dt.iloc[1], evaluation_end=prices.dt.iloc[-1], initial_cash=cash,
        execution_policy=policy, order_types=("MARKET", "LIMIT"),
        account_id=account_id,
    )
    return executor, policy


def _plan(executor, policy, prices, day, fraction):
    signal = prices.dt.iloc[day - 1].date()
    trading = prices.dt.iloc[day].date()
    generated = datetime.combine(signal, time(17, 30), ZoneInfo("Asia/Shanghai"))
    portfolio, state = executor.snapshot(TradingPoint(trading, generated))
    target = CycleTarget(fraction is not None, None if fraction is None else Decimal(str(fraction)))
    inputs = {"price": "c" * 64}
    signal_id = signal_identity_for(
        strategy=IDENTITY, signal_date=signal, target_position=float(target.active),
        input_identities=inputs, price_identities=inputs, cycle_target=target,
    )
    reference = float(prices.close.iloc[day - 1])
    raw = build_execution_plan(
        deployment_settings={"cycle_target_quantity": state.cycle_target_quantity},
        available_cash=float(portfolio.available_cash), position_quantity=portfolio.position_quantity,
        target_position=float(target.active), policy=policy,
        signal_reference_price=reference, execution_reference_price=reference,
        cycle_target=target, entry_cycle=state.entry_cycle,
        opening_signal_identity=signal_id, account_id=portfolio.account_id,
    )
    orders = tuple(PlannedOrder(
        OrderSide(order["side"]), order["quantity"], OrderType(order["order_type"]),
        None if order["order_type"] == "MARKET" else Decimal(str(order["limit_price"])),
    ) for order in raw["orders"])
    allocation = Decimal(str(raw["capital_rule"]["allocation_fraction"]))
    values = dict(
        signal_identity=signal_id, actual_quantity=portfolio.position_quantity,
        target_quantity=raw["target_quantity"], cycle_target_quantity=raw["cycle_target_quantity"],
        plan_mode=raw.get("plan_mode", "NONE"), capital_mode="signal_cash_fraction",
        allocation_fraction=allocation, orders=orders, legs=(),
        **{key: raw[key] for key in ("cycle_target", "entry_cycle_before", "entry_cycle_after", "cycle_status")},
    )
    plan = ExecutionPlan(
        strategy=IDENTITY, plan_identity=plan_identity_for(
            **values, available_cash=portfolio.available_cash, fee_rate=Decimal(str(raw["fee_rate"]))),
        symbol=IDENTITY.symbol,
        signal_date=signal, trading_date=trading, generated_at=generated,
        expected_portfolio_revision=portfolio.revision, expected_state_revision=state.revision,
        target_position=float(target.active), action=raw["action"],
        available_cash=portfolio.available_cash, fee_rate=Decimal(str(raw["fee_rate"])),
        estimated_order_cost=Decimal(str(raw["estimated_order_cost"])),
        unallocated_cash=Decimal(str(raw["unallocated_cash"])),
        references=PriceReference(Decimal(str(reference)), Decimal(str(reference)), "ADJUSTED_CLOSE", "UNADJUSTED_CLOSE"),
        required_capabilities=executor.capabilities, input_identities=inputs, price_identities=inputs,
        **values,
    )
    assert executor.snapshot(TradingPoint(trading, generated)) == (portfolio, state)
    return plan


def test_cycle_allocation_locks_budget_across_retry_topup_and_next_cycle():
    prices = pd.DataFrame({
        "dt": pd.bdate_range("2026-09-14", periods=8),
        "open": [10., 11., 10.4, 5., 20., 20., 20., 20.],
        "close": [10., 10.4, 5., 20., 20., 20., 20., 20.],
    })
    executor, policy = _account(prices)
    outcomes, plans = [], []
    for day, fraction in enumerate((.5, 1., .25, 1., None, 1., None), 1):
        plan = _plan(executor, policy, prices, day, fraction)
        outcome = executor.execute(plan)
        assert executor.execute(plan) is outcome
        outcomes.append(outcome)
        plans.append(plan)
    first = outcomes[0].state.entry_cycle
    assert first.cash_budget == Decimal("50000")
    assert first.target_quantity == 4900
    assert first.buy_cost_including_fees == 0
    assert outcomes[0].portfolio.position_quantity == 0  # Limit miss retains adopted cycle.
    assert outcomes[1].portfolio.position_quantity == 4700
    assert outcomes[1].state.entry_cycle.buy_cost_including_fees == Decimal("48928.88")
    assert outcomes[2].portfolio.position_quantity == 4900
    assert outcomes[2].state.entry_cycle.buy_cost_including_fees == Decimal("49929.88")
    assert plans[3].orders == ()  # Price and current fraction do not rebalance.
    assert outcomes[4].state.entry_cycle is None
    assert outcomes[4].state.cycle_target_quantity is None
    second = outcomes[5].state.entry_cycle
    assert second.allocation_fraction == 1
    assert second.cash_budget == outcomes[4].portfolio.available_cash
    assert second.cycle_id != first.cycle_id
    assert outcomes[-1].state.entry_cycle is None
    result = executor.finish()
    assert result.trades.status.tolist() == ["CLOSED", "CLOSED"]
    assert result.trades.cycle_id.tolist() == [first.cycle_id, second.cycle_id]
    assert result.orders.status.tolist().count("UNFILLED") == 5
    assert Decimal(json.loads(result.account_daily.entry_cycle.iloc[2])["buy_cost_including_fees"]) == Decimal("49929.88")
    assert result.account_daily.entry_cycle.iloc[4] == "null"
    assert json.loads(result.decisions.cycle_target.iloc[1])["entry_fraction"] == "1.0"
    assert result.decisions.cycle_allocation_fraction.iloc[1] == "0.5"
    for cycle in (first, second):
        bought = result.fills.query("cycle_id == @cycle.cycle_id and side == 'BUY'")
        cost = (bought.price * bought.quantity + bought.fees).sum()
        assert cost <= float(cycle.cash_budget)


def test_too_small_allocation_is_explicit_and_does_not_create_cycle():
    prices = pd.DataFrame({"dt": pd.bdate_range("2026-09-14", periods=2), "open": 10., "close": 10.})
    executor, policy = _account(prices, cash=1000.)
    plan = _plan(executor, policy, prices, 1, .001)
    assert plan.cycle_status is EntryCyclePlanStatus.INSUFFICIENT_LOT
    assert plan.entry_cycle_after is None
    result = executor.execute(plan)
    assert result.state.entry_cycle is None
    assert result.portfolio.available_cash == 1000
    assert executor.finish().orders.empty


def test_budget_exhaustion_and_failed_exit_keep_cycle_until_confirmed_flat():
    prices = pd.DataFrame({
        "dt": pd.bdate_range("2026-09-14", periods=6),
        "open": [10., 12., 11., 11., 8., 11.],
        "close": [10., 11., 20., 11., 11., 11.],
    })
    settings = deepcopy(SETTINGS)
    settings["exit"]["order_type"] = "LIMIT"
    executor, policy = _account(prices, settings=settings)
    outcomes, plans = [], []
    for day, fraction in enumerate((.5, .75, 1., None, 1.), 1):
        plan = _plan(executor, policy, prices, day, fraction)
        plans.append(plan)
        outcomes.append(executor.execute(plan))
    assert outcomes[1].portfolio.position_quantity == 4400
    assert plans[2].cycle_status is EntryCyclePlanStatus.BUDGET_LIMIT
    assert plans[2].orders == ()
    assert outcomes[2].state.entry_cycle.remaining_budget == Decimal("1551.6")
    assert outcomes[3].portfolio.position_quantity == 4400
    assert outcomes[3].state.entry_cycle.phase is EntryCyclePhase.EXITING
    assert outcomes[3].state.entry_cycle.buy_cost_including_fees == Decimal("48448.4")
    assert plans[4].cycle_target.active  # A new active signal cannot cancel an adopted exit.
    assert plans[4].cycle_status is EntryCyclePlanStatus.EXIT
    assert {order.side for order in plans[4].orders} == {OrderSide.SELL}
    assert outcomes[4].portfolio.position_quantity == 0
    assert outcomes[4].state.entry_cycle is None
    result = executor.finish()
    assert len(result.trades) == 1
    assert result.orders.query("side == 'SELL'").status.tolist() == ["UNFILLED"] * 5 + ["FILLED"] * 5


def test_account_rejects_changed_cycle_facts_before_any_mutation():
    prices = pd.DataFrame({"dt": pd.bdate_range("2026-09-14", periods=3), "open": 10., "close": 10.})
    executor, policy = _account(prices)
    executor.execute(_plan(executor, policy, prices, 1, .5))
    plan = _plan(executor, policy, prices, 2, 1.)
    forged_before = replace(plan.entry_cycle_before, buy_cost_including_fees=Decimal("1"))
    identity = plan_identity_for(**{
        key: (forged_before if key in ("entry_cycle_before", "entry_cycle_after") else getattr(plan, key))
        for key in ("signal_identity", "actual_quantity", "target_quantity", "cycle_target_quantity",
                    "plan_mode", "capital_mode", "allocation_fraction", "orders", "legs", "cycle_target",
                    "entry_cycle_before", "entry_cycle_after", "cycle_status", "available_cash", "fee_rate")
    })
    point = TradingPoint(plan.trading_date, plan.generated_at)
    before = executor.snapshot(point)
    with pytest.raises(RuntimeContractError, match="cycle"):
        executor.execute(replace(plan, entry_cycle_before=forged_before, entry_cycle_after=forged_before, plan_identity=identity))
    assert executor.snapshot(point) == before
    executor.execute(plan)


def test_dynamic_plan_cannot_be_executed_by_fixed_capital_account():
    prices = pd.DataFrame({"dt": pd.bdate_range("2026-09-14", periods=2), "open": 10., "close": 10.})
    source, policy = _account(prices)
    fixed = deepcopy(SETTINGS)
    fixed["capital"].update(mode="full_available_cash", allocation_fraction=1.)
    executor, _ = _account(prices, settings=fixed)
    with pytest.raises(RuntimeContractError, match="capital mode"):
        executor.execute(_plan(source, policy, prices, 1, .5))


def test_cycle_identity_binds_plan_to_account_even_with_equal_cash_and_revision():
    prices = pd.DataFrame({"dt": pd.bdate_range("2026-09-14", periods=2), "open": 10., "close": 10.})
    source, policy = _account(prices)
    other, _ = _account(prices, account_id="independent-account")
    plan = _plan(source, policy, prices, 1, .5)
    point = TradingPoint(plan.trading_date, plan.generated_at)
    before = other.snapshot(point)
    with pytest.raises(RuntimeContractError, match="another account"):
        other.execute(plan)
    assert other.snapshot(point) == before


@pytest.mark.parametrize("forgery", ["active_sell", "unrequested_exit"])
def test_resigned_cycle_plan_cannot_sell_or_exit_without_signal(forgery):
    prices = pd.DataFrame({"dt": pd.bdate_range("2026-09-14", periods=3), "open": 10., "close": 10.})
    executor, policy = _account(prices)
    executor.execute(_plan(executor, policy, prices, 1, .5))
    valid = _plan(executor, policy, prices, 2, 1.)
    changes = {
        "target_quantity": 0,
        "orders": (PlannedOrder(OrderSide.SELL, valid.actual_quantity, OrderType.MARKET, None),),
    }
    if forgery == "unrequested_exit":
        changes.update(
            entry_cycle_after=replace(valid.entry_cycle_after, phase=EntryCyclePhase.EXITING),
            cycle_status=EntryCyclePlanStatus.EXIT,
        )
    keys = ("signal_identity", "actual_quantity", "target_quantity", "cycle_target_quantity",
            "plan_mode", "capital_mode", "allocation_fraction", "orders", "legs", "cycle_target",
            "entry_cycle_before", "entry_cycle_after", "cycle_status", "available_cash", "fee_rate")
    identity = plan_identity_for(**{key: changes.get(key, getattr(valid, key)) for key in keys})
    point = TradingPoint(valid.trading_date, valid.generated_at)
    before = executor.snapshot(point)
    with pytest.raises(RuntimeContractError, match="cycle|active|exit"):
        executor.execute(replace(valid, plan_identity=identity, action="SELL", **changes))
    assert executor.snapshot(point) == before
    executor.execute(valid)
