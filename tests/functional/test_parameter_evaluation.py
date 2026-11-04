"""Current V4 parameter plans bind caller-declared points to owned accounts."""
from dataclasses import replace
import json

import pytest

from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import (
    EvaluationEvidenceWrite, ParameterEvaluationPlan, build_assessment_evidence,
)
from czsc_trader.research_tools.evidence import EvidenceRef
from equity_parameter_support import equity_plan


@pytest.fixture
def prepared_parameter_plan(tmp_path):
    with equity_plan(tmp_path) as prepared:
        yield prepared


def test_published_parameter_point_reaches_account_and_assessment(prepared_parameter_plan):
    context, center, plan, reference, children, execution = prepared_parameter_plan
    outcome, = context.evaluation.evaluate_many((children[0],), execution=execution)
    assert outcome.result is not None, outcome.error
    facts, = build_assessment_evidence(children[0], outcome.result, execution=execution)
    assert facts.parameter_point == plan.design.bind_point(0)
    result_ref = publish_evidence(context, EvaluationEvidenceWrite(reference.experiment,
        "parameter-account", children[0], outcome.result), execution=execution)
    value = json.loads(result_ref._read_verified(context.repository.root)[1])
    assert value["schema_version"] == 4
    assert value["request"]["lineage"]["parameter_binding"]["plan"]["sha256"] == reference.sha256
    assert facts.parent == plan.design.center
    assert ParameterEvaluationPlan.from_dict(plan.to_dict()) == plan
    assert center.candidate.content_identity.content_sha256 == plan.design.center.content_sha256


def test_parameter_plan_rejects_ambiguous_identity_and_source_declarations(prepared_parameter_plan):
    _, _, plan, _, _, _ = prepared_parameter_plan
    with pytest.raises(ValueError, match="duplicate parameter child candidate"):
        replace(plan, children=(plan.children[0], plan.children[0]))
    with pytest.raises(ValueError, match="duplicate parameter candidate payload"):
        replace(plan, children=(plan.children[0], replace(plan.children[1],
            payload_json=plan.children[0].payload_json)))
    changed = replace(plan.mapping_evidence, sha256="e" * 64, evidence_id="e" * 64 + ".json")
    with pytest.raises(ValueError, match="evidence differs"):
        replace(plan, mapping_evidence=changed)


def test_parameter_binding_does_not_require_published_plan_bytes(prepared_parameter_plan, monkeypatch):
    context, _, plan, reference, children, execution = prepared_parameter_plan
    reference.resolve(context.repository.root).unlink()
    def fail(*args, **kwargs):
        raise AssertionError("binding must not read research evidence")
    monkeypatch.setattr(EvidenceRef, "_read_verified", fail)
    assert plan.bind_point(reference, 0, repository_root=context.repository.root).point == plan.design.bind_point(0)
    prepared = context.evaluation.prepare(children[0].request, execution=execution)
    assert prepared.request.lineage == children[0].request.lineage


def test_plan_rejects_changed_nonparameter_execution_context(prepared_parameter_plan):
    context, center, plan, _, children, execution = prepared_parameter_plan
    changed = context.evaluation.prepare(replace(children[0].request,
        lineage=None, initial_cash=children[0].request.initial_cash + 1,
        audit_inputs_sha256=None), execution=execution)
    other = context.evaluation.prepare(replace(children[1].request, lineage=None), execution=execution)
    with pytest.raises(ValueError, match="nonparameter context differs"):
        ParameterEvaluationPlan.create(plan.design, center, (changed, other),
            mapping_evidence=plan.mapping_evidence, feasibility_evidence=plan.feasibility_evidence,
            dataflows=context.data, execution=execution)


def test_zero_point_plan_is_explicit_and_cannot_bind_fabricated_child(tmp_path):
    with equity_plan(tmp_path, applicable=False) as (context, _, plan, reference, children, _):
        assert plan.schema_version == 4
        assert not plan.design.is_applicable and plan.children == children == ()
        assert ParameterEvaluationPlan.from_dict(plan.to_dict()) == plan
        with pytest.raises(ValueError, match="no point to bind"):
            plan.bind_point(reference, 0, repository_root=context.repository.root)
