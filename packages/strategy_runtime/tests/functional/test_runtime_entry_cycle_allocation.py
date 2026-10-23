"""Signal-owned budgets, immutable cycle plans, and real SRT/TXE replay."""
from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from dataflows import PreparePolicy
from strategy_runtime import (
    CycleTarget, EntryCycleState, EntryCyclePhase, EntryCyclePlanStatus,
    ExecutionPolicy, RuntimeContractError, StrategyInit, StrategyRuntime,
    TradableWindow, implementation_sha256,
)
from strategy_runtime.execution_planner import build_execution_plan
from strategy_runtime.contracts import StrategyIdentity, signal_identity_for
from trading_execution_engine import HistoricalExecutor
from test_public_runtime import _flows


SETTINGS = {
    "capital": {"fee_rate": .001, "mode": "signal_cash_fraction", "target_scope": "entry_cycle"},
    "entry": {"limit_parameter": .01, "order_type": "LIMIT"},
    "exit": {"limit_ratio": .1, "order_type": "MARKET"},
    "instrument": {"lot_size": 100, "maximum_order_quantity": 1000000,
                   "price_limit_ratio": .1, "price_tick": .001},
}


def plan(fraction, *, state=None, cash=Decimal("100000"), quantity=0, price=10.):
    target = CycleTarget(fraction is not None, fraction)
    return build_execution_plan(
        deployment_settings={"cycle_target_quantity": None if state is None else state.target_quantity},
        available_cash=cash, position_quantity=quantity, target_position=float(target.active),
        policy=ExecutionPolicy("FROZEN_RULE", SETTINGS), signal_reference_price=price,
        execution_reference_price=price, cycle_target=target, entry_cycle=state,
        opening_signal_identity="1"*64, account_id="test-cycle",
    )


@pytest.mark.parametrize("fraction", [True, 0, -.01, 1.01, float("nan"), float("inf"), None])
def test_entry_fraction_rejects_invalid_values(fraction):
    with pytest.raises(RuntimeContractError):
        CycleTarget(True, fraction)


def test_cycle_state_roundtrip_and_allocation_identity_are_explicit():
    target = CycleTarget(True, Decimal(".5"))
    assert CycleTarget.from_dict(target.to_dict()) == target
    with pytest.raises(RuntimeContractError):
        CycleTarget(False, Decimal(".5"))
    with pytest.raises(RuntimeContractError):
        CycleTarget.from_dict({"active": True})
    first = plan(Decimal(".5"))
    state = first["entry_cycle_after"]
    assert EntryCycleState.from_dict(state.to_dict()) == state
    with pytest.raises(RuntimeContractError, match="decimal string"):
        CycleTarget.from_dict({"active": True, "entry_fraction": .5})
    with pytest.raises(RuntimeContractError, match="decimal strings"):
        EntryCycleState.from_dict({**state.to_dict(), "cash_budget": 50000})
    with pytest.raises(RuntimeContractError):
        replace(state, target_quantity=True)
    strategy = StrategyIdentity("S900", "S900-C0001", "a"*64, "b"*64, "588080.SH")
    facts = dict(strategy=strategy, signal_date=date(2026, 8, 27), target_position=1.,
                 input_identities={"x": "c"*64}, price_identities={"p": "d"*64})
    assert signal_identity_for(**facts, cycle_target=target) != signal_identity_for(
        **facts, cycle_target=CycleTarget(True, Decimal(1)))


def test_retries_lock_quantity_budget_and_do_not_reapply_allocation():
    first = plan(Decimal(".5"))
    state = first["entry_cycle_after"]
    assert state.cash_budget == 50000 and state.target_quantity == 4900
    assert first["cycle_status"] is EntryCyclePlanStatus.OPEN
    # Unfilled first order: new signal requests full size, but the original .5 lock wins.
    retry = plan(Decimal(1), state=state, price=20.)
    assert retry["entry_cycle_after"] == state
    assert retry["target_quantity"] == 2400
    assert retry["capital_rule"]["allocation_fraction"] == "0.5"
    # Partial fill consumes actual gross plus fee; no second multiplication by .5.
    partial = replace(state, buy_cost_including_fees=Decimal("20020"))
    retry = plan(Decimal(".75"), state=partial, quantity=2000, cash=Decimal("79980"))
    assert retry["target_quantity"] == 4900
    assert sum(o["quantity"] for o in retry["orders"]) == 2900
    capped = replace(partial, buy_cost_including_fees=Decimal("49999"))
    blocked = plan(Decimal(1), state=capped, quantity=2000)
    assert blocked["orders"] == [] and blocked["cycle_status"] is EntryCyclePlanStatus.BUDGET_LIMIT
    filled = replace(state, buy_cost_including_fees=Decimal("49049"))
    hold = plan(Decimal(1), state=filled, quantity=4900, price=20.)
    assert hold["orders"] == [] and hold["entry_cycle_after"] == filled


def test_exit_is_sticky_until_account_settlement_and_small_budget_does_not_open_cycle():
    state = plan(Decimal(".5"))["entry_cycle_after"]
    exit_plan = plan(None, state=state, quantity=4900)
    exiting = exit_plan["entry_cycle_after"]
    assert exiting.phase is EntryCyclePhase.EXITING
    assert plan(Decimal(1), state=exiting, quantity=4900)["action"] == "SELL"
    assert plan(None, state=exiting)["entry_cycle_after"] == exiting
    empty = plan(Decimal(".5"), cash=Decimal(100))
    assert empty["entry_cycle_after"] is None and empty["orders"] == []
    assert empty["cycle_status"] is EntryCyclePlanStatus.INSUFFICIENT_LOT
    assert plan(None)["cycle_status"] is EntryCyclePlanStatus.IDLE
    with pytest.raises(RuntimeContractError, match="flat account"):
        plan(Decimal(".5"), quantity=100)


@pytest.mark.parametrize("change", [{"allocation_fraction": .5}, {"target_scope": "decision"}])
def test_signal_allocation_policy_rejects_ambiguous_size_source(change):
    settings = deepcopy(SETTINGS)
    settings["capital"].update(change)
    with pytest.raises(RuntimeContractError, match="signal-owned"):
        ExecutionPolicy("FROZEN_RULE", settings)


@pytest.mark.parametrize("miss_first", [False, True])
def test_real_runtime_replays_two_distinct_allocations_without_daily_rebalancing(
    tmp_path, runtime_candidate, miss_first,
):
    path = runtime_candidate.source_root / "strategies/current_fixture.py"
    source = path.read_text(encoding="utf-8").replace(
        '"mode": "full_available_cash",', '"mode": "signal_cash_fraction",'
    ).replace('"TARGET_POSITION"', '"CYCLE_TARGET"').replace(
        'target = (values > threshold).astype(float)',
        'target = (values > 0).astype(float)')
    source = source.replace('"target_position": target,',
                            '"target_position": target, "entry_allocation_fraction": values.where(values > 0),')
    path.write_text(source, encoding="utf-8")
    descriptor = dict(runtime_candidate.payload["runtime"])
    descriptor["source_sha256"] = implementation_sha256(tuple(descriptor["source_files"]), source_root=runtime_candidate.source_root)
    candidate = replace(runtime_candidate, payload={**runtime_candidate.payload, "runtime": descriptor})
    dates = pd.bdate_range("2026-08-27", periods=6)
    strategy = StrategyRuntime(dataflows=_flows(tmp_path, flow_value=[.5, 1., .25, 0., 1.])).create(
        StrategyInit(candidate, TradableWindow(dates[1].date(), dates[-1].date()), tmp_path/"context"))
    strategy.prepare_data(policy=PreparePolicy.REUSE)
    prices = pd.DataFrame({"dt": dates, "open": 9.4, "close": 9.4})
    if miss_first:
        prices.loc[1, "open"] = 10.
    executor = HistoricalExecutor(
        strategy_reference=candidate.reference_id, symbol="588080.SH", execution_daily=prices,
        execution_intraday=pd.DataFrame(columns=["dt", "high", "low"]),
        evaluation_start=dates[1], evaluation_end=dates[-1], initial_cash=100000.,
        execution_policy=ExecutionPolicy("FROZEN_RULE", SETTINGS), order_types=("LIMIT", "MARKET"),
    )
    result = strategy.run_window(executor=executor)
    assert result.fills.side.tolist() == ["BUY", "SELL", "BUY"]
    first, _, second = list(result.fills.itertuples())
    assert first.quantity * first.price + first.fees <= 50000
    assert second.quantity > first.quantity
    assert result.fills.cycle_id.nunique() == 2
    assert result.orders.status.tolist().count("UNFILLED") == int(miss_first)


@pytest.mark.parametrize("change_mode", [False, True])
def test_runtime_rejects_mismatched_cycle_decision_and_capital_mode(tmp_path, runtime_candidate, change_mode):
    path = runtime_candidate.source_root / "strategies/current_fixture.py"
    source = path.read_text(encoding="utf-8")
    if change_mode:
        source = source.replace('"mode": "full_available_cash",', '"mode": "signal_cash_fraction",')
    else:
        source = source.replace('"TARGET_POSITION"', '"CYCLE_TARGET"')
    path.write_text(source, encoding="utf-8")
    descriptor = dict(runtime_candidate.payload["runtime"])
    descriptor["source_sha256"] = implementation_sha256(tuple(descriptor["source_files"]), source_root=runtime_candidate.source_root)
    candidate = replace(runtime_candidate, payload={**runtime_candidate.payload, "runtime": descriptor})
    with pytest.raises(RuntimeContractError, match="declared together"):
        StrategyRuntime(dataflows=_flows(tmp_path)).create(StrategyInit(
            candidate, TradableWindow(date(2026, 8, 28), date(2026, 9, 3)), tmp_path/"context"))
