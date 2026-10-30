"""Equity neighborhood plans bind real candidates, prepared assets and archived facts."""
from dataclasses import replace
import json

import pytest

from strategy_evaluator import AssessmentCandidate, ParameterAxis, RealDomain, BoundedLocalStep, RelativeChangeLimit
from strategy_evaluator import ParameterNeighborhoodProtocol, ParameterNeighborhoodRequest, ParameterNeighborhoodSpace
from strategy_evaluator import build_parameter_neighborhood_design
from strategy_manager import CandidateDerivation, CandidateDerivationKind, CandidateEvidence
from strategy_runtime import equity_source_hash
from strategy_runtime.equity import equity_hash
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite, ParameterEvaluationPlan, EvaluationLineage
from czsc_trader.research_tools.equity_assessment import build_equity_assessment_payload
from czsc_trader.research_tools.parameter_evaluation import validate_parameter_request
from equity_test_support import setup_formal_equity
from equity_test_support import archived_formal_account_bytes as archived_formal_account_bytes


def equity_plan(tmp_path, *, applicable=True, auxiliary=False):
    if auxiliary:
        from equity_test_support import setup_auxiliary
        context, request, _, _ = setup_auxiliary(tmp_path)
    else:
        context, request, _, _ = setup_formal_equity(tmp_path)
    source = request.candidate.source_root
    (source / "strategy.py").write_text(
        'from strategy_runtime.equity_definition import EquityDecision\n'
        'def decide(ctx):\n'
        '    active = int(ctx.history.Close.iloc[-1] >= ctx.parameters["threshold"])\n'
        '    return EquityDecision.from_facts(0 if ctx.portfolio.quantity else active, "threshold comparison", '
        'facts={"close": float(ctx.history.Close.iloc[-1]), "threshold": ctx.parameters["threshold"]}, '
        'next_watch="next completed bar")\n', encoding="utf-8")
    definition = replace(request.candidate.definition, parameters_json='{"threshold":10.0}',
        parameter_schema_json='{"threshold":{"type":"number","minimum":1,"maximum":20}}',
        source_sha256=equity_source_hash(source, ("strategy.py",)))
    request = context.evaluation.prepare(replace(request, candidate=replace(request.candidate, definition=definition)))
    def material(name):
        return publish_evidence(context, MaterialEvidenceWrite(request.experiment, name, b'{}', "application/json", "json"))
    mapping, feasible = material("map"), material("feasibility")
    axes = (ParameterAxis("threshold", 10.0, RealDomain(1., 20.), BoundedLocalStep(RelativeChangeLimit(.05)),
                          ("threshold",), "price"),) if applicable else ()
    design = build_parameter_neighborhood_design(ParameterNeighborhoodRequest(
        AssessmentCandidate("S999-C0001", definition.content_identity.content_sha256), ParameterNeighborhoodProtocol(),
        ParameterNeighborhoodSpace(axes, mapping.sha256, feasible.sha256)), feasibility=lambda values: True).design
    children = tuple(context.evaluation.prepare(replace(request, candidate=replace(request.candidate,
        candidate_id=f"C{index + 2:04}", definition=replace(definition,
        parameters_json=json.dumps({v.name: v.value for v in point.values}))), input_binding=None, lineage=None))
        for index, point in enumerate(design.points))
    plan = ParameterEvaluationPlan.create(design, request, children, mapping_evidence=mapping,
        feasibility_evidence=feasible, dataflows=context.data)
    ref = publish_evidence(context, MaterialEvidenceWrite(request.experiment, "plan",
        json.dumps(plan.to_dict()).encode(), "application/json", "json"))
    bound = []
    for index, child in enumerate(children):
        derivation = CandidateDerivation(request.candidate.key, request.candidate.content_identity.content_sha256,
            child.candidate.key, child.candidate.content_identity.content_sha256, CandidateDerivationKind.PARAMETERS,
            {v.name: v.value for v in design.points[index].values}, design.protocol.sha256,
            CandidateEvidence(ref.repository_path, ref.sha256))
        bound.append(replace(child, lineage=EvaluationLineage(derivation,
            plan.bind_point(ref, index, repository_root=context.repository.root))))
    return context, request, plan, ref, tuple(bound)


@pytest.mark.parametrize("applicable,auxiliary", [(True, False), (False, False), (True, True)])
def test_equity_parameter_plan_preserves_payload_inputs_and_point_mapping(tmp_path, applicable, auxiliary):
    context, request, plan, reference, children = equity_plan(tmp_path, applicable=applicable, auxiliary=auxiliary)
    assert plan.schema_version == 4
    assert ParameterEvaluationPlan.from_dict(plan.to_dict()) == plan
    assert bool(children) == applicable
    assert bool(request.input_binding.auxiliary_inputs) == auxiliary
    center = context.evaluation.evaluate(request)
    assert build_equity_assessment_payload(center.payload)[0].candidate == plan.design.center
    for index, child in enumerate(children):
        validate_parameter_request(child, context.data)
        result = context.evaluation.evaluate(child)
        evidence = build_equity_assessment_payload(result.payload)[0]
        assert evidence.parent == plan.design.center
        assert evidence.parameter_point == plan.design.bind_point(index)
    if children:
        with pytest.raises(ValueError, match="nonparameter context"):
            validate_parameter_request(replace(children[0], initial_cash=1001.), context.data)
        reference.resolve(context.repository.root).write_bytes(b"corrupt")
        with pytest.raises(ValueError, match="content differs"):
            validate_parameter_request(children[0], context.data)


@pytest.mark.parametrize("field", ["definition", "benchmark", "benchmark-strategy", "version", "binding", "window", "audit", "metrics",
                                   "target", "quantity", "orphan-expired"])
def test_archived_equity_adapter_rejects_rehashed_inconsistent_facts(archived_formal_account_bytes, field):
    payload = json.loads(archived_formal_account_bytes)
    if field == "definition":
        payload["request"]["candidate_definition"]["parameters_json"] = '{"enter":0}'
    elif field == "benchmark":
        payload["request"]["benchmark_sha256"] = "0" * 64
    elif field == "benchmark-strategy":
        payload["runs"]["buy_hold"]["decisions"][0]["target"] = 0
    elif field == "version":
        payload["schema_version"] = 1
    elif field == "target":
        payload["runs"]["candidate"]["decisions"][0]["target"] = -1
    elif field == "quantity":
        payload["runs"]["candidate"]["decisions"][0]["quantity"] = 999
    elif field == "orphan-expired":
        payload["runs"]["candidate"]["orders"].append({"order_id": "orphan", "decision_id": "absent",
            "side": "SELL", "quantity": 999, "status": "EXPIRED", "reason": "NOT_TRADABLE",
            "valid_start": payload["request"]["window"]["start"], "valid_end": payload["request"]["window"]["end"],
            "limit_price": None})
    elif field == "binding":
        payload["request"]["input_binding"]["content_identities"][0][1] = "0" * 64
    elif field == "window":
        payload["runs"]["candidate"]["account_points"].pop()
    elif field == "audit":
        payload["audit_inputs"]["bars"][3]["Close"] += 1
    else:
        payload["runs"]["candidate"]["metrics"]["annualized_return"] += 1
    payload["request_hash"] = equity_hash(payload["request"])
    payload["evaluation_identity"]["protocol_sha256"] = payload["request_hash"]
    from strategy_runtime import canonical_sha256
    payload["evaluation_id"] = canonical_sha256(payload["evaluation_identity"])
    with pytest.raises(ValueError):
        build_equity_assessment_payload(payload)
