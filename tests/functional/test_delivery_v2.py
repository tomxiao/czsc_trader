from dataclasses import replace
import json

import pytest
from strategy_manager import CandidateKey
from strategy_evaluator import compare_candidates
from strategy_evaluator import research_models as m

from czsc_trader.application import assemble_delivery, validate_delivery
from czsc_trader.research_tools import delivery as d
from test_research_delivery import (
    Deliverable,
    content,
    definition,
    experiment,
    failed_record,
    published,
    context as context,
)
from test_assessment_delivery import completed as completed, prepare
from test_research_contract_upgrade import managed_evaluation as managed_evaluation


def test_historical_reference_cannot_authenticate_a_current_candidate(context):
    record = failed_record()
    ref, _ = experiment(context, records=(record,))
    ref = replace(ref, use=d.ExperimentEvidenceUse.HISTORICAL_REFERENCE)
    identity = d.CandidateIdentityRef(CandidateKey("S900", "C0001"), record.content_sha256)
    entry = d.CandidateEntry(
        identity, "假设", "说明", (d.EvaluationEvidenceRef(ref.experiment_id, record.attempt_id),)
    )
    with pytest.raises(d.DeliveryValidationError, match="historical|authenticated"):
        assemble_delivery(
            context,
            Deliverable(
                definition(d.DeliveryStage.CANDIDATES, experiments=(ref,)),
                content(d.CandidateSet((entry,), (), (), "待研究")),
            ),
        )


def test_mandate_binds_all_same_metric_conditions_exactly(completed):
    context = completed[0]
    defined, value = prepare(completed)
    payload = value.payload
    source = published(
        context,
        d.DeliveryReceipt.from_dict(
            json.loads((context.root / "research/S900/mandates/1/receipt.json").read_text())
        ),
    )
    original = d.DeliveryContent.from_dict(
        json.loads((source / "delivery.json").read_text(encoding="utf-8"))["content"]
    )
    target = m.ResearchTarget(
        "positive",
        m.ResearchMetric.NET_ANNUAL_RETURN,
        lower=m.ConstantBound(0.0, False),
        when=m.BenchmarkCondition(m.ResearchMetric.NET_ANNUAL_RETURN, m.ComparisonOperator.LE, 0.0),
    )
    targets = (*payload.comparison_request.targets.requirements, target)
    item = replace(original.payload.items[0], requirement=d.PerformanceRequirement(targets))
    mandate = assemble_delivery(
        context,
        Deliverable(
            d.DeliveryDefinition(
                d.MandateOwner("S900"),
                d.DeliveryStage.MANDATE,
                2,
                predecessors=(payload.source_mandate,),
            ),
            replace(original, payload=d.ResearchMandate((item, original.payload.items[1]))),
        ),
    )
    comparison = replace(payload.comparison_request, targets=m.ResearchTargets(targets, 60))
    payload = replace(
        payload,
        source_mandate=mandate.reference,
        comparison_request=comparison,
        comparison=compare_candidates(comparison),
        target_bindings=(*payload.target_bindings, d.TargetMandateBinding("positive", "return")),
    )
    defined = replace(defined, predecessors=(payload.source_candidates, mandate.reference))
    receipt = assemble_delivery(context, Deliverable(defined, replace(value, payload=payload)))
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS
    for altered in (replace(target, lower=m.ConstantBound(0.0, True)), replace(target, when=None)):
        comparison = replace(comparison, targets=m.ResearchTargets((targets[0], altered), 60))
        forged = replace(
            payload, comparison_request=comparison, comparison=compare_candidates(comparison)
        )
        with pytest.raises(d.DeliveryValidationError, match="confirmed mandate"):
            assemble_delivery(
                context, Deliverable(replace(defined, revision=2), replace(value, payload=forged))
            )
