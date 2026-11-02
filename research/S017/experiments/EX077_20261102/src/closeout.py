"""Interpret retained test accounts and publish the RSCH conclusion; no replay."""
# ruff: noqa: E402
from run_holdout import ROOT, WORK, OUT, E, read, save, require, context
from datetime import date
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, load_candidate, diagnose_accounts,
    publish_evidence, validate_experiment, update_research_intent,
    ResearchIntentUpdate)
from strategy_manager import CandidateKey


def main():
    started = perf_counter()
    repository = RepositoryContext.discover(ROOT)
    research = context(repository, load_candidate(repository, CandidateKey("S017", "C0342")))
    summary = read(OUT / "results.json")
    require(not summary["passed_all_declared_test_conditions"], "This closeout interprets the observed five failures only")
    previous = d.EvidenceRef.from_dict(read(OUT / "publication.json")["report"])
    diagnostics = {}
    for key in summary["candidate_order"]:
        ref = d.EvidenceRef.from_dict(summary["results"][key]["standard"]["evidence"])
        header = read(ref.resolve(ROOT))
        identity = dict(header["evaluation_identity"])
        identity["candidate"] = CandidateKey(**identity["candidate"])
        calculation = diagnose_accounts(repository, d.AccountDiagnosisRequest(
            d.AccountRunRef(ref, d.EvaluationIdentity(**identity)), None,
            d.EvaluationWindow("TEST_2026_01_09", date(2026, 1, 2), date(2026, 9, 30))))
        require(calculation.status.value == "COMPUTED", f"Retained account diagnosis unavailable: {key}/{calculation.issues}")
        diagnostics[key] = calculation.to_dict()
    save(OUT / "account_diagnosis.json", diagnostics)

    pressure_rows, attribution = [], []
    for key in summary["candidate_order"]:
        result = summary["results"][key]
        pressure = result["pressure"]
        metrics = pressure["metrics"]
        pressure_rows.append(f"|{key}|{pressure['detail']['total_return']:.2%}|{metrics['DRAWDOWN_MAGNITUDE']:.2%}|{metrics['NET_CALMAR']:.4f}|未通过|")
        pnl = diagnostics[key]["pnl_breakdown"][0]["annual"][0]
        attribution.append(f"|{key}|{pnl['entry']:.2f}|{pnl['holding']:.2f}|{pnl['exit']:.2f}|{pnl['fees']:.2f}|{pnl['equity_change']:.2f}|")
    pressure_bh = summary["results"]["C0342"]["pressure"]["benchmark"]
    text = (WORK / "report.md").read_text(encoding="utf-8")
    text = text.replace("按事前规则，通过标准和压力条件的集合为[]，沿用训练排序的首位为None。",
        "五配置均未通过标准及压力条件，本轮没有可推荐进入阶段五的配置。频率两门全部通过，但五配置均在净Calmar、相对回撤和25%绝对回撤门上失败；频率达标不能抵消经济条件失败。\n\n"
        "RSCH建议停止本组配置的晋级，保留训练达标与测试失败两组原始结论。若用户批准继续，先围绕失效机制开展研究诊断，再决定是否返回阶段二或三；本次测试窗口已见，后续不能再将其称为独立封存测试。当前未开展新的参数或结构实验。")
    insert = f"""## 压力结果与已有账本解释

|配置|每侧0.2%区间净收益|最大回撤|净Calmar|既定压力条件|
|---|---:|---:|---:|---|
{chr(10).join(pressure_rows)}

压力买持区间净收益{pressure_bh['detail']['total_return']:.2%}、最大回撤{pressure_bh['metrics']['DRAWDOWN_MAGNITUDE']:.2%}、净Calmar {pressure_bh['metrics']['NET_CALMAR']:.4f}。

RSCH为解释负面结果，显式调用公共账户诊断读取五个既有标准账户；不重放策略、不新增审计或门禁。美元会计分解如下：

|配置|入场成交至当根收盘|此前持仓至当前收盘|卖出相对其估值基准|费用贡献|账户净变化|
|---|---:|---:|---:|---:|---:|
{chr(10).join(attribution)}

这只是按成交与估值时点分解的损益事实，不能单独证明入场、持有或退出规则的因果缺陷。它支持的结论是：失败并非只有费用压力情景才出现，标准成本账户本身已经大幅亏损；将费用贡献与其他项分列，也不能冒称删除费用后策略行为不变的反事实回测。

测试对这组训练期达标配置的可迁移性给出明确负面证据。具体是行情状态改变、选择偏差、交易规则失效或其他原因，目前尚未区分，不按结果编造已证实的金融解释。
诊断完整数值见[账户诊断](others/account_diagnosis.json)，五账户均已计算完成；该解释性工作不改变测试标准或五项失败结论。

"""
    text = text.replace("## 依据\n", insert + "## 依据\n")
    (WORK / "report.md").write_text(text, encoding="utf-8", newline="\n")
    extra = tuple(publish_evidence(research, d.MaterialEvidenceWrite(E, "holdout-" + path.stem,
        path.read_bytes(), "application/json" if path.suffix == ".json" else "text/x-python", path.suffix[1:]))
        for path in (OUT / "account_diagnosis.json", OUT / "assessment_evidence.json", Path(__file__)))
    reference = publish_evidence(research, d.ExperimentReportWrite(E,
        sha256((WORK / "report.md").read_bytes()).hexdigest(), d.ExperimentOutcome.COMPLETED,
        (previous,) + extra, previous=previous))
    validation = validate_experiment(repository, d.ExperimentValidationRequest(E, d.ExperimentValidationScope.REPORT_PUBLICATION))
    require(validation.status is d.ValidationStatus.PASS, "Final report publication did not pass")
    save(OUT / "publication_final.json", {"report": reference.to_dict(), "previous": previous.to_dict(),
        "validation": validation.to_dict(), "additional_account_replays": 0,
        "retained_standard_account_diagnoses": 5, "closeout_seconds": perf_counter() - started})
    intent = read(ROOT / "research/registrations/S017/family.json")["research_intent"]
    intent["active_final_test_20261102"].update(report=reference.to_dict(),
        conclusion="五配置频率达标，但标准及压力经济条件全部失败；无配置推荐进入阶段五。")
    intent["next_action"] = "五配置联合测试完成且全部失败，暂停晋级；等待用户决定是否授权失效机制诊断，测试窗口已见。"
    update_research_intent(repository, d.ResearchBatchRef("S017"), ResearchIntentUpdate(research_intent=intent),
        actor="RSCH", reason="补全RSCH负面结果解释与停止晋级建议，保留首版正式报告和全部账户，不追加实验")
    print("RSCH_CLOSEOUT_COMPLETED", validation.status.value, "seconds", perf_counter() - started, flush=True)


if __name__ == "__main__":
    main()
