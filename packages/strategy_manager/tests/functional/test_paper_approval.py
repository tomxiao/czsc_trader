"""Paper approval binds the current frozen content and uses public transitions."""

from dataclasses import replace
import json

import pytest

from strategy_manager import (
    PaperTradingApproval,
    StrategyRegistry,
    Qualification,
    RegistryError,
    InvalidTransitionError,
)
from strategy_manager.models import StrategyVersion, canonical_sha256


@pytest.fixture
def registered_version(tmp_path):
    """Persist a valid SM record; runtime generation belongs to TDR integration."""
    raw = {
        "schema_version": 5, "strategy_id": "S900", "version": "v1",
        "release_id": "S900-v1", "parent_version": None,
        "change_summary": "synthetic SM lifecycle",
        "source_experiment": "20261001_S900_EX01", "source_candidate": "C0001",
        "selection_data_cutoff": "2026-09-21", "forward_start": "2026-09-22",
        "strategy_payload": {"test": "SM lifecycle only"},
    }
    version = StrategyVersion.from_dict({**raw, "release_hash": canonical_sha256(raw)})
    directory = tmp_path / "S900"
    (directory / "versions").mkdir(parents=True)
    (directory / "versions/v1.json").write_text(json.dumps(version.to_dict()), encoding="utf-8")
    (directory / "lifecycle.jsonl").write_text("", encoding="utf-8")
    registry = StrategyRegistry(tmp_path)
    assert registry.get_version("S900", "v1") == version
    return registry, version




def approval(version):
    return PaperTradingApproval("S900", "v1", version.release_hash, "user", "explicit approval")


@pytest.mark.risk_cases('SM-14-C01')
def test_SM_14_C01_approval_grants_paper_qualification(registered_version):
    registry, version = registered_version
    event = registry.approve_paper_trading(approval(version))
    assert (event.from_state, event.to_state) == (Qualification.RESEARCH, Qualification.PAPER_READY)
    assert event.event_type == "PAPER_APPROVED" and event.release_hash == version.release_hash
    assert registry.assert_deployable("S900", "v1", "PAPER") == version


@pytest.mark.risk_cases('SM-14-C02')
def test_SM_14_C02_approval_rejects_wrong_hash_without_writing(registered_version):
    registry, version = registered_version
    path = registry.root / "S900/lifecycle.jsonl"
    before = path.read_bytes()
    with pytest.raises(RegistryError, match="release hash differs"):
        registry.approve_paper_trading(replace(approval(version), expected_release_hash="0" * 64))
    assert path.read_bytes() == before


@pytest.mark.risk_cases('SM-14-C03')
def test_SM_14_C03_repeat_approval_does_not_append_event(registered_version):
    registry, version = registered_version
    request = approval(version)
    registry.approve_paper_trading(request)
    path = registry.root / "S900/lifecycle.jsonl"
    approved = path.read_bytes()
    with pytest.raises(InvalidTransitionError, match="RESEARCH"):
        registry.approve_paper_trading(request)
    assert path.read_bytes() == approved


@pytest.mark.risk_cases('SM-14-C06')
def test_SM_14_C06_retired_version_cannot_be_reapproved(registered_version):
    registry, version = registered_version
    request = approval(version)
    registry.approve_paper_trading(request)
    registry.retire_version("S900", "v1", actor="user", reason="end paper trading")
    path = registry.root / "S900/lifecycle.jsonl"
    before = path.read_bytes()
    with pytest.raises(InvalidTransitionError, match="RESEARCH"):
        registry.approve_paper_trading(request)
    assert path.read_bytes() == before


@pytest.mark.risk_cases('SM-14-C04')
def test_SM_14_C04_old_events_do_not_grant_or_override_current_qualification(registered_version):
    registry, version = registered_version
    path = registry.root / "S900/lifecycle.jsonl"
    request = PaperTradingApproval("S900", "v1", version.release_hash, "user", "explicit approval")
    event = registry.approve_paper_trading(request)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[-1]["release_hash"] = "0" * 64
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    assert registry.current_qualification("S900", "v1") is Qualification.RESEARCH
    registry.approve_paper_trading(request)
    stale_retirement = replace(
        event, event_id="EVT-stale", release_hash="0" * 64, to_state=Qualification.RETIRED
    ).to_dict()
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(stale_retirement) + "\n")
    assert registry.current_qualification("S900", "v1") is Qualification.PAPER_READY
