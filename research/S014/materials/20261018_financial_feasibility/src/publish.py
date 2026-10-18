"""Publish scoped financial feasibility evidence without advancing experiments."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, create_research_context,
    publish_evidence, update_research_intent,
)
from czsc_trader.research_tools import ExperimentRef, MaterialEvidenceWrite, ResearchBatchRef

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_bytes())


def main():
    assert not (OUT / "publication.json").exists()
    audit = read(OUT / "others/review.json")
    assert audit["status"] == "PASS"
    for name, expected in audit["artifact_sha256"].items():
        assert sha256((OUT / name).read_bytes()).hexdigest() == expected, name
    for name, expected in audit["source_sha256"].items():
        assert sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
    plan = read(OUT / "proposal.json")
    assert plan["actual_calls"] == 6
    assert all(plan[k] == 0 for k in ["new_fits", "new_labels", "new_accounts"])
    family = ROOT / "research/registrations/S014/family.json"
    before = read(family)
    intent = deepcopy(before["research_intent"])
    assert "financial_feasibility" not in intent
    assert intent["strategy_accounts"] == 66 and intent["all_targets_pass_count"] == 0
    protected = {k: v for k, v in intent.items() if k not in {"stage", "pending"}}
    experiments = sorted(p.name for p in (ROOT / "research/S014/experiments").glob("EX*"))
    repo = RepositoryContext.discover(ROOT)
    ctx = create_research_context(repo, ResearchBatchRef("S014"))
    refs = {}
    for path in sorted(OUT.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        name = path.relative_to(OUT).as_posix()
        media = {".json": "application/json", ".md": "text/markdown", ".py": "text/x-python", ".csv": "text/csv"}[path.suffix]
        ref = publish_evidence(ctx, MaterialEvidenceWrite(
            ExperimentRef("S014", "EX035_20261018"),
            "financial-feasibility-" + name.replace("/", "-").replace(".", "-"),
            path.read_bytes(), media, path.suffix[1:],
        ))
        assert ref.resolve(ROOT).read_bytes() == path.read_bytes()
        refs[name] = ref.to_dict()
    assert read(family) == before
    intent["stage"] = "财务与经营信息可行性核查完成：优先盈利改善及现金质量，历史研究输入尚未就绪"
    intent["pending"] = [
        "建议切换DEV离线实现一个财务披露数据集及聚焦测试（0新调用/模型/账户）；尚未授权平台修改。",
        "财务预热另拟最多4次调用，六个前置报告期及2019年报指标；需确认新增预窗口和调用范围。",
        "正式检验前完成27期核心字段/版本原文验收，复用4期16项抽查；不追加持有期限枚举。",
    ]
    intent["financial_feasibility"] = {
        "status": plan["status"], "evidence": refs, "actual_calls": 6, "failures": 0,
        "empty": 1, "researcher_imposed_cap": 6, "user_numeric_cap_specified": False,
        "new_models": 0, "new_accounts": 0, "new_labels": 0,
        "new_supported_components": 0, "new_qualified_candidates": 0,
        "priorities": plan["prioritized_mechanisms"], "research_input_ready": False,
        "platform_change_authorized": False, "next_preheat_calls_authorized": False,
        "fees_execution_annual_targets": "UNCHANGED",
        "route_update": "Prioritize firm financial information; old holding-period diagnosis remains evidence but its next price-derived branch is not current priority.",
    }
    update_research_intent(repo, ctx.batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
                          reason="完成用户批准的财务与经营信息可行性核查：6次同账号调用、四报表覆盖及原文抽查；转向盈利改善和现金质量，不改变历史实验及经济目标，不授权DEV或新实验")
    after = read(family)
    assert all(after["research_intent"].get(k) == v for k, v in protected.items())
    assert after["research_state"] == before["research_state"]
    assert sorted(p.name for p in (ROOT / "research/S014/experiments").glob("EX*")) == experiments
    result = {"status": "PUBLISHED_FINANCIAL_FEASIBILITY_ONLY", "association": "Post-EX035 route feasibility; no new experiment/stage delivery/candidate",
              "evidence": refs, "historical_fields_preserved": True,
              "new_upstream_calls": 6, "new_models": 0, "new_accounts": 0,
              "source_versions_certified": False, "research_inputs_ready": False,
              "offline_review_passed": audit["checks_passed"]}
    with (OUT / "publication.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"published_files": len(refs), "status": result["status"], "historical_fields_preserved": True}))


if __name__ == "__main__":
    main()
