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
from test_current_contracts import (
    current_frozen as current_frozen,
    inspection as inspection,
    completed as completed,
    managed_evaluation as managed_evaluation,
)


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


def test_approval_is_content_bound_and_rejects_repeat_without_writing(current_frozen):
    context, version = current_frozen
    registry = StrategyRegistry(context.strategy_root)
    request = PaperTradingApproval("S900", "v1", version.release_hash, "user", "explicit approval")
    path = context.strategy_root / "S900/lifecycle.jsonl"
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


def test_old_content_events_do_not_grant_or_override_current_qualification(current_frozen):
    context, version = current_frozen
    registry = StrategyRegistry(context.strategy_root)
    path = context.strategy_root / "S900/lifecycle.jsonl"
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
