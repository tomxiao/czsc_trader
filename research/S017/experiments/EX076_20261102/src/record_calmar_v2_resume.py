"""Record the user's explicit resumption without changing the mandate or execution."""
# ruff: noqa: E402
from partial_selfcheck import ROOT, WORK, read, save

import copy
from hashlib import sha256

from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, ResearchIntentUpdate,
    get_research_overview, load_candidate, publish_evidence, update_research_intent)
from strategy_manager import CandidateKey
from neighborhoods import context_for


def main():
    repository = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef("S017")
    experiment = d.ExperimentRef("S017", WORK.name)
    overview = get_research_overview(repository, batch).to_dict()
    mandate = next(item["reference"] for item in overview["deliveries"] if item["stage"] == "MANDATE")
    assert mandate["revision"] == 8 and mandate["content_sha256"] == "63c77aced4cb43e4f317c6cbf787a0a629d7c8955e441358a9ca64a1b0513d74"
    state = read(WORK / "others/neighborhood_execution_v2.json")
    assert state["status"] == "RUNNING" and state["maximum_parallel_batches"] == 12
    record = {"status": "USER_EXPLICITLY_RESUMED_STAGE_FOUR", "actor": "USER",
        "question": "建议按新标准、内存允许时以12并发恢复阶段四，是否恢复？",
        "answer": "恢复", "mandate": mandate, "branch": "codex/s017-ten-rounds",
        "full_point_count": 2829, "previously_published_points_to_cold_audit": 252,
        "new_points_to_replay": 2577, "maximum_parallel_batches": 12,
        "rss_budget_gib": 48.0, "minimum_available_memory_gib": 16.0,
        "native_threads_per_worker": 1, "nested_pools": False,
        "source_hashes": state["source_hashes"], "sealed_prices_access_authorized": False,
        "freeze_or_production_authorized": False}
    output = WORK / "others/calmar_v2_resume_authorization.json"
    if output.exists():
        assert read(output) == record
    else:
        save(output, record)
    context = context_for(repository, load_candidate(repository, CandidateKey("S017", "C0338")))
    reference = publish_evidence(context, d.MaterialEvidenceWrite(experiment,
        "calmar-v2-resume-user-authorization", output.read_bytes(), "application/json", "json"))
    intent = copy.deepcopy(read(ROOT / "research/registrations/S017/family.json")["research_intent"])
    intent["active_stage_four_20261102"].update(status="CALMAR_V2_SELF_CHECK_RUNNING",
        execution_paused_by_user=False, current_parallel_work_processes=12,
        current_mandate=mandate, resume_authorization=reference.to_dict(),
        live_execution_state="research/S017/experiments/EX076_20261102/others/neighborhood_execution_v2.json",
        legacy_annual_return_gates_not_used_for_new_final_acceptance=True,
        hard_gate_definition_and_final_verification_owner="RSCH_UNDER_USER_CONFIRMED_OBJECTIVES")
    intent["next_action"] = "RSCH按MANDATE/8完整核验252旧点并回放2577新点，内存允许时最多12并发；完整N齐备后由平台按显式规则计算排序，RSCH最终核验硬门与研究结论，不打开2026封存样本或冻结。"
    update_research_intent(repository, batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
        reason="用户对新Calmar标准、内存允许时12并发恢复阶段四的询问明确回复恢复；本次不改变规则或研究范围")
    save(WORK / "others/calmar_v2_resume_publication.json", {"reference": reference.to_dict(),
        "authorization_sha256": sha256(output.read_bytes()).hexdigest(), "status": "RESUMPTION_RECORDED"})
    print("CALMAR_V2_RESUMPTION_RECORDED", reference.sha256, flush=True)


if __name__ == "__main__":
    main()
