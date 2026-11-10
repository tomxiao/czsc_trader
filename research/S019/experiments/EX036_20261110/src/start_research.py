"""Record the actual user approval for stage three and ten additional rounds."""
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader import research_tools as d
from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, create_research_context, get_research_overview,
    publish_evidence, record_research_decision, update_research_intent,
)
from dataflows import ProviderConfig
from strategy_manager import CandidateEvidence
from strategy_manager import freeze_contracts as f

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]


def main():
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef("S019")
    context = create_research_context(repo, batch, providers=ProviderConfig(bindings={}, equity_bindings={}))
    approval = publish_evidence(context, d.MaterialEvidenceWrite(d.ExperimentRef("S019", WORK.name),
        "joint-search-authorization", (WORK / "protocols/authorization.md").read_bytes(), "text/markdown", "md"))
    receipt = ROOT / "research/S019/deliveries/CANDIDATES/2/receipt.json"
    reference = json.loads(receipt.read_bytes())["reference"]
    assert reference["content_sha256"] == "0bed99d849922132a48f69feac800eb8c2b116182ed1ca351dbbd34c5b3630a3"
    confirmation = approval.resolve(ROOT)
    decision = record_research_decision(repo, f.ResearchDecision(
        "S019-JOINT-20261110", "S019", f.DecisionAction.APPROVE,
        f.StageAdvanceSubject(CandidateEvidence(receipt.relative_to(ROOT).as_posix(), sha256(receipt.read_bytes()).hexdigest()), "CANDIDATES"),
        CandidateEvidence(confirmation.relative_to(ROOT).as_posix(), approval.sha256),
        "用户批准新增10轮，暂停后明确恢复并要求C0067及C0101各一轮联合参数搜索。"))
    intent = json.loads((ROOT / "research/registrations/S019/family.json").read_bytes())["research_intent"]
    intent.update(stage="STAGE_THREE", joint_search_status="IN_PROGRESS",
        joint_search_decision=decision.to_dict(),
        joint_search_budget={"authorized_rounds": 10, "used_rounds": 0, "remaining_rounds": 10,
                             "scheduled_rounds": 2, "scheduled_proposals": 96},
        next_action="Optuna多变量TPE分别搜索C0067四维与C0101七维，各48次提议，保持原目标。")
    update_research_intent(repo, batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
                           reason="记录新增十轮及用户明确恢复后的双研究族联合搜索授权。")
    result = {"approval": approval.to_dict(), "decision": decision.to_dict(),
              "overview": get_research_overview(repo, batch).to_dict()}
    (WORK / "others/authorization.json").write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
    print("EXTENSION_APPROVED", flush=True)


if __name__ == "__main__":
    main()
