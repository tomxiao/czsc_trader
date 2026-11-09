# Risk ownership: TDR-12 TDR-15
"""Historical contracts remain readable without permitting relabelled new writes."""
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest
from strategy_evaluator import research_models as m
from czsc_trader.application import RepositoryContext, assemble_delivery, validate_delivery
from czsc_trader.application import delivery_service as service
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef, ResearchBatchRef
from czsc_trader.research_tools.evidence import EvidenceRef
from test_research_delivery import content


@pytest.fixture
def context(minimal_repo):
    # A delivery-only fixture needs no database or market-data capability.
    return SimpleNamespace(repository=RepositoryContext.discover(minimal_repo),
                           batch=ResearchBatchRef("S900"))


def _historical_mandate(context, version=8):
    """Install an explicit immutable-format fixture, without a legacy write API."""
    target = m.ParameterGroupTarget("parameter", 32, 26,
        (m.ResearchTarget("return", m.ResearchMetric.NET_ANNUAL_RETURN,
                         lower=m.ConstantBound(0.0, False)),),
        (m.ResearchTarget("drawdown", m.ResearchMetric.DRAWDOWN_MAGNITUDE,
                         upper=m.ConstantBound(0.25, True)),))
    if version == 11:
        target = m.ParameterNeighborhoodTarget(target.target_id, 13, 16,
                                               target.joint_targets, target.all_point_targets)
    payload = d.ResearchMandate((d.MandateItem("parameter", d.MandateItemKind.CONSTRAINT,
        "Historical fixed-count contract", d.ConfirmationRecord(d.ConfirmationStatus.PROPOSED),
        d.PerformanceRequirement((target,))),))
    definition = d.DeliveryDefinition(context.batch, d.DeliveryStage.MANDATE, 1, schema_version=version)
    value = content(payload)
    root = service._delivery_path(context.repository, definition)
    root.mkdir(parents=True)
    (root / "delivery.json").write_bytes(d._canonical({"schema_version": version,
        "definition": definition.to_dict(), "content": value.to_dict()}))
    (root / "report.md").write_bytes(value.report.encode())
    files = service._manifest(root)
    reference = d.DeliveryReference(context.batch, d.DeliveryStage.MANDATE, 1, d._digest(files))
    receipt = d.DeliveryReceipt(reference, files, schema_version=version)
    (root / "receipt.json").write_bytes(d._canonical(receipt))
    public = service._public_delivery_path(context.repository, reference)
    public.mkdir(parents=True)
    for name in ("report.md", "receipt.json"):
        (public / name).write_bytes((root / name).read_bytes())
    return definition, value, receipt, root


@pytest.mark.parametrize("version", [pytest.param(8, id='TDR-12-C07')])
def test_historical_mandate_full_read_preserves_bytes_and_cannot_be_republished(context, version):
    definition, value, receipt, root = _historical_mandate(context, version)
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    result = validate_delivery(context.repository, receipt.reference)
    assert result.status is d.ValidationStatus.PASS, result.issues
    assert before == {path.name: path.read_bytes() for path in root.iterdir()}
    assert d.DeliveryDefinition.from_dict(definition.to_dict()) == definition
    assert d.DeliveryReceipt.from_dict(receipt.to_dict()) == receipt
    with pytest.raises(d.DeliveryValidationError, match="read-only"):
        assemble_delivery(context.repository, definition, value)
    if version == 8:
        with pytest.raises(d.DeliveryValidationError, match="historical methods"):
            assemble_delivery(context.repository, replace(definition, revision=2, schema_version=12), value)


def _account_ref(version):
    return EvidenceRef(ExperimentRef("S900", "EX001_20261007"), "a" * 64 + ".json", "a" * 64,
                       "application/json", "account", "account_evaluation", version)


@pytest.mark.parametrize('body,reference', [(7, 8)])
def test_TDR_12_C09_account_reference_schema_cannot_relabel_document(monkeypatch, body, reference):
    from czsc_trader.research_tools import evaluation
    calls = []
    monkeypatch.setattr(evaluation, "validate_evaluation_evidence", calls.append)
    with pytest.raises(d.DeliveryValidationError, match="schema differs"):
        service._certify_account(json.dumps({"schema_version": body}).encode(), _account_ref(reference))
    assert calls == []
