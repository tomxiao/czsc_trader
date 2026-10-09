"""Stage handoffs authenticate conclusions and selected evidence, independently of work."""
from dataclasses import replace
from datetime import date
import json
import shutil

import pytest
from factor_signal_catalog import CatalogStatus, FactorDefinition
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


def test_delivery_keeps_selected_evidence_and_excludes_work(context):
    reference = attachment(context)
    fact = d.FactValue("sample", .25, "ratio", d.FactStatus.AVAILABLE, (reference,))
    definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.COMPONENTS, 1)
    value = replace(content(), facts=(fact,))
    experiment = reference.experiment.resolve(context.repository.root)
    (experiment / "others/unselected.txt").write_text("technical iteration")
    receipt = assemble_delivery(context.repository, definition, value)
    publication = published(context.repository, receipt)
    assert (publication / reference.path).is_file()
    assert not list(publication.rglob("others"))
    shutil.rmtree(experiment / "others")
    reference.resolve(context.repository.root).unlink()
    assert validate_delivery(context.repository, receipt.reference).status is d.ValidationStatus.PASS
    assert d.DeliveryContent.from_dict(json.loads((publication / "delivery.json").read_text(encoding="utf-8"))["content"]) == value


def test_researcher_report_and_declared_evidence_are_preserved(context):
    reference = attachment(context, "counterexample", {"result": "negative"})
    report = (
        "先回答用户的问题。\r\n\r\n"
        "### 自选章节：反证与边界\r\n"
        f"证据：[有效负面结果](<{reference.path}>)\r\n"
        "| 解释 | 下一步 |\r\n| --- | --- |\r\n| 结论由研究员判断 | 停止 |\r\n"
    )
    value = content(report=report, evidence=(reference,))
    definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.COMPONENTS, 1)
    receipt = assemble_delivery(context.repository, definition, value)
    publication = published(context.repository, receipt)
    assert receipt.schema_version == definition.schema_version == 6
    assert (publication / "report.md").read_bytes() == report.encode("utf-8")
    assert (publication / reference.path).read_bytes() == reference.resolve(context.repository.root).read_bytes()
    reference.resolve(context.repository.root).unlink()
    assert validate_delivery(context.repository, receipt.reference).status is d.ValidationStatus.PASS
    assert assemble_delivery(context.repository, definition, value) == receipt
    with pytest.raises(d.DeliveryConflictError):
        assemble_delivery(context.repository, definition, replace(value, report=report + "新结论"))
    with pytest.raises(d.DeliveryConflictError):
        assemble_delivery(context.repository, definition,
                          replace(value, payload=d.ComponentPanel((), "changed")))
    (publication / "report.md").write_bytes(report.encode("utf-8") + b"corrupt")
    for scope in d.DeliveryValidationScope:
        assert validate_delivery(context.repository, receipt.reference, scope=scope).status is d.ValidationStatus.FAIL


def test_component_delivery_retains_claims_without_judging_the_research(context):
    reference = attachment(context, "research-material", {"researcher_claim": "需要人工判断"})
    definition = d.ExperimentDefinitionRef(reference, "researcher_component")
    test = d.ComponentTestResult("role-test", "EX002_20261007", reference,
                                d.ComponentTestStatus.SUPPORTED, "研究员解释检验方法", (reference,))
    component = d.ComponentEntry("component", definition, "风险控制", "未来收益", "20日", "对照组",
                                 "决策前可得", "复权价格", "开发池", "研究员声明支持", (test,))
    value = content(d.ComponentPanel((component,), "结论与方法由研究员负责"))
    # Selected material exists. The platform neither consults today's FSC catalog
    # nor tries to infer whether this declared method/claim is scientifically valid.
    receipt = assemble_delivery(context.repository,
        d.DeliveryDefinition(context.batch, d.DeliveryStage.COMPONENTS, 1), value)
    assert validate_delivery(context.repository, receipt.reference).status is d.ValidationStatus.PASS
    copied = published(context.repository, receipt) / reference.path
    copied.write_bytes(b"changed")
    assert validate_delivery(context.repository, receipt.reference).status is d.ValidationStatus.FAIL


def test_component_uses_selected_definition_snapshot_independently_of_current_catalog(context):
    factor = FactorDefinition(
        factor_id="F-RESEARCH", name="Selected definition", description="Researcher-owned interpretation",
        information_family="PRICE", tags=("daily",), inputs=("daily.close",),
        provider="research", implementation="researcher.component", formula="close",
        availability="After close", causality="Completed bars", parameters={},
        status=CatalogStatus.DISCOVERED, version=1,
    )
    evidence = attachment(context, "selected-factor-definition", factor.to_dict())
    reference = d.CatalogDefinitionRef(d.CatalogDefinitionKind.FACTOR, factor.factor_id,
                                       factor.version, factor.definition_sha256, evidence)
    component = d.ComponentEntry("component", reference, "环境", "收益", "20日", "对照组",
                                 "决策前", "复权", "开发池", "研究员的判断", ())
    value = content(d.ComponentPanel((component,), "定义身份可核验，研究结论由研究员负责"))
    definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.COMPONENTS, 1)
    assert not (context.repository.root / "catalog").exists()
    receipt = assemble_delivery(context.repository, definition, value)
    assert validate_delivery(context.repository, receipt.reference).status is d.ValidationStatus.PASS
    wrong = replace(component, definition=replace(reference, version=2))
    with pytest.raises(d.DeliveryValidationError, match="definition identity"):
        assemble_delivery(context.repository, replace(definition, revision=2),
                          replace(value, payload=d.ComponentPanel((wrong,), "错误的引用身份")))


def test_missing_report_evidence_blocks_publication(context):
    reference = attachment(context)
    reference.resolve(context.repository.root).unlink()
    with pytest.raises(d.DeliveryValidationError):
        assemble_delivery(context.repository,
            d.DeliveryDefinition(context.batch, d.DeliveryStage.COMPONENTS, 1),
            content(report="研究员的结论", evidence=(reference,)))
    assert not (context.repository.research_root / "S900/deliveries/COMPONENTS/1").exists()


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


@pytest.mark.parametrize("location", ["public", "package"])
def test_delivery_rejects_a_missing_public_or_complete_package(context, location):
    from czsc_trader.application.delivery_service import _public_delivery_path

    definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.COMPONENTS, 1)
    value = content()
    receipt = assemble_delivery(context.repository, definition, value)
    public = _public_delivery_path(context.repository, receipt.reference)
    package = published(context.repository, receipt)
    assert {path.name for path in public.iterdir()} == {"report.md", "receipt.json"}
    for name in ("report.md", "receipt.json"):
        assert (public / name).read_bytes() == (package / name).read_bytes()
    shutil.rmtree(public if location == "public" else package)
    assert validate_delivery(context.repository, receipt.reference).status is d.ValidationStatus.FAIL
    with pytest.raises(d.DeliveryValidationError, match="incomplete"):
        assemble_delivery(context.repository, definition, value)


@pytest.mark.parametrize("filename", ["report.md", "receipt.json"])
def test_delivery_rejects_public_copy_tampering(context, filename):
    from czsc_trader.application.delivery_service import _public_delivery_path

    definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.COMPONENTS, 1)
    value = content()
    receipt = assemble_delivery(context.repository, definition, value)
    public = _public_delivery_path(context.repository, receipt.reference)
    (public / filename).write_bytes(b"tampered")
    result = validate_delivery(context.repository, receipt.reference)
    assert result.status is d.ValidationStatus.FAIL
    assert result.issues[0].code == "PUBLIC_DELIVERY"
    with pytest.raises(d.DeliveryValidationError, match="differs"):
        assemble_delivery(context.repository, definition, value)


def test_public_publication_failure_rolls_back_its_complete_package(context, monkeypatch):
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
        assemble_delivery(context.repository, definition, content())
    assert not package.exists() and not public.exists()
    monkeypatch.undo()
    receipt = assemble_delivery(context.repository, definition, content())
    assert validate_delivery(context.repository, receipt.reference).status is d.ValidationStatus.PASS
