"""Save E9 review through local repository APIs; no experiment execution."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re

from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, create_research_context,
    publish_evidence, update_research_intent,
)
from czsc_trader.research_tools import ExperimentRef, MaterialEvidenceWrite, ResearchBatchRef


def main():
    out = Path(__file__).resolve().parent
    root = out.parents[3]
    family = root / "research/registrations/S014/family.json"

    def read(path):
        return json.loads(path.read_bytes())

    assert not (out / "publication.json").exists()
    audit, plan = read(out / "independent_review.json"), read(out / "proposal.json")
    assert audit["status"] == "PASS" and plan["execution_authorized"] is False
    for name, expected in audit["artifact_sha256"].items():
        assert sha256((out / name).read_bytes()).hexdigest() == expected, name
    for rel, expected in audit["source_sha256"].items():
        assert sha256((root / rel).read_bytes()).hexdigest() == expected, rel
    assert plan["proposed_caps"]["account_runs"] == 69
    assert plan["proposed_caps"]["node_groups"] == 145
    for key in ("new_calls", "new_labels", "new_fits", "new_accounts", "new_matching"):
        assert plan[key] == 0
    for link in re.findall(r"\]\(([^)]+)\)", (out / "report.md").read_text(encoding="utf-8")):
        assert (out / link).is_file() or link == "publication.json", link
    before = read(family)
    intent = deepcopy(before["research_intent"])
    assert "e9_extension_review" not in intent
    assert intent["strategy_accounts"] == 66 and intent["all_targets_pass_count"] == 0
    assert len(list((root / "research/S014/experiments").glob("EX*"))) == 34
    protected = {k: deepcopy(v) for k,v in intent.items() if k not in {"stage", "pending", "e9_extension_review"}}
    repo = RepositoryContext.discover(root)
    ctx = create_research_context(repo, ResearchBatchRef("S014"))
    refs = {}
    for name in ("report.md", "proposal.json", "inventory.py", "inventory.json", "independent_review.json", "publish.py"):
        path = out / name
        media = {".md": "text/markdown", ".py": "text/x-python", ".json": "application/json"}[path.suffix]
        ref = publish_evidence(ctx, MaterialEvidenceWrite(
            ExperimentRef("S014", "EX034_20261018"), "e9-review-"+name.replace(".", "-"),
            path.read_bytes(), media, path.suffix[1:],
        ))
        assert ref.resolve(root).read_bytes() == path.read_bytes()
        refs[name] = ref.to_dict()
    assert read(family) == before
    intent["stage"] = "阶段二固定E9延伸方案评审完成：69次诊断账户及145组局部标签待授权"
    intent["pending"] = ["建议批准固定E9敏感性检验：最多69次诊断账户（1控制+68H路径，失败计入）及145组局部标签；77组H现金精确复用，0新数据/拟合，不自动新增期限或候选。"]
    intent["e9_extension_review"] = {
        "status": plan["status"], "authorization": plan["authorization"], "evidence": refs,
        "proposed_caps": plan["proposed_caps"], "exact_H_cash_reuse": 77,
        "H_replay_paths": 68, "control_accounts": 1,
        "execution_authorized": False, "new_calls": 0, "new_labels": 0,
        "new_fits": 0, "new_accounts": 0, "new_matching": 0,
        "fees_execution_annual_targets": "UNCHANGED",
        "new_supported_components": 0, "new_qualified_candidates": 0,
    }
    update_research_intent(repo, ctx.batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
                          reason="完成固定E9方法延伸评审，证明77节点可精确复用现金，将建议新账户压缩至69；仅留证评审，不生成新标签、不运行账户、不恢复旧额度")
    after = read(family)
    assert all(after["research_intent"].get(k) == v for k,v in protected.items())
    assert after["research_state"] == before["research_state"]
    result = {"status": "PUBLISHED_LOCAL_REVIEW_ONLY", "evidence": refs,
              "association": "EX034 followup review; no new experiment or stage delivery",
              "historical_fields_preserved": True, "proposed_accounts": 69,
              "future_execution_authorized": False, "new_accounts": 0, "new_labels": 0,
              "new_calls": 0, "new_fits": 0}
    with (out / "publication.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"saved_materials": len(refs), "historical_fields_preserved": True, "execution_authorized": False}))


if __name__ == "__main__":
    main()
