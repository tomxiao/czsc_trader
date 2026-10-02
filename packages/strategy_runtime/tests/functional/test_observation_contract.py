from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from strategy_runtime import (
    ConstantGuide,
    EvidenceGuide,
    ObservationDefinition,
    ObservationFact,
    ObservationSeries,
    ObservationValueType as ValueType,
    ObservationFormat as Format,
    StrategyObservation,
    ObservationUnavailable,
    RuntimeContractError,
    RuntimeCompatibilityError,
    RuntimeBinding,
    RuntimeBindingSpec,
    ExecutionPlan,
    StrategyIdentity,
    PriceReference,
    ExecutionCapabilities,
    materialize_observation,
)
from strategy_runtime.contracts import signal_identity_for, plan_identity_for
from test_strategy_runtime_contracts import _definition


def observed_plan(evidence=None):
    declaration = ObservationDefinition(
        (
            ObservationSeries(
                "score",
                "Score",
                "score",
                (ConstantGuide("entry", "Entry", 0.2), EvidenceGuide("exit", "Exit", "exit")),
            ),
        ),
        (
            ObservationFact("reason", "Reason", "reason", ValueType.TEXT, Format.TEXT),
            ObservationFact("active", "Active", "active", ValueType.BOOLEAN, Format.BOOLEAN),
            ObservationFact("count", "Count", "count", ValueType.INTEGER, Format.INTEGER),
        ),
    )
    definition = replace(_definition(), observation=declaration)
    strategy = StrategyIdentity(
        definition.strategy_family_id,
        definition.release_id,
        definition.release_hash,
        definition.runtime_sha256,
        definition.tradable_symbol,
    )
    signal = dict(
        strategy=strategy,
        signal_date=date(2026, 9, 1),
        target_position=0.0,
        input_identities={"input": "a" * 64},
        price_identities={"price": "b" * 64},
    )
    execution = dict(
        signal_identity=signal_identity_for(**signal),
        actual_quantity=0,
        target_quantity=0,
        cycle_target_quantity=0,
        plan_mode="NONE",
        capital_mode="full_available_cash",
        allocation_fraction=Decimal(1),
        orders=(),
        legs=(),
    )
    plan = ExecutionPlan(
        **signal,
        **execution,
        plan_identity=plan_identity_for(**execution),
        symbol=definition.tradable_symbol,
        trading_date=date(2026, 9, 2),
        generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        expected_portfolio_revision=0,
        expected_state_revision=0,
        action="WAIT",
        available_cash=Decimal(1000),
        fee_rate=Decimal(".001"),
        estimated_order_cost=Decimal(0),
        unallocated_cash=Decimal(1000),
        references=PriceReference(Decimal(1), Decimal(1), "hfq", "raw"),
        required_capabilities=ExecutionCapabilities(()),
        evidence=evidence
        or {
            "score": 0.31,
            "exit": 0.08,
            "reason": "完整理由" * 100,
            "active": False,
            "count": 2,
            "private": "hidden",
        },
    )
    return definition, plan


def test_materialized_facts_preserve_identity_types_and_full_text():
    definition, plan = observed_plan()
    observation = materialize_observation(definition, plan)
    assert StrategyObservation.from_dict(observation.to_dict()) == observation
    assert (
        ObservationDefinition.from_dict(definition.observation.to_dict()) == definition.observation
    )
    assert observation.plan_identity == plan.plan_identity
    assert observation.series[0].guides[1].value == 0.08
    assert observation.facts[0].value == "完整理由" * 100
    assert observation.facts[1].value is False
    assert "private" not in str(observation.to_dict())


@pytest.mark.parametrize(
    "field,value",
    [
        ("score", True),
        ("score", float("nan")),
        ("exit", float("inf")),
        ("reason", 4),
        ("active", 1),
        ("count", False),
    ],
)
def test_invalid_plan_evidence_is_rejected(field, value):
    definition, plan = observed_plan()
    with pytest.raises(RuntimeContractError):
        materialize_observation(definition, replace(plan, evidence={**plan.evidence, field: value}))


def test_missing_evidence_and_foreign_definition_are_rejected():
    definition, plan = observed_plan()
    with pytest.raises(RuntimeContractError, match="missing exit"):
        materialize_observation(definition, replace(plan, evidence={"score": 0.3}))
    with pytest.raises(RuntimeContractError, match="differs from runtime"):
        materialize_observation(
            replace(definition, observation=ObservationDefinition((), ())), plan
        )
    with pytest.raises(RuntimeContractError):
        materialize_observation(definition.observation, plan.evidence)


def test_definition_controls_content_identity_and_empty_series_are_valid():
    from strategy_runtime.identity import content_identity

    definition, _ = observed_plan()
    changed = replace(
        definition, observation=ObservationDefinition((), definition.observation.facts)
    )
    assert definition.runtime_sha256 != changed.runtime_sha256
    assert (
        content_identity(definition, ("strategy.py",), (), {}).content_sha256
        != content_identity(changed, ("strategy.py",), (), {}).content_sha256
    )
    with pytest.raises(RuntimeContractError):
        ObservationDefinition((definition.observation.series[0],) * 2, ())
    assert (
        ObservationUnavailable.from_dict(ObservationUnavailable("missing fact").to_dict()).message
        == "missing fact"
    )


def test_binding_rejects_old_schema_untyped_spec_and_extra_chart_fields():
    spec = RuntimeBindingSpec(("strategies/test.py",), "a" * 64, ("strategies/test.py",), "b" * 64)
    binding = RuntimeBinding("S900-v1", "c" * 64, spec)
    assert RuntimeBinding.from_dict(binding.to_dict()) == binding
    for changes in (
        {"schema_version": 1},
        {"charts": {}},
        {"install_files": []},
        {"source_files": ["../x.py"]},
    ):
        with pytest.raises(RuntimeCompatibilityError):
            RuntimeBinding.from_dict({**binding.to_dict(), **changes})
    with pytest.raises(RuntimeCompatibilityError):
        RuntimeBinding("S900-v1", "c" * 64, spec.to_dict())
