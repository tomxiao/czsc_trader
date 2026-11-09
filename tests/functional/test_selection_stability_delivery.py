# Risk ownership: TDR-18
"""Saved V4 observations flow through selection diagnostics and unchanged schema 15."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from dataflows import BarFrequency, MarketId
from strategy_evaluator import research_models as m
from strategy_evaluator import (
    CandidatePerformanceAssessmentRequest, ParameterNeighborhoodRequest,
    ParameterNeighborhoodSpace, assess_candidates, build_parameter_neighborhood_design,
    assess_selection_stability, compare_candidates,
    SelectionDirection, SelectionMetricOrder, SelectionNoFilter, SelectionRule,
    SelectionWindow, SelectionWindowPair, SelectionWindowPlan, WindowCoverageStatus,
)
from strategy_runtime import canonical_sha256, equity_source_hash
from czsc_trader.application import (
    CandidateRegistrationRequest, assemble_delivery, publish_evidence,
    project_selection_window_facts, register_candidate, validate_delivery,
)
from czsc_trader.research_tools import (
    EvaluationEvidenceWrite, MaterialEvidenceWrite, ResearchExecutionSession,
    build_assessment_evidence,
    SelectionProjectionBudget, SelectionProjectionStatus, SelectionStabilityEvidence,
    SelectionWindowFactsRequest, SelectionWindowFactsResult, SelectionWindowSource,
)
from czsc_trader.research_tools import delivery as d
from account_parity_support import setup_account
from assessment_delivery_support import assessment_request, comparison_request
from test_research_delivery import content, published


def _accounts(root, market, frequency, *, drawdown_basis="BAR_CLOSE"):
    """Two actual accounts share inputs/benchmark but retain independent identities."""
    context, request = setup_account(root, market, frequency)
    request = replace(request, drawdown_basis=drawdown_basis)
    source = request.candidate.source_root
    (source / "strategy.py").write_text(
        "from strategy_runtime import AccountDecision, AccountStepResult\n"
        "from strategy_runtime.equity_replay import StateRecord\n"
        "def step(ctx, state):\n"
        "    target = ctx.parameters['allocation'] * (.25,.5,.25,0.)[len(ctx.history)%4]\n"
        "    return AccountStepResult(AccountDecision.from_facts(target, 'allocation', "
        "facts={'target':target}, next_watch='next bar'), cycle_values=StateRecord())\n",
        encoding="utf-8",
    )
    definition = replace(request.candidate.definition,
        source_sha256=equity_source_hash(source, ("strategy.py",)),
        parameters_json='{"allocation":1.0}',
        parameter_schema_json='{"allocation":{"type":"number","minimum":0,"maximum":1}}')
    prepared, references, facts = [], [], []
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        for index, allocation in enumerate((1., .5), 1):
            candidate = replace(request.candidate, candidate_id=f"C{index:04}",
                definition=replace(definition, parameters_json=json.dumps({"allocation": allocation})))
            item = context.evaluation.prepare(replace(request, candidate=candidate), execution=execution)
            outcome, = context.evaluation.evaluate_many((item,), execution=execution)
            assert outcome.result is not None, outcome.error
            fact, = build_assessment_evidence(item, outcome.result, execution=execution)
            reference = publish_evidence(context,
                EvaluationEvidenceWrite(item.experiment, f"selection-account-{index}", item, outcome.result),
                execution=execution)
            prepared.append(item)
            references.append(reference)
            facts.append(fact)
    return context, tuple(prepared), tuple(references), tuple(facts)


def _schema15(context, prepared, reference, fact):
    """Prepare an existing first-five report before testing storage-only publication."""
    register_candidate(context.repository, CandidateRegistrationRequest(
        prepared.candidate, prepared.experiment, (reference,), ()))
    # No tunable axes are declared by this publication fixture. Its original
    # diagnostics honestly retain their inapplicable/insufficient states.
    design = build_parameter_neighborhood_design(ParameterNeighborhoodRequest(
        fact.candidate, m.ParameterNeighborhoodProtocol(),
        ParameterNeighborhoodSpace((), "a" * 64, "b" * 64)),
        feasibility=lambda values: True).design
    seed = assessment_request((fact,))
    protocol = replace(seed.protocol, baseline_window=prepared.request.window_id,
        standard_scenario=prepared.request.scenario_id).to_dict()
    protocol["type"] = "CalmarSelfCheckProtocol"
    baseline = replace(seed, protocol=m.CalmarSelfCheckProtocol.from_dict(protocol),
        incomplete=(), parameter_designs=(design,))
    assessment = CandidatePerformanceAssessmentRequest(baseline, ())
    panel = assess_candidates(assessment)
    seed_comparison = comparison_request(panel)
    replacements = {
        m.ResearchMetric.NET_ANNUAL_RETURN: m.ResearchMetric.NET_CALMAR,
        m.ResearchMetric.PARAMETER_RETURN_Q10: m.ResearchMetric.PARAMETER_CALMAR_Q10,
        m.ResearchMetric.ROLLING_EXCESS_Q10: m.ResearchMetric.ROLLING_EXCESS_CALMAR_Q10,
        m.ResearchMetric.STRESS_ANNUAL_LOSS: m.ResearchMetric.STRESS_CALMAR_LOSS,
    }
    policy = replace(seed_comparison.policy, formula_version="research-ranking-v6",
        bins=tuple(replace(x, metric=replacements.get(x.metric, x.metric))
                   for x in seed_comparison.policy.bins))
    comparison = m.CalmarComparisonRequest(seed_comparison.candidates,
        seed_comparison.targets, panel, policy, (design,),
        m.CommonNeighborhoodComparisonContract(m.RelativeChangeLimit(.05), ()))
    confirmation = publish_evidence(context, MaterialEvidenceWrite(prepared.experiment,
        "selection-fixture-confirmation", b'{"engineering_fixture":true}', "application/json", "json"))
    confirmed = d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED, confirmation)
    mandate = d.ResearchMandate((
        d.MandateItem("targets", d.MandateItemKind.OBJECTIVE, "Synthetic bounds", confirmed,
            d.PerformanceRequirement(seed_comparison.targets.requirements)),
        d.MandateItem("benchmark", d.MandateItemKind.BENCHMARK, "Buy hold", confirmed,
            d.BenchmarkRequirement(prepared.request.benchmark)),
        d.MandateItem("frequency", d.MandateItemKind.EXECUTION, "Original report frequency", confirmed,
            d.NumericRequirement("frequency_window_days", "sessions", lower=60., upper=60.)),
    ))
    mandate_receipt = assemble_delivery(context.repository,
        d.DeliveryDefinition(context.batch, d.DeliveryStage.MANDATE, 1), content(mandate)).receipt
    entry = d.CandidateEntry(d.CandidateIdentityRef(prepared.candidate.key,
        prepared.candidate.content_identity.content_sha256), "Synthetic account", "Original report",
        (d.EvaluationEvidenceRef(reference, (fact.evaluation_id,)),))
    candidates = assemble_delivery(context.repository,
        d.DeliveryDefinition(context.batch, d.DeliveryStage.CANDIDATES, 1),
        content(d.CandidateSet((entry,), (prepared.candidate.key,), (), "Existing center"))).receipt
    payload = d.CandidateAssessmentDelivery(candidates.reference, mandate_receipt.reference,
        assessment, panel, comparison, compare_candidates(comparison),
        tuple(d.TargetMandateBinding(x.target_id, "targets")
              for x in seed_comparison.targets.requirements),
        "frequency", "benchmark", "Synthetic independent attachment acceptance", (reference,), ())
    definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.ASSESSMENT, 1,
        predecessors=(candidates.reference, mandate_receipt.reference), schema_version=15)
    return definition, payload


def _forbid_research_recomputation(patch):
    from czsc_trader.application import delivery_service
    from czsc_trader.research_tools import equity_replay
    from strategy_evaluator import research_assessment
    import strategy_evaluator

    def forbidden(*args, **kwargs):
        raise AssertionError("selection and its publication must not replay or recompute original diagnostics")

    patch.setattr(equity_replay, "_replay", forbidden)
    patch.setattr(delivery_service, "_certify_account", forbidden)
    patch.setattr(delivery_service, "_validate_content", forbidden)
    for module in (strategy_evaluator, research_assessment):
        patch.setattr(module, "assess_candidates", forbidden)
        patch.setattr(module, "compare_candidates", forbidden)
    return forbidden


@pytest.mark.parametrize('market,frequency', [(MarketId.US, BarFrequency.M30)])
def test_TDR_18_C09_saved_accounts_selection_attach_to_schema15_without_recomputation(tmp_path, monkeypatch, market, frequency):
    context, prepared, references, account_facts = _accounts(tmp_path, market, frequency)
    definition, old_payload = _schema15(context, prepared[0], references[0], account_facts[0])
    calendar = tuple(f"2026-10-{day}" for day in range(27, 31))
    selection = SelectionWindow("selection", calendar[0], calendar[1])
    observation = SelectionWindow("observation", calendar[2], calendar[3])
    plan = SelectionWindowPlan(calendar, canonical_sha256(calendar), (
        SelectionWindowPair("pair-a", selection, observation),
        SelectionWindowPair("pair-b", selection, observation),
    ), ("Synthetic four-session integration; not a 60-session frequency acceptance",))
    request = SelectionWindowFactsRequest(tuple(SelectionWindowSource(fact.candidate, ref)
        for fact, ref in zip(account_facts, references, strict=True)), plan, 2, 1,
        SelectionProjectionBudget(20, 20_000_000, 20_000_000))
    rule = SelectionRule("fixture-v1", "e" * 64, SelectionNoFilter(), (
        SelectionMetricOrder(m.ResearchMetric.NET_ANNUAL_RETURN, SelectionDirection.MAXIMIZE),), 2, 1)
    with monkeypatch.context() as computation:
        _forbid_research_recomputation(computation)
        reads = {}
        read_bytes = Path.read_bytes

        def counted_read(path):
            reads[path] = reads.get(path, 0) + 1
            return read_bytes(path)

        computation.setattr(Path, "read_bytes", counted_read)
        projection = project_selection_window_facts(context.repository, request)
        assert projection.status is SelectionProjectionStatus.COMPLETE, projection.failures
        assert len(projection.sources) == 2
        assert len({x.benchmark_source_id for x in projection.sources}) == 1
        assert projection.stats.projected_accounts == 3  # Two candidates, one shared benchmark.
        assert projection.stats.projected_windows == 6  # Two unique windows, not four pair legs.
        assert projection.stats.read_count == len(reads)
        assert set(reads.values()) == {1}
        assert projection.stats.decode_count == 6  # Headers 2, candidates 2, input 1, benchmark 1.
        assert len(projection.facts) == 6
        assert all(x.status is WindowCoverageStatus.COMPLETE for x in projection.facts)
        assert SelectionWindowFactsResult.from_dict(json.loads(json.dumps(projection.to_dict()))) == projection
        analysis = projection.analysis_request(rule)
        result = assess_selection_stability(analysis)
        assert result.selected_windows == 2
        assert all(len(x.eligible) == 2 for x in result.decisions)
        future_changed = replace(analysis, facts=tuple(replace(x, diagnostics=tuple(
            replace(value, value=value.value + 1.)
            if value.metric is m.ResearchMetric.NET_ANNUAL_RETURN and value.value is not None
            else value for value in x.diagnostics)) if x.window == observation else x
            for x in analysis.facts))
        changed_values = assess_selection_stability(future_changed)
        assert changed_values.decisions == result.decisions
        assert changed_values.observations != result.observations
        # Drop only future observations: candidate universe and prior decisions are fixed.
        future_missing = replace(analysis, facts=tuple(
            x for x in analysis.facts if x.window == selection))
        changed = assess_selection_stability(future_missing)
        assert changed.decisions == result.decisions
        assert changed.ranking_incomplete_windows == 2
        evidence = SelectionStabilityEvidence(projection, analysis, result, plan.limitations)
        raw = json.dumps(evidence.to_dict(), sort_keys=True).encode()
        assert SelectionStabilityEvidence.from_dict(json.loads(raw)) == evidence

    from czsc_trader.application import selection_stability_service
    from strategy_evaluator import selection_stability
    import strategy_evaluator
    with monkeypatch.context() as storage_only:
        forbidden = _forbid_research_recomputation(storage_only)
        storage_only.setattr(selection_stability, "assess_selection_stability", forbidden)
        storage_only.setattr(strategy_evaluator, "assess_selection_stability", forbidden)
        storage_only.setattr(strategy_evaluator, "project_equity_windows", forbidden)
        storage_only.setattr(selection_stability_service, "project_equity_windows", forbidden)
        storage_only.setattr(selection_stability_service, "project_selection_window_facts", forbidden)
        attached = publish_evidence(context, MaterialEvidenceWrite(prepared[0].experiment,
            "selection-stability", raw, "application/json", "json"))
        delivery_content = content(old_payload, evidence=(attached,))
        assembled = assemble_delivery(context.repository, definition, delivery_content)
        assert assembled.receipt.schema_version == 15
        assert assembled.validation.status is d.ValidationStatus.PASS
        assert assembled.validation.scope is d.DeliveryValidationScope.INTEGRITY
        assert assembled.validation.stats.accounts_authenticated == 0
        assert assembled.validation.stats.recomputation_seconds == 0
        # Cold read from the sealed package, independent of experiment material.
        attached.resolve(context.repository.root).unlink()
        checked = validate_delivery(context.repository, assembled.receipt.reference)
        assert checked.status is d.ValidationStatus.PASS
        assert checked.scope is d.DeliveryValidationScope.INTEGRITY
        assert checked.stats.accounts_authenticated == 0
        assert checked.stats.recomputation_seconds == 0
        stored = json.loads((published(context.repository, assembled.receipt) / "delivery.json").read_text(encoding="utf-8"))
        loaded = d.DeliveryContent.from_dict(stored["content"])
        assert loaded.payload == old_payload
        assert loaded.evidence == (attached,)
