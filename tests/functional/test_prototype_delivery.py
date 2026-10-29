"""Prototype handoffs preserve executable identities without candidate promotion."""

from dataclasses import replace
import json

import pytest
from strategy_manager import CandidateKey, ResearchState, StrategyRegistry

from czsc_trader.application import (
    assemble_delivery, validate_delivery, publish_evidence, update_research_intent,
    ResearchIntentUpdate,
)
from czsc_trader.application.research_overview_service import get_research_overview
from czsc_trader import research_tools as public
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvaluationEvidenceWrite
from czsc_trader.research_tools.overview import ResearchOverview
from test_research_contract_upgrade import managed_evaluation as managed_evaluation
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


def test_prototype_revision_and_overview_preserve_research_state(overview_context):
    research, _ = overview_context
    update_research_intent(research.repository, research.batch,
        ResearchIntentUpdate(research_state=ResearchState.PAUSED), actor="test", reason="paused")
    item = entry(research)
    component = d.ComponentEntry("path", item.definition, "entry", "return", "three days",
        "unfiltered", "known at decision", "adjusted", "development", "not yet validated", ())
    use = d.PrototypeComponentUse("path", "entry", "Distinguish continuation")
    first_panel = d.PrototypePanel(
        (replace(item, components=(use,), disposition=d.PrototypeDisposition.DEVELOP),),
        (component,), (), "Researcher recommends development",
    )
    first = assemble_delivery(research.repository, definition(research), content(first_panel))
    assert first.receipt.schema_version == 10
    source = d.PrototypeReference(first.receipt.reference, "P1")
    changed = replace(item, disposition=d.PrototypeDisposition.STOP, sources=(source,),
                      judgment="The proposed mechanism was rejected")
    second = assemble_delivery(research.repository,
        definition(research, 2, (first.receipt.reference,)), content(panel(changed)))
    overview = get_research_overview(research.repository, research.batch)
    assert overview.registered_state is ResearchState.PAUSED
    assert overview.snapshot.scope == "METADATA_ONLY"
    assert len(overview.deliveries) == 1
    latest = overview.deliveries[0]
    assert latest.stage is d.DeliveryStage.PROTOTYPES
    assert latest.reference == second.receipt.reference
    assert latest.metadata_state == "READABLE"
    assert not hasattr(overview, "prototype_panels")
    assert not hasattr(overview, "counts")
    assert ResearchOverview.from_dict(json.loads(json.dumps(overview.to_dict()))) == overview
    # New claims and sources do not mutate the original package or reinterpret it.
    item.definition.evidence.resolve(research.repository.root).unlink()
    assert validate_delivery(research.repository, first.receipt.reference).status is d.ValidationStatus.PASS
    assert validate_delivery(research.repository, second.receipt.reference).status is d.ValidationStatus.PASS
    assert public.PrototypePanel is d.PrototypePanel
    assert d.PrototypePanel.from_dict(first_panel.to_dict()) == first_panel
    assert d.PrototypePanel.from_dict(panel(changed).to_dict()) == panel(changed)


def test_unregistered_prototype_authenticates_real_accounts_and_identity(managed_evaluation, monkeypatch):
    research, request = managed_evaluation
    request = research.evaluation.prepare(request)
    result = research.evaluation.evaluate(request)
    account = publish_evidence(research, EvaluationEvidenceWrite(
        ExperimentRef("S900", request.experiment_id), "prototype-account", request, result))
    run = result.runs[0].identity
    ref = d.EvaluationEvidenceRef(account, tuple(x.identity.evaluation_id for x in result.runs))
    item = entry(research, identity=d.CandidateIdentityRef(run.candidate, run.content_sha256), evaluations=(ref,))
    source_material = attachment(research, "source-material", {"source": "selected implementation"})
    parameter_material = attachment(research, "parameter-material", {"lookback": 3})
    item = replace(item, evidence=(source_material, parameter_material))

    def no_registration(*args, **kwargs):
        pytest.fail("prototype publication must not access candidate registration")

    monkeypatch.setattr(StrategyRegistry, "get_candidate_registration", no_registration)
    assembled = assemble_delivery(research.repository, definition(research), content(panel(item)))
    assert assembled.validation.stats.accounts_authenticated == 1
    assert validate_delivery(research.repository, assembled.receipt.reference).status is d.ValidationStatus.PASS
    wrong = replace(item, identity=replace(item.identity, content_sha256="b" * 64))
    with pytest.raises(d.DeliveryValidationError) as error:
        assemble_delivery(research.repository, definition(research, 2), content(panel(wrong)))
    assert error.value.issues[0].code == "CANDIDATE_CONFLICT"
    wrong = replace(item, evaluations=(replace(ref, evaluation_ids=("f" * 64,)),))
    with pytest.raises(d.DeliveryValidationError) as error:
        assemble_delivery(research.repository, definition(research, 2), content(panel(wrong)))
    assert error.value.issues[0].code == "EVALUATION_REFERENCE"
    for prefix in ("assets/deliveries", "deliveries"):
        assert not (research.repository.research_root / f"S900/{prefix}/PROTOTYPES/2").exists()
    # The package retains every explicitly selected material, including accounts,
    # rather than depending on original publication files or mutable work.
    for material in (item.definition.evidence, source_material, parameter_material, account):
        expected = material.resolve(research.repository.root).read_bytes()
        retained = published(research.repository, assembled.receipt) / material.path
        assert retained.read_bytes() == expected
        material.resolve(research.repository.root).unlink()
    assert validate_delivery(research.repository, assembled.receipt.reference).status is d.ValidationStatus.PASS
    (published(research.repository, assembled.receipt) / source_material.path).write_bytes(b"changed")
    assert validate_delivery(research.repository, assembled.receipt.reference).status is d.ValidationStatus.FAIL


def test_prototype_panel_preserves_comparisons_and_negative_delivery(overview_context):
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


@pytest.mark.parametrize("damage", ["duplicate-prototype", "duplicate-component", "duplicate-comparison", "absent-component", "absent-control",
    "self-comparison", "no-result", "missing-account-reason", "wrong-disposition", "unknown-fact"])
def test_prototype_contract_rejects_ambiguous_relationships(overview_context, damage):
    research, _ = overview_context
    item = entry(research)
    comparison = d.PrototypeComparison("compare", "P1", "U", "question", item.definition.evidence,
                                       item.evidence, "conclusion")
    with pytest.raises((ValueError, TypeError)):
        if damage == "duplicate-prototype":
            d.PrototypePanel((item, item), (), (), "duplicate")
        elif damage == "duplicate-component":
            component = d.ComponentEntry("c", item.definition, "entry", "return", "day", "none",
                "known", "adjusted", "development", "declared", ())
            replace(panel(item), components=(component, component))
        elif damage == "duplicate-comparison":
            control = replace(item, prototype_id="U")
            d.PrototypePanel((item, control), (), (comparison, comparison), "duplicate")
        elif damage == "absent-component":
            panel(replace(item, components=(d.PrototypeComponentUse("missing", "entry", "reason"),)))
        elif damage == "absent-control":
            replace(panel(item), comparisons=(comparison,))
        elif damage == "self-comparison":
            replace(comparison, control_id="P1")
        elif damage == "no-result":
            replace(comparison, evidence=())
        elif damage == "missing-account-reason":
            replace(item, missing_evaluation_reason=None)
        elif damage == "wrong-disposition":
            replace(item, disposition="DEVELOP")
        else:
            test = d.ComponentTestResult("test", "EX001_20261007", item.definition.evidence,
                d.ComponentTestStatus.SUPPORTED, "declared", item.evidence, ("unknown",))
            component = d.ComponentEntry("c", item.definition, "entry", "return", "day", "none",
                "known", "adjusted", "development", "declared", (test,))
            content(replace(panel(item), components=(component,)))


@pytest.mark.parametrize("damage", ["undeclared-source", "absent-source-entry", "source-hash", "cross-batch", "wrong-schema", "wrong-stage"])
def test_prototype_source_and_stage_errors_leave_no_publication(overview_context, damage):
    research, _ = overview_context
    item = entry(research)
    first = assemble_delivery(research.repository, definition(research), content(panel(item))).receipt
    source = d.PrototypeReference(first.reference, "P1")
    next_definition = definition(research, 2, (first.reference,))
    next_item = replace(item, sources=(source,))
    with pytest.raises((ValueError, TypeError)):
        if damage == "undeclared-source":
            next_definition = definition(research, 2)
        elif damage == "absent-source-entry":
            next_item = replace(next_item, sources=(replace(source, prototype_id="absent"),))
        elif damage == "source-hash":
            next_item = replace(next_item, sources=(replace(source,
                delivery=replace(source.delivery, content_sha256="f" * 64)),))
        elif damage == "cross-batch":
            next_item = replace(next_item, identity=replace(item.identity, key=CandidateKey("S901", "C0001")))
        elif damage == "wrong-schema":
            next_definition = replace(next_definition, schema_version=8)
        elif damage == "wrong-stage":
            next_definition = d.DeliveryDefinition(research.batch, d.DeliveryStage.COMPONENTS, 2)
        assemble_delivery(research.repository, next_definition, content(panel(next_item)))
    for prefix in ("assets/deliveries", "deliveries"):
        assert not (research.repository.research_root / f"S900/{prefix}/PROTOTYPES/2").exists()


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_prototype_material_integrity_and_atomic_failure(overview_context, damage):
    research, _ = overview_context
    item = entry(research)
    source = item.definition.evidence.resolve(research.repository.root)
    if damage == "missing":
        source.unlink()
    else:
        source.write_bytes(b"changed")
    with pytest.raises(d.DeliveryValidationError):
        assemble_delivery(research.repository, definition(research), content(panel(item)))
    for prefix in ("assets/deliveries", "deliveries"):
        assert not (research.repository.research_root / f"S900/{prefix}/PROTOTYPES/1").exists()
