"""Typed neighborhood plans bind actual payload leaves, not a mapping declaration alone."""

from dataclasses import replace
import json

import pytest

from czsc_trader.research_tools import ParameterEvaluationPlan
from czsc_trader.research_tools.parameter_evaluation import _payload_json
from test_parameter_evaluation import prepared_parameter_plan as prepared_parameter_plan
from test_parameter_evaluation import parameter_plan
from test_research_contract_upgrade import managed_evaluation as managed_evaluation


@pytest.mark.parametrize("mutation", ["wrong_point", "hidden_parameter", "wrong_type", "hidden_payload"])
def test_plan_rejects_payload_not_equal_to_prescribed_point(prepared_parameter_plan, mutation):
    _, _, plan, _, _ = prepared_parameter_plan
    child = plan.children[0]
    payload = json.loads(child.payload_json)
    if mutation == "wrong_point":
        payload["parameters"]["threshold"] = .123
    elif mutation == "hidden_parameter":
        payload["parameters"]["undeclared"] = 3
    elif mutation == "wrong_type":
        payload["parameters"]["threshold"] = str(payload["parameters"]["threshold"])
    else:
        payload["undeclared"] = {"outside_parameters": True}
    altered = replace(child, payload_json=_payload_json(payload))
    with pytest.raises(ValueError, match="declared point mapping"):
        replace(plan, children=(altered, *plan.children[1:]))


def test_plan_rejects_missing_point_and_duplicate_content(prepared_parameter_plan):
    _, _, plan, _, _ = prepared_parameter_plan
    with pytest.raises(ValueError, match="every design point"):
        replace(plan, children=plan.children[:-1])
    duplicate = replace(plan.children[1], candidate=replace(
        plan.children[1].candidate, content_sha256=plan.children[0].candidate.content_sha256))
    with pytest.raises(ValueError, match="duplicate parameter candidate content"):
        replace(plan, children=(plan.children[0], duplicate))


@pytest.mark.parametrize("mutation", ["value", "type", "path"])
def test_plan_authenticates_declared_center_payload(prepared_parameter_plan, mutation):
    _, _, plan, _, _ = prepared_parameter_plan
    payload = json.loads(plan.center.payload_json)
    if mutation == "value":
        payload["parameters"]["threshold"] = .4
    elif mutation == "type":
        payload["parameters"]["threshold"] = "0.5"
    else:
        del payload["parameters"]["threshold"]
    altered = replace(plan.center, payload_json=_payload_json(payload))
    with pytest.raises(ValueError, match="center payload differs|payload path does not exist"):
        replace(plan, center=altered)


def test_new_plan_schema_cannot_be_downgraded(prepared_parameter_plan):
    _, _, plan, _, _ = prepared_parameter_plan
    assert plan.schema_version == 3
    saved = plan.to_dict()
    saved["schema_version"] = 1
    with pytest.raises(ValueError, match="schema differs"):
        ParameterEvaluationPlan.from_dict(saved)


def test_structural_control_cannot_use_local_evaluation_plan(prepared_parameter_plan):
    from strategy_evaluator import StudyPurpose

    _, _, plan, _, _ = prepared_parameter_plan
    design = replace(plan.design, protocol=replace(plan.design.protocol, purpose=StudyPurpose.STRUCTURAL_CONTROL))
    with pytest.raises(ValueError, match="structural controls are separate"):
        replace(plan, design=design)


def test_create_rejects_hidden_parameter_even_when_execution_is_unchanged(managed_evaluation):
    research, request = managed_evaluation
    with pytest.raises(ValueError, match="declared point mapping"):
        parameter_plan(research, request, child_parameters=lambda point: {"unreported": 1})


def test_nested_payload_path_preserves_exact_typed_values(prepared_parameter_plan):
    from strategy_evaluator.parameter_neighborhood import (
        ParameterAxis, IntegerDomain, BoundedLocalStep, AbsoluteChangeLimit, ParameterNeighborhoodSpace,
        ParameterNeighborhoodRequest, build_parameter_neighborhood_design,
    )

    _, _, plan, _, _ = prepared_parameter_plan
    space = ParameterNeighborhoodSpace((ParameterAxis("nested_hold", 3, IntegerDomain(1, 10),
        BoundedLocalStep(AbsoluteChangeLimit(1.)), ("timing", "hold"), "sessions"),),
        plan.mapping_evidence.sha256, plan.feasibility_evidence.sha256)
    design = build_parameter_neighborhood_design(ParameterNeighborhoodRequest(
        plan.design.center, plan.design.protocol, space), feasibility=lambda values: True).design
    payload = json.loads(plan.center.payload_json)
    payload["parameters"]["timing"] = {"hold": 3, "unchanged": True}
    center = replace(plan.center, payload_json=_payload_json(payload))
    children = []
    for original, point in zip(plan.children, design.points, strict=True):
        child_payload = json.loads(center.payload_json)
        child_payload["parameters"]["timing"]["hold"] = point.values[0].value
        children.append(replace(original, payload_json=_payload_json(child_payload)))
    typed = replace(plan, design=design, center=center, children=tuple(children))
    assert ParameterEvaluationPlan.from_dict(typed.to_dict()) == typed
    child_payload = json.loads(children[0].payload_json)
    child_payload["parameters"]["timing"]["hold"] = float(child_payload["parameters"]["timing"]["hold"])
    with pytest.raises(ValueError, match="declared point mapping"):
        replace(typed, children=(replace(children[0], payload_json=_payload_json(child_payload)), children[1]))


def test_legacy_sphere_plan_is_readable_but_cannot_start_new_work(prepared_parameter_plan):
    from strategy_evaluator import (
        ParameterCoordinate, ParameterCoordinateKind, ParameterPerturbationDesign,
        ParameterPerturbationPoint, ParameterPerturbationProtocol, ParameterSpace,
    )
    from czsc_trader.application import publish_evidence
    from czsc_trader.research_tools import MaterialEvidenceWrite
    from czsc_trader.research_tools.parameter_evaluation import (
        ParameterEvaluationBinding, read_parameter_plan,
    )

    research, center, plan, reference, children = prepared_parameter_plan
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
    assert read_parameter_plan(oldref, center.repository_root) == legacy
    with pytest.raises(TypeError, match="legacy sphere plans are read-only"):
        ParameterEvaluationPlan.create(olddesign, center, (), mapping_evidence=plan.mapping_evidence,
            feasibility_evidence=plan.feasibility_evidence, dataflows=research.data)
    with pytest.raises(ValueError, match="read-only"):
        legacy.bind_point(oldref, 0, repository_root=center.repository_root)
    oldbinding = ParameterEvaluationBinding(oldref, olddesign.bind_point(0))
    request = replace(children[0], lineage=replace(children[0].lineage, parameter_binding=oldbinding))
    with pytest.raises(ValueError, match="read-only|legacy|schema 2"):
        research.evaluation.prepare(request)


def test_legacy_cartesian_plan_remains_read_only_without_changing_serialization(prepared_parameter_plan):
    from strategy_evaluator.parameter_neighborhood import NumericOffsets
    from czsc_trader.application import publish_evidence
    from czsc_trader.research_tools import MaterialEvidenceWrite
    from czsc_trader.research_tools.parameter_evaluation import read_parameter_plan

    research, center, plan, reference, _ = prepared_parameter_plan
    old_axis = replace(plan.design.space.axes[0], rule=NumericOffsets((-.05, .05)))
    legacy_design = replace(plan.design,
        protocol=replace(plan.design.protocol, version="parameter-cartesian-neighborhood-v1"),
        space=replace(plan.design.space, axes=(old_axis,)))
    legacy = replace(plan, design=legacy_design, schema_version=2)
    original = legacy.to_dict()
    assert ParameterEvaluationPlan.from_dict(original).to_dict() == original
    oldref = publish_evidence(research, MaterialEvidenceWrite(reference.experiment,
        "legacy-cartesian-plan", json.dumps(original).encode(), "application/json", "json"))
    assert read_parameter_plan(oldref, center.repository_root).to_dict() == original
    with pytest.raises(ValueError, match="read-only"):
        ParameterEvaluationPlan.create(legacy_design, center, (), mapping_evidence=plan.mapping_evidence,
            feasibility_evidence=plan.feasibility_evidence, dataflows=research.data)
    with pytest.raises(ValueError, match="read-only"):
        legacy.bind_point(oldref, 0, repository_root=center.repository_root)
