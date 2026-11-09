"""SM content identity and forward-evidence lifecycle through public contracts."""

from dataclasses import replace
import json

import pytest
from strategy_manager import (
    EvidenceRequiredError, InvalidTransitionError, PaperTradingApproval,
    PerformanceEvidence, RegistryError, StrategyFamily, StrategyRegistry,
    StrategyVersion, ValidationError, canonical_sha256,
)


@pytest.fixture
def version_record():
    """Model validation needs only authenticated input, without registry writes."""
    raw = {
        "schema_version": 5, "strategy_id": "S900", "version": "v1", "release_id": "S900-v1",
        "parent_version": None, "change_summary": "SM content", "source_experiment": "20261001_S900_EX01",
        "source_candidate": "C0001", "selection_data_cutoff": "2026-09-21",
        "forward_start": "2026-09-22", "strategy_payload": {"test": "SM only"},
    }
    return StrategyVersion.from_dict({**raw, "release_hash": canonical_sha256(raw)})


@pytest.fixture
def frozen_record(tmp_path, version_record):
    registry = StrategyRegistry(tmp_path)
    family = StrategyFamily.from_dict({
        "schema_version": 2, "strategy_id": "S900", "name": "SM contract input",
        "scope": ["588080.SH"], "research_intent": {"objective": "test"},
        "research_state": "RESEARCHING", "created_at": "2026-10-01T10:00:00+08:00",
        "created_by": "tester", "updated_at": "2026-10-01T10:00:00+08:00",
    })
    registry.create_family(family, actor="tester", reason="synthetic input")
    version = version_record
    path = tmp_path / "S900/versions/v1.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(version.to_dict()), encoding="utf-8")
    return registry, version


@pytest.mark.parametrize('field,value', [
    pytest.param("change_summary", "changed", id='SM-13-C01'),
    pytest.param("strategy_payload", {"changed": True}, id='SM-13-C02'),
])
@pytest.mark.risk_cases('SM-13-C01', 'SM-13-C02')
def test_frozen_record_authenticates_metadata_and_payload(version_record, field, value):
    version = version_record
    assert StrategyVersion.from_dict(version.to_dict()) == version
    with pytest.raises(ValidationError, match="release_hash"):
        StrategyVersion.from_dict({**version.to_dict(), field: value})




@pytest.fixture
def forward_evidence(version_record):
    version = version_record
    return PerformanceEvidence.from_dict({
        "schema_version": 1, "evidence_id": "forward1", "strategy_id": "S900", "version": "v1",
        "release_hash": version.release_hash, "phase": "PAPER_FORWARD",
        "period_start": "2026-10-01", "period_end": "2026-10-02",
        "data_identity": {"fixture": "synthetic"}, "initial_capital": 100000., "fee_rate": .001,
        "maximum_drawdown": -.01, "calmar_ratio": 1., "win_loss_ratio": None,
        "win_loss_ratio_status": "UNAVAILABLE", "total_return": .01, "sharpe_ratio": None,
        "closed_trades": 0, "source_path": "synthetic.json", "source_hash": "a" * 64,
        "recorded_at": "2026-10-02T10:00:00+08:00", "recorded_by": "test",
    })


def approve(registry, version):
    registry.approve_paper_trading(PaperTradingApproval(
        "S900", "v1", version.release_hash, "test", "synthetic approval"))


@pytest.mark.risk_cases('SM-14-C05')
def test_SM_14_C05_live_promotion_requires_current_forward_evidence(frozen_record):
    registry, version = frozen_record
    approve(registry, version)
    path = registry.root / "S900/lifecycle.jsonl"
    before = path.read_bytes()
    with pytest.raises(EvidenceRequiredError, match="PAPER_FORWARD"):
        registry.promote_version("S900", "v1", actor="test", reason="missing", evidence_ids=[])
    assert path.read_bytes() == before


@pytest.mark.risk_cases('SM-14-C07')
def test_SM_14_C07_retired_version_cannot_promote(frozen_record):
    registry, version = frozen_record
    approve(registry, version)
    registry.retire_version("S900", "v1", actor="test", reason="retire")
    path = registry.root / "S900/lifecycle.jsonl"
    before = path.read_bytes()
    with pytest.raises(InvalidTransitionError):
        registry.promote_version("S900", "v1", actor="test", reason="invalid", evidence_ids=[])
    assert path.read_bytes() == before


@pytest.mark.risk_cases('SM-15-C01')
def test_SM_15_C01_unavailable_metrics_remain_null(frozen_record, forward_evidence):
    registry, _ = frozen_record
    evidence = replace(forward_evidence, calmar_ratio=None, sharpe_ratio=None)
    assert registry.record_evidence(evidence) == evidence
    stored = registry.evidence("S900", "v1")
    assert stored == [evidence]
    assert stored[0].calmar_ratio is None
    assert stored[0].sharpe_ratio is None


@pytest.mark.risk_cases('SM-15-C02')
def test_SM_15_C02_stale_evidence_is_readable_but_cannot_qualify_current_version(
    frozen_record, forward_evidence,
):
    registry, version = frozen_record
    approve(registry, version)
    registry.record_evidence(forward_evidence)
    historical = replace(forward_evidence, evidence_id="previous-content", release_hash="0" * 64)
    path = registry.root / "S900/evidence.jsonl"
    before = path.read_bytes()
    with pytest.raises(RegistryError, match="release_hash"):
        registry.record_evidence(historical)
    assert path.read_bytes() == before
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(historical.to_dict()) + "\n")
    assert registry.evidence("S900", "v1") == [forward_evidence, historical]
    lifecycle = registry.root / "S900/lifecycle.jsonl"
    before = lifecycle.read_bytes()
    with pytest.raises(RegistryError, match="current content"):
        registry.promote_version("S900", "v1", actor="test", reason="stale",
                                 evidence_ids=[historical.evidence_id])
    assert lifecycle.read_bytes() == before


@pytest.mark.risk_cases('SM-15-C03')
def test_SM_15_C03_source_hash_mismatch_does_not_register(frozen_record, forward_evidence, tmp_path):
    registry, _ = frozen_record
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"source": {"changed": True}}), encoding="utf-8")
    with pytest.raises(RegistryError, match="source evidence hash mismatch"):
        registry.record_evidence(forward_evidence, source_file=source)
    assert registry.evidence("S900", "v1") == []
    assert not (registry.root / "S900/evidence/forward1.json").exists()




@pytest.mark.risk_cases('SM-15-C04')
def test_SM_15_C04_pte_export_preserves_statistics_and_artifact(frozen_record, tmp_path):
    from paper_trading_engine.performance_export import export_performance

    registry, version = frozen_record

    class Observations:
        """A minimal read port; the real exporter computes and serializes the evidence."""
        def virtual_account(self, account_id):
            assert account_id == "forward"
            return {"strategy_id": "S900", "strategy_name_snapshot": "Synthetic",
                    "strategy_version": "v1", "release_hash": version.release_hash,
                    "qualification_snapshot": "PAPER_READY", "initial_cash": "1000",
                    "created_at": "2026-10-01T00:00:00+00:00", "observation_start": "2026-10-01"}

        def account_snapshots(self, account_id):
            return [{"session": "2026-10-01", "total_assets": "900"}]

        def account_fills(self, account_id):
            return []

        def account_intents(self, account_id):
            return [{"payload": {"fee_rate": "0.001"}}]

    source = tmp_path / "pte-export.json"
    bundle = export_performance(Observations(), "forward", source, recorded_by="test")
    evidence = PerformanceEvidence.from_dict(bundle["evidence"])
    assert evidence.total_return == pytest.approx(-0.1)
    assert evidence.maximum_drawdown == pytest.approx(-0.1)
    assert evidence.calmar_ratio is None and evidence.sharpe_ratio is None
    assert evidence.win_loss_ratio_status == "NO_CLOSED_TRADES"
    assert bundle["source"]["statistics"] == {
        "observation_count": 1, "annualization_status": "INSUFFICIENT_OBSERVATIONS"}
    assert registry.record_evidence(evidence, source_file=source) == evidence
    assert registry.evidence("S900", "v1") == [evidence]
    artifact = registry.root / "S900/evidence" / f"{evidence.evidence_id}.json"
    assert artifact.read_bytes() == source.read_bytes()
