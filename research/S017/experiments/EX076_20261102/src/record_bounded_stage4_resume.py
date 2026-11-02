"""Record the current user's stage-four continuation via public research APIs."""
# ruff: noqa: E402
from neighborhoods import ROOT, E, context_for, read
from run_bounded_stage4_v1 import save, OUT
from copy import deepcopy
from czsc_trader.application import (RepositoryContext, load_candidate, publish_evidence,
    update_research_intent, ResearchIntentUpdate)
from czsc_trader import research_tools as d
from strategy_manager import CandidateKey


def main():
    repository = RepositoryContext.discover(ROOT)
    mandate = read(OUT / "mandate_reference.json")
    record = {"actor": "USER", "instruction": "切换RSCH，继续完成阶段四",
        "scope": "Six existing stage-three candidates; fixed declared 257-point design, current implementation",
        "strategy_account_limit": 269, "maximum_public_workers": 12,
        "independent_account_audit_required": False, "sealed_2026_access_authorized": False,
        "stage_five_or_freeze_authorized": False, "new_mandate": mandate}
    path = OUT / "run_authorization.json"
    save(path, record)
    context = context_for(repository, load_candidate(repository, CandidateKey("S017", "C0338")))
    reference = publish_evidence(context, d.MaterialEvidenceWrite(E, "bounded-v1-user-continuation",
        path.read_bytes(), "application/json", "json"))
    intent = deepcopy(read(ROOT / "research/registrations/S017/family.json")["research_intent"])
    intent["active_stage_four_20261102"].update(status="BOUNDED_V1_SELF_CHECK_RUNNING",
        execution_paused_by_user=False, current_parallel_work_processes=12,
        current_mandate=mandate, resume_authorization=reference.to_dict(),
        live_execution_state="research/S017/experiments/EX076_20261102/others/bounded_v1/manifest.json",
        legacy_annual_return_gates_not_used_for_new_final_acceptance=True,
        hard_gate_definition_and_final_verification_owner="RSCH_UNDER_USER_CONFIRMED_OBJECTIVES")
    intent["next_action"] = "RSCH完成六候选257点声明集及12标准压力账户，自检全部五项并按统一Calmar协议完成阶段四交付；不使用2026封存行情，不进入阶段五。"
    update_research_intent(repository, d.ResearchBatchRef("S017"), ResearchIntentUpdate(research_intent=intent),
        actor="RSCH", reason="用户明确切换RSCH继续完成阶段四；采用已评审有限点集，目标和排序方向不变")
    save(OUT / "run_authorization_publication.json", {"reference": reference.to_dict()})
    print("BOUNDED_RESUMPTION_RECORDED", reference.sha256, flush=True)


if __name__ == "__main__":
    main()
