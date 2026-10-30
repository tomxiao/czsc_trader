"""Current account parameter plans bind prepared inputs and real prospective points."""
import json


from czsc_trader.research_tools import ParameterEvaluationPlan


from contextlib import contextmanager
from dataclasses import replace


@contextmanager
def equity_plan(tmp_path, *, applicable=True):
    """Yield one explicit account execution owner and its authenticated prospective plan."""
    from strategy_evaluator import (AssessmentCandidate, ParameterAxis, RealDomain, BoundedLocalStep,
        RelativeChangeLimit, ParameterNeighborhoodProtocol, ParameterNeighborhoodRequest,
        ParameterNeighborhoodSpace, build_parameter_neighborhood_design)
    from strategy_manager import CandidateDerivation, CandidateDerivationKind, CandidateEvidence
    from strategy_runtime import equity_source_hash
    from czsc_trader.application import publish_evidence
    from czsc_trader.research_tools import MaterialEvidenceWrite, EvaluationLineage, ResearchExecutionSession
    from equity_test_support import setup_account_research

    context, request, _, _ = setup_account_research(tmp_path)
    source = request.candidate.source_root
    (source / "strategy.py").write_text(
        "from strategy_runtime import AccountDecision\n"
        "from strategy_runtime import AccountStepResult, StateRecord\n"
        "def step(ctx, state):\n"
        "    active = int(ctx.history.last()['Close'] >= ctx.parameters['threshold'])\n"
        "    return AccountStepResult(AccountDecision.from_facts(0 if ctx.portfolio.quantity else active, "
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
