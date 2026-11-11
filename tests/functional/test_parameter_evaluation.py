# Risk ownership: TDR-14
"""Current V4 parameter plans bind caller-declared points to owned accounts."""
from dataclasses import replace
import json

import pytest

from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import (
    EvaluationEvidenceWrite, ParameterEvaluationPlan, build_assessment_evidence,
)
from equity_parameter_support import equity_plan


@pytest.fixture
def prepared_parameter_plan(tmp_path):
    with equity_plan(tmp_path) as prepared:
        yield prepared


def test_TDR_14_C01_published_parameter_point_reaches_account_and_assessment(prepared_parameter_plan):
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


def test_TDR_14_C03_plan_rejects_changed_nonparameter_execution_context(prepared_parameter_plan):
    context, center, plan, _, children, execution = prepared_parameter_plan
    changed = context.evaluation.prepare(replace(children[0].request,
        lineage=None, initial_cash=children[0].request.initial_cash + 1,
        audit_inputs_sha256=None), execution=execution)
    other = context.evaluation.prepare(replace(children[1].request, lineage=None), execution=execution)
    with pytest.raises(ValueError, match="nonparameter context differs"):
        ParameterEvaluationPlan.create(plan.design, center, (changed, other),
            mapping_evidence=plan.mapping_evidence, feasibility_evidence=plan.feasibility_evidence,
            dataflows=context.data, execution=execution)


def test_TDR_14_C05_zero_point_plan_is_explicit_and_cannot_bind_fabricated_child(tmp_path):
    with equity_plan(tmp_path, applicable=False) as (context, center, plan, reference, children, execution):
        assert plan.schema_version == 4
        assert not plan.design.is_applicable and plan.children == children == ()
        assert ParameterEvaluationPlan.from_dict(plan.to_dict()) == plan
        with pytest.raises(ValueError, match="no point to bind"):
            plan.bind_point(reference, 0, center, execution=execution)


def test_TDR_14_C09_binding_reuses_preparation_and_preserves_exact_execution_contract(
        prepared_parameter_plan, monkeypatch):
    from czsc_trader.research_tools import equity_replay
    from czsc_trader.research_tools.parameter_evaluation import validate_parameter_request

    context, _, plan, reference, children, execution = prepared_parameter_plan
    child = context.evaluation.prepare(replace(children[0].request, lineage=None), execution=execution)
    changed = context.evaluation.prepare(replace(child.request, initial_cash=child.request.initial_cash + 1,
        audit_inputs_sha256=None), execution=execution)

    def unexpected(*args, **kwargs):
        raise AssertionError("binding repeated expensive preparation")

    monkeypatch.setattr(type(child.candidate), "verify", unexpected)
    monkeypatch.setattr(equity_replay, "_fetch_products", unexpected)
    monkeypatch.setattr(context.data, "prepare", unexpected)
    bound = plan.bind_point(reference, 0, child, execution=execution)
    assert bound.snapshot is child.snapshot
    assert bound.benchmark_identity is child.benchmark_identity
    assert bound.request.prepared is child.request.prepared
    assert bound.request.input_binding is child.request.input_binding
    contract = json.loads(bound.contract_content)
    expected = equity_replay._bytes(bound.request._identity_with_sources(
        context.evaluation.execution_spec, contract["engine_sources"]))
    assert bound.contract_content == expected
    assert bound.contract_content == children[0].contract_content
    assert bound.request.lineage.derivation.changes == {x.name: x.value for x in plan.design.points[0].values}
    validate_parameter_request(bound, context.data, execution=execution)
    with pytest.raises(ValueError, match="actual child content"):
        plan.bind_point(reference, 1, child, execution=execution)
    with pytest.raises(ValueError, match="nonparameter context"):
        plan.bind_point(reference, 0, changed, execution=execution)
    with pytest.raises(ValueError, match="not issued"):
        plan.bind_point(reference, 0, replace(child), execution=execution)
    with pytest.raises(ValueError, match="prior lineage"):
        plan.bind_point(reference, 0, bound, execution=execution)
    with pytest.raises(ValueError, match="ParameterEvaluationPlan.bind_point"):
        context.evaluation.prepare(bound.request, execution=execution)
