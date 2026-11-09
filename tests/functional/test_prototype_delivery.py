# Risk ownership: TDR-12
"""Prototype handoffs preserve executable identities without candidate promotion."""

from dataclasses import replace
import json

from strategy_manager import CandidateKey

from czsc_trader.application import (
    assemble_delivery,
)
from czsc_trader.research_tools import delivery as d
from managed_evaluation_support import managed_evaluation as managed_evaluation
from test_research_delivery import attachment, content, published
from test_research_overview import overview_context as overview_context


def definition(research, revision=1, predecessors=()):
    return d.DeliveryDefinition(research.batch, d.DeliveryStage.PROTOTYPES, revision,
                                predecessors, schema_version=10)


def entry(research, *, prototype_id="P1", identity=None, evaluations=()):
    material = attachment(research, "prototype-definition", {"parameters": {}, "rules": "synthetic"})
    return d.PrototypeEntry(
        prototype_id, identity or d.CandidateIdentityRef(CandidateKey("S900", "C0001"), "a" * 64),
        d.ExperimentDefinitionRef(material, "strategy_runtime.fixture"),
        "Hypothesis remains a researcher judgment", (), evaluations,
        d.PrototypeDisposition.INVESTIGATE, "Further evidence needed", ("Synthetic material",),
        "Compare a minimal executable prototype", (material,),
        missing_evaluation_reason=None if evaluations else "No account has been evaluated",
    )


def panel(item):
    return d.PrototypePanel((item,), (), (), "Research recommendation, not authorization")


def test_TDR_12_C04_prototype_panel_preserves_comparisons_and_negative_delivery(overview_context):
    research, _ = overview_context
    subject = entry(research)
    control = replace(subject, prototype_id="U", identity=replace(subject.identity, key=CandidateKey("S900", "C0002")))
    comparison = d.PrototypeComparison("path-v-unfiltered", "P1", "U", "Does path add value?",
        subject.definition.evidence, subject.evidence, "No conclusion without account comparison")
    value = content(d.PrototypePanel((subject, control), (), (comparison,), "Exploration only"))
    receipt = assemble_delivery(research.repository, definition(research), value).receipt
    saved = json.loads((published(research.repository, receipt) / "delivery.json").read_text(encoding="utf-8"))
    assert d.DeliveryContent.from_dict(saved["content"]) == value
    empty = content(d.PrototypePanel((), (), (), "No worthwhile prototype found"))
    negative = assemble_delivery(research.repository, definition(research, 2, (receipt.reference,)), empty)
    assert negative.validation.status is d.ValidationStatus.PASS
    assert negative.receipt.schema_version == 10
