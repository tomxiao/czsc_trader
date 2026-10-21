"""Record completed stage-four work after both public validations pass."""
from common import ROOT, EROOT, WORK, read, save
from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, get_research_overview, update_research_intent,
)
from czsc_trader.research_tools import ResearchBatchRef


def main():
    validation = read(EROOT / "others/delivery_validation.json")
    assert validation["validation"]["status"] == validation["experiment"]["status"] == "PASS"
    assert read(EROOT / "others/final_checks.json")["status"] == "PASS"
    summary = read(WORK / "summary.json")
    reference = validation["delivery"]
    assert reference["stage"] == "ASSESSMENT" and reference["revision"] == 1
    repository = RepositoryContext.discover(ROOT)
    batch = ResearchBatchRef("S015")
    intent = read(ROOT / "research/registrations/S015/family.json")["research_intent"]
    intent.update(
        current_phase="阶段四已完成，ASSESSMENT/1已交付，等待用户选型决定",
        next_gate="请用户选择进入阶段五的具体候选、补证或暂不推进；技术检验及冻结尚未授权",
        assessment_sha256=reference["content_sha256"],
    )
    update_research_intent(repository, batch, ResearchIntentUpdate(research_intent=intent),
                           actor="RSCH", reason="阶段四完整比较与报告已发布并通过FULL及报告一致性核验")
    overview = get_research_overview(repository, batch)
    save(EROOT / "others/overview_after.json", overview.to_dict())
    ranked = sorted((row for row in summary["rows"] if row["status"] in
                     ("RANKED", "TIED", "PARTIALLY_ORDERED")),
                    key=lambda row: (row["pareto_layer"], row["rank_min"], row["candidate_id"]))
    accepted = summary["acceptance_counts"].get("PASSED", 0)
    path = ROOT / "research/S015/HANDOFF.md"
    handoff = path.read_text(encoding="utf-8")
    handoff = handoff.replace(
        "阶段四EX005正在执行，完整覆盖98个交接身份；尚未形成阶段四最终结论。",
        "阶段四EX005已完成，完整覆盖98个交接身份；最新交付为[ASSESSMENT/1](deliveries/ASSESSMENT/1/report.md)，FULL与REPORT_PUBLICATION均PASS。")
    handoff = handoff.replace(
        "当前先完成全部账户、公开证据核验及正式比较，再请用户选择阶段五具体候选。",
        "全部账户、公开证据核验及正式比较已经完成，当前请用户选择阶段五具体候选。")
    marker = "\n## 阶段四完成（EX005，2026-10-22）\n"
    if marker in handoff:
        raise RuntimeError("stage-four handoff already appended; inspect before repeating closeout")
    handoff += marker + f"""
- 本阶段98个交接候选全部保留身份；96个适用中心各32点，两个不适用中心为C0030/C0062；98个中心均完成费用翻倍，共3170份新增账户，3351份账户投影完成公开认证。
- 完整目标通过{accepted}/98个，可比排序集合{len(ranked)}个。验收状态：`{summary['acceptance_counts']}`；比较状态：`{summary['status_counts']}`。正式排序和选择代价见[报告](deliveries/ASSESSMENT/1/report.md)。
- 参数检验覆盖全部规定32点；C0030/C0062因有效连续维度不足而没有32点检验，不计通过或可推荐。全部设计的max_days未变化，不声称±1日稳健性，也未另加半径或离散检验。
- 181个已保留搜索账户包含158条精确收益路径和6个零方差列；有效次数及DSR缺失原样披露。所有数据均为已见开发池，时间、集中度、重抽样和选择偏差仅作诊断，不增加经济硬门。
- 执行中按用户要求尝试两组各8进程；出现两次Windows进程池故障后恢复为单组8进程、每批33账户。后段22中心由新增队列完成、余5中心由原队列续跑；全部已发布结果保留。两次失败、原请求重试及恢复决定均已正式留证；第二次33项批次的实际完成数未知，不把3170份唯一场景称为物理执行总次数。
- [事前协议](experiments/EX005_20261022/protocols/stage4.json)、[实验报告](experiments/EX005_20261022/report.md)、[独立数值核验](experiments/EX005_20261022/others/final_checks.json)、[交付验证](experiments/EX005_20261022/others/delivery_validation.json)、[研究概览](experiments/EX005_20261022/others/overview_after.json)。聚焦验证已完成，未执行仓库级全量回归。
- ASSESSMENT/1内容身份：`{reference['content_sha256']}`；精确前驱为CANDIDATES/2与MANDATE/2。正式资产位于`assets/runs/EX005_20261022/`、`assets/evidence/EX005_20261022/`与`assets/deliveries/ASSESSMENT/1/`，需独立保留。
- 前文阶段三“未执行阶段四”等措辞均为历史时点。当前等待用户选择进入阶段五的具体候选、补证或暂不推进；没有记录用户选型、启动技术检验、冻结、PTE或生产，也未合并master、打tag或推送。
"""
    path.write_text(handoff, encoding="utf-8", newline="\n")
    print({"closed_out": reference, "accepted": accepted, "rankable": len(ranked)}, flush=True)


if __name__ == "__main__":
    main()
