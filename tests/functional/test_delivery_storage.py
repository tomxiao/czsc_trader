"""Publication transaction boundaries and content-addressed evidence."""
from dataclasses import replace
import pytest
from czsc_trader.application import assemble_delivery, publish_evidence, validate_delivery
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.evidence import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from test_research_delivery import content, attachment, published
from test_research_contract_upgrade import managed_evaluation as managed_evaluation


def test_evidence_publication_is_explicit_idempotent_and_batch_scoped(managed_evaluation):
    research, _ = managed_evaluation
    request = MaterialEvidenceWrite(ExperimentRef("S900", "EX001_20261007"), "measurement", b"test", "text/plain", "txt")
    first = publish_evidence(research, request)
    assert first == publish_evidence(research, request)
    assert first.resolve(research.repository.root).read_bytes() == b"test"
    with pytest.raises(ValueError, match="another research batch"):
        publish_evidence(research, replace(request, experiment=ExperimentRef("S901", "EX001_20261007")))
    with pytest.raises(ValueError, match="allocated experiment"):
        publish_evidence(research, replace(request, experiment=ExperimentRef("S900", "EX002_20261007")))
    first.resolve(research.repository.root).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="overwritten"):
        publish_evidence(research, request)
    with pytest.raises(ValueError, match="differs"):
        first.resolve(research.repository.root)


def test_delivery_idempotence_conflict_and_payload_tamper(managed_evaluation):
    research, _ = managed_evaluation
    definition = d.DeliveryDefinition(research.batch, d.DeliveryStage.COMPONENTS, 1)
    receipt = assemble_delivery(research.repository, definition, content())
    assert receipt == assemble_delivery(research.repository, definition, content())
    with pytest.raises(d.DeliveryConflictError):
        assemble_delivery(research.repository, definition, content(d.ComponentPanel((), "changed")))
    report = published(research.repository, receipt) / "report.md"
    report.write_bytes(report.read_bytes() + b"corrupt")
    for scope in d.DeliveryValidationScope:
        assert validate_delivery(research.repository, receipt.reference, scope=scope).status is d.ValidationStatus.FAIL


def test_missing_selected_evidence_leaves_no_visible_delivery(managed_evaluation):
    research, _ = managed_evaluation
    reference = attachment(research)
    reference.resolve(research.repository.root).unlink()
    fact = d.FactValue("missing", None, "ratio", d.FactStatus.INSUFFICIENT_DATA, (reference,), "not available")
    definition = d.DeliveryDefinition(research.batch, d.DeliveryStage.COMPONENTS, 1)
    with pytest.raises(d.DeliveryValidationError):
        assemble_delivery(research.repository, definition, replace(content(), facts=(fact,)))
    assert not (research.repository.research_root / "S900/deliveries/COMPONENTS/1").exists()
