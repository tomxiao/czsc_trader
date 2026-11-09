# Risk ownership: TDR-12
"""Stage-five envelopes and metadata never imply legacy technical acceptance."""

from dataclasses import replace
from hashlib import sha256

import pytest
from strategy_manager import (
    ResearchEvidenceOwner, ResearchEvidenceRef, DecisionReference,
    FreezeReceipt, FreezeRequestId, FreezeStatus,
)

from czsc_trader.research_tools import delivery as d
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
        # Overview reports the unsupported receipt without decoding this payload.
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
