# Risk ownership: TDR-14
"""Typed parameter plans retain declared inputs without implicit research certification."""

from dataclasses import replace
import json

import pytest

from czsc_trader.research_tools import ParameterEvaluationPlan
from czsc_trader.research_tools.parameter_evaluation import _payload_json
from test_parameter_evaluation import prepared_parameter_plan as prepared_parameter_plan


def _decoded_payload(value):
    payload = json.loads(value)
    payload["parameters"] = json.loads(payload["equity_definition"].pop("parameters_json"))
    return payload


def _encoded_payload(payload):
    payload = json.loads(_payload_json(payload))
    payload["equity_definition"]["parameters_json"] = _payload_json(payload.pop("parameters"))
    return _payload_json(payload)


def test_TDR_14_C02_plan_rejects_missing_point_and_duplicate_content(prepared_parameter_plan):
    _, _, plan, _, _, _ = prepared_parameter_plan
    with pytest.raises(ValueError, match="every design point"):
        replace(plan, children=plan.children[:-1])
    duplicate = replace(plan.children[1], candidate=replace(
        plan.children[1].candidate, content_sha256=plan.children[0].candidate.content_sha256))
    with pytest.raises(ValueError, match="duplicate parameter candidate content"):
        replace(plan, children=(plan.children[0], duplicate))


def test_TDR_14_C08_nested_payload_path_preserves_exact_typed_values(prepared_parameter_plan):
    from strategy_evaluator.parameter_neighborhood import (
        ParameterAxis, IntegerDomain, BoundedLocalStep, AbsoluteChangeLimit, ParameterNeighborhoodSpace,
        ParameterNeighborhoodRequest, build_parameter_neighborhood_design,
    )

    _, _, plan, _, _, _ = prepared_parameter_plan
    space = ParameterNeighborhoodSpace((ParameterAxis("nested_hold", 3, IntegerDomain(1, 10),
        BoundedLocalStep(AbsoluteChangeLimit(1.)), ("timing", "hold"), "sessions"),),
        plan.mapping_evidence.sha256, plan.feasibility_evidence.sha256)
    design = build_parameter_neighborhood_design(ParameterNeighborhoodRequest(
        plan.design.center, plan.design.protocol, space), feasibility=lambda values: True).design
    payload = _decoded_payload(plan.center.payload_json)
    payload["parameters"]["timing"] = {"hold": 3, "unchanged": True}
    center = replace(plan.center, payload_json=_encoded_payload(payload))
    children = []
    for original, point in zip(plan.children, design.points, strict=True):
        child_payload = _decoded_payload(center.payload_json)
        child_payload["parameters"]["timing"]["hold"] = point.values[0].value
        children.append(replace(original, payload_json=_encoded_payload(child_payload)))
    typed = replace(plan, design=design, center=center, children=tuple(children))
    assert ParameterEvaluationPlan.from_dict(typed.to_dict()) == typed
    child_payload = _decoded_payload(children[0].payload_json)
    child_payload["parameters"]["timing"]["hold"] = float(child_payload["parameters"]["timing"]["hold"])
    changed = replace(typed, children=(replace(children[0], payload_json=_encoded_payload(child_payload)), children[1]))
    assert type(_decoded_payload(changed.children[0].payload_json)["parameters"]["timing"]["hold"]) is float


def test_TDR_14_C06_legacy_sphere_plan_is_readable_but_cannot_start_new_work(prepared_parameter_plan):
    from strategy_evaluator import (
        ParameterCoordinate, ParameterCoordinateKind, ParameterPerturbationDesign,
        ParameterPerturbationPoint, ParameterPerturbationProtocol, ParameterSpace,
    )
    from czsc_trader.application import publish_evidence
    from czsc_trader.research_tools import MaterialEvidenceWrite
    from czsc_trader.research_tools.parameter_evaluation import (
        read_parameter_plan,
    )

    research, center, plan, reference, children, _ = prepared_parameter_plan
    oldspace = ParameterSpace((ParameterCoordinate("threshold", .5, 0., 1.,
        ParameterCoordinateKind.CONTINUOUS),), plan.mapping_evidence.sha256,
        plan.feasibility_evidence.sha256)
    # Reconstruct a historical serialized geometry; do not invoke a retired generator.
    olddesign = ParameterPerturbationDesign(plan.design.center,
        ParameterPerturbationProtocol(point_count=2), oldspace,
        (ParameterPerturbationPoint(0, (.45,), .05), ParameterPerturbationPoint(1, (.55,), .05)),
        2, ())
    legacy = replace(plan, design=olddesign, schema_version=1)
    assert ParameterEvaluationPlan.from_dict(legacy.to_dict()) == legacy
    oldref = publish_evidence(research, MaterialEvidenceWrite(reference.experiment,
        "legacy-read-only-plan", json.dumps(legacy.to_dict()).encode(), "application/json", "json"))
    assert read_parameter_plan(oldref, research.repository.root) == legacy
    with pytest.raises(TypeError, match="typed neighborhood"):
        ParameterEvaluationPlan.create(olddesign, center, (), mapping_evidence=plan.mapping_evidence,
            feasibility_evidence=plan.feasibility_evidence, dataflows=research.data)
    with pytest.raises(ValueError, match="read-only"):
        legacy.bind_point(oldref, 0, repository_root=research.repository.root)


def test_TDR_14_C07_legacy_cartesian_plan_remains_read_only_without_changing_serialization(prepared_parameter_plan):
    from strategy_evaluator.parameter_neighborhood import NumericOffsets
    from czsc_trader.application import publish_evidence
    from czsc_trader.research_tools import MaterialEvidenceWrite
    from czsc_trader.research_tools.parameter_evaluation import read_parameter_plan

    research, center, plan, reference, _, _ = prepared_parameter_plan
    old_axis = replace(plan.design.space.axes[0], rule=NumericOffsets((-.5, .5)))
    legacy_design = replace(plan.design,
        protocol=replace(plan.design.protocol, version="parameter-cartesian-neighborhood-v1"),
        space=replace(plan.design.space, axes=(old_axis,)))
    legacy = replace(plan, design=legacy_design, schema_version=2)
    original = legacy.to_dict()
    assert ParameterEvaluationPlan.from_dict(original).to_dict() == original
    oldref = publish_evidence(research, MaterialEvidenceWrite(reference.experiment,
        "legacy-cartesian-plan", json.dumps(original).encode(), "application/json", "json"))
    assert read_parameter_plan(oldref, research.repository.root).to_dict() == original
    with pytest.raises(ValueError, match="read-only"):
        ParameterEvaluationPlan.create(legacy_design, center, (), mapping_evidence=plan.mapping_evidence,
            feasibility_evidence=plan.feasibility_evidence, dataflows=research.data)
    with pytest.raises(ValueError, match="read-only"):
        legacy.bind_point(oldref, 0, repository_root=research.repository.root)
