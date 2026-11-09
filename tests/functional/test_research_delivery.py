# Risk ownership: TDR-11 TDR-12
"""Stage handoffs authenticate conclusions and selected evidence, independently of work."""
from dataclasses import replace
from datetime import date
import json
import shutil

import pytest
from czsc_trader.application import assemble_delivery, validate_delivery, publish_evidence
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import MaterialEvidenceWrite


def content(payload=None, **kwargs):
    return d.DeliveryContent(payload=payload if payload is not None else d.ComponentPanel((), "未发现支持机制的证据"),
                            status=d.DeliveryStatus.COMPLETE, facts=(), explanations=(),
                            report=kwargs.pop("report", "研究员报告：当前结果和下一步建议。"), **kwargs)


def attachment(research, name="source", value=None):
    experiment = ExperimentRef(research.strategy_id, "EX001_20261007")
    return publish_evidence(research, MaterialEvidenceWrite(experiment, name,
        json.dumps(value if value is not None else {"measurement": .25}, sort_keys=True).encode(),
        "application/json", "json"))


def published(context, receipt):
    from czsc_trader.application.delivery_service import _delivery_path
    return _delivery_path(context, receipt.reference)


@pytest.fixture
def context(minimal_repo):
    """Material publication needs an allocated experiment, without market preparation."""
    from evaluation_seed_support import restored_context
    from czsc_trader.application import create_experiment, ExperimentRequest

    research = restored_context(minimal_repo)
    create_experiment(research, ExperimentRequest("Synthetic publication", "Evidence integrity", date(2026, 10, 7)))
    return research


@pytest.mark.parametrize('remove_source', [pytest.param(False, id='TDR-11-C01'), pytest.param(True, id='TDR-11-C02')])
def test_delivery_keeps_selected_evidence_and_excludes_work(context, remove_source):
    reference = attachment(context)
    fact = d.FactValue("sample", .25, "ratio", d.FactStatus.AVAILABLE, (reference,))
    definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.COMPONENTS, 1)
    value = replace(content(), facts=(fact,))
    experiment = reference.experiment.resolve(context.repository.root)
    (experiment / "others/unselected.txt").write_text("technical iteration")
    receipt = assemble_delivery(context.repository, definition, value).receipt
    publication = published(context.repository, receipt)
    assert (publication / reference.path).is_file()
    assert not list(publication.rglob("others"))
    if remove_source:
        shutil.rmtree(experiment / "others")
        reference.resolve(context.repository.root).unlink()
    assert validate_delivery(context.repository, receipt.reference).status is d.ValidationStatus.PASS
    assert d.DeliveryContent.from_dict(json.loads((publication / "delivery.json").read_text(encoding="utf-8"))["content"]) == value


def test_TDR_11_C03_missing_direct_predecessor_blocks_publication(context):
    from czsc_trader.application.delivery_service import _delivery_path
    parent = assemble_delivery(context.repository,
        d.DeliveryDefinition(context.batch, d.DeliveryStage.COMPONENTS, 1), content()).receipt.reference
    shutil.rmtree(_delivery_path(context.repository, parent))
    definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.COMPONENTS, 2, (parent,))
    with pytest.raises(d.DeliveryValidationError):
        assemble_delivery(context.repository, definition, content())
    assert not (context.repository.research_root / 'S900/deliveries/COMPONENTS/2').exists()
    assert not (context.repository.research_root / 'S900/assets/deliveries/COMPONENTS/2').exists()


def test_TDR_12_C01_stage_payload_and_explicit_partial_state(context):
    definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.COMPONENTS, 1)
    with pytest.raises(d.DeliveryValidationError):
        assemble_delivery(context.repository, definition, content(d.ResearchMandate(()))).receipt


def test_TDR_11_C08_public_publication_failure_rolls_back_its_complete_package(context, monkeypatch):
    from pathlib import Path
    from czsc_trader.application.delivery_service import _delivery_path, _public_delivery_path

    definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.COMPONENTS, 1)
    public = _public_delivery_path(context.repository, definition)
    package = _delivery_path(context.repository, definition)
    original = Path.rename

    def fail_public(source, target):
        if target == public:
            raise OSError("public publication denied")
        return original(source, target)

    monkeypatch.setattr(Path, "rename", fail_public)
    with pytest.raises(d.DeliveryValidationError, match="public publication denied"):
        assemble_delivery(context.repository, definition, content()).receipt
    assert not package.exists() and not public.exists()
    monkeypatch.undo()
    receipt = assemble_delivery(context.repository, definition, content()).receipt
    assert validate_delivery(context.repository, receipt.reference).status is d.ValidationStatus.PASS


def test_TDR_12_C03_partial_requires_explicit_missing_items(context):
    definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.COMPONENTS, 1)
    partial = replace(content(), status=d.DeliveryStatus.PARTIAL, incomplete_items=("缺失资金流数据",))
    receipt = assemble_delivery(context.repository, definition, partial).receipt
    assert validate_delivery(context.repository, receipt.reference).status is d.ValidationStatus.PASS
    with pytest.raises(ValueError):
        replace(partial, incomplete_items=())
