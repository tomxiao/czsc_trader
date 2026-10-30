"""Real equity stage-A/C evidence survives source cleanup and is recomputed."""
from dataclasses import replace
import json

import pytest
from strategy_evaluator import assess_candidates, compare_candidates
from strategy_evaluator import research_models as m
from strategy_runtime import canonical_sha256
from czsc_trader.application import (assemble_delivery, validate_delivery, publish_evidence,
                                    register_candidate, CandidateRegistrationRequest)
from czsc_trader.research_tools import EvaluationEvidenceWrite, MaterialEvidenceWrite, build_assessment_evidence
from czsc_trader.research_tools import delivery as d
from test_equity_parameter_evaluation import equity_plan
from test_assessment_delivery import assessment_request, comparison_request
from test_research_delivery import content, published


@pytest.mark.parametrize("applicable", [True, False])
def test_equity_stage4_authenticates_plan_targets_and_archived_accounts(tmp_path, applicable):
    with equity_plan(tmp_path, applicable=applicable) as (research, request, plan, plan_ref, children, execution):
        _check_equity_delivery(research, request, plan, plan_ref, children, execution, applicable)


def _check_equity_delivery(research, request, plan, plan_ref, children, execution, applicable):
    context = research.repository
    evidence, refs = [], []
    pressure = research.evaluation.prepare(replace(request.request, scenario_id="PRESSURE", measurement_tier="STRESS",
        fee_rate=request.request.fee_rate * 2, input_binding=None, audit_inputs_sha256=None), execution=execution)
    for index, item in enumerate((request, pressure, *children)):
        outcome, = research.evaluation.evaluate_many((item,), execution=execution)
        assert outcome.result is not None, outcome.error
        result = outcome.result
        evidence.extend(build_assessment_evidence(item, result, execution=execution))
        refs.append(publish_evidence(research, EvaluationEvidenceWrite(item.experiment, f"account-{index}", item, result), execution=execution))
    register_candidate(context, CandidateRegistrationRequest(request.candidate, request.experiment, (refs[0],), ()))
    links = tuple(m.PerturbationLink(plan.design.center, row.candidate, 1.,
        canonical_sha256(child.request.lineage.derivation.to_dict()), child.request.lineage.parameter_binding.point)
        for child, row in zip(children, evidence[2:], strict=True))
    seed = assessment_request((evidence[0],))
    assessment = replace(seed, protocol=replace(seed.protocol, baseline_window=request.request.window_id,
        standard_scenario=request.request.scenario_id, stress_scenario=pressure.request.scenario_id),
        perturbations=links, evidence=tuple(evidence), incomplete=(), parameter_designs=(plan.design,))
    panel = assess_candidates(assessment)
    targets = (
        m.ResearchTarget("center", m.ResearchMetric.NET_ANNUAL_RETURN, lower=m.ConstantBound(-1., True)),
        m.ParameterNeighborhoodTarget("neighborhood", 1, 1,
            (m.ResearchTarget("point-return", m.ResearchMetric.NET_ANNUAL_RETURN, lower=m.ConstantBound(-1., True)),),
            (m.ResearchTarget("point-dd", m.ResearchMetric.DRAWDOWN_MAGNITUDE, upper=m.ConstantBound(1., True)),)),
        m.ResearchTarget("stress", m.ResearchMetric.NET_ANNUAL_RETURN, lower=m.ConstantBound(-1., True),
                         scope=m.TargetScope.STRESS, one_way_cost=pressure.request.fee_rate),
    )
    comparison = replace(comparison_request(panel), targets=m.ResearchTargets(targets, 60))
    confirmation = publish_evidence(research, MaterialEvidenceWrite(request.experiment, "confirmed-targets",
        b'{"engineering_fixture":true}', "application/json", "json"))
    confirmed = d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED, confirmation)
    mandate = d.ResearchMandate((
        d.MandateItem("targets", d.MandateItemKind.OBJECTIVE, "Synthetic limits", confirmed,
                     d.PerformanceRequirement(targets)),
        d.MandateItem("benchmark", d.MandateItemKind.BENCHMARK, "Equity buy hold", confirmed,
                     d.BenchmarkRequirement(request.request.benchmark)),
        d.MandateItem("frequency", d.MandateItemKind.EXECUTION, "Session frequency", confirmed,
                     d.NumericRequirement("frequency_window_days", "sessions", lower=60., upper=60.)),
    ))
    assert d.ResearchMandate.from_dict(json.loads(json.dumps(mandate.to_dict()))) == mandate
    mandate_receipt = assemble_delivery(context, d.DeliveryDefinition(research.batch, d.DeliveryStage.MANDATE, 1),
                                        content(mandate)).receipt
    identity = d.CandidateIdentityRef(request.candidate.key, request.candidate.content_identity.content_sha256)
    entry = d.CandidateEntry(identity, "Synthetic timing", "Check archived facts",
                            (d.EvaluationEvidenceRef(refs[0], (evidence[0].evaluation_id,)),))
    candidates = assemble_delivery(context, d.DeliveryDefinition(research.batch, d.DeliveryStage.CANDIDATES, 1),
        content(d.CandidateSet((entry,), (request.candidate.key,), (), "One synthetic center"))).receipt
    payload = d.CandidateAssessmentDelivery(candidates.reference, mandate_receipt.reference,
        assessment, panel, comparison, compare_candidates(comparison),
        tuple(d.TargetMandateBinding(t.target_id, "targets") for t in targets), "frequency", "benchmark",
        "Engineering closure only; no research selection", tuple(refs), (), parameter_plans=(plan_ref,))
    definition = d.DeliveryDefinition(research.batch, d.DeliveryStage.ASSESSMENT, 1,
                                     predecessors=(candidates.reference, mandate_receipt.reference))
    assembled = assemble_delivery(context, definition, content(payload))
    assert assembled.validation.status is d.ValidationStatus.PASS
    assert assembled.validation.stats.accounts_authenticated == 2 + len(children)
    assert validate_delivery(context, assembled.receipt.reference).status is d.ValidationStatus.PASS
    check = payload.comparison.rows[0].target_checks[1]
    assert check.status is (m.TargetCheckStatus.PASSED if applicable else m.TargetCheckStatus.NOT_APPLICABLE)
    relaxed = replace(targets[0], lower=m.ConstantBound(-2., True))
    altered = replace(comparison, targets=m.ResearchTargets((relaxed, *targets[1:]), 60))
    with pytest.raises(d.DeliveryValidationError, match="confirmed mandate|targets must be preserved"):
        assemble_delivery(context, replace(definition, revision=2), content(replace(payload,
            comparison_request=altered, comparison=compare_candidates(altered))))
    # Remove only individually named fixture sources; the delivered snapshot must stand alone.
    (request.candidate.source_root / "strategy.py").unlink()
    originals = {ref.resolve(context.root) for ref in (plan_ref, plan.mapping_evidence, plan.feasibility_evidence, *refs)}
    for original in originals:
        original.unlink()
    assert validate_delivery(context, assembled.receipt.reference).status is d.ValidationStatus.PASS
    saved = published(context, assembled.receipt)
    assert (saved / plan.mapping_evidence.path).is_file()
    assert (saved / plan.feasibility_evidence.path).is_file()
