"""Real equity stage-A/C evidence survives source cleanup and is recomputed."""
from dataclasses import replace
import json

import pytest
from strategy_evaluator import (
    assess_candidates, compare_candidates, CandidatePerformanceAssessmentRequest,
    project_parameter_performance, DeclaredParameterPointSet, DeclaredPointSetComparisonContract,
)
from strategy_evaluator import research_models as m
from strategy_runtime import canonical_sha256
from czsc_trader.application import (assemble_delivery, validate_delivery, publish_evidence,
                                    register_candidate, CandidateRegistrationRequest)
from czsc_trader.research_tools import EvaluationEvidenceWrite, MaterialEvidenceWrite, build_assessment_evidence
from czsc_trader.research_tools import delivery as d
from equity_parameter_support import equity_plan
from test_assessment_delivery import assessment_request, comparison_request
from test_research_delivery import content, published


@pytest.mark.parametrize("applicable", [True, False])
@pytest.mark.parametrize("ranking", ["research-ranking-v4", "research-ranking-v5", "research-ranking-v6"])
def test_equity_stage4_authenticates_plan_targets_and_archived_accounts(tmp_path, applicable, ranking):
    with equity_plan(tmp_path, applicable=applicable) as (research, request, plan, plan_ref, children, execution):
        _check_equity_delivery(research, request, plan, plan_ref, children, execution, applicable, ranking)


def test_declared_point_set_delivery_reuses_original_bindings_and_rejects_forged_numeric_facts(tmp_path):
    with equity_plan(tmp_path) as (research, request, plan, plan_ref, children, execution):
        _check_equity_delivery(research, request, plan, plan_ref, children, execution, True,
                               "research-ranking-v6", declared=True)


def _check_equity_delivery(research, request, plan, plan_ref, children, execution, applicable, ranking,
                           *, declared=False):
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
    if ranking == "research-ranking-v6":
        protocol = assessment.protocol.to_dict()
        protocol["type"] = "CalmarSelfCheckProtocol"
        assessment = replace(assessment, protocol=m.CalmarSelfCheckProtocol.from_dict(protocol))
    if declared:
        geometry = DeclaredParameterPointSet(plan.design, (plan.design.point_count - 1,), "d" * 64)
        assessment = replace(assessment, parameter_designs=(geometry,),
            perturbations=tuple(x for x in assessment.perturbations if x.parameter_point.point_index in geometry.point_indices),
            evidence=tuple(x for x in assessment.evidence if x.parent is None
                           or x.parameter_point.point_index in geometry.point_indices))
        assessment_input = CandidatePerformanceAssessmentRequest(
            replace(assessment, evidence=tuple(x for x in assessment.evidence if x.parent is None)),
            tuple(project_parameter_performance(x) for x in assessment.evidence if x.parent is not None))
    else:
        assessment_input = assessment
    panel = assess_candidates(assessment_input)
    performance_metric = m.ResearchMetric.NET_CALMAR if ranking == "research-ranking-v6" else m.ResearchMetric.NET_ANNUAL_RETURN
    performance_lower = -1e100 if ranking == "research-ranking-v6" else -1.
    targets = (
        m.ResearchTarget("center", m.ResearchMetric.NET_ANNUAL_RETURN, lower=m.ConstantBound(-1., True)),
        m.ParameterNeighborhoodTarget("neighborhood", 1, 1,
            (m.ResearchTarget("point-performance", performance_metric, lower=m.ConstantBound(performance_lower, True)),),
            (m.ResearchTarget("point-dd", m.ResearchMetric.DRAWDOWN_MAGNITUDE, upper=m.ConstantBound(1., True)),)),
        m.ResearchTarget("stress", performance_metric, lower=m.ConstantBound(performance_lower, True),
                         scope=m.TargetScope.STRESS, one_way_cost=pressure.request.fee_rate),
        m.ResearchTarget("calmar", m.ResearchMetric.NET_CALMAR, lower=m.BenchmarkBound(1.5, False),
                         one_way_cost=request.request.fee_rate),
    )
    comparison = replace(comparison_request(panel), targets=m.ResearchTargets(targets, 60))
    if ranking in ("research-ranking-v5", "research-ranking-v6"):
        replacements = {
            m.ResearchMetric.NET_ANNUAL_RETURN: m.ResearchMetric.NET_CALMAR,
            m.ResearchMetric.PARAMETER_RETURN_Q10: m.ResearchMetric.PARAMETER_CALMAR_Q10,
        }
        if ranking == "research-ranking-v6":
            replacements.update({m.ResearchMetric.ROLLING_EXCESS_Q10: m.ResearchMetric.ROLLING_EXCESS_CALMAR_Q10,
                                 m.ResearchMetric.STRESS_ANNUAL_LOSS: m.ResearchMetric.STRESS_CALMAR_LOSS})
        bins = tuple(replace(item, metric=replacements.get(item.metric, item.metric))
                     for item in comparison.policy.bins)
        scale = m.CommonNeighborhoodComparisonContract(m.RelativeChangeLimit(.05), ())
        comparison = m.CalmarComparisonRequest(comparison.candidates, comparison.targets, panel,
            replace(comparison.policy, bins=bins, formula_version=ranking), assessment.parameter_designs,
            DeclaredPointSetComparisonContract("d" * 64, scale) if declared else scale)
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
        assessment_input, panel, comparison, compare_candidates(comparison),
        tuple(d.TargetMandateBinding(t.target_id, "targets") for t in targets), "frequency", "benchmark",
        "Engineering closure only; no research selection", tuple(refs), (), parameter_plans=(plan_ref,))
    definition = d.DeliveryDefinition(research.batch, d.DeliveryStage.ASSESSMENT, 1,
                                     predecessors=(candidates.reference, mandate_receipt.reference),
                                     schema_version=15 if declared else {"research-ranking-v4": 12,
                                         "research-ranking-v5": 13, "research-ranking-v6": 14}[ranking])
    assembled = assemble_delivery(context, definition, content(payload))
    assert assembled.validation.status is d.ValidationStatus.PASS
    assert assembled.validation.stats.accounts_authenticated == 2 + len(children)
    assert validate_delivery(context, assembled.receipt.reference).status is d.ValidationStatus.PASS
    if declared:
        assert assembled.receipt.schema_version == 15
        assert d.DeliveryContent.from_dict(content(payload).to_dict()).payload == payload
        point, = assessment_input.parameter_evidence
        assert point.parameter_point == plan.design.bind_point(plan.design.point_count - 1)
        forged = replace(assessment_input, parameter_evidence=(replace(point,
            performance=replace(point.performance, annual_return=point.performance.annual_return + .25)),))
        with pytest.raises(d.DeliveryValidationError, match="saved evaluation facts"):
            assemble_delivery(context, replace(definition, revision=2),
                              content(replace(payload, assessment_request=forged)))
    if not declared and ranking in ("research-ranking-v5", "research-ranking-v6"):
        assert assembled.receipt.schema_version == (14 if ranking == "research-ranking-v6" else 13)
        assert d.DeliveryContent.from_dict(content(payload).to_dict()).payload == payload
        with pytest.raises(d.DeliveryValidationError, match="ranking version"):
            assemble_delivery(context, replace(definition, revision=2, schema_version=12), content(payload))
        with pytest.raises(d.DeliveryValidationError, match="designs must equal"):
            changed_request = replace(assessment, parameter_designs=(), perturbations=(),
                                      evidence=tuple(evidence[:2]))
            assemble_delivery(context, replace(definition, revision=2),
                              content(replace(payload, assessment_request=changed_request)))
    if not declared and ranking == "research-ranking-v6":
        with pytest.raises(d.DeliveryValidationError, match="ranking version"):
            assemble_delivery(context, replace(definition, revision=2, schema_version=13), content(payload))
        old_protocol = assessment.protocol.to_dict()
        old_protocol["type"] = "NeighborhoodSelfCheckProtocol"
        with pytest.raises(d.DeliveryValidationError, match="ranking version"):
            assemble_delivery(context, replace(definition, revision=2), content(replace(payload,
                assessment_request=replace(assessment, protocol=m.NeighborhoodSelfCheckProtocol.from_dict(old_protocol)))))
        row = panel.rows[0]
        rolling = replace(row.rolling_calmar_excess_q10, status=m.DiagnosticStatus.AVAILABLE,
                          value=123.456, reason=None)
        forged_panel = replace(panel, rows=(replace(row, rolling_calmar_excess_q10=rolling),))
        forged_request = replace(comparison, panel=forged_panel)
        forged = replace(payload, assessment=forged_panel, comparison_request=forged_request,
                         comparison=compare_candidates(forged_request))
        with pytest.raises(d.DeliveryValidationError, match="recomputation"):
            assemble_delivery(context, replace(definition, revision=2), content(forged))
    check = payload.comparison.rows[0].target_checks[1]
    expected = m.TargetCheckStatus.PASSED if applicable else m.TargetCheckStatus.NOT_APPLICABLE
    if ranking == "research-ranking-v6" and applicable:
        assert all(point.joint_checks[0].target.metric is m.ResearchMetric.NET_CALMAR for point in check.points)
        if any(point.joint_checks[0].status is m.TargetCheckStatus.INDETERMINATE for point in check.points):
            expected = m.TargetCheckStatus.INDETERMINATE
    assert check.status is expected
    calmar = payload.comparison.rows[0].target_checks[-1]
    assert calmar.target == targets[-1]
    assert calmar.evaluation_ids == (evidence[0].evaluation_id,)
    altered_calmar = replace(targets[-1], lower=m.BenchmarkBound(1.6, False))
    altered = replace(comparison, targets=m.ResearchTargets((*targets[:-1], altered_calmar), 60))
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
