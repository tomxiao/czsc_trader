"""Current contracts and explicit rejection of retired serialized formats."""

from dataclasses import replace
import json
from pathlib import Path

import pytest
from research_experiment import ExperimentBinding
from strategy_manager import StrategyRegistry, StrategyVersion, ValidationError, PaperTradingApproval
from strategy_runtime import StrategyRelease, RuntimeContractError
from czsc_trader.application import inspect_candidate, freeze_candidate, deploy_strategy
from czsc_trader.research_tools import delivery as d
from test_candidate_freeze import (
    inspection as inspection, approve,
    completed as completed, managed_evaluation as managed_evaluation,
)


def test_real_installed_versions_report_execution_contract_fees():
    from czsc_trader.application.context import RepositoryContext
    from czsc_trader.application.strategy_runtime_service import list_installed_strategies

    context = RepositoryContext.discover(Path(__file__).resolve().parents[2])
    result = list_installed_strategies(context)
    assert result.status == "PASS"
    assert {row["strategy_version_id"]: row["fee_rate"] for row in result.result["strategies"]} == {
        "S001-v1": 0.0005, "S001-v2": 0.0005, "S002-v1": 0.0005,
        "S003-v1": 0.00012, "S007-v1": 0.001,
    }


@pytest.fixture
def current_frozen(inspection):
    context, request, source = inspection
    report = inspect_candidate(context, request)
    receipt = freeze_candidate(context, approve(context, report, source))
    assert receipt.status.value == "COMMITTED", receipt
    deploy_strategy(context, "S900-v1")
    return context, StrategyRegistry(context.strategy_root).get_version("S900", "v1")


@pytest.mark.parametrize("schema", [1, 2, 3, 4, True, "5", None, 6])
def test_retired_release_formats_are_rejected_without_writing(tmp_path, schema):
    raw = {"schema_version": schema, "strategy_id": "S900"}
    path = tmp_path / "original.json"
    path.write_text(json.dumps(raw))
    before = path.read_bytes()
    with pytest.raises(ValidationError, match="schema_version must be 5"):
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
    import strategy_runtime as srt

    for module, names in (
        (srt, ("ChartRuntime", "validate_chart_context", "validate_observation_descriptor", "validate_observation_payload")),
        (d, ("LegacyDeliveryReference",)),
        (app, ("BacktestRequestV2",)),
        (backtest, ("run_backtest_v2", "_run_backtest")),
        (bars, ("validate_30m_against_daily", "validate_a_share_30m_bars")),
        (se, ("OPC_V1", "OPC_V2")),
    ):
        assert all(not hasattr(module, name) for name in names)


def test_current_frozen_identity_covers_metadata_and_payload(current_frozen):
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


def test_current_binding_rejects_foreign_release_identity(current_frozen):
    from strategy_runtime import StrategyRuntime, load_strategy_deployment, RuntimeCompatibilityError
    context, version = current_frozen
    deployment = load_strategy_deployment(context.strategy_root, version.release_id)
    with pytest.raises(RuntimeCompatibilityError, match="differs from frozen release"):
        StrategyRuntime().describe(StrategyRelease.from_mapping(version.to_dict()),
            source_root=deployment.source_root, runtime_binding=replace(deployment.binding, release_hash="0" * 64))


def test_current_version_lifecycle_requires_forward_evidence(current_frozen):
    from strategy_manager import EvidenceRequiredError, InvalidTransitionError, PerformanceEvidence, Qualification, RegistryError

    context, version = current_frozen
    registry = StrategyRegistry(context.strategy_root)
    registry.approve_paper_trading(PaperTradingApproval("S900", "v1", version.release_hash, "test", "synthetic approval"))
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
    historical = replace(evidence, evidence_id="previous-content", release_hash="0" * 64)
    with pytest.raises(RegistryError, match="release_hash"):
        registry.record_evidence(historical)
    # An existing historical record stays readable but cannot approve current content.
    registry._append_jsonl(context.strategy_root / "S900/evidence.jsonl", historical.to_dict())
    assert registry.validate_all()["evidence"] == 2
    with pytest.raises(RegistryError, match="current content"):
        registry.promote_version("S900", "v1", actor="test", reason="stale", evidence_ids=[historical.evidence_id])
    registry.promote_version("S900", "v1", actor="test", reason="forward", evidence_ids=[evidence.evidence_id])
    assert registry.current_qualification("S900", "v1") is Qualification.LIVE_READY
    with pytest.raises(InvalidTransitionError, match="RESEARCH"):
        registry.approve_paper_trading(PaperTradingApproval("S900", "v1", version.release_hash, "test", "repeat"))
    registry.downgrade_version("S900", "v1", actor="test", reason="paper only", evidence_ids=[evidence.evidence_id])
    assert registry.current_qualification("S900", "v1") is Qualification.PAPER_READY
    registry.retire_version("S900", "v1", actor="test", reason="retire")
    with pytest.raises(InvalidTransitionError):
        registry.promote_version("S900", "v1", actor="test", reason="invalid", evidence_ids=[])


def test_frozen_binding_rejects_observation_digest_tampering(current_frozen):
    from strategy_runtime import StrategyRuntime, RuntimeCompatibilityError, load_strategy_deployment
    context, version = current_frozen
    release = StrategyRelease.from_mapping(version.to_dict())
    deployed = load_strategy_deployment(context.strategy_root, version.release_id)
    corrupted = replace(deployed.binding, spec=replace(deployed.binding.spec, observation_sha256='0'*64))
    with pytest.raises(RuntimeCompatibilityError, match='observation'):
        StrategyRuntime().describe(release, source_root=deployed.source_root, runtime_binding=corrupted)
    with pytest.raises(RuntimeCompatibilityError, match='requires RuntimeBinding'):
        StrategyRuntime().describe(release, source_root=deployed.source_root, runtime_binding=deployed.binding.to_dict())
    with pytest.raises(RuntimeCompatibilityError):
        StrategyRuntime().describe(release, source_root=deployed.source_root)
    assert 'charts' not in deployed.binding.to_dict()
    assert all(not name.startswith('charts/') for name in deployed.install_files)
