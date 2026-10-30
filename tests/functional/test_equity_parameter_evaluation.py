"""Legacy parameter computation is rejected; archived facts retain independent validation."""
import json

import pytest

from strategy_runtime.equity import equity_hash
from czsc_trader.research_tools import ParameterEvaluationPlan
from czsc_trader.research_tools.equity_assessment import build_equity_assessment_payload
from czsc_trader.research_tools.parameter_evaluation import validate_parameter_request
from czsc_trader.application.backtest_service import run_backtest
from equity_test_support import setup_formal_equity
from equity_test_support import archived_formal_account_bytes as archived_formal_account_bytes


from contextlib import contextmanager
from dataclasses import replace


@contextmanager
def equity_plan(tmp_path, *, applicable=True):
    """Yield one explicit V3 execution owner and its authenticated prospective plan."""
    from strategy_evaluator import (AssessmentCandidate, ParameterAxis, RealDomain, BoundedLocalStep,
        RelativeChangeLimit, ParameterNeighborhoodProtocol, ParameterNeighborhoodRequest,
        ParameterNeighborhoodSpace, build_parameter_neighborhood_design)
    from strategy_manager import CandidateDerivation, CandidateDerivationKind, CandidateEvidence
    from strategy_runtime import equity_source_hash
    from czsc_trader.application import publish_evidence
    from czsc_trader.research_tools import MaterialEvidenceWrite, EvaluationLineage, ResearchExecutionSession
    from equity_test_support import setup_v3

    context, request, _, _ = setup_v3(tmp_path)
    source = request.candidate.source_root
    (source / "strategy.py").write_text(
        "from strategy_runtime.equity_definition import EquityDecision\n"
        "from strategy_runtime.equity_replay import StepResult, StateRecord\n"
        "def step(ctx, state):\n"
        "    active = int(ctx.history.last()['Close'] >= ctx.parameters['threshold'])\n"
        "    return StepResult(EquityDecision.from_facts(0 if ctx.portfolio.quantity else active, "
        "'threshold comparison', facts={'threshold': ctx.parameters['threshold']}, "
        "next_watch='next completed bar'), cycle_values=StateRecord())\n", encoding="utf-8")
    definition = replace(request.candidate.definition, parameters_json='{"threshold":10.0}',
        parameter_schema_json='{"threshold":{"type":"number","minimum":1,"maximum":20}}',
        source_sha256=equity_source_hash(source, ("strategy.py",)))
    request = replace(request, candidate=replace(request.candidate, definition=definition))
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        center = context.evaluation.prepare(request, execution=execution)
        def material(name, content):
            return publish_evidence(context, MaterialEvidenceWrite(request.experiment, name, content,
                "application/json", "json"), execution=execution)
        mapping, feasible = material("map", b"{}"), material("feasibility", b"{}")
        axes = (ParameterAxis("threshold", 10.0, RealDomain(1., 20.),
            BoundedLocalStep(RelativeChangeLimit(.05)), ("threshold",), "price"),) if applicable else ()
        design = build_parameter_neighborhood_design(ParameterNeighborhoodRequest(
            AssessmentCandidate("S999-C0001", definition.content_identity.content_sha256),
            ParameterNeighborhoodProtocol(), ParameterNeighborhoodSpace(axes, mapping.sha256, feasible.sha256)),
            feasibility=lambda values: True).design
        children = tuple(context.evaluation.prepare(replace(center.request, candidate=replace(center.candidate,
            candidate_id=f"C{index + 2:04}", definition=replace(definition,
                parameters_json=json.dumps({v.name: v.value for v in point.values})))), execution=execution)
            for index, point in enumerate(design.points))
        plan = ParameterEvaluationPlan.create(design, center, children, mapping_evidence=mapping,
            feasibility_evidence=feasible, dataflows=context.data, execution=execution)
        ref = material("plan", json.dumps(plan.to_dict()).encode())
        bound = []
        for index, child in enumerate(children):
            derivation = CandidateDerivation(center.candidate.key, center.candidate.content_identity.content_sha256,
                child.candidate.key, child.candidate.content_identity.content_sha256, CandidateDerivationKind.PARAMETERS,
                {v.name: v.value for v in design.points[index].values}, design.protocol.sha256,
                CandidateEvidence(ref.repository_path, ref.sha256))
            proposed = replace(child.request, lineage=EvaluationLineage(derivation,
                plan.bind_point(ref, index, repository_root=context.repository.root)))
            bound.append(context.evaluation.prepare(proposed, execution=execution))
        yield context, center, plan, ref, tuple(bound), execution


def test_legacy_equity_computation_entry_points_reject_before_data_access(tmp_path):
    context, request, _, calls = setup_formal_equity(tmp_path)
    from strategy_evaluator import (AssessmentCandidate, ParameterNeighborhoodProtocol,
        ParameterNeighborhoodRequest, ParameterNeighborhoodSpace, build_parameter_neighborhood_design)
    from czsc_trader.application import publish_evidence
    from czsc_trader.research_tools import MaterialEvidenceWrite
    mapping = publish_evidence(context, MaterialEvidenceWrite(request.experiment, "mapping",
        b"{}", "application/json", "json"))
    feasible = publish_evidence(context, MaterialEvidenceWrite(request.experiment, "feasibility",
        b"{}", "application/json", "json"))
    design = build_parameter_neighborhood_design(ParameterNeighborhoodRequest(
        AssessmentCandidate(f"{request.candidate.strategy_id}-{request.candidate.candidate_id}", request.candidate.content_identity.content_sha256),
        ParameterNeighborhoodProtocol(), ParameterNeighborhoodSpace((), mapping.sha256, feasible.sha256)),
        feasibility=lambda _: True).design
    with pytest.raises(TypeError, match="session-owned"):
        ParameterEvaluationPlan.create(design, request, (), mapping_evidence=mapping,
            feasibility_evidence=feasible, dataflows=context.data)
    with pytest.raises(TypeError, match="session-owned"):
        validate_parameter_request(request, context.data)
    with pytest.raises(TypeError, match="ResearchExecutionSession"):
        run_backtest(context, request.candidate, request)
    assert calls == []


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
