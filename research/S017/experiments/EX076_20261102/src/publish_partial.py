"""Publish actual partial results and the bounded supplementary DEV request."""
# ruff: noqa: E402
from partial_selfcheck import ROOT, WORK, KEYS, read, save

from hashlib import sha256
import copy

from dataflows import ProviderConfig
from czsc_trader.application import (RepositoryContext, create_research_context, publish_evidence,
    validate_experiment, update_research_intent, ResearchIntentUpdate, load_candidate)
from czsc_trader import research_tools as d
from strategy_manager import CandidateKey
from strategy_runtime import ExecutionResources


def main():
    summary = read(WORK / "others/partial_selfcheck_summary.json")
    panel = read(WORK / "others/partial_selfcheck_panel.json")
    pressure = read(WORK / "others/pressure.json")
    assert summary["status"] == "PARTIAL_NOT_STAGE4_COMPLETE"
    assert summary["rankable_candidates"] == [] and summary["neighbors_run"] == 0
    assert read(WORK / "others/dev_completion.json")["total_focused_nodes_passed"] == 284
    rows = {row["candidate"]["candidate_id"].split("-")[1]: row for row in panel["rows"]}
    standard = read(ROOT / "research/S017/experiments/EX072_20261102/others/all_accounts.json")
    table, diagnostics = [], []
    for key in KEYS:
        result = pressure["records"][key]
        c, b = result["candidate"], result["benchmark"]
        table.append(f"|{key}|{c['annualized_return']:.4%}|{c['drawdown']:.4%}|{b['annualized_return']:.4%}|"
                     + ("通过" if result["pressure_all_pass"] else "压力相对收益未通过") + "|")
        row = rows[key]
        metrics = {value["metric"]: value["value"] for value in row["diagnostics"]}
        interval = row["uncertainty"]
        diagnostics.append(f"|{key}|{metrics['ROLLING_EXCESS_Q10']:.6f}|{metrics['PROFIT_CONCENTRATION']:.4%}|"
                           f"{metrics['STRESS_ANNUAL_LOSS']:.4%}|{interval['lower_95']:.6f}—{interval['upper_95']:.6f}|")
    report = """# EX076：Calmar排序实现完成，阶段四自检部分完成

用户批准六点进入阶段四，随后确认Calmar/DD分层、逐点Calmar Q10首排，以及共同完整合法邻域比较和零g绝对0.05。确认原话和精确协议已留证。已授权最小DEV目标达成，阶段四完整自检与排序尚未达成。

## 做了哪些尝试

同分支DEV提交07158c342新增v5强类型比较及ASSESSMENT schema13：认证真实完整design、三hash、N、轴语义/单位/域/规则与共同合同；真实边界/点数/签名保留。Pareto使用中心Calmar/DD；同层第一项为全部邻点逐点R_i/D_i的等权LINEAR Q10。其他优先级和MANDATE/7全部11项硬条件保持。旧默认schema12/v4调用及旧schema8/11/12读取分别保留原公式，历史原件不改。

176项SE、106项TDR和2项旧ASSESSMENT FULL读取，共284项聚焦测试通过，Ruff及diff检查通过。未执行全仓回归。工程通过不等于候选经济验收。

六个每侧0.2%费用压力场景按固定2024—2025训练、100000美元独立初始资金及既有V4成交合同真实回放，4进程各1线程；六个策略场景和一个共享买持计算，原始账户全部发布。随后完整认证六标准与六压力既有公共账户，以SE复核时间、集中度、成对统计不确定性和全部11目标；本次复核零新金融账户。六真实完整design均通过新共同合同，所有2829邻点仍如实未运行，参数统计不补值，六点均不产生正式名次。

## 有哪些收获

### 固定费用压力

|配置|压力净年化|压力最大回撤|同场景买持净年化|压力硬门结果|
|---|---:|---:|---:|---|
""" + "\n".join(table) + """

C0338、C0342通过现行压力硬门；另四点在压力净年化严格超过同场景买持这一项失败。它们此前标准中心五门达标记录保留；本次阶段四总验收则记失败，不能用Calmar主排序替换仍有效的压力收益硬门。

### 可从现有账本完成的诊断

滚动超额为252实际交易日窗口、步长21的策略与买持收益差Q10；集中度为最大单笔盈利占全部正盈利比例；压力年化损失为标准减压力年化。区间为同历日成对stationary bootstrap净年化差95%区间，1000次、平均块长20、seed17。它们只报告，不新增硬门；重叠窗口不独立。

|配置|滚动超额Q10|最大单笔盈利贡献|压力年化损失|成对年化差95%区间|
|---|---:|---:|---:|---|
""" + "\n".join(diagnostics) + """

本批只有六个入围中心，不能将它们或EX072的25点当作完整S017多轮选择历史。族内选择偏差指标仍记证据不足，不据六点矩阵宣称已经消除过拟合或独立验证。全部仍为反复使用的训练；2026封存价格与策略绩效未读取。

### 尚未完成与技术限制

六完整邻域N依次为485、323、485、485、323、728，总2829。当前每份SE事实内嵌策略完整账本约55—56MB及买持账本约18MB；六份压力事实JSON实测508425515字节，推算完整邻域同格式约240GB。主机物理内存约128GB，且SE/TDR会整体复制、解码和缓存全部事实；最终正式交付不是只靠分批回放便能控制内存。

完整邻域尚未运行，不宣称参数稳健性、完整策略验收或正式排名。C0338和C0342总验收为INDETERMINATE；另四点为FAILED；全部无Pareto层级与名次。没有以缺点为N/A、裁剪邻域或只对两点算参数后冒称六点完整。

## 下一步建议是什么

建议批准[有界事实DEV补充方案](protocols/bounded_assessment_dev_request.md)，将完整V4原账保留为独立可认证证据，向SE提供经原账重建的强类型紧凑观测，FULL逐份认证并释放大日志。此能力不在本次Calmar排序最小DEV授权内，待用户明确授权后由DEV实施，再由RSCH继续已批准阶段四；不改11项硬门、2829完整点集或金融执行语义。无新搜索、封存测试、选型冻结、PTE、生产、合并/tag/push。

## 有什么依据

[用户确认](protocols/confirmed_ranking_contract.json)、[原评审及确认更新](protocols/ranking_and_neighborhood_review.md)、[DEV验收](others/dev_completion.json)、[压力原账与逐项结果](others/pressure.json)、[SE部分自检](others/partial_selfcheck_panel.json)、[全部目标状态](others/partial_comparison.json)、[部分状态摘要](others/partial_selfcheck_summary.json)。正式报告 outcome=INCOMPLETE，不发布虚假的完整ASSESSMENT。
"""
    (WORK / "report.md").write_text(report, encoding="utf-8", newline="\n")
    repository = RepositoryContext.discover(ROOT)
    batch, experiment = d.ResearchBatchRef("S017"), d.ExperimentRef("S017", WORK.name)
    candidate = load_candidate(repository, CandidateKey("S017", KEYS[0]))
    context = create_research_context(repository, batch,
        providers=ProviderConfig(bindings={}, equity_bindings={}),
        execution_spec=candidate.definition.execution_spec, resources=ExecutionResources(4, 1, 17))
    materials = {}
    paths = sorted((*WORK.glob("protocols/*"), *WORK.glob("src/*.py"), *WORK.glob("others/*.json")))
    for path in paths:
        if path.name == "partial_publication.json":
            continue
        name = path.parent.name + "-" + path.stem.replace("_", "-")
        mime = {".json": "application/json", ".md": "text/markdown", ".py": "text/x-python"}[path.suffix]
        materials[path.relative_to(WORK).as_posix()] = publish_evidence(context,
            d.MaterialEvidenceWrite(experiment, name, path.read_bytes(), mime, path.suffix[1:]))
    accounts = tuple(d.EvidenceRef.from_dict(value)
                     for key in KEYS for value in (standard[key]["evidence"], pressure["records"][key]["evidence"]))
    reference = publish_evidence(context, d.ExperimentReportWrite(experiment, sha256(report.encode()).hexdigest(),
        d.ExperimentOutcome.INCOMPLETE, tuple((*materials.values(), *accounts))))
    checked = validate_experiment(repository, d.ExperimentValidationRequest(experiment,
        d.ExperimentValidationScope.REPORT_PUBLICATION))
    assert checked.status is d.ValidationStatus.PASS, checked.to_dict()
    intent = copy.deepcopy(read(ROOT / "research/registrations/S017/family.json")["research_intent"])
    intent["active_stage_four_20261102"].update({
        "status": "PARTIAL_PENDING_BOUNDED_FACTS_DEV_AUTHORIZATION",
        "new_ranking_platform_implementation": "COMPLETE_284_FOCUSED_TESTS_PASS",
        "dev_commit": "07158c34299935447582fcfe4af42e415ae316fc",
        "neighborhood_comparability_and_zero_scale": "USER_CONFIRMED_COMMON_CONTRACT_ZERO_G_ABSOLUTE_005",
        "neighbors_executed": 0, "planned_neighbors": 2829,
        "pressure_completed": 6, "pressure_pass": ["C0338", "C0342"],
        "latest_report": reference.to_dict(), "full_assessment_delivery_published": False,
        "next_dev_scope_authorized": False, "sealed_test_authorized": False})
    intent["next_action"] = "请用户批准EX076有界事实DEV补充方案；实施后自主继续已批准的六完整邻域及Calmar排序。阶段四尚未完成，2026封存不动。"
    update_research_intent(repository, batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
        reason="已批准Calmar排序DEV目标达成；真实压力与既有账户部分自检已完成，保留四点经济失败和2829点未检，补充平台有界事实方案待授权")
    save(WORK / "others/partial_publication.json", {"status": "PARTIAL_PUBLISHED",
        "report": reference.to_dict(), "experiment_validation": checked.to_dict(),
        "materials": {key: ref.to_dict() for key, ref in materials.items()},
        "stage4_complete": False, "formal_assessment_published": False})
    print("EX076_PARTIAL_REPORT_PUBLISHED", reference.sha256, flush=True)


if __name__ == "__main__":
    main()
