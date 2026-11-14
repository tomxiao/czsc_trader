# Risk ownership: TDR-12
"""Mixed typed neighborhoods reach Calmar publication on both equity markets."""

from contextlib import contextmanager
from dataclasses import replace
import json

import pytest
from dataflows import BarFrequency, MarketId
from strategy_evaluator import research_models as m
from strategy_evaluator import (
    AssessmentCandidate, BoundedLocalStep, CandidatePerformanceAssessmentRequest,
    CategoricalDomain, DeclaredParameterPointSet, DeclaredPointSetComparisonContract,
    ExplicitValues, IntegerDomain, ParameterAxis, ParameterNeighborhoodProtocol,
    ParameterNeighborhoodRequest, ParameterNeighborhoodSpace, RealDomain,
    RelativeChangeLimit, assess_candidates, build_parameter_neighborhood_design,
    compare_candidates, project_parameter_performance,
)
from strategy_runtime import canonical_sha256, equity_source_hash
from czsc_trader.application import (
    CandidateRegistrationRequest, assemble_delivery, publish_evidence,
    register_candidate, validate_delivery,
)
from czsc_trader.research_tools import (
    EvaluationEvidenceWrite, MaterialEvidenceWrite,
    ParameterEvaluationPlan, ResearchExecutionSession, build_assessment_evidence,
)
from czsc_trader.research_tools import delivery as d
from account_parity_support import setup_account
from assessment_delivery_support import assessment_request, comparison_request
from test_research_delivery import content


@contextmanager
def mixed_plan(tmp_path, market):
    context, request = setup_account(tmp_path, market, BarFrequency.DAILY)
    source = request.candidate.source_root
    (source / "strategy.py").write_text(
        "from strategy_runtime import AccountDecision, AccountStepResult, StateRecord\n"
        "def step(ctx, state):\n"
        "    p = ctx.parameters\n"
        "    target = float(10. >= p['threshold']) if not ctx.portfolio.quantity else 0.\n"
        "    return AccountStepResult(AccountDecision.from_facts(target, 'mixed parameter fixture', "
        "facts={'lookback':p['lookback'], 'probe':p['probe'], 'mode':p['mode']}, "
        "next_watch='next session'), cycle_values=StateRecord())\n", encoding="utf-8")
    parameters = {"threshold": 9.0, "lookback": 20, "probe": 3, "mode": "hold"}
    schema = {
        "threshold": {"type": "number", "minimum": 1, "maximum": 20},
        "lookback": {"type": "integer", "minimum": 1, "maximum": 40},
        "probe": {"type": "integer", "minimum": 1, "maximum": 10},
        "mode": {"type": "string", "enum": ["hold", "exit"]},
    }
    definition = replace(request.candidate.definition, parameters_json=json.dumps(parameters),
        parameter_schema_json=json.dumps(schema), source_sha256=equity_source_hash(source, ("strategy.py",)))
    request = replace(request, candidate=replace(request.candidate, definition=definition))
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        center = context.evaluation.prepare(request, execution=execution)

        def material(name, payload):
            return publish_evidence(context, MaterialEvidenceWrite(request.experiment, name,
                payload, "application/json", "json"), execution=execution)

        mapping, feasible = material("mapping", b"{}"), material("feasibility", b"{}")
        local = BoundedLocalStep(RelativeChangeLimit(.05))
        axes = (
            ParameterAxis("threshold", 9.0, RealDomain(1., 20.), local, ("threshold",), "price"),
            ParameterAxis("lookback", 20, IntegerDomain(1, 40), local, ("lookback",), "sessions"),
            ParameterAxis("probe", 3, IntegerDomain(1, 10), local, ("probe",), "sessions"),
            ParameterAxis("mode", "hold", CategoricalDomain(("hold", "exit")),
                          ExplicitValues(("hold",)), ("mode",), "category"),
        )
        source_design = build_parameter_neighborhood_design(ParameterNeighborhoodRequest(
            AssessmentCandidate("S999-C0001", definition.content_identity.content_sha256),
            ParameterNeighborhoodProtocol(), ParameterNeighborhoodSpace(axes, mapping.sha256, feasible.sha256)),
            feasibility=lambda values: True).design
        assert source_design.point_count == 8
        geometry = DeclaredParameterPointSet(source_design, (0, 7), "d" * 64)
        selected = tuple({value.name: value.value for value in point.values} for point in geometry.points)
        assert {point["lookback"] for point in selected} == {19, 21}
        assert any(point["threshold"] != parameters["threshold"] for point in selected)
        assert all(type(point["lookback"]) is int and type(point["probe"]) is int
                   and point["probe"] == 3 and point["mode"] == "hold" for point in selected)
        children = tuple(context.evaluation.prepare(replace(request, candidate=replace(center.candidate,
            candidate_id=f"C{index + 2:04}", definition=replace(definition,
                parameters_json=json.dumps({v.name: v.value for v in point.values})))), execution=execution)
            for index, point in enumerate(geometry.points))
        plan = ParameterEvaluationPlan.create(geometry, center, children, mapping_evidence=mapping,
            feasibility_evidence=feasible, dataflows=context.data, execution=execution)
        plan_ref = material("selected-plan", json.dumps(plan.to_dict()).encode())
        bound = []
        for point_id, child in zip(geometry.point_indices, children, strict=True):
            bound.append(plan.bind_point(plan_ref, point_id, child, execution=execution))
        yield context, center, plan, plan_ref, tuple(bound), execution


@pytest.mark.parametrize('market', (MarketId.CN,))
def test_TDR_12_C06_mixed_parameter_calmar_schema15_delivery_is_storage_only(tmp_path, monkeypatch, market):
    with mixed_plan(tmp_path, market) as (context, center, plan, plan_ref, children, execution):
        assert center.candidate.instrument.market is market
        assert center.candidate.definition.contract_version == 5
        pressure = context.evaluation.prepare(replace(center.request, scenario_id="PRESSURE",
            measurement_tier="STRESS", fee_rate=center.request.fee_rate * 2,
            input_binding=None, audit_inputs_sha256=None), execution=execution)
        facts, references = [], []
        for index, item in enumerate((center, pressure, *children)):
            outcome, = context.evaluation.evaluate_many((item,), execution=execution)
            assert outcome.result is not None, outcome.error
            facts.extend(build_assessment_evidence(item, outcome.result, execution=execution))
            references.append(publish_evidence(context, EvaluationEvidenceWrite(item.experiment,
                f"account-{index}", item, outcome.result), execution=execution))
        register_candidate(context.repository, CandidateRegistrationRequest(
            center.candidate, center.experiment, (references[0],), ()))
        links = tuple(m.PerturbationLink(plan.design.center, fact.candidate, 1.,
            canonical_sha256(child.request.lineage.derivation.to_dict()), child.request.lineage.parameter_binding.point)
            for child, fact in zip(children, facts[2:], strict=True))
        seed = assessment_request((facts[0],))
        protocol = replace(seed.protocol, baseline_window=center.request.window_id,
            standard_scenario=center.request.scenario_id, stress_scenario=pressure.request.scenario_id).to_dict()
        protocol["type"] = "CalmarSelfCheckProtocol"
        assessment = CandidatePerformanceAssessmentRequest(replace(seed,
            protocol=m.CalmarSelfCheckProtocol.from_dict(protocol), evidence=tuple(facts[:2]),
            perturbations=links, incomplete=(), parameter_designs=(plan.design,)),
            tuple(project_parameter_performance(fact) for fact in facts[2:]))
        assert tuple(point.parameter_point.point_index for point in assessment.parameter_evidence) == (0, 7)
        panel = assess_candidates(assessment)
        targets = (
            m.ResearchTarget("center", m.ResearchMetric.NET_CALMAR, lower=m.ConstantBound(-1e100, True)),
            m.ParameterNeighborhoodTarget("neighborhood", 1, 1,
                (m.ResearchTarget("point-calmar", m.ResearchMetric.NET_CALMAR, lower=m.ConstantBound(-1e100, True)),),
                (m.ResearchTarget("point-dd", m.ResearchMetric.DRAWDOWN_MAGNITUDE, upper=m.ConstantBound(1., True)),)),
            m.ResearchTarget("stress", m.ResearchMetric.NET_CALMAR, lower=m.ConstantBound(-1e100, True),
                scope=m.TargetScope.STRESS, one_way_cost=pressure.request.fee_rate),
        )
        seed_comparison = comparison_request(panel)
        replacements = {
            m.ResearchMetric.NET_ANNUAL_RETURN: m.ResearchMetric.NET_CALMAR,
            m.ResearchMetric.PARAMETER_RETURN_Q10: m.ResearchMetric.PARAMETER_CALMAR_Q10,
            m.ResearchMetric.ROLLING_EXCESS_Q10: m.ResearchMetric.ROLLING_EXCESS_CALMAR_Q10,
            m.ResearchMetric.STRESS_ANNUAL_LOSS: m.ResearchMetric.STRESS_CALMAR_LOSS,
        }
        comparison_request_value = m.CalmarComparisonRequest(seed_comparison.candidates,
            m.ResearchTargets(targets, 60), panel, replace(seed_comparison.policy,
                bins=tuple(replace(item, metric=replacements.get(item.metric, item.metric))
                           for item in seed_comparison.policy.bins), formula_version="research-ranking-v6"),
            (plan.design,), DeclaredPointSetComparisonContract(plan.design.construction_sha256,
                m.CommonNeighborhoodComparisonContract(RelativeChangeLimit(.05), ())))
        comparison = compare_candidates(comparison_request_value)
        neighborhood = comparison.rows[0].target_checks[1]
        assert neighborhood.status is m.TargetCheckStatus.PASSED
        assert len(neighborhood.points) == 2
        confirmation = publish_evidence(context, MaterialEvidenceWrite(center.experiment, "confirmed-targets",
            b'{"engineering_fixture":true}', "application/json", "json"), execution=execution)
        confirmed = d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED, confirmation)
        mandate = d.ResearchMandate((
            d.MandateItem("targets", d.MandateItemKind.OBJECTIVE, "Synthetic limits", confirmed,
                         d.PerformanceRequirement(targets)),
            d.MandateItem("benchmark", d.MandateItemKind.BENCHMARK, "Equity buy hold", confirmed,
                         d.BenchmarkRequirement(center.request.benchmark)),
            d.MandateItem("frequency", d.MandateItemKind.EXECUTION, "Session frequency", confirmed,
                         d.NumericRequirement("frequency_window_days", "sessions", lower=60., upper=60.)),
        ))
        mandate_receipt = assemble_delivery(context.repository,
            d.DeliveryDefinition(context.batch, d.DeliveryStage.MANDATE, 1), content(mandate)).receipt
        identity = d.CandidateIdentityRef(center.candidate.key, center.candidate.content_identity.content_sha256)
        entry = d.CandidateEntry(identity, "Mixed parameters", "Synthetic cross-market fixture",
            (d.EvaluationEvidenceRef(references[0], (facts[0].evaluation_id,)),))
        candidates = assemble_delivery(context.repository,
            d.DeliveryDefinition(context.batch, d.DeliveryStage.CANDIDATES, 1),
            content(d.CandidateSet((entry,), (center.candidate.key,), (), "One synthetic center"))).receipt
        payload = d.CandidateAssessmentDelivery(candidates.reference, mandate_receipt.reference,
            assessment, panel, comparison_request_value, comparison,
            tuple(d.TargetMandateBinding(target.target_id, "targets") for target in targets),
            "frequency", "benchmark", "Software acceptance only", tuple(references), (), parameter_plans=(plan_ref,))
        definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.ASSESSMENT, 1,
            predecessors=(candidates.reference, mandate_receipt.reference), schema_version=15)
        assert d.DeliveryContent.from_dict(content(payload).to_dict()).payload == payload

        from czsc_trader.application import delivery_service
        from czsc_trader.research_tools import equity_replay
        from strategy_evaluator import research_assessment
        import strategy_evaluator

        def forbidden(*args, **kwargs):
            raise AssertionError("INTEGRITY publication must not replay, authenticate accounts or recompute SE")

        with monkeypatch.context() as storage_only:
            storage_only.setattr(delivery_service, "_certify_account", forbidden)
            storage_only.setattr(delivery_service, "_validate_content", forbidden)
            storage_only.setattr(equity_replay, "_replay", forbidden)
            for module in (strategy_evaluator, research_assessment):
                storage_only.setattr(module, "assess_candidates", forbidden)
                storage_only.setattr(module, "compare_candidates", forbidden)
            assembled = assemble_delivery(context.repository, definition, content(payload))
            assert assembled.receipt.schema_version == 15
            assert assembled.validation.status is d.ValidationStatus.PASS
            assert assembled.validation.scope is d.DeliveryValidationScope.INTEGRITY
            assert assembled.validation.stats.accounts_authenticated == 0
            assert assembled.validation.stats.recomputation_seconds == 0
            checked = validate_delivery(context.repository, assembled.receipt.reference)
            assert checked.status is d.ValidationStatus.PASS
            assert checked.scope is d.DeliveryValidationScope.INTEGRITY
            assert checked.stats.accounts_authenticated == 0
            assert checked.stats.recomputation_seconds == 0
