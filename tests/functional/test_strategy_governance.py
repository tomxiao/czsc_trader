from __future__ import annotations

import json
from pathlib import Path


from strategy_manager import GovernanceStage, StrategyRegistry

from czsc_trader.application.context import RepositoryContext
from czsc_trader.application.research_governance_service import (
    create_research_batch,
    update_research_intent,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


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
    assert not (minimal_repo / "strategies" / "S910").exists()
