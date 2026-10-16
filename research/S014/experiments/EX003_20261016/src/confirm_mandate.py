"""Publish the user-confirmed mandate as a new immutable revision."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import json

from czsc_trader.application import (
    RepositoryContext, create_research_context, publish_evidence, assemble_delivery,
    validate_delivery, update_research_intent, ResearchIntentUpdate,
)
from czsc_trader.research_tools import (
    ResearchBatchRef, ExperimentRef, MaterialEvidenceWrite, DeliveryReference,
    DeliveryContent, DeliveryDefinition, DeliveryStage, DeliveryStatus, ValidationStatus,
    ResearchMandate, ConfirmationRecord, ConfirmationStatus, FactValue, FactStatus,
)

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]


def main():
    repository = RepositoryContext.discover(ROOT)
    context = create_research_context(repository, ResearchBatchRef("S014"))
    experiment = ExperimentRef("S014", "EX003_20261016")
    prior_experiment = ROOT / "research/S014/experiments/EX002_20261016"
    previous = DeliveryReference.from_dict(json.loads((prior_experiment / "others/result.json").read_text(encoding="utf-8"))["delivery"])
    if validate_delivery(repository, previous).status is not ValidationStatus.PASS:
        raise RuntimeError("Previous published mandate failed validation")
    document = json.loads((ROOT / "research/S014/assets/deliveries/MANDATE/1/delivery.json").read_text(encoding="utf-8"))
    prior_content = DeliveryContent.from_dict(document["content"])
    readiness_path = prior_experiment / "others/input_readiness_fixed_1.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    if not readiness["ready"]:
        raise RuntimeError("Full-period native inputs are not ready")
    authority = {"source": "Current human-user conversation", "verbatim": [
        "确认阶段一方案。请切换dev，在研究外独立验证tushare数据的可得性", "继续"],
        "context": "User confirmed MANDATE/1 proposals, approved the DEV fix and then continuation in RSCH after the fix was merged.",
        "approved": {"partial_2026_in_annual_gates": True, "initial_cash": 100000,
                     "fixed_buyhold_premium": .01, "stage_two_initial_hours": 2,
                     "max_workers": 2, "native_threads_per_worker": 1,
                     "additional_upstream_call_cap": 50},
        "scope": "S014 only. No strategy-stage advance, candidate selection or freezing approval is fabricated."}
    contract = json.loads((prior_experiment / "protocols/research_contract.json").read_text(encoding="utf-8"))
    contract["annual_method"]["partial_year_confirmation"] = "CONFIRMED"
    contract["capital_proposal"]["confirmation"] = "CONFIRMED"
    contract["benchmark_proposal"]["confirmation"] = "CONFIRMED"
    contract["stage_two_proposal"]["confirmation"] = "CONFIRMED; component-stage execution now authorized."
    contract["pending"] = []
    contract["readiness"] = {"all_inputs_ready": True, "source_calls_after_fix": len(readiness["upstream_calls"]),
                             "transport_fix": "824b144b", "source_publication_timestamp_verified": False}
    for name, value in (("authorization", authority), ("confirmed_contract", contract)):
        (EXPERIMENT / f"protocols/{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    material = {
        "authorization": EXPERIMENT / "protocols/authorization.json",
        "confirmed-contract": EXPERIMENT / "protocols/confirmed_contract.json",
        "input-readiness": readiness_path,
        "readiness-program": prior_experiment / "src/prepare_after_http_fix.py",
        "annual-method": prior_experiment / "src/annual_contract.py",
        "annual-checks": prior_experiment / "others/annual_contract_check.json",
    }
    refs = {}
    for name, path in material.items():
        suffix = path.suffix[1:]
        refs[name] = publish_evidence(context, MaterialEvidenceWrite(experiment, name, path.read_bytes(),
                                     "application/json" if suffix == "json" else "text/x-python", suffix))
    confirmation = ConfirmationRecord(ConfirmationStatus.CONFIRMED, refs["authorization"])
    mandate = ResearchMandate(tuple(replace(item, confirmation=confirmation) for item in prior_content.payload.items))
    calls = len(readiness["upstream_calls"])
    report = f"""# S014 阶段一确认与数据恢复报告

阶段一已完成，用户已确认研究约定，完整周期的5类正式输入全部READY，可以开始获准的阶段二组件研究。
本修订承接MANDATE/1的PARTIAL交付，保留旧报告、旧证据和旧副本原状；数据恢复和用户确认不会追溯改变旧结论。

## 已确认约定

- 研究标的600722.SH，周期2020-01-01至2026-10-15。
- 每个自然年均须满足收益与严格回撤目标；2026年截至10月15日也纳入硬门，标明部分年度，不年化。
- BuyHold盈利时策略收益率至少为其1.5倍，否则策略收益率严格为正；每年策略最大回撤幅度严格小于BuyHold，相等不达标。
- 全开发池频率为60乘闭合交易总数除以评价交易日总数，至少3；不增加滚动窗口硬门。
- 策略及基准初始资金10万元，单侧费用0.1%，HFQ_RESEARCH单位，账户跨年连续。
- 基准固定为前一可交易日收盘价上浮1%的限价BuyHold，未成交重新计划，建仓后持有，不因年度边界平仓。

## 实际输入准备

修复824b144b已合并至研究分支。通过本批次ResearchContext.data公开prepare/fetch，
完整周期日历2480条，后复权日线、不复权日线、涨跌停及股票交易状态各1642条，全部READY。
股票状态为1642个TRADING交易日，期间无被声明的全日停牌。准备引用、字段、哈希及完整HTTP调用记录随证据保存。
本次用了{calls}次上游调用，属于获准新增50次预算，余量{50 - calls}次；阶段二优先复用已绑定资产。
失败历史不删除，没有人工填充、替换供应商或复用DEV临时快照。
READY不证明历史发布时间、修订历史或真实排队成交；仍保留原声明的限制。

## 阶段二范围

检验趋势延续、短期反转及波动和流动性风险过滤的信息用途，先与简单量价基线及时间分层比较。
标签须区分未来价格变化、限价是否可成交、费用、退出延迟和资金占用；组件统计不等于策略收益。
适用时序特征普查实际使用tsfresh；不进行模型超参数或策略参数搜索，后续参数搜索使用Optuna。
阶段二首轮2小时、2进程、每进程1原生线程、种子13，网络调用计入本轮50次总预算。
本轮仅进入组件阶段，完整策略构建、阶段三推进、冻结及生产均待相应后续授权。

整个周期属于开发池内检验；已见技术信息不重新命名为独立封存样本。
组件预热先使用研究窗口内历史，明确样本损失；额外预窗口输入在使用前单列说明。
年度指标7组合成边界已通过，真实策略仍未评价；阶段四强类型年度目标对接尚待核验。

## 成果与下一步

本交付为COMPLETE，表示阶段一约定和输入准备完成；不表示存在有效组件、达标策略或已批准进入阶段三。
确认依据及完整约定见本实验protocols/，正式证据引用见others/result.json。
下一步在新实验内执行事前声明的组件检验，正式保存支持和负面结果，完成后呈现报告并请用户决定是否进入阶段三。
"""
    content = DeliveryContent(mandate, DeliveryStatus.COMPLETE,
                              facts=(FactValue("ready-inputs", 5, "datasets", FactStatus.AVAILABLE, (refs["input-readiness"],)),),
                              explanations=(), report=report, evidence=tuple(refs.values()))
    receipt = assemble_delivery(repository, DeliveryDefinition(context.batch, DeliveryStage.MANDATE, 2, (previous,)), content)
    checked = validate_delivery(repository, receipt.reference)
    if checked.status is not ValidationStatus.PASS:
        raise RuntimeError(checked.issues)
    public = ROOT / "research/S014/deliveries/MANDATE/2/report.md"
    copied = EXPERIMENT / "others/report.md"
    raw = public.read_bytes()
    copied.write_bytes(raw)
    verification = {"formal_report": public.relative_to(ROOT).as_posix(), "experiment_report": copied.relative_to(ROOT).as_posix(),
                    "bytes": len(raw), "sha256": sha256(raw).hexdigest(), "status": "PASS"}
    assert copied.read_bytes() == raw
    (EXPERIMENT / "protocols/report_copy_verification.json").write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
    result = {"experiment": experiment.to_dict(), "delivery": receipt.reference.to_dict(), "status": "COMPLETE",
              "validation": checked.to_dict(), "evidence": {name: ref.to_dict() for name, ref in refs.items()},
              "ready_inputs": readiness["records"], "source_calls_after_fix": calls, "remaining_source_budget": 50 - calls,
              "report_copy": verification}
    (EXPERIMENT / "others/result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_research_intent(repository, context.batch, ResearchIntentUpdate(research_intent={
        "stage": "阶段二：获准开始组件研究", "research_window": contract["research_window"], "objectives": contract["objectives"],
        "confirmed_contract": "research/S014/experiments/EX003_20261016/protocols/confirmed_contract.json",
        "authorization": authority, "mandate": receipt.reference.to_dict(), "ready": True,
        "resources": {"max_workers": 2, "native_threads_per_worker": 1, "initial_hours": 2, "remaining_source_calls": 50 - calls},
        "boundaries": contract["boundaries"], "pending": ["完成组件阶段后由用户决定是否进入阶段三"]}),
        actor="RSCH", reason="用户确认阶段一方案并批准继续，完整输入恢复READY，开始组件阶段")
    print(json.dumps({"delivery": receipt.reference.to_dict(), "validation": checked.status.value, "status": "COMPLETE"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
