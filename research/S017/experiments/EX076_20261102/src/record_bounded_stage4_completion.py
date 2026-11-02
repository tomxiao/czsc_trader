"""Close the completed stage-four intent through the public research API."""
# ruff: noqa: E402
from copy import deepcopy

from neighborhoods import ROOT, E, context_for, read
from run_bounded_stage4_v1 import OUT, save
from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, load_candidate, publish_evidence,
    update_research_intent,
)
from czsc_trader import research_tools as d
from strategy_manager import CandidateKey


def main():
    publication = read(OUT / "publication.json")
    analysis = read(OUT / "analysis.json")
    manifest = read(OUT / "manifest.json")
    verification = read(OUT / "rsch_verification.json")
    assert publication["status"] == "STAGE4_COMPLETE_SCHEMA15_FULL_PASS"
    assert manifest["status"] == "COMPLETED"
    assert verification["hard_target_statuses_equal"]
    assessment = publication["assessment"]["reference"]
    repository = RepositoryContext.discover(ROOT)
    intent = deepcopy(read(ROOT / "research/registrations/S017/family.json")["research_intent"])
    previous = intent["active_stage_four_20261102"]
    completion = {
        "status": "STAGE4_COMPLETE_PENDING_USER_STAGE_FIVE_SELECTION",
        "assessment": assessment,
        "report": publication["report"],
        "mandate": read(OUT / "mandate_reference.json"),
        "rankable_candidates": analysis["rankable_candidates"],
        "recommended_candidate": "C0342",
        "excluded_candidates": {"C0339": "17 of 42 declared parameter points exceed the 25% drawdown cap"},
        "declared_parameter_points": 257,
        "strategy_accounts": 269,
        "shared_benchmark_accounts": 2,
        "original_2829_point_cartesian_design_completed": False,
        "hard_gate_definition_and_final_verification_owner": "RSCH_UNDER_USER_CONFIRMED_OBJECTIVES",
        "tdr_role": "DETERMINISTIC_CALCULATION_AND_SORTING_BY_EXPLICIT_INPUT_RULES",
        "independent_net_annual_return_gate_used": False,
        "independent_account_audit_performed": False,
        "execution_elapsed_seconds": analysis["execution_observation"]["elapsed_seconds"],
        "formal_delivery_validation_stats": publication["assembly_full_validation"].get("stats"),
        "formal_delivery_retry": read(OUT / "delivery_only_retry.json"),
        "delivery_processing_review": {
            "basis": "Read-only code review; no live stack sample or per-loop timing",
            "account_dependency_closures": "Cache hits still materialize the complete account dependency closure in multiple serial passes",
            "source_plan_processing": "All 2829 source children reconstructed and validated despite 257 selected points",
            "progress_gap": "Account closure and parameter plan checks precede the RECOMPUTATION event without granular progress",
            "additional_account_replays": 0,
            "performance_target_proven": False,
        },
        "maximum_parallel_work_processes": 12,
        "current_parallel_work_processes": 0,
        "sealed_2026_prices_accessed": False,
        "stage_five_authorized": False,
        "freeze_or_production_authorized": False,
        "family_selection_bias": "INSUFFICIENT_DATA_REPORT_ONLY",
        "annual_excess_return_95pct_intervals": "ALL_SIX_INCLUDE_ZERO",
        "resume_authorization": previous["resume_authorization"],
        "execution_manifest": "research/S017/experiments/EX076_20261102/others/bounded_v1/manifest.json",
        "publication_record": "research/S017/experiments/EX076_20261102/others/bounded_v1/publication.json",
    }
    context = context_for(repository, load_candidate(repository, CandidateKey("S017", "C0342")))
    path = OUT / "completion.json"
    save(path, completion)
    evidence = publish_evidence(context, d.MaterialEvidenceWrite(
        E, "bounded-v1-stage-four-completion", path.read_bytes(), "application/json", "json"))
    intent["active_stage_four_20261102"] = {**completion, "completion_evidence": evidence.to_dict()}
    intent["next_action"] = "阶段四完成：推荐C0342，等待用户选择是否进入阶段五技术检验；不读取2026封存行情，不冻结或部署。"
    update_research_intent(repository, d.ResearchBatchRef("S017"), ResearchIntentUpdate(research_intent=intent),
        actor="RSCH", reason="257点及12中心标准压力场景完成，RSCH硬门与排序核验、ASSESSMENT FULL及报告发布均通过")
    save(OUT / "completion_publication.json", {"reference": evidence.to_dict()})
    print("STAGE4_COMPLETION_RECORDED", assessment["content_sha256"], flush=True)


if __name__ == "__main__":
    main()
