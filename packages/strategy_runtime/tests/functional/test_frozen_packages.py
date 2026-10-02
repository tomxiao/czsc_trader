"""Current real frozen packages load and preserve account execution semantics."""
from dataclasses import replace
from pathlib import Path

import pytest

from strategy_manager import StrategyRegistry
from strategy_runtime import (
    RuntimeCompatibilityError,
    StrategyIdentity,
    StrategyRelease,
    StrategyRuntime,
    load_strategy_deployment,
    materialize_observation,
)
from strategy_runtime.contracts import signal_identity_for, plan_identity_for
from strategy_runtime.execution_planner import build_execution_plan
from test_observation_contract import observed_plan

ROOT = Path(__file__).resolve().parents[4] / "strategies"
RELEASES = ("S001-v1", "S001-v2", "S002-v1", "S003-v1", "S007-v1")


def definition(release_id):
    family, version = release_id.split("-")
    record = StrategyRegistry(ROOT).get_version(family, version)
    return StrategyRuntime(strategy_root=ROOT).describe(StrategyRelease.from_mapping(record.to_dict()))


@pytest.mark.parametrize("release_id", RELEASES)
def test_current_packages_have_no_research_governance_or_chart_dependency(release_id):
    family, version = release_id.split("-")
    model = StrategyRegistry(ROOT).get_version(family, version)
    assert model.schema_version == 5
    assert not {"origin", "governance", "governance_hash"} & model.to_dict().keys()
    deployed = load_strategy_deployment(ROOT, release_id)
    assert not any(name.startswith("charts/") for name in deployed.install_files)
    actual = definition(release_id)
    assert actual.schema_version == 3
    assert actual.observation.sha256 == deployed.binding.spec.observation_sha256
    with pytest.raises(RuntimeCompatibilityError, match="differs from frozen release"):
        StrategyRuntime().describe(
            StrategyRelease.from_mapping(model.to_dict()), source_root=deployed.source_root,
            runtime_binding=replace(deployed.binding, release_hash="0" * 64),
        )


@pytest.mark.parametrize("release_id", RELEASES)
def test_current_observation_uses_declared_fields_and_current_identity(release_id):
    actual = definition(release_id)
    _, template = observed_plan()
    strategy = StrategyIdentity(actual.strategy_family_id, actual.release_id, actual.release_hash,
                                actual.runtime_sha256, actual.tradable_symbol)
    signal = signal_identity_for(strategy=strategy, signal_date=template.signal_date,
                                 target_position=template.target_position,
                                 input_identities=template.input_identities,
                                 price_identities=template.price_identities)
    evidence = {series.value_field: 0.3 for series in actual.observation.series}
    for series in actual.observation.series:
        for guide in series.guides:
            if hasattr(guide, "value_field"):
                evidence[guide.value_field] = 0.2
    identity = plan_identity_for(signal_identity=signal, actual_quantity=template.actual_quantity,
                                 target_quantity=template.target_quantity,
                                 cycle_target_quantity=template.cycle_target_quantity,
                                 plan_mode=template.plan_mode, capital_mode=template.capital_mode,
                                 allocation_fraction=template.allocation_fraction,
                                 orders=template.orders, legs=template.legs)
    plan = replace(template, strategy=strategy, symbol=actual.tradable_symbol,
                   signal_identity=signal, plan_identity=identity, evidence=evidence)
    facts = materialize_observation(actual, plan)
    assert facts.strategy == strategy
    assert len(facts.series) == len(actual.observation.series)


@pytest.mark.parametrize("release_id", RELEASES)
@pytest.mark.parametrize("target", [0.0, 1.0])
def test_held_position_does_not_restart_account_cycle(release_id, target):
    actual = definition(release_id)
    plan = build_execution_plan(
        deployment_settings={"cycle_target_quantity": 5900}, available_cash=50000,
        position_quantity=5900, target_position=target, policy=actual.execution,
        signal_reference_price=5.0, execution_reference_price=5.0,
    )
    assert plan["actual_quantity"] == 5900
    if release_id == "S003-v1":
        assert plan["cycle_target_quantity"] == plan["target_quantity"] == 5900
        assert plan["action"] == ("ROTATE" if target else "HOLD")
        assert plan["plan_mode"] != "CORE_SETUP"
        assert [x["order"]["side"] for x in plan["plan_legs"]] == (["BUY", "SELL"] if target else [])
    else:
        assert plan["action"] == ("HOLD" if target else "SELL")
        assert plan["target_quantity"] == (5900 if target else 0)
