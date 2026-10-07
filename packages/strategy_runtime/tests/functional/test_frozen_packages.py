"""Current real frozen packages load and preserve account execution semantics."""
from dataclasses import fields, replace
from pathlib import Path

import pytest

from strategy_manager import StrategyRegistry
from strategy_runtime import (
    StrategyIdentity,
    StrategyCandidate,
    StrategyDefinition,
    StrategyRelease,
    StrategyRuntime,
    load_strategy_deployment,
    materialize_observation,
    ObservationValueType,
)
from strategy_runtime.contracts import signal_identity_for, plan_identity_for
from test_observation_contract import observed_plan

ROOT = Path(__file__).resolve().parents[4] / "strategies"
pytestmark = pytest.mark.release_acceptance


@pytest.fixture(scope="module")
def loaded_release(registered_release):
    """Load each immutable installed package once, retaining independent checks."""
    deployment = load_strategy_deployment(ROOT, registered_release.release_id)
    runtime = StrategyRuntime(strategy_root=ROOT)
    actual = runtime.describe(StrategyRelease.from_mapping(registered_release.to_dict()))
    return registered_release, deployment, actual, runtime


def test_real_package_behavior_is_independent_of_candidate_or_release_identity(loaded_release):
    record, deployment, release, runtime = loaded_release
    family, _ = record.release_id.split("-")
    candidate = runtime.describe(
        StrategyCandidate(family, "C0001", record.strategy_payload, deployment.source_root)
    )
    for field in fields(StrategyDefinition):
        assert getattr(candidate, field.name) == getattr(release, field.name)
    assert candidate.identity_kind == "CANDIDATE"
    assert candidate.release_id == f"{family}-C0001"
    assert release.identity_kind == "RELEASE"
    assert release.release_id == record.release_id


@pytest.mark.parametrize("release_id", ("S001-v1", "S001-v2", "S002-v1"))
def test_real_rebindable_package_uses_parameter_factory(release_id):
    family, version = release_id.split("-")
    record = StrategyRegistry(ROOT).get_version(family, version)
    runtime = StrategyRuntime(strategy_root=ROOT)
    release = StrategyRelease.from_mapping(record.to_dict())
    original = runtime.describe(release)
    rebound = runtime.describe(release, symbol="510500.SH")
    assert rebound.tradable_symbol == "510500.SH"
    assert rebound.parameters == original.parameters
    assert rebound.release_hash == original.release_hash
    assert rebound.release_id == original.release_id


def test_current_packages_have_no_research_governance_or_chart_dependency(loaded_release):
    model, deployed, actual, _ = loaded_release
    assert model.schema_version == 5
    assert not {"origin", "governance", "governance_hash"} & model.to_dict().keys()
    assert not any(name.startswith("charts/") for name in deployed.install_files)
    assert actual.schema_version == 3
    assert actual.observation.sha256 == deployed.binding.spec.observation_sha256



def test_current_observation_uses_declared_fields_and_current_identity(loaded_release):
    _, _, actual, _ = loaded_release
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
    values = {
        ObservationValueType.NUMBER: 0.3, ObservationValueType.INTEGER: 1,
        ObservationValueType.BOOLEAN: True, ObservationValueType.TEXT: "synthetic reason",
    }
    evidence.update({fact.value_field: values[fact.value_type] for fact in actual.observation.facts})
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
    assert len(facts.facts) == len(actual.observation.facts)
