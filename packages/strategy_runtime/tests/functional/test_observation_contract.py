from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
import json

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
    SignalAvailability,
    SignalRender,
    SignalGroup,
    SignalSeriesDefinition,
    SignalStateOption,
    SignalStateDefinition,
    SignalPanelDefinition,
    SignalPanelSnapshot,
)
from strategy_runtime.contracts import signal_identity_for, plan_identity_for
from test_strategy_runtime_contracts import _definition


def observed_plan(evidence=None, signal_panel=None):
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
        signal_panel,
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


def signal_panel_plan(**evidence):
    panel = SignalPanelDefinition(
        (SignalGroup("conditions", "入场条件", "比例", "price_ratio", Format.PERCENT, 2),
         SignalGroup("boundaries", "机会边界", "元", "hfq", Format.NUMBER, 3)),
        (SignalSeriesDefinition("space", "修复空间", "conditions", "obs_space",
                                guides=(ConstantGuide("minimum", "最低门槛", .002),)),
         SignalSeriesDefinition("target", "固定目标", "boundaries", "obs_target", SignalRender.STEP,
                                "obs_target_status", "obs_segment", "obs_reason",
                                (EvidenceGuide("center", "当前中心", "obs_center"),))),
        (SignalStateDefinition("opportunity", "机会状态", "obs_state",
                               (SignalStateOption("active", "有效"), SignalStateOption("ended", "结束"))),),
    )
    original = dict(observed_plan()[1].evidence)
    original.update(obs_space=.03, obs_target=1.5, obs_target_status="AVAILABLE",
                    obs_segment="2026-09-01", obs_center=1.45, obs_state="active")
    original.update(evidence)
    return observed_plan(original, signal_panel=panel)


def test_v3_signal_panel_materializes_strategy_owned_semantics_without_changing_legacy_facts():
    definition, plan = signal_panel_plan()
    observed = materialize_observation(definition, plan)
    encoded = json.loads(json.dumps(observed.to_dict()))
    assert encoded["contract_version"] == "strategy_observation.v3"
    assert StrategyObservation.from_dict(encoded) == observed
    assert ObservationDefinition.from_dict(json.loads(json.dumps(definition.observation.to_dict()))) == definition.observation
    panel = observed.signal_panel
    assert panel == SignalPanelSnapshot.from_dict(panel.to_dict())
    assert panel.series[0].value == .03  # Ratio stays a ratio; the renderer formats percent.
    assert panel.series[1].segment_id == "2026-09-01"
    assert panel.series[1].guides[0].value == 1.45
    assert panel.states[0].value == "active"
    assert observed.series == materialize_observation(*observed_plan()).series
    assert observed.facts == materialize_observation(*observed_plan()).facts
    assert definition.observation.signal_panel.evidence_fields == (
        "obs_center", "obs_reason", "obs_segment", "obs_space", "obs_state", "obs_target", "obs_target_status",
    )
    assert plan.orders == () and observed.action == "WAIT"
    assert "private" not in str(encoded)


@pytest.mark.parametrize("status,reason", [("INACTIVE", None), ("UNAVAILABLE", "行情不完整")])
def test_v3_inactive_and_unavailable_values_do_not_leak_stale_targets_or_guides(status, reason):
    definition, plan = signal_panel_plan()
    evidence = dict(plan.evidence, obs_target_status=status, obs_reason=reason)
    for key in ("obs_target", "obs_segment", "obs_center"):
        evidence.pop(key)
    observed = materialize_observation(definition, replace(plan, evidence=evidence))
    target = observed.signal_panel.series[1]
    assert target.status == SignalAvailability(status)
    assert target.value is None and target.segment_id is None and target.guides == ()
    assert target.reason == reason


@pytest.mark.parametrize("changes", [
    {"obs_target": True},
    {"obs_target": float("nan")},
    {"obs_center": float("inf")},
    {"obs_target_status": "UNKNOWN"},
    {"obs_target_status": True},
    {"obs_segment": ""},
    {"obs_state": "undeclared"},
    {"obs_target_status": "UNAVAILABLE", "obs_reason": None},
])
def test_v3_materialization_rejects_invalid_values_and_state_semantics(changes):
    definition, plan = signal_panel_plan()
    with pytest.raises(RuntimeContractError):
        materialize_observation(definition, replace(plan, evidence={**plan.evidence, **changes}))


@pytest.mark.parametrize("missing", ["obs_target", "obs_target_status", "obs_segment", "obs_state"])
def test_v3_available_evidence_requires_explicit_declared_values(missing):
    definition, plan = signal_panel_plan()
    evidence = {k: v for k, v in plan.evidence.items() if k != missing}
    with pytest.raises(RuntimeContractError, match="missing"):
        materialize_observation(definition, replace(plan, evidence=evidence))


@pytest.mark.parametrize("mutation", ["foreign_group", "unit_override", "missing_panel", "unknown_version", "stale_inactive", "undeclared_state"])
def test_v3_snapshot_reader_rejects_inconsistent_or_undeclared_display_contracts(mutation):
    observed = materialize_observation(*signal_panel_plan())
    value = json.loads(json.dumps(observed.to_dict()))
    panel = value["signal_panel"]
    if mutation == "foreign_group":
        panel["series"][0]["group"] = "absent"
    elif mutation == "unit_override":
        panel["series"][0]["unit"] = "元"
    elif mutation == "missing_panel":
        value.pop("signal_panel")
    elif mutation == "unknown_version":
        value["contract_version"] = "strategy_observation.v4"
    elif mutation == "stale_inactive":
        panel["series"][1]["status"] = "INACTIVE"
    else:
        panel["states"][0]["value"] = "unknown"
    with pytest.raises(RuntimeContractError):
        StrategyObservation.from_dict(value)


def test_v3_declarations_reject_inconsistent_groups_and_untyped_rendering():
    definition, _ = signal_panel_plan()
    panel = definition.observation.signal_panel
    with pytest.raises(RuntimeContractError):
        replace(panel, groups=panel.groups[:1])
    with pytest.raises(RuntimeContractError):
        replace(panel.series[0], render="LINE")
    with pytest.raises(RuntimeContractError):
        replace(panel.states[0], options=(panel.states[0].options[0],) * 2)
    with pytest.raises(RuntimeContractError):
        replace(panel.groups[0], format=Format.TEXT)
    with pytest.raises(RuntimeContractError):
        replace(panel.groups[0], precision=True)
    with pytest.raises(RuntimeContractError):
        replace(panel, series=panel.series + (panel.series[0],))


def test_failed_strategy_observation_calculation_cannot_materialize_a_partial_ready_panel():
    definition, plan = signal_panel_plan()
    failed = replace(plan, evidence={**plan.evidence, "_observation_error": "ValueError: invalid observation rows"})
    with pytest.raises(RuntimeContractError, match="signal panel calculation unavailable"):
        materialize_observation(definition, failed)
    assert failed.orders == plan.orders and failed.target_position == plan.target_position
    assert failed.plan_identity == plan.plan_identity
    malformed = replace(plan, evidence={**plan.evidence, "_observation_error": True})
    with pytest.raises(RuntimeContractError, match="text is required"):
        materialize_observation(definition, malformed)


def test_v2_serialization_retains_exact_declared_shape_and_unavailable_version():
    declaration = ObservationDefinition((ObservationSeries("score", "Score", "score", (
        ConstantGuide("entry", "Entry", .2),)),), ())
    assert declaration.to_dict() == {
        "contract_version": "strategy_observation.v2",
        "series": [{"key": "score", "label": "Score", "value_field": "score", "guides": [
            {"kind": "CONSTANT", "key": "entry", "label": "Entry", "value": .2},
        ]}], "facts": [],
    }
    assert declaration.sha256 == "f003dc5f5f249a97c612cec6725594f149054185e4761f3a69d28e5b4f3ec0c4"
    old = materialize_observation(*observed_plan())
    assert "signal_panel" not in old.to_dict()
    assert StrategyObservation.from_dict(old.to_dict()) == old
    unavailable = ObservationUnavailable("missing")
    assert unavailable.to_dict() == {"contract_version": "strategy_observation.v2", "status": "UNAVAILABLE", "message": "missing"}
    v3 = ObservationUnavailable("missing", "strategy_observation.v3")
    assert ObservationUnavailable.from_dict(v3.to_dict()) == v3
