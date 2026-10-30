"""V4 registrations and self-contained stage snapshots outlive research sources."""

import json

import pytest

from dataflows import BarFrequency, MarketId
from czsc_trader.application import (
    CandidateRegistrationRequest,
    assemble_delivery,
    load_candidate,
    publish_evidence,
    register_candidate,
    validate_delivery,
    get_research_overview,
)
from czsc_trader.research_tools import (
    EvaluationEvidenceWrite,
    MaterialEvidenceWrite,
    ResearchExecutionSession,
    build_assessment_evidence,
)
from czsc_trader.research_tools import delivery as d
from account_parity_support import setup_account


@pytest.mark.parametrize("market", [MarketId.CN, MarketId.US])
def test_v4_registered_candidate_and_stage_snapshot_have_independent_source_closure(
    tmp_path, monkeypatch, market
):
    context, request = setup_account(tmp_path, market, BarFrequency.DAILY, events=True)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        (outcome,) = context.evaluation.evaluate_many((prepared,), execution=execution)
        assert outcome.result is not None, outcome.error
        (fact,) = build_assessment_evidence(prepared, outcome.result, execution=execution)
        reference = publish_evidence(
            context,
            EvaluationEvidenceWrite(request.experiment, "v4-delivery", prepared, outcome.result),
            execution=execution,
        )
        assert reference.schema == "equity_research" and reference.schema_version == 4
    record = register_candidate(
        context.repository,
        CandidateRegistrationRequest(request.candidate, request.experiment, (reference,), ()),
    )
    loaded = load_candidate(context.repository, request.candidate.key)
    assert loaded.definition.contract_version == 4
    assert loaded.instrument.market is market
    assert loaded.source_root != request.candidate.source_root
    material = publish_evidence(
        context,
        MaterialEvidenceWrite(
            request.experiment,
            "definition",
            json.dumps(request.candidate.payload).encode(),
            "application/json",
            "json",
        ),
    )
    entry = d.PrototypeEntry(
        "P1",
        d.CandidateIdentityRef(request.candidate.key, record.content_sha256),
        d.ExperimentDefinitionRef(material, request.candidate.definition.entrypoint),
        "Synthetic cross-market allocation",
        (),
        (d.EvaluationEvidenceRef(reference, (fact.evaluation_id,)),),
        d.PrototypeDisposition.INVESTIGATE,
        "Software contract acceptance",
        ("Synthetic facts are not real-data research admission",),
        "Independent review",
        (material,),
    )
    assembled = assemble_delivery(
        context.repository,
        d.DeliveryDefinition(context.batch, d.DeliveryStage.PROTOTYPES, 1, ()),
        d.DeliveryContent(
            d.PrototypePanel((entry,), (), (), "V4 source closure"),
            d.DeliveryStatus.COMPLETE,
            (),
            (),
            report="# V4 contract fixture\n",
        ),
    )
    assert assembled.validation.status is d.ValidationStatus.PASS
    receipt = assembled.receipt.reference

    from czsc_trader.application import delivery_service as service

    original_certify = service._certify_account

    def forbidden_certification(*args, **kwargs):
        raise AssertionError("metadata overview must not recompute the numerical account")

    monkeypatch.setattr(service, "_certify_account", forbidden_certification)
    shallow = get_research_overview(context.repository, context.batch)
    assert shallow.snapshot.scope == "METADATA_ONLY"
    (latest,) = shallow.deliveries
    assert latest.reference == receipt and latest.metadata_state == "READABLE"
    assert not any("assets/evidence" in item.repository_path for item in shallow.snapshot.sources)
    monkeypatch.setattr(service, "_certify_account", original_certify)
    full = validate_delivery(context.repository, receipt, scope=d.DeliveryValidationScope.FULL)
    assert full.status is d.ValidationStatus.PASS, full.issues
    assert full.stats.accounts_authenticated == 1

    # Delete only named files in this isolated fixture; no shared repository source is touched.
    document = outcome.result.payload
    origin = reference.resolve(context.repository.root)
    originals = {origin, material.resolve(context.repository.root)}
    originals.update(
        origin.parent / (document[name]["sha256"] + ".json")
        for name in ("input_ref", "candidate_ref", "benchmark_ref")
    )
    originals.update(
        request.candidate.source_root / name for name in request.candidate.definition.source_files
    )
    for original in originals:
        assert original.is_relative_to(tmp_path)
        original.unlink()
    retained = load_candidate(context.repository, request.candidate.key)
    assert retained.content_identity.content_sha256 == record.content_sha256
    retained.verify()
    checked = validate_delivery(context.repository, receipt, scope=d.DeliveryValidationScope.FULL)
    assert checked.status is d.ValidationStatus.PASS, checked.issues
    assert checked.stats.accounts_authenticated == 1

    # Packaged source corruption must fail despite successful earlier certification.
    package = service._delivery_path(context.repository, receipt)
    dependency = package / "evidence" / (document["input_ref"]["sha256"] + ".json")
    assert dependency.is_relative_to(tmp_path)
    dependency.write_bytes(b"{}")
    rejected = validate_delivery(context.repository, receipt, scope=d.DeliveryValidationScope.FULL)
    assert rejected.status is d.ValidationStatus.FAIL
