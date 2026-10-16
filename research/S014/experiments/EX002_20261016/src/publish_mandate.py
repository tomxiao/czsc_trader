"""Publish the RSCH-authored stage-one proposal and its actual readiness evidence."""
from datetime import date
from hashlib import sha256
from pathlib import Path
from uuid import UUID
import json

from dataflows import DataRequest, Dataset, PreparedDataRef
from strategy_evaluator import ResearchTarget, ResearchMetric, ConstantBound
from czsc_trader.application import (
    RepositoryContext, create_research_context, publish_evidence, assemble_delivery,
    validate_delivery, update_research_intent, ResearchIntentUpdate,
)
from czsc_trader.research_tools import (
    ResearchBatchRef, ExperimentRef, EvaluationResources, MaterialEvidenceWrite, EvidenceRef,
    ResearchMandate, MandateItem, MandateItemKind, ConfirmationRecord, ConfirmationStatus,
    NumericRequirement, PerformanceRequirement, BenchmarkRequirement, EvaluationBenchmark, LimitBuyHold,
    DeliveryDefinition, DeliveryStage, DeliveryContent, DeliveryStatus, ValidationStatus,
    FactValue, FactStatus,
)

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]


def main():
    repository = RepositoryContext.discover(ROOT)
    context = create_research_context(repository, ResearchBatchRef("S014"),
                                      resources=EvaluationResources(2, 1, 13))
    experiment = ExperimentRef("S014", "EX002_20261016")
    contract = json.loads((EXPERIMENT / "protocols/research_contract.json").read_text(encoding="utf-8"))
    authority = {
        "source": "Current human-user conversation and the user-edited RSCH document.",
        "verbatim": ["ok，新开研究分支，启动S014（金牛化工）的策略研究", "RSCH文档可以提交",
                     "研究周期为2020-1-1至2026-10-15", "每个自然年都要严格由于buyhold"],
        "rsch_rules_commit": "a1441988",
        "rule_sha256": sha256((ROOT / "research/RSCH_AGENT.md").read_bytes()).hexdigest(),
        "scope": "Start S014 and prepare its stage-one agreement; no fabricated approval of proposed parameters or stage-two completion.",
        "execution_confirmation": "Earlier user decisions retain one-way 0.1%, HFQ and the simplified daily-range buy/sell model.",
    }
    authority_path = EXPERIMENT / "protocols/authorization_basis.json"
    authority_path.write_text(json.dumps(authority, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    paths = {
        "authorization": authority_path,
        "rsch-rules": ROOT / "research/RSCH_AGENT.md",
        "contract": EXPERIMENT / "protocols/research_contract.json",
        "readiness-first": EXPERIMENT / "others/input_readiness.json",
        "readiness-script-error": EXPERIMENT / "others/input_readiness_retry.json",
        "readiness-third": EXPERIMENT / "others/input_readiness_attempt3.json",
        "readiness-final": EXPERIMENT / "others/input_readiness_attempt4.json",
        "source-small-windows": EXPERIMENT / "others/source_diagnostic.json",
        "source-exact-ranges": EXPERIMENT / "others/source_failed_ranges.json",
        "annual-method": EXPERIMENT / "src/annual_contract.py",
        "annual-check-program": EXPERIMENT / "src/check_annual_contract.py",
        "annual-check-result": EXPERIMENT / "others/annual_contract_check.json",
        "input-program": EXPERIMENT / "src/prepare_inputs.py",
    }
    refs = {}
    for name, path in paths.items():
        suffix = path.suffix.lstrip(".")
        media = {"json": "application/json", "py": "text/x-python", "md": "text/markdown"}[suffix]
        refs[name] = publish_evidence(context, MaterialEvidenceWrite(experiment, name, path.read_bytes(), media, suffix))
    old = json.loads((ROOT / "research/S014/experiments/EX001_20261016/others/result.json").read_text(encoding="utf-8"))
    old_ref = EvidenceRef.from_dict(old["evidence"]["technical-diagnosis"])
    old_ref.resolve(ROOT)
    confirmed = ConfirmationRecord(ConfirmationStatus.CONFIRMED, refs["authorization"])
    proposed = ConfirmationRecord(ConfirmationStatus.PROPOSED)
    benchmark = EvaluationBenchmark(LimitBuyHold(100, .01, .01, .1, 1000000))
    items = (
        MandateItem("symbol", MandateItemKind.TRADABLE_SYMBOL, "600722.SH 金牛化工，单标的日频择时", confirmed),
        MandateItem("window", MandateItemKind.HORIZON, "2020-01-01至2026-10-15，开发池内时序分层，不宣称独立封存样本", confirmed),
        MandateItem("annual-return", MandateItemKind.OBJECTIVE, contract["objectives"]["annual_return"], confirmed),
        MandateItem("annual-drawdown", MandateItemKind.CONSTRAINT, contract["objectives"]["annual_drawdown"], confirmed),
        MandateItem("frequency", MandateItemKind.CONSTRAINT, contract["objectives"]["frequency"], confirmed,
                    PerformanceRequirement((ResearchTarget("full-frequency", ResearchMetric.FULL_SAMPLE_FREQUENCY,
                                                          lower=ConstantBound(3.0, True)),))),
        MandateItem("frequency-window", MandateItemKind.EXECUTION, "全期折算至60个评价交易日，停牌估值日仍计入分母", confirmed,
                    NumericRequirement("frequency_window_days", "sessions", 60.0, 60.0)),
        MandateItem("execution", MandateItemKind.EXECUTION, "单侧0.1%、HFQ_RESEARCH、只做多不加杠杆，日线区间成交与强制股票交易状态", confirmed),
        MandateItem("partial-year", MandateItemKind.HORIZON, "建议2026年截至10月15日的期间纳入逐年硬门，单列覆盖，不年化", proposed),
        MandateItem("capital", MandateItemKind.RESOURCE, "建议初始资金10万元", proposed,
                    NumericRequirement("initial_cash", "CNY", 100000.0, 100000.0)),
        MandateItem("benchmark", MandateItemKind.BENCHMARK, "建议固定前一可交易日收盘价上浮1%的限价BuyHold，未成交重试，建仓后持有", proposed,
                    BenchmarkRequirement(benchmark)),
        MandateItem("stage-two", MandateItemKind.RESOURCE, "建议阶段二2进程、每进程1原生线程、2小时、最多新增50次上游调用；预算不作为研究充分性证明", proposed),
        MandateItem("data-permission", MandateItemKind.DATA_PERMISSION, "既有Tushare权限、S014批次空间、本标的日线与执行输入；新增外部源另行授权", confirmed),
    )
    latest = json.loads(paths["readiness-final"].read_text(encoding="utf-8"))
    calendar_item = latest["results"][0]
    reference = calendar_item["reference"]
    prepared = PreparedDataRef(UUID(reference["space_id"]), UUID(reference["preparation_id"]), reference["manifest_sha256"])
    calendar = context.data.fetch(DataRequest(Dataset.TRADING_CALENDAR, "SSE", "2020-01-01", "2026-10-15", "2026-10-15"), prepared=prepared)
    if not calendar.ready:
        raise RuntimeError("Cannot authenticate prepared calendar")
    sessions = int(calendar.dataframe.IsOpen.eq(1).sum())
    calls = latest["prior_upstream_calls"] + len(latest["upstream_calls"])
    failures = sum(x.get("http_status") == 502 for x in latest["upstream_calls"])
    report = f"""# S014 金牛化工策略研究：阶段一约定与启动报告

研究已在独立分支启动。目标、标的和周期已确认；年度指标程序的合成检查通过。
正式行情准备尚未通过，因此本轮未开始信息组件检验、策略参数搜索或策略账户评价。
本交付为PARTIAL，表示研究准备和约定仍有待完成事项；技术校验PASS不表示已获准推进或策略有效。

## 已确认目标

- 标的600722.SH；研究周期2020-01-01至2026-10-15。
- 每个纳入验收的自然年：BuyHold收益率为正时，策略收益率至少为其1.5倍；否则策略收益率严格为正。
- 每个纳入验收的自然年：策略最大回撤幅度严格小于BuyHold，相等不达标。
- 开发池全期交易频率为60乘闭合交易总数除以评价交易日总数，至少3；滚动窗口不另设频率硬门。
- 保持单侧0.1%费用、后复权研究单位、T决策至下一可交易日执行、限价买入与简化市价卖出合同。

## 年度计算与验证

连续账户跨年承接现金和持仓。年度期初使用上一年末净值，首年使用初始资金；年度收益不年化。
最大回撤在年度期初净值及本年全部净值路径上计算，全期回撤另作诊断。年末及研究末日不强制平仓。
本实验src/annual_contract.py与src/check_annual_contract.py验证7组边界，结果为PASS，见others/annual_contract_check.json。
检查包括跨年连续估值、1.5倍收益等号、回撤等号、零回撤、亏损基准、交易集中但全期频率达标及缺失账户日期拒绝。
这些合成检查不使用真实行情，不证明策略收益。年度规则目前由实验程序显式计算，阶段四强类型比较对接仍需核验。

## 数据准备与限制

通过S014批次的DFLS公开prepare/fetch准备日历、后复权日线、不复权日线、涨跌停和股票交易状态。
交易日历READY，确认评价期有{sessions}个交易所交易日；其余4类输入在最新准备中仍为非READY。
累计调用{calls}次，当前上限100次。最后一次显式准备记录到{failures}次HTTP502，影响历史日历、证券基本信息及涨跌停请求。
确切失败区间的独立只读探针曾正常返回数据，且10月15日行情、因子和日历的小窗口探针成功。
因此当前证据支持“上游读取不稳定导致准备失败”，不能据此认定供应商没有相应历史覆盖。
准备第二次尝试还发生过研究脚本PreparedDataRef序列化错误，已修正；这项技术错误与上游HTTP失败分别保留。
准备结果见others/input_readiness*.json；HTTP状态见others/input_readiness_attempt4.json。
未使用非READY输入、人工填充或临时供应商缓存拼接，没有账户评价或参数搜索。
历史EX001结论仅覆盖至2026-09-30，关联原正式证据，不将其当作新截止日准备通过的证明。
历史发布时间及修订记录未核验，不能声称严格历史时点可得。

## 样本用途及下一阶段方案

整个约定期间用于开发池内的时序检验；既往已检查行情形态与成交边界，不将其重新命名为未见封存样本。
阶段二建议从趋势延续、短期反转和风险过滤的竞争解释出发，检查入场、退出及减少无效交易的信息用途。
先用简单量价对照与时间分层，标签与T+1可成交、费用、退出和持仓占用分别核验，移除跨越验证边界的训练标签。
适用的时序普查使用已安装tsfresh；搜索使用Optuna；独立CPU任务在传输预检后采用2进程、每进程1原生线程。
建议首轮预算2小时、最多新增50次上游调用，预算边界报告已完成与未回答问题，不因首次有效或预算耗尽宣称研究充分。
本阶段不登记候选；完整策略构建与搜索由获准的阶段三承接。

## 待确认与下一步

1. 建议2026-01-01至2026-10-15作为部分年度也纳入收益和回撤硬门，单列日期，不作年化。
2. 建议策略与BuyHold初始资金均为10万元；固定BuyHold为前一可交易日收盘价上浮1%的限价、100单位一手、原始价位0.01元，随市场规则换算单位。
3. 基准未成交则下一可交易日重新计划，建仓后持有，不随候选搜索修改；明确批准后进入阶段二。
4. 新周期正式输入仍须全部READY。应先解决或等待上游HTTP502恢复，再显式重试准备；不把年度统计程序通过当作数据准备通过。

约定全文见protocols/research_contract.json。确认依据见protocols/authorization_basis.json。
本轮只在S014材料及资产区写入，通过公共API更新研究意图并发布证据；未修改平台、历史研究原件、冻结、PTE或生产。
分支为codex/s014-jinniu-research，未合并或推送。所有正式数据资产及完整交付包须与引用共同保存，Git中的报告不能单独恢复忽略的资产。
"""
    incomplete = ("新周期4类市场输入仍非READY，已定位到上游HTTP502", "2026部分年度、初始资金及固定基准提案待确认", "阶段二推进待用户审阅阶段一交付后批准")
    content = DeliveryContent(ResearchMandate(items), DeliveryStatus.PARTIAL,
                             facts=(FactValue("exchange-sessions", sessions, "sessions", FactStatus.AVAILABLE, (refs["readiness-final"],)),
                                    FactValue("synthetic-boundaries", 7, "checks", FactStatus.AVAILABLE, (refs["annual-check-result"],))),
                             explanations=(), incomplete_items=incomplete, report=report,
                             evidence=(*refs.values(), old_ref))
    receipt = assemble_delivery(repository, DeliveryDefinition(context.batch, DeliveryStage.MANDATE, 1), content)
    checked = validate_delivery(repository, receipt.reference)
    if checked.status is not ValidationStatus.PASS:
        raise RuntimeError(checked.issues)
    public = ROOT / "research/S014/deliveries/MANDATE/1/report.md"
    copy = EXPERIMENT / "others/report.md"
    raw = public.read_bytes()
    copy.write_bytes(raw)
    verification = {"formal_report": public.relative_to(ROOT).as_posix(),
                    "experiment_report": copy.relative_to(ROOT).as_posix(), "bytes": len(raw),
                    "sha256": sha256(raw).hexdigest(), "status": "PASS"}
    if copy.read_bytes() != raw:
        raise RuntimeError("Report copy differs")
    (EXPERIMENT / "protocols/report_copy_verification.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {"experiment": experiment.to_dict(), "delivery": receipt.reference.to_dict(),
              "delivery_status": "PARTIAL", "validation": checked.to_dict(),
              "evidence": {name: ref.to_dict() for name, ref in refs.items()},
              "report_copy": verification, "upstream_calls": calls, "ready_inputs": 1,
              "not_ready_inputs": 4, "strategy_evaluations": 0, "parameter_searches": 0}
    (EXPERIMENT / "others/result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    intent = {"stage": "阶段一：研究约定已形成PARTIAL正式交付，待确认及输入恢复", "objective": "发现满足逐年收益、逐年回撤及全期频率目标的金牛化工日频策略",
              "authorization": authority, "research_window": contract["research_window"], "objectives": contract["objectives"],
              "execution": contract["execution"], "resources": {"max_workers": 2, "native_threads_per_worker": 1, "readiness_call_cap": 100, "calls_used": calls},
              "scope": contract["data_and_sample_use"], "delivery": receipt.reference.to_dict(),
              "pending": list(incomplete), "boundaries": contract["boundaries"], "updated_on": date(2026, 10, 16).isoformat()}
    update_research_intent(repository, context.batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
                           reason="用户授权新分支启动S014，指定2020-01-01至2026-10-15，落实已提交研究目标并如实保留数据准备失败")
    print(json.dumps({"delivery": receipt.reference.to_dict(), "validation": checked.status.value,
                      "status": "PARTIAL", "upstream_calls": calls}, ensure_ascii=False))


if __name__ == "__main__":
    main()
