"""Stage-five envelopes and metadata never imply legacy technical acceptance."""

from dataclasses import replace
from hashlib import sha256
import json

import pytest
from strategy_manager import (
    ResearchEvidenceOwner, ResearchEvidenceRef, DecisionReference,
    FreezeReceipt, FreezeRequestId, FreezeStatus,
)

from czsc_trader.application.delivery_service import validate_delivery
from czsc_trader.application.research_overview_service import get_research_overview
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.overview import ResearchCountKind, ResearchOverviewError
from test_research_overview import overview_context as overview_context


def _retained_inspection(research, experiment, revision, schema, *, definition_schema=None, receipt_schema=None):
    """Build a metadata-only retained fixture; never fake an inspection PASS."""
    repository = research.repository.root
    folder = repository / f"research/S900/assets/deliveries/INSPECTION/{revision}"
    folder.mkdir(parents=True)
    report_bytes = b'{"metadata_only_fixture":true}'
    digest = sha256(report_bytes).hexdigest()
    reference = ResearchEvidenceRef(ResearchEvidenceOwner("S900", experiment.experiment_id),
                                    f"inspection/{digest}", digest)
    (folder / "support").mkdir()
    (folder / "support" / digest).write_bytes(report_bytes)
    content = d.DeliveryContent(d.CandidateInspectionDelivery(reference, (), None, ("review",)),
                               d.DeliveryStatus.COMPLETE, (), (), report="Retained delivery metadata")
    document = {
        "schema_version": schema,
        "definition": {
            "type": "DeliveryDefinition", "batch": research.batch.to_dict(), "stage": "INSPECTION",
            "revision": revision, "predecessors": [],
            "schema_version": schema if definition_schema is None else definition_schema,
        },
        "content": content.to_dict(),
    }
    if schema == 8:
        # Deliberately not a current or historical executable report schema:
        # overview must authenticate its envelope without decoding its payload.
        document["content"]["payload"] = {"historical_payload_is_opaque": True}
    (folder / "delivery.json").write_bytes(d._canonical(document))
    (folder / "report.md").write_bytes(content.report.encode())
    files = tuple(d.PublicationFile(item.relative_to(folder).as_posix(), sha256(item.read_bytes()).hexdigest())
                  for item in sorted(folder.rglob("*")) if item.is_file())
    delivery = d.DeliveryReference(research.batch, d.DeliveryStage.INSPECTION, revision, d._digest(files))
    receipt = {"type": "DeliveryReceipt", "reference": delivery.to_dict(),
               "files": [item.to_dict() for item in files],
               "schema_version": schema if receipt_schema is None else receipt_schema}
    (folder / "receipt.json").write_bytes(d._canonical(receipt))
    public = repository / f"research/S900/deliveries/INSPECTION/{revision}"
    public.mkdir(parents=True)
    for name in ("report.md", "receipt.json"):
        (public / name).write_bytes((folder / name).read_bytes())
    return delivery, folder


def test_inspection_requires_schema9_and_no_research_predecessors(overview_context):
    research, experiment = overview_context
    reference = d.DeliveryReference(research.batch, d.DeliveryStage.ASSESSMENT, 1, "1" * 64)
    assert d.DeliveryDefinition(research.batch, d.DeliveryStage.INSPECTION, 1).schema_version == 9
    with pytest.raises(ValueError, match="schema"):
        d.DeliveryDefinition(research.batch, d.DeliveryStage.INSPECTION, 1, schema_version=8)
    with pytest.raises(ValueError, match="predecessors"):
        d.DeliveryDefinition(research.batch, d.DeliveryStage.INSPECTION, 1, (reference,), 9)
    definition = d.DeliveryDefinition(research.batch, d.DeliveryStage.INSPECTION, 1, schema_version=9)
    assert d.DeliveryDefinition.from_dict(definition.to_dict()) == definition
    for stage in tuple(d.DeliveryStage)[:-1]:
        with pytest.raises(ValueError, match="schema"):
            d.DeliveryDefinition(research.batch, stage, 1, schema_version=9)
    report = ResearchEvidenceRef(ResearchEvidenceOwner("S900", experiment.experiment_id),
                                 f"inspection/{'2' * 64}", "2" * 64)
    payload = d.CandidateInspectionDelivery(report, (), None, ())
    assert d.CandidateInspectionDelivery.from_dict(payload.to_dict()) == payload
    for invalid, error in (((" ",), ValueError), ((1,), TypeError)):
        with pytest.raises(error):
            replace(payload, pending_decisions=invalid)
    assert set(payload.to_dict()) == {"type", "inspection", "decisions", "freeze", "pending_decisions"}
    foreign = ResearchEvidenceRef(ResearchEvidenceOwner("S901"), "decisions/select.json", "3" * 64)
    with pytest.raises(ValueError, match="research batch"):
        replace(payload, decisions=(DecisionReference("select", foreign),))
    with pytest.raises(ValueError, match="research batch"):
        replace(payload, freeze=FreezeReceipt(FreezeRequestId("S901", "foreign"), FreezeStatus.NOT_FOUND))


@pytest.mark.parametrize("definition_schema,receipt_schema", [(8, 9), (9, 8)])
def test_overview_rejects_crossed_inspection_schemas(overview_context, definition_schema, receipt_schema):
    research, experiment = overview_context
    _retained_inspection(research, experiment, 1, 9,
                         definition_schema=definition_schema, receipt_schema=receipt_schema)
    with pytest.raises(ResearchOverviewError, match="schema differs"):
        get_research_overview(research.repository, research.batch)


def test_legacy_inspection_is_metadata_only_and_does_not_hide_new_revision(overview_context):
    research, experiment = overview_context
    old, old_folder = _retained_inspection(research, experiment, 1, 8)
    original = (old_folder / "delivery.json").read_bytes()
    first = get_research_overview(research.repository, research.batch)
    assert first.deliveries[0].reference == old
    assert any(item.code == "UNSUPPORTED_LEGACY_INSPECTION" and "unknown" in item.message
               for item in first.limitations)
    validation = validate_delivery(research.repository, old)
    assert validation.status is d.ValidationStatus.FAIL
    assert validation.issues[0].code == "UNSUPPORTED_LEGACY_INSPECTION"
    new, _ = _retained_inspection(research, experiment, 2, 9)
    second = get_research_overview(research.repository, research.batch)
    assert second.deliveries[0].reference == new
    assert any(item.code == "UNSUPPORTED_LEGACY_INSPECTION" for item in second.limitations)
    assert (old_folder / "delivery.json").read_bytes() == original


def test_legacy_metadata_still_rejects_corrupted_files(overview_context):
    research, experiment = overview_context
    _, folder = _retained_inspection(research, experiment, 1, 8)
    (folder / "report.md").write_bytes(b"tampered")
    with pytest.raises(ResearchOverviewError, match="hash differs"):
        get_research_overview(research.repository, research.batch)


def test_inspection_objects_are_authenticated_but_never_counted_as_accounts(overview_context):
    research, experiment = overview_context
    content = json.dumps({"source_kind": "published_result", "schema_version": 7}).encode()
    digest = sha256(content).hexdigest()
    path = research.repository.root / f"research/S900/assets/evidence/{experiment.experiment_id}/inspection/{digest}"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    overview = get_research_overview(research.repository, research.batch)
    count = next(item for item in overview.counts if item.kind is ResearchCountKind.PUBLISHED_ACCOUNT_EVALUATIONS)
    assert count.value == 0
    assert any(item.repository_path.endswith(f"inspection/{digest}") for item in overview.snapshot.sources)
    path.write_bytes(b"changed bytes")
    with pytest.raises(ResearchOverviewError) as exc:
        get_research_overview(research.repository, research.batch)
    assert exc.value.code == "INVALID_INSPECTION_EVIDENCE"
    assert exc.value.repository_path.endswith(digest)


@pytest.mark.parametrize("relative", ["unexpected", "inspection/not-a-hash", f"inspection/{'a' * 64}/nested"])
def test_unknown_or_nested_inspection_layout_is_not_silently_ignored(overview_context, relative):
    research, experiment = overview_context
    path = research.repository.root / f"research/S900/assets/evidence/{experiment.experiment_id}/{relative}"
    path.mkdir(parents=True)
    with pytest.raises(ResearchOverviewError) as exc:
        get_research_overview(research.repository, research.batch)
    assert exc.value.code in {"INVALID_EVIDENCE_LAYOUT", "INVALID_INSPECTION_EVIDENCE"}


def test_inspection_receipt_schema_must_match_its_stage(overview_context):
    research, _ = overview_context
    reference = d.DeliveryReference(research.batch, d.DeliveryStage.INSPECTION, 1, "1" * 64)
    files = (d.PublicationFile("delivery.json", "2" * 64),)
    assert d.DeliveryReceipt(reference, files).schema_version == 9
    with pytest.raises(ValueError, match="schema"):
        d.DeliveryReceipt(reference, files, schema_version=8)
    receipt = d.DeliveryReceipt(reference, files, schema_version=9)
    assert d.DeliveryReceipt.from_dict(receipt.to_dict()) == receipt
    with pytest.raises(ValueError, match="schema"):
        replace(receipt, reference=replace(reference, stage=d.DeliveryStage.ASSESSMENT))
