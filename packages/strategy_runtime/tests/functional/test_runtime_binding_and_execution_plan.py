from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from dataflows import PreparePolicy

from strategy_runtime import (
    ExecutionPolicy,
    ExecutionState,
    PortfolioSnapshot,
    RuntimeContractError,
    StrategyInit,
    StrategyRelease,
    StrategyRuntime,
    TradableWindow,
    TradingPoint,
    implementation_sha256,
)
from strategy_runtime.execution_planner import build_execution_plan
from test_public_runtime import _flows


ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("schema", [None, True, "5", 1, 6])
def test_release_only_accepts_current_serialized_contract(schema):
    with pytest.raises(RuntimeContractError, match="unsupported strategy release schema"):
        StrategyRelease.from_mapping({"schema_version": schema})


@pytest.mark.parametrize("policy_type", ["FROZEN_RULE", "INTRADAY_OVERLAY"])
@pytest.mark.parametrize("target", [0.0, 1.0])
def test_held_position_does_not_restart_account_cycle(policy_type, target):
    settings = {
        "capital": {"allocation_fraction": 1.0, "fee_rate": .001,
                    "mode": "full_available_cash", "target_scope": "entry_cycle"},
        "entry": {"limit_parameter": .2, "order_type": "LIMIT"},
        "exit": {"limit_ratio": .2, "order_type": "LIMIT"},
        "instrument": {"lot_size": 100, "maximum_order_quantity": 1000000,
                       "price_limit_ratio": .2, "price_tick": .001},
    } if policy_type == "FROZEN_RULE" else {
        "lot_size": 100, "one_way_cost": .001, "core_fraction": .5, "event_fraction": .5,
    }
    plan = build_execution_plan(
        deployment_settings={"cycle_target_quantity": 5900}, available_cash=50000,
        position_quantity=5900, target_position=target,
        policy=ExecutionPolicy(policy_type, settings),
        signal_reference_price=5.0, execution_reference_price=5.0,
    )
    assert plan["actual_quantity"] == 5900
    if policy_type == "INTRADAY_OVERLAY":
        assert plan["cycle_target_quantity"] == plan["target_quantity"] == 5900
        assert plan["action"] == ("ROTATE" if target else "HOLD")
        assert plan["plan_mode"] != "CORE_SETUP"
        assert [x["order"]["side"] for x in plan["plan_legs"]] == (["BUY", "SELL"] if target else [])
    else:
        assert plan["action"] == ("HOLD" if target else "SELL")
        assert plan["target_quantity"] == (5900 if target else 0)


def test_target_execution_plan_honors_frozen_limit_exit() -> None:
    policy = ExecutionPolicy(
        "FROZEN_RULE",
        {
            "capital": {
                "allocation_fraction": 1.0,
                "fee_rate": 0.001,
                "mode": "full_available_cash",
                "target_scope": "entry_cycle",
            },
            "entry": {"limit_parameter": 0.2, "order_type": "LIMIT"},
            "exit": {"limit_ratio": 0.2, "order_type": "LIMIT"},
            "instrument": {
                "lot_size": 100,
                "maximum_order_quantity": 1000000,
                "price_limit_ratio": 0.2,
                "price_tick": 0.001,
            },
        },
    )

    plan = build_execution_plan(
        deployment_settings={"cycle_target_quantity": 1000},
        available_cash=100.0,
        position_quantity=1000,
        target_position=0.0,
        policy=policy,
        signal_reference_price=1.6,
        execution_reference_price=1.5,
    )

    assert plan["action"] == "SELL"
    assert plan["orders"][0]["order_type"] == "LIMIT"
    assert plan["orders"][0]["limit_price"] < 1.5


def test_frozen_rule_rejects_fractional_target_positions() -> None:
    policy = ExecutionPolicy(
        "FROZEN_RULE",
        {
            "capital": {
                "allocation_fraction": 1.0,
                "fee_rate": 0.001,
                "mode": "full_available_cash",
                "target_scope": "entry_cycle",
            },
            "entry": {"limit_parameter": 0.2, "order_type": "LIMIT"},
            "exit": {"limit_ratio": 0.2, "order_type": "LIMIT"},
            "instrument": {
                "lot_size": 100,
                "maximum_order_quantity": 1000000,
                "price_limit_ratio": 0.2,
                "price_tick": 0.001,
            },
        },
    )

    with pytest.raises(RuntimeContractError, match="binary target position"):
        build_execution_plan(
            deployment_settings={},
            available_cash=10000.0,
            position_quantity=0,
            target_position=0.5,
            policy=policy,
            signal_reference_price=1.5,
            execution_reference_price=1.5,
        )


def test_intraday_overlay_capital_terms_are_explicit_for_each_plan_mode(
    tmp_path, runtime_candidate,
) -> None:
    # The synthetic strategy owns the overlay policy. Exercise its published
    # plans, including the capital terms and identity, through the real loader.
    path = runtime_candidate.source_root / "strategies/current_fixture.py"
    source = path.read_text(encoding="utf-8")
    start, end = source.index("            execution=ExecutionPolicy("), source.index("            monitoring=")
    source = source[:start] + '''            execution=ExecutionPolicy("INTRADAY_OVERLAY", {
                "lot_size": 100, "one_way_cost": .001,
                "core_fraction": .5, "event_fraction": .5,
            }),
''' + source[end:]
    path.write_text(source, encoding="utf-8")
    descriptor = dict(runtime_candidate.payload["runtime"])
    descriptor["source_sha256"] = implementation_sha256(
        tuple(descriptor["source_files"]), source_root=runtime_candidate.source_root)
    candidate = replace(runtime_candidate, payload={**runtime_candidate.payload, "runtime": descriptor})
    strategy = StrategyRuntime(dataflows=_flows(tmp_path, flow_value=[.8, .8, .8, .8, .1])).create(
        StrategyInit(candidate, TradableWindow(date(2026, 9, 2), date(2026, 9, 3)), tmp_path / "context"))
    strategy.prepare_data(policy=PreparePolicy.REUSE)

    def plan(trading_date, signal_date, quantity, cycle_quantity):
        now = datetime.combine(signal_date, datetime.min.time().replace(hour=20),
                               tzinfo=ZoneInfo("Asia/Shanghai"))
        return strategy.plan_at(
            point=TradingPoint(trading_date, now),
            portfolio=PortfolioSnapshot("overlay", "588080.SH", Decimal("50000"),
                                        Decimal("100000"), quantity, 1, now),
            state=ExecutionState(1, now, cycle_quantity))

    setup = plan(date(2026, 9, 2), date(2026, 9, 1), 0, None)
    assert (setup.plan_mode, setup.capital_mode, setup.allocation_fraction) == (
        "CORE_SETUP", "available_cash_fraction", Decimal(".5"))
    rotation = plan(date(2026, 9, 2), date(2026, 9, 1), setup.target_quantity, setup.cycle_target_quantity)
    assert (rotation.plan_mode, rotation.capital_mode, rotation.allocation_fraction) == (
        "CORE_EVENT_INTRADAY_ROTATION", "full_available_cash", Decimal(1))
    hold = plan(date(2026, 9, 3), date(2026, 9, 2), setup.target_quantity, setup.cycle_target_quantity)
    assert (hold.plan_mode, hold.capital_mode, hold.allocation_fraction) == (
        "NONE", "full_available_cash", Decimal(1))
    assert len({setup.plan_identity, rotation.plan_identity, hold.plan_identity}) == 3


def test_target_execution_plan_preserves_audited_marketable_exit_semantics() -> None:
    policy = ExecutionPolicy(
        "FROZEN_RULE",
        {
            "capital": {
                "allocation_fraction": 1.0,
                "fee_rate": 0.001,
                "mode": "full_available_cash",
                "target_scope": "entry_cycle",
            },
            "entry": {"limit_parameter": 0.2, "order_type": "LIMIT"},
            "exit": {"limit_ratio": 0.2, "order_type": "LIMIT"},
            "instrument": {
                "lot_size": 100,
                "maximum_order_quantity": 1000000,
                "price_limit_ratio": 0.2,
                "price_tick": 0.001,
            },
            "virtual_fill": {"sell": "marketable_limit_at_open"},
        },
    )

    plan = build_execution_plan(
        deployment_settings={"cycle_target_quantity": 1000},
        available_cash=100.0,
        position_quantity=1000,
        target_position=0.0,
        policy=policy,
        signal_reference_price=1.5,
        execution_reference_price=1.5,
    )

    assert plan["action"] == "SELL"
    assert plan["orders"][0]["order_type"] == "MARKET"
    assert plan["orders"][0]["limit_price"] == 1.5
