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
    ValidationError,
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


@pytest.mark.parametrize(
    "field,value",
    [
        ("strategy_id", "S11"),
        ("version", "v0"),
        ("expected_release_hash", "a" * 63),
        ("expected_release_hash", " " + "a" * 64),
        ("actor", ""),
        ("reason", "  "),
        ("version", True),
        ("expected_release_hash", None),
    ],
)
def test_approval_rejects_invalid_fields(field, value):
    values = dict(
        strategy_id="S900",
        version="v1",
        expected_release_hash="a" * 64,
        actor="user",
        reason="approved paper trading",
    )
    values[field] = value
    with pytest.raises(ValidationError):
        PaperTradingApproval(**values)


def test_approval_is_content_bound_and_rejects_repeat_without_writing(registered_version):
    registry, version = registered_version
    request = PaperTradingApproval("S900", "v1", version.release_hash, "user", "explicit approval")
    path = registry.root / "S900/lifecycle.jsonl"
    before = path.read_bytes()
    with pytest.raises(TypeError):
        registry.approve_paper_trading({})
    with pytest.raises(RegistryError, match="release hash differs"):
        registry.approve_paper_trading(replace(request, expected_release_hash="0" * 64))
    with pytest.raises(InvalidTransitionError, match="LIVE_READY"):
        registry.downgrade_version("S900", "v1", actor="user", reason="invalid", evidence_ids=[])
    assert path.read_bytes() == before
    event = registry.approve_paper_trading(request)
    assert (event.from_state, event.to_state) == (Qualification.RESEARCH, Qualification.PAPER_READY)
    assert event.event_type == "PAPER_APPROVED" and event.release_hash == version.release_hash
    assert registry.assert_deployable("S900", "v1", "PAPER") == version
    approved = path.read_bytes()
    with pytest.raises(InvalidTransitionError, match="RESEARCH"):
        registry.approve_paper_trading(request)
    assert path.read_bytes() == approved
    registry.retire_version("S900", "v1", actor="user", reason="end paper trading")
    with pytest.raises(InvalidTransitionError, match="RESEARCH"):
        registry.approve_paper_trading(request)


def test_old_content_events_do_not_grant_or_override_current_qualification(registered_version):
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
