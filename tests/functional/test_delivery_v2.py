"""Converged delivery schemas reject ambiguous identity and illegal values."""
from dataclasses import replace
import pytest
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ResearchBatchRef, ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef, MaterialEvidenceWrite


@pytest.mark.parametrize("value", [True, 0, -1, "1"])
def test_revision_requires_positive_integer(value):
    with pytest.raises((TypeError, ValueError)):
        d.DeliveryDefinition(ResearchBatchRef("S900"), d.DeliveryStage.COMPONENTS, value)


@pytest.mark.parametrize("report", ["", " \n\t", None, b"report"])
def test_delivery_requires_nonempty_researcher_report(report):
    with pytest.raises((TypeError, ValueError)):
        d.DeliveryContent(d.ComponentPanel((), "negative finding"), d.DeliveryStatus.COMPLETE,
                          (), (), report=report)


def test_old_delivery_schema_is_not_reinterpreted():
    with pytest.raises(ValueError, match="schema"):
        d.DeliveryDefinition(ResearchBatchRef("S900"), d.DeliveryStage.COMPONENTS, 1, schema_version=5)


def test_evidence_references_and_search_summary_are_content_contracts():
    owner = ExperimentRef("S900", "EX001_20261007")
    reference = EvidenceRef(owner, "a" * 64 + ".json", "a" * 64, "application/json", "measurement")
    assert EvidenceRef.from_dict(reference.to_dict()) == reference
    summary = d.SearchSummary("search", "mechanism census", "518850", 20, 10, "净年化优先", evidence=(reference,))
    assert d.SearchSummary.from_dict(summary.to_dict()) == summary
    with pytest.raises(ValueError):
        replace(summary, unique_configurations=21)
    for name in ("../escape", "CON", "a/b", "x" * 101):
        with pytest.raises(ValueError):
            MaterialEvidenceWrite(owner, name, b"x", "text/plain", "txt")
