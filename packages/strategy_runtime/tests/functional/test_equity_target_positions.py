"""Equity-weight sizing and real SRT/TXE feedback across changing position levels."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal

import pandas as pd
import pytest

from dataflows import PreparePolicy
from strategy_runtime import (ExecutionPolicy, RuntimeContractError, StrategyInit,
                              StrategyRuntime, TradableWindow, implementation_sha256)
from strategy_runtime.execution_planner import build_execution_plan
from trading_execution_engine import HistoricalExecutor
from test_public_runtime import _flows


SETTINGS = {
    "capital": {"fee_rate": .001, "mode": "target_equity_fraction",
                "target_scope": "decision", "allocation_fraction": 1.0},
    "entry": {"limit_parameter": .01, "order_type": "LIMIT"},
    "exit": {"limit_ratio": .1, "order_type": "MARKET"},
    "instrument": {"lot_size": 100, "maximum_order_quantity": 1000,
                   "price_limit_ratio": .1, "price_tick": .001},
}


def plan(target, cash=10000., actual=1000, *, settings=None, scale=1., reference=10.):
    return build_execution_plan(
        deployment_settings={"cycle_target_quantity": 99900},
        available_cash=cash, position_quantity=actual, target_position=target,
        policy=ExecutionPolicy("FROZEN_RULE", settings or SETTINGS),
        signal_reference_price=reference*scale, execution_reference_price=reference*scale,
        unadjusted_reference_price=reference if scale != 1 else None, price_scale=scale,
    )


@pytest.mark.parametrize("target,quantity,side", [
    (0., 0, "SELL"), (.25, 500, "SELL"), (.5, 1000, None),
    (.75, 1500, "BUY"), (1., 1900, "BUY"),
])
def test_equity_weights_size_actual_portfolio_and_respect_fee_cash_cap(target, quantity, side):
    result = plan(target)
    assert result["target_position"] == target
    assert result["target_quantity"] == quantity
    assert result["delta_quantity"] == quantity - 1000
    assert [o["side"] for o in result["orders"]] == ([] if side is None else [side])
    assert result["capital_rule"]["target_scope"] == "decision"
    assert result["unallocated_cash"] >= 0
    if side == "BUY":
        assert result["orders"][0]["limit_price"] == 10.1
    elif side == "SELL":
        assert result["orders"][0]["order_type"] == "MARKET"


def test_equity_weights_split_orders_round_lots_and_use_scaled_account_prices():
    result = plan(.75, cash=60000., actual=0)
    assert result["target_quantity"] == 4500
    assert [o["quantity"] for o in result["orders"]] == [1000, 1000, 1000, 1000, 500]
    scaled = plan(.25, cash=20000., actual=1000, scale=2.)
    assert scaled["target_quantity"] == 500
    assert scaled["orders"][0]["limit_price"] == 20.
    assert plan(.5, cash=100., actual=0)["orders"] == []


def test_unchanged_equity_weight_rebalances_price_drift_using_actual_holdings():
    assert plan(.5)["orders"] == []  # 10000 cash + 1000 units at 10: already 50%.
    risen = plan(.5, reference=20.)
    fallen = plan(.5, reference=5.)
    assert (risen["action"], risen["target_quantity"]) == ("SELL", 700)
    assert (fallen["action"], fallen["target_quantity"]) == ("BUY", 1500)


@pytest.mark.parametrize("target", [-.01, 1.01, float("nan"), float("inf"), True, None, "0.5"])
def test_equity_weights_reject_invalid_targets(target):
    with pytest.raises(RuntimeContractError, match="finite and in"):
        plan(target)


@pytest.mark.parametrize("field,value", [
    ("target_scope", "entry_cycle"), ("allocation_fraction", .5), ("allocation_fraction", True),
])
def test_equity_weight_policy_rejects_ambiguous_capital_contract(field, value):
    settings = deepcopy(SETTINGS)
    settings["capital"][field] = value
    with pytest.raises(RuntimeContractError, match="decision scope and allocation fraction one"):
        ExecutionPolicy("FROZEN_RULE", settings)


@pytest.mark.parametrize("first_order_misses", [False, True])
@pytest.mark.parametrize("exit_target", [0., .00001])
def test_real_runtime_and_account_keep_fractional_targets_and_one_cycle_until_flat(
    tmp_path, runtime_candidate, first_order_misses, exit_target,
):
    path = runtime_candidate.source_root / "strategies/current_fixture.py"
    source = path.read_text(encoding="utf-8").replace(
        '"mode": "full_available_cash",',
        '"mode": "target_equity_fraction", "allocation_fraction": 1.0,',
    ).replace('"target_scope": "entry_cycle"', '"target_scope": "decision"').replace(
        'target = (values > threshold).astype(float)', 'target = values.astype(float)')
    path.write_text(source, encoding="utf-8")
    descriptor = dict(runtime_candidate.payload["runtime"])
    descriptor["source_sha256"] = implementation_sha256(
        tuple(descriptor["source_files"]), source_root=runtime_candidate.source_root)
    candidate = replace(runtime_candidate, payload={**runtime_candidate.payload, "runtime": descriptor})
    dates = pd.bdate_range("2026-08-27", periods=6)
    strategy = StrategyRuntime(dataflows=_flows(tmp_path, flow_value=[.5, 1., .25, exit_target, .5])).create(
        StrategyInit(candidate, TradableWindow(dates[1].date(), dates[-1].date()), tmp_path/"context"))
    strategy.prepare_data(policy=PreparePolicy.REUSE)
    prices = pd.DataFrame({"dt": dates, "open": 9.4, "close": 9.4})
    if first_order_misses:
        prices.loc[1, "open"] = 10.  # Above the buy limit, with no intraday touch.
    executor = HistoricalExecutor(
        strategy_reference=candidate.reference_id, symbol="588080.SH", execution_daily=prices,
        execution_intraday=pd.DataFrame(columns=["dt", "high", "low"]),
        evaluation_start=dates[1], evaluation_end=dates[-1], initial_cash=100000.,
        execution_policy=ExecutionPolicy("FROZEN_RULE", SETTINGS), order_types=("LIMIT", "MARKET"),
    )
    result = strategy.run_window(executor=executor)
    assert result.account_daily.target_position.tolist() == [.5, 1., .25, exit_target, .5]
    assert result.fills.side.tolist() == (["BUY"] if not first_order_misses else []) + ["BUY", "SELL", "SELL", "BUY"]
    assert result.orders.status.tolist().count("UNFILLED") == int(first_order_misses)
    if first_order_misses:
        assert result.account_daily.quantity.iloc[0] == 0
        assert result.account_daily.cash.iloc[0] == 100000.
    assert result.trades.status.tolist() == ["CLOSED", "OPEN"]
    assert result.fills.cycle_id.iloc[:-1].nunique() == 1
    assert result.fills.cycle_id.iloc[-1] != result.fills.cycle_id.iloc[0]
    expected_cash = Decimal("100000")
    for row in result.fills.itertuples():
        gross = Decimal(str(row.price))*row.quantity
        expected_cash += (-gross if row.side == "BUY" else gross) - Decimal(str(row.fees))
    assert result.account_daily.cash.iloc[-1] == pytest.approx(float(expected_cash))
    closed = result.trades.iloc[0]
    assert closed.quantity == result.fills.iloc[:-1].query("side == 'BUY'").quantity.sum()
    assert closed.net_return == pytest.approx((1-.001)/(1+.001)-1)
