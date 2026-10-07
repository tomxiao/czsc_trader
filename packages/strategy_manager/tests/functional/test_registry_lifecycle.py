"""SM content identity and forward-evidence lifecycle through public contracts."""

from dataclasses import replace
import json

import pytest
from strategy_manager import (
    EvidenceRequiredError, InvalidTransitionError, PaperTradingApproval,
    PerformanceEvidence, Qualification, RegistryError, StrategyFamily, StrategyRegistry,
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


@pytest.mark.parametrize("field,value", [("change_summary", "changed"),
                                         ("strategy_payload", {"changed": True})])
def test_frozen_record_authenticates_metadata_and_payload(version_record, field, value):
    version = version_record
    assert StrategyVersion.from_dict(version.to_dict()) == version
    with pytest.raises(ValidationError, match="release_hash"):
        StrategyVersion.from_dict({**version.to_dict(), field: value})


@pytest.mark.parametrize("changes", [{"schema_version": 3}, {"governance": {}},
                                      {"origin": None}, {"release_hash": None}])
def test_frozen_record_rejects_noncurrent_structure(version_record, changes):
    version = version_record
    with pytest.raises((TypeError, ValueError, ValidationError)):
        StrategyVersion.from_dict({**version.to_dict(), **changes})


def test_lifecycle_requires_current_forward_evidence(frozen_record):
    registry, version = frozen_record
    registry.approve_paper_trading(PaperTradingApproval("S900", "v1", version.release_hash,
                                                       "test", "synthetic approval"))
    lifecycle_path = registry.root / "S900/lifecycle.jsonl"
    before = lifecycle_path.read_bytes()
    with pytest.raises(EvidenceRequiredError, match="PAPER_FORWARD"):
        registry.promote_version("S900", "v1", actor="test", reason="missing", evidence_ids=[])
    assert lifecycle_path.read_bytes() == before
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
    evidence_path = registry.root / "S900/evidence.jsonl"
    before_evidence = evidence_path.read_bytes()
    with pytest.raises(RegistryError, match="release_hash"):
        registry.record_evidence(historical)
    assert evidence_path.read_bytes() == before_evidence
    # Historical persisted input is readable; it cannot qualify current content.
    with evidence_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(historical.to_dict()) + "\n")
    assert registry.validate_all()["evidence"] == 2
    with pytest.raises(RegistryError, match="current content"):
        registry.promote_version("S900", "v1", actor="test", reason="stale",
                                 evidence_ids=[historical.evidence_id])
    assert lifecycle_path.read_bytes() == before
    registry.promote_version("S900", "v1", actor="test", reason="forward", evidence_ids=[evidence.evidence_id])
    assert registry.current_qualification("S900", "v1") is Qualification.LIVE_READY
    with pytest.raises(InvalidTransitionError, match="RESEARCH"):
        registry.approve_paper_trading(PaperTradingApproval("S900", "v1", version.release_hash,
                                                           "test", "repeat"))
    registry.downgrade_version("S900", "v1", actor="test", reason="paper only", evidence_ids=[evidence.evidence_id])
    assert registry.current_qualification("S900", "v1") is Qualification.PAPER_READY
    registry.retire_version("S900", "v1", actor="test", reason="retire")
    with pytest.raises(InvalidTransitionError):
        registry.promote_version("S900", "v1", actor="test", reason="invalid", evidence_ids=[])
