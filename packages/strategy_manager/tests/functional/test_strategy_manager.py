from pathlib import Path
import json
import shutil
import pytest
from strategy_manager import (
    StrategyRegistry,
    StrategyFamily,
    EvidenceRequiredError,
    InvalidTransitionError,
    PerformanceEvidence,
    Qualification,
    RegistryError,
    ValidationError,
)

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def registry(tmp_path):
    destination = tmp_path / "strategies"
    shutil.copytree(ROOT / "strategies", destination)
    return StrategyRegistry(destination)


@pytest.mark.parametrize(
    "family,version",
    [("S001", "v1"), ("S001", "v2"), ("S002", "v1"), ("S003", "v1"), ("S007", "v1")],
)
def test_frozen_governance_remains_readable(registry, family, version):
    assert registry.validate_version_governance(family, version) == "LEGACY_GOVERNANCE_ACCEPTED"
    assert registry.get_version(family, version).release_hash
    assert registry.validate_all()["versions"] == 5


def test_retired_writers_and_models_are_unavailable():
    import strategy_manager as sm

    assert not any(name.startswith("_legacy_") for name in dir(StrategyRegistry))
    for name in (
        "append_governance_seal",
        "create_frozen_version_from_credential",
        "record_legacy_governance_acceptance",
    ):
        assert not hasattr(StrategyRegistry, name)
    for name in (
        "CandidateSnapshot",
        "EvaluationMandate",
        "AdjudicationReport",
        "FreezeReviewCase",
        "FreezeApproval",
    ):
        assert name not in sm.__all__ and not hasattr(sm, name)


def test_frozen_payload_tampering_is_rejected(registry):
    path = registry.root / "S001/versions/v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["strategy_payload"]["tampered"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises((RegistryError, ValidationError, ValueError)):
        registry.get_version("S001", "v1")


@pytest.mark.parametrize("mode", ["missing", "duplicate", "wrong_hash"])
def test_historical_acceptance_cannot_be_removed_duplicated_or_rebound(registry, mode):
    path = registry.root / "S001/lifecycle.jsonl"
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    accepted = next(
        e
        for e in events
        if e["version"] == "v1" and e["event_type"] == "LEGACY_GOVERNANCE_ACCEPTED"
    )
    if mode == "missing":
        events.remove(accepted)
    elif mode == "duplicate":
        events.append(accepted.copy())
    else:
        accepted["release_hash"] = "0" * 64
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    with pytest.raises(EvidenceRequiredError):
        registry.validate_version_governance("S001", "v1")


def test_historical_credential_chain_rejects_tampering(registry):
    path = registry.root / "S007/credentials/SGC-S007-002.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["reason"] = "changed"
    path.write_text("".join(json.dumps(e) + "\n" for e in rows), encoding="utf-8")
    with pytest.raises((RegistryError, ValidationError, ValueError)):
        registry.validate_all()


def test_lifecycle_still_requires_forward_evidence(registry):
    with pytest.raises(EvidenceRequiredError, match="PAPER_FORWARD"):
        registry.promote_version("S007", "v1", actor="test", reason="no evidence", evidence_ids=[])
    source = registry.evidence("S007", "v1")[0].to_dict()
    source.update(
        evidence_id="EVD-TEST-FORWARD",
        phase="PAPER_FORWARD",
        period_start="2026-10-01",
        period_end="2026-10-02",
    )
    registry.record_evidence(PerformanceEvidence.from_dict(source))
    registry.promote_version(
        "S007", "v1", actor="test", reason="forward evidence", evidence_ids=["EVD-TEST-FORWARD"]
    )
    assert registry.current_qualification("S007", "v1") is Qualification.LIVE_READY
    registry.retire_version("S007", "v1", actor="test", reason="retire")
    with pytest.raises(InvalidTransitionError):
        registry.promote_version("S007", "v1", actor="test", reason="invalid", evidence_ids=[])


def test_family_registration_still_validates_names_and_identity(tmp_path):
    registry = StrategyRegistry(tmp_path)
    raw = {
        "schema_version": 2,
        "strategy_id": "S900",
        "name": "test family",
        "scope": ["588080.SH"],
        "research_intent": {"objective": "test"},
        "research_state": "RESEARCHING",
        "created_at": "2026-10-01T10:00:00+08:00",
        "created_by": "tester",
        "updated_at": "2026-10-01T10:00:00+08:00",
    }
    family = StrategyFamily.from_dict(raw)
    registry.create_family(family, actor="tester", reason="authorized")
    assert registry.get_family("S900") == family
    assert registry.validate_all()["strategies"] == 1
    with pytest.raises((RegistryError, ValidationError)):
        registry.create_family(
            StrategyFamily.from_dict({**raw, "strategy_id": "S901"}),
            actor="tester",
            reason="duplicate name",
        )
