from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest
from strategy_manager import GovernanceStage, StrategyRegistry

from czsc_trader.application import (
    RepositoryContext,
    ValidationError,
    create_research_batch,
    update_research_intent,
)


def _write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def test_research_family_can_start_a_second_governed_batch(minimal_repo: Path) -> None:
    context = RepositoryContext.discover(minimal_repo)
    first = _write_json(
        minimal_repo / "first-batch.json",
        {
            "strategy_id": "S910",
            "name": "多批次研究策略",
            "scope": ["588080.SH"],
            "research_intent": {"objective": "建立首个候选"},
        },
    )
    create_research_batch(context, first, actor="tester", reason="批准首轮研究")
    second = _write_json(
        minimal_repo / "second-batch.json",
        {
            "strategy_id": "S910",
            "name": "多批次研究策略",
            "scope": ["588080.SH"],
            "research_intent": {"objective": "研究下一冻结版本"},
            "credential_id": "SGC-S910-002",
        },
    )
    result = create_research_batch(context, second, actor="tester", reason="批准第二轮研究")
    assert (result.status, result.command) == ("PASS", "research.create")
    updated = update_research_intent(
        context,
        "S910",
        _write_json(
            minimal_repo / "intent-update.json",
            {
                "research_intent": {"objective": "等待新数据继续研究"},
                "research_state": "PAUSED",
            },
        ),
        actor="tester",
        reason="暂停等待新数据",
    )

    registry = StrategyRegistry(minimal_repo / "research" / "registrations")
    assert registry.get_family("S910").research_intent == {"objective": "等待新数据继续研究"}
    assert (
        registry.get_governance_credential("S910", "SGC-S910-001").stage
        is GovernanceStage.RESEARCH_INITIATED
    )
    assert (
        registry.get_governance_credential("S910", "SGC-S910-002").stage
        is GovernanceStage.RESEARCH_INITIATED
    )
    assert result.result["research_batch_document"] == ("research/S910/batches/SGC-S910-002.md")
    assert updated.result["family"]["research_state"] == "PAUSED"
    assert (updated.status, updated.command) == ("PASS", "research.intent.update")
    credential = registry.get_governance_credential("S910", "SGC-S910-002")
    document = minimal_repo / result.result["research_batch_document"]
    assert credential.seals[-1].artifact_hashes["research_batch"] == sha256(document.read_bytes()).hexdigest()
    assert result.result["governance_credential"]["credential_hash"] == credential.credential_hash
    assert not (minimal_repo / "strategies" / "S910").exists()


def _batch(**changes):
    return {"strategy_id": "S910", "name": "public research identity", "scope": ["588080.SH"],
            "research_intent": {"objective": "synthetic"}, **changes}


def _research_files(context):
    return {path.relative_to(context.research_root): path.read_bytes()
            for path in context.research_root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("changes", [{"unexpected": True}, {"name": "conflicting name"},
                                      {"scope": ["510500.SH"]},
                                      {"credential_id": "SGC-S910-001"},
                                      {"credential_id": None}])
def test_research_creation_rejects_invalid_or_conflicting_batch_without_writes(minimal_repo, changes):
    context = RepositoryContext.discover(minimal_repo)
    create_research_batch(context, _write_json(minimal_repo / "initial.json", _batch()),
                          actor="test", reason="initial identity")
    before = _research_files(context)
    request = _write_json(minimal_repo / "invalid.json", _batch(credential_id="SGC-S910-002", **changes)
                          if "credential_id" not in changes else _batch(**changes))
    with pytest.raises(ValidationError) as error:
        create_research_batch(context, request, actor="test", reason="conflicting request")
    assert error.value.code == "research_batch_creation_failed"
    assert _research_files(context) == before
    assert not (context.strategy_root / "S910").exists()


@pytest.mark.parametrize("operation", ["create_family", "start_research_batch"])
def test_research_document_rolls_back_when_registration_fails(minimal_repo, monkeypatch, operation):
    context = RepositoryContext.discover(minimal_repo)
    request = _batch()
    if operation == "start_research_batch":
        create_research_batch(context, _write_json(minimal_repo / "initial.json", request),
                              actor="test", reason="initial identity")
        request = _batch(credential_id="SGC-S910-002")
    before = _research_files(context)
    observed = []
    def fail_registration(*args, **kwargs):
        observed.append(True)
        document = context.research_root / "S910" / (
            "HANDOFF.md" if operation == "create_family" else "batches/SGC-S910-002.md"
        )
        assert document.is_file(), "exercise failure after the requested document is published"
        raise OSError("injected registration write failure")
    monkeypatch.setattr(StrategyRegistry, operation, fail_registration)
    with pytest.raises(ValidationError) as error:
        create_research_batch(context, _write_json(minimal_repo / "request.json", request),
                              actor="test", reason="registration failure")
    assert error.value.code == "research_batch_creation_failed"
    assert observed == [True]
    assert _research_files(context) == before
    if operation == "create_family":
        assert not (context.research_root / "S910").exists()
    assert not (context.strategy_root / "S910").exists()


@pytest.mark.parametrize("update", [{}, {"unexpected": True}, {"research_state": "INVALID"}])
def test_research_intent_rejects_invalid_update_without_changing_identity(minimal_repo, update):
    context = RepositoryContext.discover(minimal_repo)
    create_research_batch(context, _write_json(minimal_repo / "initial.json", _batch()),
                          actor="test", reason="initial identity")
    before = _research_files(context)
    with pytest.raises(ValidationError) as error:
        update_research_intent(context, "S910", _write_json(minimal_repo / "update.json", update),
                               actor="test", reason="invalid update")
    assert error.value.code == "research_intent_update_failed"
    assert _research_files(context) == before
    assert not (context.strategy_root / "S910").exists()


def test_research_intent_reports_registration_write_failure(minimal_repo, monkeypatch):
    context = RepositoryContext.discover(minimal_repo)
    create_research_batch(context, _write_json(minimal_repo / "initial.json", _batch()),
                          actor="test", reason="initial identity")
    before = _research_files(context)
    def write_failure(*args, **kwargs):
        raise OSError("injected intent registration write failure")
    monkeypatch.setattr(StrategyRegistry, "update_family", write_failure)
    with pytest.raises(ValidationError) as error:
        update_research_intent(context, "S910", _write_json(minimal_repo / "update.json",
                               {"research_intent": {"objective": "changed"}}),
                               actor="test", reason="write failure")
    assert error.value.code == "research_intent_update_failed"
    assert _research_files(context) == before
