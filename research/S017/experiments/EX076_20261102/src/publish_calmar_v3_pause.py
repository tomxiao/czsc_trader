"""Record the latest pause and preserve current results; do not run any accounts."""
# ruff: noqa: E402
from partial_selfcheck import ROOT, WORK, read, save

import copy
from datetime import datetime
from hashlib import sha256

from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, ResearchIntentUpdate,
    load_candidate, publish_evidence, update_research_intent, validate_experiment)
from strategy_manager import CandidateKey
from neighborhoods import context_for


def main():
    accepted = read(WORK / "others/complete_numeric_aggregation_rsch_acceptance.json")
    assert accepted["status"] == "PASS_RSCH_PERFORMANCE_INPUT_EQUIVALENCE"
    assert read(WORK / "others/neighborhood_execution_v2_control.json")["pause_requested"] is True
    failed = read(WORK / "others/neighborhood_execution_v2.json")
    assert failed["status"] == "FAILED_EXPLICIT_REVIEW_NO_RETRY"
    assert not (WORK / "others/neighborhood_batches_v2/b-C0342-0048-v3.json").exists()
    record = {"status": "PAUSED_BY_USER_AFTER_CURRENT_PROCESSES_FINISHED",
        "user_instruction": "完成当前进程的计算任务后请先暂停", "recorded_at": datetime.now().astimezone().isoformat(),
        "current_computation_processes": 0, "original_published_points": 252,
        "new_completed_batch_points": 192, "old_points_cold_audited": 108,
        "additional_checkpoint_publication_receipts_pending_recovery": 8,
        "recovery_probe_started": False, "new_or_resumed_batches_started_after_pause": 0,
        "v3_validation": "RUFF_AND_AST_ONLY_NOT_REAL_RECOVERY_ACCEPTANCE",
        "numeric_capability_rsch_acceptance": "PASS_16_EXISTING_ACCOUNTS_ZERO_REPLAYS",
        "whole_request_TDR_FULL_claimed": False, "stage_four_complete": False,
        "next_action": "等待用户明确恢复后，先验收公开RESUME复用探针，再恢复完整点集；当前不计算新点、不自动恢复。"}
    output = WORK / "others/calmar_v3_pause_state.json"
    assert not output.exists(), "Existing pause publication requires explicit review"
    save(output, record)
    repository = RepositoryContext.discover(ROOT)
    batch, experiment = d.ResearchBatchRef("S017"), d.ExperimentRef("S017", WORK.name)
    context = context_for(repository, load_candidate(repository, CandidateKey("S017", "C0338")))
    materials = {}
    for name, path in (
        ("calmar-v3-user-pause", output),
        ("complete-numeric-aggregation-request", WORK / "protocols/complete_numeric_aggregation_request.md"),
        ("complete-numeric-aggregation-dev", WORK / "others/complete_numeric_aggregation_dev_completion.json"),
        ("complete-numeric-aggregation-rsch-acceptance", WORK / "others/complete_numeric_aggregation_rsch_acceptance.json"),
        ("calmar-v2-pool-failure-inventory", WORK / "others/calmar_v2_pool_failure_inventory.json"),
        ("calmar-v2-failed-state", WORK / "others/interrupted_attempts/calmar_v2_pool_failure/neighborhood_execution_v2.json"),
        ("calmar-v3-explicit-recovery-manifest", WORK / "others/calmar_v3_recovery_manifest.json"),
        ("calmar-v3-independent-process-source", WORK / "src/resume_calmar_v3.py"),
        ("calmar-v2-complete-analysis-source", WORK / "src/finalize_calmar_v2_analysis.py"),
        ("calmar-v2-complete-numeric-source", WORK / "src/complete_calmar_v2_ranking.py"),
        ("calmar-v3-pause-publication-source", WORK / "src/publish_calmar_v3_pause.py"),
    ):
        mime = {".json": "application/json", ".md": "text/markdown", ".py": "text/x-python"}[path.suffix]
        materials[name] = publish_evidence(context, d.MaterialEvidenceWrite(experiment, name,
            path.read_bytes(), mime, path.suffix[1:]))
    report = """# EX076：按用户最新指令暂停，保留结果与显式恢复清单

用户先批准按统一Calmar约定恢复阶段四，随后明确要求“完成当前进程的计算任务后请先暂停”。当前原邻点进程池已因技术故障退出，16既有账户两路数值验收已完成，已核实无运行中的自检进程。控制已设pause_requested=true；未启动独立进程恢复探针或任何新批次，保持暂停等待下一步指令。

## 做了哪些尝试

本次恢复沿用MANDATE/8、原prospective完整2829点及真实边界，最多12批并发、每进程1线程。252旧点保留，其中108点完成冷读复核；192个新点完成回放、认证、发布及批次收尾。检查点另有两批共8份发布回执，尚未完成恢复收尾，未混入192点计数。其余在途缓存及未派单点均保留，不重置N或自动重试。

原ProcessPoolExecutor工作进程回收时，在multiprocessing.Queue._sem.release报告WinError 6无效句柄，进而BrokenProcessPool。调度明确失败并停派单；没有证明内存不足，也没有确认其与公开Python相近问题属于同一根因。RSCH已核对旧进程退出、全部在途文件、断点存在和实现身份；原故障状态及11份未收尾工作JSON按SHA归档，已完成结果保持原位。

显式v3恢复清单覆盖全部剩余点。新研究编排改用每批一个独立Popen进程，保留最多12批、48GiB进程树预算、至少16GiB可用内存和35%批峰值余量；现存断点只用公开RESUME，不匹配时明确失败，不回退CREATE。该脚本仅通过Ruff及AST静态检查，真实恢复尚未验收。按最新暂停指令没有启动探针或全队列。

## 有哪些收获

RSCH提出逐点绩效事实的完整聚合需求，DEV在SE新增强类型纯数值输入，复用v8计算和v6排序，本地提交ed75fda1d。281项单进程SE聚焦检查、Ruff和差异空白检查通过，未执行全仓回归。RSCH复用六标准、六压力、四邻点共16个已发布账户，原账与绩效输入两路的全部数值行、分位数、覆盖、目标判定及比较一致，标准投影与真实来源准备一致；认证18份唯一账本，零新研究回放。

新面板明确标为PERFORMANCE_PROJECTION，不宣称该输入调用重新执行所有原账TDR FULL审计；该类型尚未整合原全账CandidateAssessmentDelivery/FULL。正式ASSESSMENT交付未发布，完整N尚未齐备，当前没有六配置最终排名或策略通过结论。RSCH制定并最终核验用户确认的硬门，平台按显式事实和规则计算。当前无独立净年化收益门，旧annual joint_pass和压力年化失败仅属于旧规则历史。

## 下一步建议

当前保持暂停。用户明确恢复后，先用单批验证公开RESUME能复用4个已算结果和4份发布，再按资源约定恢复剩余完整点集；全部N齐备后才计算完整分位数和平台排序，RSCH独立核验研究条件。2026封存价格及绩效未读取，未新搜、冻结、部署、合并或推送。

## 有什么依据

[暂停状态](others/calmar_v3_pause_state.json)、[实时控制](others/neighborhood_execution_v2_control.json)、[故障清点](others/calmar_v2_pool_failure_inventory.json)、[恢复清单](others/calmar_v3_recovery_manifest.json)、[DEV聚焦验证](others/complete_numeric_aggregation_dev_completion.json)、[RSCH真实账户等价验收](others/complete_numeric_aggregation_rsch_acceptance.json)、[现行Calmar规则](protocols/confirmed_calmar_selfcheck_v2.json)。原账、历史失败、原计划及旧交付保留，assets中的正式依赖须与Git材料共同保存。
"""
    (WORK / "report.md").write_text(report, encoding="utf-8", newline="\n")
    previous = d.EvidenceRef.from_dict(read(WORK / "report_ref.json")["report"])
    reference = publish_evidence(context, d.ExperimentReportWrite(experiment,
        sha256(report.encode()).hexdigest(), d.ExperimentOutcome.INCOMPLETE,
        tuple(materials.values()), previous=previous))
    checked = validate_experiment(repository, d.ExperimentValidationRequest(experiment,
        d.ExperimentValidationScope.REPORT_PUBLICATION))
    assert checked.status is d.ValidationStatus.PASS
    intent = copy.deepcopy(read(ROOT / "research/registrations/S017/family.json")["research_intent"])
    intent["active_stage_four_20261102"].update(status=record["status"], execution_paused_by_user=True,
        current_parallel_work_processes=0, maximum_parallel_work_processes_when_resumed=12,
        latest_report=reference.to_dict(), latest_pause=materials["calmar-v3-user-pause"].to_dict(),
        neighbors_executed=444, neighbors_remaining=2385, old_neighbor_cold_audits_completed=108,
        checkpoint_publication_receipts_pending_recovery=8,
        complete_numeric_aggregation_dev_commit="ed75fda1d",
        complete_numeric_aggregation_rsch_acceptance=materials["complete-numeric-aggregation-rsch-acceptance"].to_dict(),
        execution_revision_pending="v3_STATIC_ONLY_NOT_STARTED", recovery_probe_started=False,
        full_assessment_delivery_published=False)
    intent["next_action"] = record["next_action"]
    update_research_intent(repository, batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
        reason="用户要求完成当前进程计算后暂停；当前全部计算进程已退出，16既有账户数值等价验收通过，保留192新点和108旧点复核及断点，禁止启动恢复探针或新批次")
    save(WORK / "others/calmar_v3_pause_publication.json", {"status": "USER_PAUSE_RECORDED",
        "report": reference.to_dict(), "experiment_validation": checked.to_dict(),
        "materials": {name: ref.to_dict() for name, ref in materials.items()},
        "active_computation_processes": 0, "stage_four_complete": False})
    print("CALMAR_V3_USER_PAUSE_RECORDED", reference.sha256, flush=True)


if __name__ == "__main__":
    main()
