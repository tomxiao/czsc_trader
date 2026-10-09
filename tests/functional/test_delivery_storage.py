"""Publication transaction boundaries and content-addressed evidence."""
from dataclasses import replace
import pytest
from czsc_trader.application import assemble_delivery, publish_evidence
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.evidence import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from test_research_delivery import content, attachment, context as context


def test_evidence_publication_is_explicit_idempotent_and_batch_scoped(context):
    research = context
    request = MaterialEvidenceWrite(ExperimentRef("S900", "EX001_20261007"), "measurement", b"test", "text/plain", "txt")
    first = publish_evidence(research, request)
    assert first == publish_evidence(research, request)
    assert first.path == f"evidence/{first.sha256}.txt"
    assert first.repository_path == f"research/S900/assets/evidence/EX001_20261007/{first.sha256}.txt"
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


def test_missing_selected_evidence_leaves_no_visible_delivery(context):
    research = context
    reference = attachment(research)
    reference.resolve(research.repository.root).unlink()
    fact = d.FactValue("missing", None, "ratio", d.FactStatus.INSUFFICIENT_DATA, (reference,), "not available")
    definition = d.DeliveryDefinition(research.batch, d.DeliveryStage.COMPONENTS, 1)
    with pytest.raises(d.DeliveryValidationError):
        assemble_delivery(research.repository, definition, replace(content(), facts=(fact,)))
    assert not (research.repository.research_root / "S900/deliveries/COMPONENTS/1").exists()
    assert not (research.repository.research_root / "S900/assets/deliveries/COMPONENTS/1").exists()
