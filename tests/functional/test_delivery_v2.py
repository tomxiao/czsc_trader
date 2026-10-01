from dataclasses import replace
from hashlib import sha256
import json
import shutil

import pytest
from research_experiment import load_experiment_input
from strategy_manager import CandidateKey
from strategy_runtime import canonical_sha256
from strategy_evaluator import compare_candidates
from strategy_evaluator import research_models as m

from czsc_trader.application import assemble_delivery, validate_delivery
from czsc_trader.research_tools import delivery as d
from test_research_delivery import (
    Deliverable,
    attachment,
    content,
    definition,
    experiment,
    failed_record,
    published,
    context as context,
)
from test_assessment_delivery import completed as completed, prepare
from test_research_contract_upgrade import managed_evaluation as managed_evaluation


def historical_experiment(context):
    ref, artifact = experiment(context)
    root = context.root / ref.workspace_path
    envelope = json.loads((root / "execution_envelope.json").read_text())
    receipt = envelope["receipt"]
    receipt["schema_version"] = 1
    del receipt["trace"]["data_scope"]
    receipt["trace"]["evaluations"] = [{"old_trial": "history-only"}]
    digest = canonical_sha256(receipt)
    envelope["receipt_sha256"] = digest
    (root / "execution_envelope.json").write_text(json.dumps(envelope), encoding="utf-8")
    (root / "execution_receipt.json").write_text(
        json.dumps({**receipt, "receipt_sha256": digest}), encoding="utf-8"
    )
    load_experiment_input(root, expected_receipt_sha256=digest)
    return replace(
        ref, receipt_sha256=digest, use=d.ExperimentEvidenceUse.HISTORICAL_REFERENCE
    ), artifact


def test_historical_component_evidence_retains_original_receipt_and_closure(context):
    ref, artifact = historical_experiment(context)
    successor, _ = experiment(
        context, number=2, predecessors={ref.experiment_id: ref.receipt_sha256}
    )
    protocol = attachment(context, "protocol.json")
    evidence = d.EvidenceRef(
        f"experiments/{ref.experiment_id}/{artifact.path}", artifact.sha256, "application/json"
    )
    test = d.ComponentTestResult(
        "old-test",
        ref.experiment_id,
        protocol.reference,
        d.ComponentTestStatus.SUPPORTED,
        "历史开发池结论",
        (evidence,),
    )
    component = d.ComponentEntry(
        "component",
        d.ExperimentDefinitionRef(ref.experiment_id, "a" * 64, "b" * 64, "experiment.Component"),
        "机会环境",
        "收益",
        "1日",
        "常量",
        "次日",
        "前复权",
        "已见开发池",
        "继承原结论",
        (test,),
    )
    value = content(d.ComponentPanel((component,), "历史引用"), attachments=(protocol,))
    defined = definition(experiments=(ref, successor))
    before = (context.root / ref.workspace_path / "execution_receipt.json").read_bytes()
    receipt = assemble_delivery(context, Deliverable(defined, value))
    root = published(context, receipt)
    assert receipt.schema_version == 3
    assert (root / f"experiments/{ref.experiment_id}/execution_receipt.json").read_bytes() == before
    assert "HISTORICAL_REFERENCE" in (root / "report.md").read_text(encoding="utf-8")
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS
    with pytest.raises(d.DeliveryValidationError, match="predecessor"):
        assemble_delivery(
            context, Deliverable(replace(defined, revision=2, experiments=(successor,)), content())
        )
    wrong = replace(ref, use=d.ExperimentEvidenceUse.CURRENT_EVALUATION)
    with pytest.raises(d.DeliveryValidationError, match="schema 2"):
        assemble_delivery(
            context,
            Deliverable(replace(defined, revision=2, experiments=(wrong, successor)), value),
        )
    temporary = (context.root / ".tmp").resolve()
    assert temporary.is_relative_to(context.root.resolve())
    shutil.rmtree(temporary)
    assert validate_delivery(context, receipt.reference).status is d.ValidationStatus.PASS


def test_historical_reference_cannot_authenticate_a_current_candidate(context):
    record = failed_record()
    ref, _ = experiment(context, records=(record,))
    ref = replace(ref, use=d.ExperimentEvidenceUse.HISTORICAL_REFERENCE)
    identity = d.CandidateIdentityRef(CandidateKey("S900", "C001"), record.content_sha256)
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
            json.loads(
                (context.root / "research/S900/deliveries/MANDATE/1/receipt.json").read_text()
            )
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
                "S900", d.DeliveryStage.MANDATE, 2, predecessors=(payload.source_mandate,)
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


def test_v1_public_validation_is_read_only_and_new_writer_refuses_v1(context):
    from czsc_trader.application import _delivery_reader_v1 as reader
    from czsc_trader.research_tools import _delivery_v1 as old

    defined = old.DeliveryDefinition("S900", old.DeliveryStage.COMPONENTS, 1)
    value = old.DeliveryContent.from_dict(content().to_dict())
    root = context.root / "research/S900/deliveries/COMPONENTS/1"
    root.mkdir(parents=True)
    (root / "delivery.json").write_bytes(
        old._canonical({"schema_version": 1, "definition": defined, "content": value})
    )
    (root / "report.md").write_bytes(reader._report(defined, value, root))
    files = reader._manifest(root)
    reference = old.DeliveryReference("S900", old.DeliveryStage.COMPONENTS, 1, old._digest(files))
    (root / "receipt.json").write_bytes(old._canonical(old.DeliveryReceipt(reference, files)))
    before = {p.name: sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
    ref = d.DeliveryReference.from_dict(reference.to_dict())
    assert validate_delivery(context, ref).status is d.ValidationStatus.PASS
    assert {p.name: sha256(p.read_bytes()).hexdigest() for p in root.iterdir()} == before
    successor = assemble_delivery(
        context, Deliverable(replace(definition(), revision=2, predecessors=(ref,)), content())
    )
    assert validate_delivery(context, successor.reference).status is d.ValidationStatus.PASS
    with pytest.raises(ValueError, match="schema"):
        replace(definition(), schema_version=1)
    (root / "report.md").write_bytes(b"tampered")
    assert validate_delivery(context, ref).status is d.ValidationStatus.FAIL
    assert validate_delivery(context, successor.reference).status is d.ValidationStatus.FAIL


def test_v1_assessment_uses_original_targets_formula_and_report(completed):
    """Construct a v1 archive fixture; the production writer only publishes v2."""
    from czsc_trader.application import _delivery_reader_v1 as reader
    from czsc_trader.research_tools import _delivery_v1 as old
    from strategy_evaluator import _research_models_v1 as om
    from strategy_evaluator._research_assessment_v1 import assess_candidates as old_assess
    from strategy_evaluator._research_assessment_v1 import compare_candidates as old_compare

    context = completed[0]
    defined, value = prepare(completed)
    current = assemble_delivery(context, Deliverable(defined, value))

    def publish_v1(stage, payload, predecessors=()):
        source = context.root / f"research/S900/deliveries/{stage.value}/1"
        destination = source.parent / "10"
        shutil.copytree(source, destination)
        document = json.loads((source / "delivery.json").read_text(encoding="utf-8"))
        spec = document["definition"]
        spec.update(schema_version=1, revision=10, predecessors=[x.to_dict() for x in predecessors])
        for ref in spec["experiments"]:
            del ref["use"]
            # Build a genuine old-schema fixture before sealing its receipt.
            # Production validation must continue to reject newer projections.
            exp_root = destination / "experiments" / ref["experiment_id"]
            envelope_path = exp_root / "execution_envelope.json"
            envelope = json.loads(envelope_path.read_text())
            receipt = envelope["receipt"]
            changed_hashes = {}
            for record in receipt["trace"]["evaluations"]:
                artifact = record.get("result_artifact")
                if artifact is None:
                    continue
                artifact_path = exp_root / artifact["path"]
                result = json.loads(artifact_path.read_text())
                result["schema_version"] = 3
                for evidence in result["assessment_evidence"]:
                    evidence["scenario_context"].pop("benchmark_contract_sha256")
                artifact_path.write_text(json.dumps(result), encoding="utf-8")
                digest = sha256(artifact_path.read_bytes()).hexdigest()
                changed_hashes[artifact["sha256"]] = digest
                artifact["sha256"] = digest
                record_path = artifact_path.with_name("record.json")
                record_path.write_text(json.dumps(record), encoding="utf-8")
            for name in receipt["artifact_sha256"]:
                receipt["artifact_sha256"][name] = sha256((exp_root / name).read_bytes()).hexdigest()
            for artifact in envelope["result"]["artifacts"]:
                artifact["sha256"] = receipt["artifact_sha256"][artifact["path"]]
            receipt["result_sha256"] = canonical_sha256(envelope["result"])
            digest = canonical_sha256(receipt)
            envelope["receipt_sha256"] = digest
            envelope_path.write_text(json.dumps(envelope), encoding="utf-8")
            (exp_root / "execution_receipt.json").write_text(
                json.dumps({**receipt, "receipt_sha256": digest}), encoding="utf-8")
            ref["receipt_sha256"] = digest
        document["content"]["payload"] = payload.to_dict()
        def update_refs(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == "sha256" and item in changed_hashes:
                        value[key] = changed_hashes[item]
                    else:
                        update_refs(item)
            elif isinstance(value, list):
                for item in value:
                    update_refs(item)
        if spec["experiments"]:
            update_refs(document["content"])
        v1def = old.DeliveryDefinition.from_dict(spec)
        v1content = old.DeliveryContent.from_dict(document["content"])
        (destination / "delivery.json").write_bytes(
            old._canonical({"schema_version": 1, "definition": v1def, "content": v1content})
        )
        (destination / "report.md").write_bytes(reader._report(v1def, v1content, destination))
        files = reader._manifest(destination)
        ref = old.DeliveryReference("S900", stage, 10, old._digest(files))
        (destination / "receipt.json").write_bytes(old._canonical(old.DeliveryReceipt(ref, files)))
        return ref

    mandate_doc = json.loads(
        (context.root / "research/S900/deliveries/MANDATE/1/delivery.json").read_text(
            encoding="utf-8"
        )
    )
    mandate_payload = mandate_doc["content"]["payload"]
    mandate_payload["items"] = [x for x in mandate_payload["items"] if x["kind"] != "BENCHMARK"]
    mandate_payload["items"][0]["requirement"] = old.NumericRequirement(
        "net_annual_return", "ratio", lower=-1.0
    ).to_dict()
    mandate = publish_v1(old.DeliveryStage.MANDATE, old.ResearchMandate.from_dict(mandate_payload))
    candidates_doc = json.loads(
        (context.root / "research/S900/deliveries/CANDIDATES/1/delivery.json").read_text(
            encoding="utf-8"
        )
    )
    candidates = publish_v1(
        old.DeliveryStage.CANDIDATES,
        old.CandidateSet.from_dict(candidates_doc["content"]["payload"]),
    )
    request_data = value.payload.assessment_request.to_dict()
    for evidence in request_data["evidence"]:
        evidence["scenario_context"].pop("benchmark_contract_sha256")
    request = om.CandidateAssessmentRequest.from_dict(request_data)
    panel = old_assess(request)
    comparison = om.CandidateComparisonRequest(
        request.centers,
        om.ResearchTargets(
            (om.ResearchTarget(om.ResearchMetric.NET_ANNUAL_RETURN, lower=-1.0),), 60
        ),
        panel,
        om.ComparisonPolicy(
            "1",
            tuple(
                om.MetricBinSpec(metric, 0.0001, 0.0, om.BinRounding.FLOOR)
                for metric in om.RANKING_METRICS
            ),
        ),
    )
    payload = old.CandidateAssessmentDelivery(
        candidates,
        mandate,
        request,
        panel,
        comparison,
        old_compare(comparison),
        (old.TargetMandateBinding(om.ResearchMetric.NET_ANNUAL_RETURN, "return"),),
        None,
        value.payload.recommendation,
        tuple(old.EvidenceRef.from_dict(x.to_dict()) for x in value.payload.contrary_evidence),
        value.payload.pending_decisions,
    )
    ref = publish_v1(old.DeliveryStage.ASSESSMENT, payload, (candidates, mandate))
    public_ref = d.DeliveryReference.from_dict(ref.to_dict())
    root = published(
        context,
        d.DeliveryReceipt.from_dict(
            json.loads(
                (context.root / "research/S900/deliveries/ASSESSMENT/10/receipt.json").read_text()
            )
        ),
    )
    before = {
        p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }
    result = validate_delivery(context, public_ref)
    assert result.status is d.ValidationStatus.PASS, result.issues
    assert validate_delivery(context, current.reference).status is d.ValidationStatus.PASS
    assert {
        p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    } == before
