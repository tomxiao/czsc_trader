"""Publish the completed method review; never execute proposed label research."""

import json
import re
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from czsc_trader.application import (
    RepositoryContext,
    ResearchIntentUpdate,
    create_research_context,
    publish_evidence,
    update_research_intent,
)
from czsc_trader.research_tools import (
    ExperimentRef,
    MaterialEvidenceWrite,
    ResearchBatchRef,
)


def main():
    root = Path(__file__).resolve().parents[4]
    out = Path(__file__).resolve().parent
    family = root / "research/registrations/S014/family.json"

    def read(path):
        return json.loads(path.read_text(encoding="utf-8"))

    assert not (out / "publication.json").exists()
    audit = read(out / "independent_review.json")
    assert audit["status"] == "PASS"
    for name, key in {
        "report.md": "report_sha256",
        "proposal.json": "proposal_sha256",
        "inventory.json": "inventory_sha256",
        "inventory.py": "inventory_script_sha256",
    }.items():
        assert sha256((out / name).read_bytes()).hexdigest() == audit[key]
    proposal = read(out / "proposal.json")
    assert proposal["execution_authorized"] is False
    assert proposal["proposed_caps"]["decision_node_groups"] == 146
    for key in ("actual_new_calls", "actual_new_fits", "actual_new_labels",
                "actual_new_accounts", "actual_new_matching_calls"):
        assert proposal[key] == 0
    links = re.findall(r"\]\(([^)]+)\)", (out / "report.md").read_text(encoding="utf-8"))
    for link in links:
        path = (out / link).resolve()
        assert path.is_relative_to(root)
        assert path.is_file() or link == "publication.json", link
    before = read(family)
    intent = deepcopy(before["research_intent"])
    protected = {k: deepcopy(v) for k, v in intent.items()
                 if k not in {"stage", "pending", "action_value_method_review"}}
    assert "action_value_method_review" not in intent
    assert before["research_state"] == "RESEARCHING"
    assert intent["strategy_accounts"] == 66
    assert intent["all_targets_pass_count"] == 0
    assert len(list((root / "research/S014/experiments").glob("EX*"))) == 33
    repo = RepositoryContext.discover(root)
    ctx = create_research_context(repo, ResearchBatchRef("S014"))
    refs = {}
    for name in ("report.md", "proposal.json", "inventory.py", "inventory.json",
                 "independent_review.json", "publish.py"):
        path = out / name
        media = {".md": "text/markdown", ".py": "text/x-python",
                 ".json": "application/json"}[path.suffix]
        ref = publish_evidence(ctx, MaterialEvidenceWrite(
            ExperimentRef("S014", "EX033_20261018"),
            "action-value-method-review-" + name.replace(".", "-"),
            path.read_bytes(), media, path.suffix[1:],
        ))
        assert ref.resolve(root).read_bytes() == path.read_bytes()
        refs[name] = ref.to_dict()
    assert read(family) == before
    intent["stage"] = "继续S014：账户动作价值方法评审完成，一期固定终值检验待授权"
    intent["pending"] = [
        "建议批准146组固定E+6三支终值对照，失败计入；0新增数据、拟合、完整账户和撮合。当前仅完成方法评审，尚未生成新标签。"
    ]
    intent["action_value_method_review"] = {
        "status": proposal["status"],
        "authorization": proposal["current_authorization"],
        "evidence": refs,
        "anchor": proposal["anchor"],
        "proposed_caps": proposal["proposed_caps"],
        "execution_authorized": False,
        "actual_new_calls": 0, "actual_new_fits": 0,
        "actual_new_labels": 0, "actual_new_accounts": 0,
        "actual_new_matching_calls": 0,
        "new_supported_components": 0, "new_qualified_candidates": 0,
        "whole_project_pause": "NOT_IMPLEMENTED",
        "recommendation_update": "继续方法研究；取代此前整个S014暂停建议，不改变EX033及既有规则未获支持的证据结论。",
        "fees_execution_annual_targets": "UNCHANGED",
    }
    update_research_intent(
        repo, ctx.batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
        reason="完成S014动作价值方法评审并公开留证；仅建议146组固定终值检验，不启动实验、不恢复额度、不改变历史结果和经济目标",
    )
    after = read(family)
    assert all(after["research_intent"][k] == v for k, v in protected.items())
    assert after["research_state"] == before["research_state"]
    publication = {
        "status": "PUBLISHED_METHOD_REVIEW_ONLY",
        "evidence": refs,
        "association": "Post-EX033 method review; no new experiment or stage delivery",
        "protected_research_intent_sha256": sha256(json.dumps(
            protected, ensure_ascii=True, sort_keys=True).encode()).hexdigest(),
        "relative_links_checked": len(links),
        "historical_experiments": 33, "historical_accounts": 66,
        "historical_fields_preserved": True,
        "new_calls": 0, "new_fits": 0, "new_labels": 0, "new_accounts": 0,
        "future_execution_authorized": False,
    }
    with (out / "publication.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(publication, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"published": len(refs), "historical_fields_preserved": True,
                      "execution_authorized": False}))


if __name__ == "__main__":
    main()
