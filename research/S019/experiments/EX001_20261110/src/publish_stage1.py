"""Publish the confirmed mandate and the user's stage-two authorization."""
from hashlib import sha256
import json
from pathlib import Path

import strategy_evaluator as se
from czsc_trader import research_tools as d
from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, assemble_delivery, create_research_context,
    publish_evidence, record_research_decision, update_research_intent, validate_experiment,
)
from dataflows import ProviderConfig
from strategy_manager import CandidateEvidence
from strategy_manager import freeze_contracts as f
from strategy_runtime.equity_definition import execution_spec_from_dict

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
EXP = d.ExperimentRef("S019", "EX001_20261110")


def targets():
    metric = se.ResearchMetric
    center = (
        se.ResearchTarget("center-nar", metric.NET_ANNUAL_RETURN, lower=se.ConstantBound(0.55, True)),
        se.ResearchTarget("center-calmar", metric.NET_CALMAR, lower=se.ConstantBound(5.0, True)),
        se.ResearchTarget("center-risk", metric.DRAWDOWN_MAGNITUDE, upper=se.ConstantBound(0.25, True)),
        se.ResearchTarget("center-relative-risk", metric.DRAWDOWN_MAGNITUDE, upper=se.BenchmarkBound(0.8, True)),
        se.ResearchTarget("center-frequency", metric.FREQUENCY_MEDIAN, lower=se.ConstantBound(6.0, True)),
        se.FrequencyCoverageTarget("center-coverage", 60, 3, 9, 10),
    )
    neighborhood = se.ParameterNeighborhoodTarget("parameters", 4, 5, (
        se.ResearchTarget("neighbor-nar", metric.NET_ANNUAL_RETURN, lower=se.ConstantBound(0.50, True)),
        se.ResearchTarget("neighbor-calmar", metric.NET_CALMAR, lower=se.ConstantBound(4.5, True)),
        se.ResearchTarget("neighbor-relative-risk", metric.DRAWDOWN_MAGNITUDE, upper=se.BenchmarkBound(0.9, True)),
    ), (se.ResearchTarget("neighbor-risk", metric.DRAWDOWN_MAGNITUDE, upper=se.ConstantBound(0.25, True)),))
    stress = (
        se.ResearchTarget("stress-nar", metric.NET_ANNUAL_RETURN, lower=se.ConstantBound(0.50, True), scope=se.TargetScope.STRESS, one_way_cost=0.002),
        se.ResearchTarget("stress-calmar", metric.NET_CALMAR, lower=se.ConstantBound(4.5, True), scope=se.TargetScope.STRESS, one_way_cost=0.002),
        se.ResearchTarget("stress-risk", metric.DRAWDOWN_MAGNITUDE, upper=se.ConstantBound(0.25, True), scope=se.TargetScope.STRESS, one_way_cost=0.002),
        se.ResearchTarget("stress-relative-risk", metric.DRAWDOWN_MAGNITUDE, upper=se.BenchmarkBound(1.0, False),
            when=se.BenchmarkCondition(metric.DRAWDOWN_MAGNITUDE, se.ComparisonOperator.GT, 0.0), scope=se.TargetScope.STRESS, one_way_cost=0.002),
        se.ResearchTarget("stress-zero-risk", metric.DRAWDOWN_MAGNITUDE, upper=se.ConstantBound(0.0, True),
            when=se.BenchmarkCondition(metric.DRAWDOWN_MAGNITUDE, se.ComparisonOperator.LE, 0.0), scope=se.TargetScope.STRESS, one_way_cost=0.002),
    )
    result = se.ResearchTargets((*center, neighborhood, *stress), 60)
    assert se.ResearchTargets.from_dict(result.to_dict()) == result
    return result


def save(name, value):
    (WORK / "others" / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef("S019")
    context = create_research_context(repo, batch, providers=ProviderConfig(bindings={}, equity_bindings={}))
    authorization = {
        "source": "current_user_conversation",
        "date": "2026-11-10",
        "quotes": [
            "改为NAR >=55%吧，简单一些",
            "新开研究分支，然后继续",
            "关于自检和数据样本：\n1、参数扰动的达标判定应该是一个比例，而不是具体到 13/16 的数值\n2、数据样本应该由你来决定如何使用\n其他结论都认同",
            "通过率>=80%吧，简化一下",
        ],
        "interpretation": "确认其余阶段一约定及阶段二首轮推进；扰动联合通过率≥80%；样本用途由RSCH在授权范围内决定。",
        "parameter_pass_rate": 0.8,
        "target_contract": targets().to_dict(),
    }
    save("authorization.json", authorization)
    evidence = []
    for name, path, mime, extension in (
        ("user-confirmation", WORK / "others/authorization.json", "application/json", "json"),
        ("confirmed-agreement", ROOT / "research/S019/materials/stage1_agreement.md", "text/markdown", "md"),
        ("daily-data-preparation", WORK / "others/daily_preparation.json", "application/json", "json"),
        ("m30-data-preparation", WORK / "others/m30_preparation.json", "application/json", "json"),
        ("cross-frequency-audit", WORK / "others/cross_frequency_audit.json", "application/json", "json"),
        ("data-preparation-source", WORK / "src/prepare_data.py", "text/x-python", "py"),
        ("data-read-source", WORK / "src/load_data.py", "text/x-python", "py"),
        ("stage-one-publication-source", Path(__file__), "text/x-python", "py"),
    ):
        evidence.append(publish_evidence(context, d.MaterialEvidenceWrite(EXP, name, path.read_bytes(), mime, extension)))
    confirmed = d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED, evidence[0])
    frozen = json.loads((ROOT / "strategies/S018/versions/v1.json").read_text(encoding="utf-8"))
    settings = frozen["strategy_payload"]["equity_definition"]["execution_spec"]
    daily_spec = execution_spec_from_dict(settings)
    m30_spec = execution_spec_from_dict({**settings, "decision_clock": "30m"})
    items = (
        d.MandateItem("object", d.MandateItemKind.TRADABLE_SYMBOL, "MU唯一交易标的，SOXX行业观察，独立经济假设。", confirmed),
        d.MandateItem("targets", d.MandateItemKind.OBJECTIVE, "中心NAR≥55%、Calmar≥5、默认回撤及双频率；扰动联合通过率≥80%；压力与扰动采用50%及4.5门槛。", confirmed, d.PerformanceRequirement(targets().requirements)),
        d.MandateItem("frequency-days", d.MandateItemKind.EXECUTION, "完整60交易日滚动窗口。", confirmed, d.NumericRequirement("frequency_window_days", "sessions", 60.0, 60.0)),
        d.MandateItem("daily-benchmark", d.MandateItemKind.BENCHMARK, "日线同条件MU买持，标准和压力成本分别匹配。", confirmed, d.BenchmarkRequirement(d.EvaluationBenchmark(d.EquityBuyHold(daily_spec)))),
        d.MandateItem("m30-benchmark", d.MandateItemKind.BENCHMARK, "30分钟同条件MU买持，按自身执行区间固定合同。", confirmed, d.BenchmarkRequirement(d.EvaluationBenchmark(d.EquityBuyHold(m30_spec)))),
        d.MandateItem("clock", d.MandateItemKind.HORIZON, "决策周期30分钟至日线；信息在完整柱可用后进入下一执行区间。", confirmed),
        d.MandateItem("data", d.MandateItemKind.DATA_PERMISSION, "Futu MU/SOXX日线及30分钟；RSCH选择样本用途，已见范围留证。首轮2022预热、2023-01-03至2026-10-30开发。", confirmed),
        d.MandateItem("resources", d.MandateItemKind.RESOURCE, "现有研究依赖，账户批量最多4进程、每进程1数值线程，临时文件位于.tmp。", confirmed),
        d.MandateItem("ranking", d.MandateItemKind.OBJECTIVE, "全部适用硬门满足后按未舍入NAR降序，完全相同并列。正式排序契约需DEV支持。", confirmed),
        d.MandateItem("account", d.MandateItemKind.EXECUTION, "10万美元，HFQ整数模拟单位，价格步长0.01，每侧0.1%费用，买入溢价1%、严格触价、卖出市价、卖出款即时可用研究假设。", confirmed),
    )
    report = (WORK / "report.md").read_text(encoding="utf-8")
    assembled = assemble_delivery(repo, d.DeliveryDefinition(batch, d.DeliveryStage.MANDATE, 1),
        d.DeliveryContent(d.ResearchMandate(items), d.DeliveryStatus.COMPLETE, (), (), report=report, evidence=tuple(evidence)))
    assert assembled.validation.status is d.ValidationStatus.PASS
    receipt_path = ROOT / "research/S019/deliveries/MANDATE/1/receipt.json"
    confirmation_path = evidence[0].resolve(ROOT)
    decision = record_research_decision(repo, f.ResearchDecision(
        "S019-STAGE2-20261110", "S019", f.DecisionAction.APPROVE,
        f.StageAdvanceSubject(CandidateEvidence(receipt_path.relative_to(ROOT).as_posix(), sha256(receipt_path.read_bytes()).hexdigest()), "COMPONENTS"),
        CandidateEvidence(confirmation_path.relative_to(ROOT).as_posix(), sha256(confirmation_path.read_bytes()).hexdigest()),
        "用户认可阶段一其余结论并授权RSCH决定样本用途，最新确认扰动通过率至少80%；据此推进阶段二首轮。",
    ))
    report_ref = publish_evidence(context, d.ExperimentReportWrite(EXP, sha256((WORK / "report.md").read_bytes()).hexdigest(), d.ExperimentOutcome.COMPLETED, tuple(evidence)))
    check = validate_experiment(repo, d.ExperimentValidationRequest(EXP, d.ExperimentValidationScope.REPORT_PUBLICATION))
    assert check.status is d.ValidationStatus.PASS
    family = json.loads((ROOT / "research/registrations/S019/family.json").read_text(encoding="utf-8"))
    intent = {**family["research_intent"], "stage": "STAGE_TWO", "stage_one_status": "COMPLETE",
        "parameter_joint_pass_rate_min": 0.8,
        "sample_selection_authority": "RSCH_WITHIN_AUTHORIZED_SCOPE",
        "development": {"history_start": "2022-01-03", "start": "2023-01-03", "end": "2026-10-30", "exposure": "SEEN_S018_DAILY_WINDOW"},
        "mandate": assembled.receipt.reference.to_dict(), "next_action": "开展隔夜、日内及可执行剩余收益的首轮机制研究。"}
    update_research_intent(repo, batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH", reason="用户确认80%联合通过率，授权RSCH选择样本，并认可阶段二推进。")
    result = {"mandate": assembled.receipt.reference.to_dict(), "validation": assembled.validation.to_dict(),
        "stage_two_decision": decision.to_dict(), "report": report_ref.to_dict(), "experiment_validation": check.to_dict()}
    save("publication.json", result)
    print(json.dumps({"mandate": "PASS", "report": check.status.value, "stage": "STAGE_TWO"}))


if __name__ == "__main__":
    main()
