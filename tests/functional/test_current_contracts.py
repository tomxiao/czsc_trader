"""Current contracts and explicit rejection of retired serialized formats."""

from dataclasses import replace
import json

import pytest
from research_experiment import ExperimentBinding
from strategy_manager import StrategyRegistry, StrategyVersion, ValidationError
from strategy_runtime import ChartRuntime, StrategyRelease, RuntimeContractError
from czsc_trader.application import inspect_candidate, freeze_candidate, deploy_strategy
from czsc_trader.research_tools import delivery as d
from test_candidate_freeze import (
    inspection as inspection, approve,
    completed as completed, managed_evaluation as managed_evaluation,
)


@pytest.fixture
def current_frozen(inspection):
    context, request, source = inspection
    report = inspect_candidate(context, request)
    receipt = freeze_candidate(context, approve(context, report, source))
    assert receipt.status.value == "COMMITTED", receipt
    deploy_strategy(context, "S900-v1")
    return context, StrategyRegistry(context.strategy_root).get_version("S900", "v1")


@pytest.mark.parametrize("schema", [1, 2, 3, True, "4", None, 5])
def test_retired_release_formats_are_rejected_without_writing(tmp_path, schema):
    raw = {"schema_version": schema, "strategy_id": "S900"}
    path = tmp_path / "original.json"
    path.write_text(json.dumps(raw))
    before = path.read_bytes()
    with pytest.raises(ValidationError, match="schema_version must be 4"):
        StrategyVersion.from_dict(raw)
    with pytest.raises(RuntimeContractError, match="unsupported strategy release schema"):
        StrategyRelease.from_mapping(raw)
    assert path.read_bytes() == before


@pytest.mark.parametrize("schema", [1, 2, True, "3", 4])
def test_retired_binding_is_rejected_before_loading_source(schema):
    with pytest.raises(ValueError, match="schema_version must be 3"):
        ExperimentBinding(schema, "experiment", "Experiment", ("experiment.py",), "a" * 64, ())


@pytest.mark.parametrize("schema", [1, 2, 3, True, "4"])
def test_delivery_receipt_rejects_old_schema(schema):
    reference = d.DeliveryReference(d.MandateOwner("S900"), d.DeliveryStage.MANDATE, 1, "a" * 64)
    raw = d.DeliveryReceipt(reference, (d.EvidenceRef("report.md", "b" * 64, "text/markdown"),)).to_dict()
    raw["schema_version"] = schema
    with pytest.raises((TypeError, ValueError)):
        d.DeliveryReceipt.from_dict(raw)


def test_removed_public_names_are_unavailable():
    import czsc_trader.application as app
    import czsc_trader.backtesting as backtest
    import dataflows.bar_utils as bars
    import strategy_evaluator as se

    for module, names in (
        (d, ("LegacyDeliveryReference",)),
        (app, ("BacktestRequestV2",)),
        (backtest, ("run_backtest_v2", "_run_backtest")),
        (bars, ("validate_30m_against_daily", "validate_a_share_30m_bars")),
        (se, ("OPC_V1", "OPC_V2")),
    ):
        assert all(not hasattr(module, name) for name in names)


def test_current_frozen_identity_covers_governance_and_payload(current_frozen):
    _, version = current_frozen
    assert StrategyVersion.from_dict(version.to_dict()) == version
    for field, value in (("change_summary", "changed"), ("strategy_payload", {"changed": True})):
        raw = {**version.to_dict(), field: value}
        with pytest.raises(ValidationError, match="release_hash"):
            StrategyVersion.from_dict(raw)
        with pytest.raises(RuntimeContractError, match="complete frozen record"):
            StrategyRelease.from_mapping(raw)
    for changes in ({"schema_version": 3}, {"governance": {}}, {"origin": None}, {"release_hash": None}):
        with pytest.raises((TypeError, ValueError, ValidationError)):
            replace(version, **changes)


def test_current_chart_rejects_foreign_release_identity(current_frozen):
    context, version = current_frozen
    with pytest.raises(ValueError, match="identity hash differs"):
        ChartRuntime(context.strategy_root).render_backtest(
            version.release_id,
            {
                "contract_version": "strategy_chart.v1", "mode": "BACKTEST",
                "strategy": {"strategy_id": "S900", "reference_id": version.release_id,
                             "identity_hash": "0" * 64, "symbol": "588080.SH"},
                "window": {"evaluation_start": "2026-09-15", "evaluation_end": "2026-09-21"},
                "market_data": {"identity": "synthetic", "adjustment": "hfq", "bars": [{"date": "2026-09-15", "open": 1, "high": 1, "low": 1, "close": 1}]},
                "strategy_output": {}, "execution": {},
                "render": {"format": "html", "plotly_runtime": "embedded"},
            },
        )


def test_current_version_lifecycle_requires_forward_evidence(current_frozen):
    from strategy_manager import EvidenceRequiredError, InvalidTransitionError, PerformanceEvidence, Qualification

    context, version = current_frozen
    registry = StrategyRegistry(context.strategy_root)
    registry._transition("S900", "v1", Qualification.PAPER_READY, "PAPER_APPROVED", "test", "synthetic approval", [])
    with pytest.raises(EvidenceRequiredError, match="PAPER_FORWARD"):
        registry.promote_version("S900", "v1", actor="test", reason="missing", evidence_ids=[])
    evidence = PerformanceEvidence.from_dict({
        "schema_version": 1, "evidence_id": "forward1", "strategy_id": "S900", "version": "v1",
        "release_hash": version.release_hash, "phase": "PAPER_FORWARD",
        "period_start": "2026-10-01", "period_end": "2026-10-02",
        "data_identity": {"fixture": "synthetic"}, "initial_capital": 100000., "fee_rate": .001,
        "maximum_drawdown": -.01, "calmar_ratio": 1., "win_loss_ratio": None,
        "win_loss_ratio_status": "UNAVAILABLE", "total_return": .01, "sharpe_ratio": None,
        "closed_trades": 0, "source_path": "synthetic.json", "source_hash": "a" * 64,
        "recorded_at": "2026-10-02T10:00:00+08:00", "recorded_by": "test",
    })
    registry.record_evidence(evidence)
    registry.promote_version("S900", "v1", actor="test", reason="forward", evidence_ids=[evidence.evidence_id])
    assert registry.current_qualification("S900", "v1") is Qualification.LIVE_READY
    registry.retire_version("S900", "v1", actor="test", reason="retire")
    with pytest.raises(InvalidTransitionError):
        registry.promote_version("S900", "v1", actor="test", reason="invalid", evidence_ids=[])
