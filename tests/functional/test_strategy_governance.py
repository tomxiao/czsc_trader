from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from strategy_manager import GovernanceStage, StrategyRegistry

from czsc_trader.application.context import RepositoryContext
from czsc_trader.application.research_governance_service import (
    create_research_batch,
    update_research_intent,
)
from czsc_trader.application.research_registration import validate_registration_origin


REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def test_research_family_can_start_a_second_governed_batch(functional_repo: Path) -> None:
    context = RepositoryContext.discover(functional_repo)
    first = _write_json(
        functional_repo / "first-batch.json",
        {
            "strategy_id": "S910",
            "name": "多批次研究策略",
            "scope": ["588080.SH"],
            "research_intent": {"objective": "建立首个候选"},
        },
    )
    create_research_batch(context, first, actor="tester", reason="批准首轮研究")
    second = _write_json(
        functional_repo / "second-batch.json",
        {
            "strategy_id": "S910",
            "name": "多批次研究策略",
            "scope": ["588080.SH"],
            "research_intent": {"objective": "研究下一冻结版本"},
            "credential_id": "SGC-S910-002",
        },
    )
    result = create_research_batch(context, second, actor="tester", reason="批准第二轮研究")
    updated = update_research_intent(
        context,
        "S910",
        _write_json(
            functional_repo / "intent-update.json",
            {
                "research_intent": {"objective": "等待新数据继续研究"},
                "research_state": "PAUSED",
            },
        ),
        actor="tester",
        reason="暂停等待新数据",
    )

    registry = StrategyRegistry(functional_repo / "research" / "registrations")
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
    assert not (functional_repo / "strategies" / "S910").exists()


def test_historical_research_registrations_are_closed_and_traceable() -> None:
    context = RepositoryContext.discover(REPO_ROOT, explicit_root=REPO_ROOT)
    registry = StrategyRegistry(context.research_registry_root)

    for strategy_id, expected_versions in {
        "S001": ["S001-v1", "S001-v2"],
        "S002": ["S002-v1"],
        "S003": ["S003-v1"],
        "S007": ["S007-v1"],
    }.items():
        origin = validate_registration_origin(context, strategy_id)
        assert origin is not None
        assert origin["mode"] == "LEGACY_BACKFILL"
        assert origin["state"] == "PROMOTED_CLOSED"
        assert [
            item["strategy_version_id"] for item in origin["versions_at_backfill"]
        ] == expected_versions
        assert registry.get_family(strategy_id).strategy_id == strategy_id


def test_historical_registration_rejects_a_changed_frozen_version_hash(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    (root / "src" / "czsc_trader").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='origin-test'\n")
    shutil.copytree(REPO_ROOT / "strategies", root / "strategies")
    shutil.copytree(
        REPO_ROOT / "research" / "registrations",
        root / "research" / "registrations",
    )
    for strategy_id in ("S001", "S002", "S003", "S007"):
        destination = root / "research" / strategy_id / "HANDOFF.md"
        destination.parent.mkdir(parents=True)
        shutil.copy2(REPO_ROOT / "research" / strategy_id / "HANDOFF.md", destination)
    context = RepositoryContext.discover(root, explicit_root=root)
    path = context.research_registry_root / "S001" / "registration_origin.json"
    origin = json.loads(path.read_text(encoding="utf-8"))
    origin["versions_at_backfill"][0]["strategy_version_hash"] = "0" * 64
    _write_json(path, origin)

    with pytest.raises(ValueError, match="differs from frozen strategy version"):
        validate_registration_origin(context, "S001")
