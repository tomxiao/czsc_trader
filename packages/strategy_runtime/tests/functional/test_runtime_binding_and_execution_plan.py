from __future__ import annotations

import json
import inspect
from decimal import Decimal
from pathlib import Path
import sys

import pytest

from strategy_runtime import (
    ExecutionPolicy,
    RuntimeCompatibilityError,
    RuntimeContractError,
    StrategyRelease,
    StrategyRuntime,
    canonical_sha256,
)
from strategy_runtime.loader import StrategyLoader
from strategy_runtime.execution_planner import build_execution_plan
from strategy_runtime.strategy import _capital_terms


ROOT = Path(__file__).resolve().parents[4]


def test_schema_v2_release_hash_covers_executable_identity_not_governance() -> None:
    from strategy_runtime import StrategyRelease, canonical_sha256

    executable = {
        "schema_version": 2,
        "strategy_id": "S008",
        "version": "v1",
        "release_id": "S008-v1",
        "strategy_payload": {"symbol": "588080.SH", "runtime": "example"},
    }
    payload = {
        **executable,
        "parent_version": None,
        "change_summary": "首个冻结版本",
        "source_experiment": "experiments/S008/EX01",
        "source_candidate": "C001",
        "selection_data_cutoff": "2026-09-02",
        "forward_start": "2026-09-03",
        "governance": {"review_id": "FR-S008-C001-001"},
        "governance_hash": "0" * 64,
        "release_hash": canonical_sha256(executable),
    }
    release = StrategyRelease.from_mapping(payload)
    assert release.release_hash == payload["release_hash"]

    changed = dict(payload)
    changed["change_summary"] = "只改变治理说明"
    assert StrategyRelease.from_mapping(changed).release_hash == release.release_hash


def test_schema_v3_release_hash_accepts_sgc_governance_projection() -> None:
    from strategy_runtime import StrategyRelease, canonical_sha256

    executable = {
        "schema_version": 3,
        "strategy_id": "S008",
        "version": "v1",
        "release_id": "S008-v1",
        "strategy_payload": {"symbol": "588080.SH", "runtime": "example"},
    }
    payload = {
        **executable,
        "governance": {
            "credential_id": "SGC-S008-001",
            "approval_seal_hash": "a" * 64,
        },
        "release_hash": canonical_sha256(executable),
    }
    release = StrategyRelease.from_mapping(payload)
    assert release.release_hash == payload["release_hash"]


def test_every_active_frozen_release_has_a_matching_source_binding() -> None:
    root = Path(__file__).resolve().parents[4]
    for strategy_id, version in (
        ("S001", "v1"),
        ("S001", "v2"),
        ("S002", "v1"),
        ("S003", "v1"),
        ("S007", "v1"),
    ):
        payload = json.loads(
            (root / "strategies" / strategy_id / "versions" / f"{version}.json").read_text(
                encoding="utf-8"
            )
        )
        strategy = StrategyLoader(ROOT / "strategies").load(
            StrategyRelease.from_mapping(payload)
        )
        assert strategy.definition.release_id == f"{strategy_id}-{version}"
        assert strategy.definition.implementation.source_sha256
        assert strategy.definition.runtime_sha256


def test_runtime_rejects_release_without_deployed_implementation() -> None:
    raw = {
        "strategy_id": "S999",
        "version": "v1",
        "release_id": "S999-v1",
        "strategy_payload": {"kind": "test"},
    }
    raw["release_hash"] = canonical_sha256(raw)

    with pytest.raises(RuntimeCompatibilityError, match="deployment file"):
        StrategyRuntime(ROOT / "strategies").describe(StrategyRelease.from_mapping(raw))


def test_strategy_release_rejects_payload_with_a_borrowed_hash() -> None:
    raw = json.loads((ROOT / "strategies/S002/versions/v1.json").read_text(encoding="utf-8"))
    raw["strategy_payload"]["rule"]["portfolio_rule"]["holding_sessions"] = 6

    with pytest.raises(RuntimeContractError, match="complete frozen record"):
        StrategyRelease.from_mapping(raw)


def test_loader_rejects_source_that_differs_from_frozen_binding(monkeypatch) -> None:
    root = Path(__file__).resolve().parents[4]
    payload = json.loads((root / "strategies/S007/versions/v1.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(
        "strategy_runtime.loader.implementation_sha256",
        lambda _files, **_kwargs: "0" * 64,
    )

    with pytest.raises(RuntimeCompatibilityError, match="differs from runtime binding"):
        StrategyLoader(ROOT / "strategies").load(StrategyRelease.from_mapping(payload))


def test_loader_executes_helpers_from_the_authenticated_release_closure() -> None:
    payload = json.loads(
        (ROOT / "strategies/S007/versions/v1.json").read_text(encoding="utf-8")
    )
    strategy = StrategyLoader(ROOT / "strategies").load(
        StrategyRelease.from_mapping(payload)
    )
    module = sys.modules[strategy.__class__.__module__]
    release_root = ROOT / "strategies/S007/releases/v1/runtime/strategy_runtime"

    assert Path(inspect.getsourcefile(module.next_session_calculation_scope)).resolve() == (
        release_root / "calculation.py"
    ).resolve()
    assert Path(inspect.getsourcefile(module.effective_target_order_type)).resolve() == (
        release_root / "execution_rules.py"
    ).resolve()


def test_symbol_binding_is_explicit_and_fails_closed() -> None:
    root = Path(__file__).resolve().parents[4]

    s001_payload = json.loads(
        (root / "strategies/S001/versions/v2.json").read_text(encoding="utf-8")
    )
    bound = StrategyLoader(ROOT / "strategies").load_for_symbol(
        StrategyRelease.from_mapping(s001_payload), "159352.SZ"
    )
    etf_subjects = {
        item.subject
        for item in bound.definition.inputs.requirements
        if item.dataset.startswith("etf.")
    }
    assert etf_subjects == {"159352.SZ"}

    s007_payload = json.loads(
        (root / "strategies/S007/versions/v1.json").read_text(encoding="utf-8")
    )
    with pytest.raises(RuntimeCompatibilityError, match="does not support"):
        StrategyLoader(ROOT / "strategies").load_for_symbol(
            StrategyRelease.from_mapping(s007_payload), "588300.SH"
        )


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


def test_intraday_overlay_capital_terms_are_explicit_for_each_plan_mode() -> None:
    policy = ExecutionPolicy(
        "INTRADAY_OVERLAY",
        {
            "core_fraction": 0.5,
            "event_fraction": 0.5,
        },
    )

    assert _capital_terms(
        raw={"plan_mode": "CORE_SETUP"},
        execution_policy=policy,
    ) == ("available_cash_fraction", Decimal("0.5"))
    assert _capital_terms(
        raw={"plan_mode": "CORE_EVENT_INTRADAY_ROTATION"},
        execution_policy=policy,
    ) == ("full_available_cash", Decimal("1"))
    assert _capital_terms(
        raw={"plan_mode": "NONE"},
        execution_policy=policy,
    ) == ("full_available_cash", Decimal("1"))


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
