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
        "mechanism-extension-authorization", (WORK / "protocols/authorization.md").read_bytes(), "text/markdown", "md"))
    receipt = ROOT / "research/S019/deliveries/CANDIDATES/1/receipt.json"
    reference = json.loads(receipt.read_bytes())["reference"]
    assert reference["content_sha256"] == "2cf3962a685d5475c141dd2d46f259a1ab5e06d954cd9881fb21a9ef97dbbd3e"
    confirmation = approval.resolve(ROOT)
    decision = record_research_decision(repo, f.ResearchDecision(
        "S019-REOPEN-20261110", "S019", f.DecisionAction.APPROVE,
        f.StageAdvanceSubject(CandidateEvidence(receipt.relative_to(ROOT).as_posix(), sha256(receipt.read_bytes()).hexdigest()), "COMPONENTS"),
        CandidateEvidence(confirmation.relative_to(ROOT).as_posix(), approval.sha256),
        "用户明确再授权10轮，并授权RSCH自主决定用于阶段二或三及具体研究问题。"))
    intent = json.loads((ROOT / "research/registrations/S019/family.json").read_bytes())["research_intent"]
    intent.update(stage="STAGE_TWO", extension_status="IN_PROGRESS",
        extension_stage_authority=["STAGE_TWO", "STAGE_THREE"], extension_decision=decision.to_dict(),
        extension_budget={"authorized_rounds": 10, "used_rounds": 0, "remaining_rounds": 10},
        next_action="Review recovery mechanisms using C0067, then choose finite account comparisons.")
    update_research_intent(repo, batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
                           reason="User authorized ten more rounds and autonomous stage-two/three allocation.")
    result = {"approval": approval.to_dict(), "decision": decision.to_dict(),
              "overview": get_research_overview(repo, batch).to_dict()}
    (WORK / "others/authorization.json").write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
    print("EXTENSION_APPROVED", flush=True)


if __name__ == "__main__":
    main()
