"""Stage handoffs authenticate conclusions and selected evidence, independently of work."""
from dataclasses import replace
import json
import shutil

import pytest
from czsc_trader.application import assemble_delivery, validate_delivery, publish_evidence
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import MaterialEvidenceWrite
from test_research_contract_upgrade import managed_evaluation as managed_evaluation


def content(payload=None, **kwargs):
    return d.DeliveryContent(payload=payload if payload is not None else d.ComponentPanel((), "未发现支持机制的证据"),
                            status=d.DeliveryStatus.COMPLETE, facts=(), explanations=(), **kwargs)


def attachment(research, name="source", value=None):
    experiment = ExperimentRef(research.strategy_id, "EX001_20261007")
    return publish_evidence(research, MaterialEvidenceWrite(experiment, name,
        json.dumps(value if value is not None else {"measurement": .25}, sort_keys=True).encode(),
        "application/json", "json"))


def published(context, receipt):
    from czsc_trader.application.delivery_service import _delivery_path
    return _delivery_path(context, receipt.reference)


@pytest.fixture
def context(managed_evaluation):
    return managed_evaluation[0]


def test_delivery_keeps_selected_evidence_and_excludes_work(context):
    reference = attachment(context)
    fact = d.FactValue("sample", .25, "ratio", d.FactStatus.AVAILABLE, (reference,))
    definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.COMPONENTS, 1)
    value = replace(content(), facts=(fact,))
    experiment = reference.experiment.resolve(context.repository.root)
    (experiment / "work/unselected.txt").write_text("technical iteration")
    receipt = assemble_delivery(context.repository, definition, value)
    publication = published(context.repository, receipt)
    assert (publication / reference.path).is_file()
    assert not list(publication.rglob("work"))
    shutil.rmtree(experiment / "work")
    reference.resolve(context.repository.root).unlink()
    assert validate_delivery(context.repository, receipt.reference).status is d.ValidationStatus.PASS
    assert d.DeliveryContent.from_dict(json.loads((publication / "delivery.json").read_text(encoding="utf-8"))["content"]) == value


def test_new_revision_retains_old_conclusion(context):
    definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.COMPONENTS, 1)
    first = assemble_delivery(context.repository, definition, content())
    changed = content(d.ComponentPanel((), "新检验得到不同结论"))
    second = assemble_delivery(context.repository, replace(definition, revision=2, predecessors=(first.reference,)), changed)
    assert first.reference != second.reference
    assert validate_delivery(context.repository, first.reference).status is d.ValidationStatus.PASS
    assert validate_delivery(context.repository, second.reference).status is d.ValidationStatus.PASS


def test_stage_payload_and_explicit_partial_state(context):
    definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.COMPONENTS, 1)
    with pytest.raises(d.DeliveryValidationError):
        assemble_delivery(context.repository, definition, content(d.ResearchMandate(())))
    partial = replace(content(), status=d.DeliveryStatus.PARTIAL, incomplete_items=("缺失资金流数据",))
    receipt = assemble_delivery(context.repository, definition, partial)
    assert validate_delivery(context.repository, receipt.reference).status is d.ValidationStatus.PASS
    with pytest.raises(ValueError):
        replace(partial, incomplete_items=())
