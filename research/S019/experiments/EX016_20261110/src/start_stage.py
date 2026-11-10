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
        "stage-three-authorization", (WORK / "protocols/authorization.md").read_bytes(), "text/markdown", "md"))
    receipt = ROOT / "research/S019/deliveries/PROTOTYPES/1/receipt.json"
    reference = json.loads(receipt.read_bytes())["reference"]
    assert reference["content_sha256"] == "96ada5b59c64af07197adf3894f986abeda7739aae86b08ee493b5ecb7c1ffa2"
    confirmation = approval.resolve(ROOT)
    decision = record_research_decision(repo, f.ResearchDecision(
        "S019-STAGE3-20261110", "S019", f.DecisionAction.APPROVE,
        f.StageAdvanceSubject(CandidateEvidence(receipt.relative_to(ROOT).as_posix(), sha256(receipt.read_bytes()).hexdigest()), "CANDIDATES"),
        CandidateEvidence(confirmation.relative_to(ROOT).as_posix(), approval.sha256),
        "用户对以C0035进入阶段三并追加10轮优化额度的完整提议明确回复同意。"))
    intent = json.loads((ROOT / "research/registrations/S019/family.json").read_bytes())["research_intent"]
    intent.update(stage="STAGE_THREE", stage_three_approval="APPROVED", stage_three_status="IN_PROGRESS",
        stage_three_decision=decision.to_dict(), stage_three_budget={"authorized_rounds": 10, "used_rounds": 0, "remaining_rounds": 10},
        next_action="先比较C0035的4/6/7日持有，再按账户证据优化Calmar与期限敏感性。")
    update_research_intent(repo, batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
                           reason="记录本会话明确阶段三批准及新增十轮额度")
    result = {"approval": approval.to_dict(), "decision": decision.to_dict(),
              "overview": get_research_overview(repo, batch).to_dict()}
    (WORK / "others/authorization.json").write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
    print("STAGE_THREE_APPROVED", flush=True)


if __name__ == "__main__":
    main()
