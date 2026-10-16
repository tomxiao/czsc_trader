"""Publish phase-two closure honestly, with a bounded phase-three proposal."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import json

from czsc_trader.application import (
    RepositoryContext, create_research_context, publish_evidence, assemble_delivery,
    validate_delivery, update_research_intent, ResearchIntentUpdate,
)
from czsc_trader.research_tools import (
    ResearchBatchRef, ExperimentRef, EvidenceRef, MaterialEvidenceWrite, DeliveryReference,
    DeliveryDefinition, DeliveryStage, DeliveryContent, DeliveryStatus, ValidationStatus,
    ComponentPanel, ComponentEntry, ComponentTestResult, ComponentTestStatus, ExperimentDefinitionRef,
    FactValue, FactStatus,
)

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
RUN = ROOT / "research/S014/assets/runs/EX007_20261017/first"


def main():
    if (EXPERIMENT / "others/result.json").exists():
        raise RuntimeError("Already published")
    repository = RepositoryContext.discover(ROOT)
    context = create_research_context(repository, ResearchBatchRef("S014"))
    experiment = ExperimentRef("S014", "EX007_20261017")
    prior_result = json.loads((ROOT / "research/S014/experiments/EX006_20261016/others/result.json").read_text(encoding="utf-8"))
    mandate_result = json.loads((ROOT / "research/S014/experiments/EX003_20261016/others/result.json").read_text(encoding="utf-8"))
    prior_ref, mandate_ref = (DeliveryReference.from_dict(r["delivery"]) for r in (prior_result, mandate_result))
    for ref in (prior_ref, mandate_ref):
        if validate_delivery(repository, ref).status is not ValidationStatus.PASS:
            raise RuntimeError("Predecessor failed validation")
    previous = DeliveryContent.from_dict(json.loads((ROOT / "research/S014/assets/deliveries/COMPONENTS/3/delivery.json").read_text(encoding="utf-8"))["content"])
    audit = json.loads((EXPERIMENT / "others/audit.json").read_text(encoding="utf-8"))
    fixed = json.loads((EXPERIMENT / "others/computation_result.json").read_text(encoding="utf-8"))
    online = json.loads((EXPERIMENT / "others/online_result.json").read_text(encoding="utf-8"))
    if audit["status"] != "PASS":
        raise RuntimeError("Audit not PASS")
    for item in audit["manifest"]:
        if sha256((ROOT / item["path"]).read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("Audited material changed")
    refs = {}
    for name in ("published_design.json", "followup_published.json"):
        refs.update({key: EvidenceRef.from_dict(value) for key, value in json.loads((EXPERIMENT / "protocols" / name).read_text(encoding="utf-8")).items()})
    for name, ref in refs.items():
        path = EXPERIMENT / ("protocols/design.json" if name == "design" else "protocols/followup_design.json" if name == "followup-design" else f"src/{name}.py")
        if ref.resolve(ROOT).read_bytes() != path.read_bytes():
            raise RuntimeError("Predeclared source changed")
    provenance = {"authorization": "请以能推进进入阶段三为目标，自主完成阶段二", "base_commit": "933d395d",
        "phase_two_complete": True, "phase_three_recommended": True, "phase_three_approved": False,
        "phase_three_proposal": "One falsifiable recent-support/re-entry hypothesis, three deterministic account contrasts A/B/C, no broad search",
        "initial_model_solves": fixed["fits"], "online_model_solves_including_repeated_annual": online["fits"],
        "audit_model_recomputations": audit["fixed_fit_recomputations"] + audit["online_fit_recomputations"],
        "nominal_history_comparisons": 192, "new_source_calls": 0, "remaining_source_calls": 6, "strategy_accounts": 0,
        "new_component_definitions": 4, "supported_auxiliary_components": 2, "new_supported_return_components": 0,
        "workers": 2, "native_threads_per_worker": 1, "seed": 13,
        "selection_disclosure": "All data previously seen. Online response research adapted after inspecting fixed holding results. No independent holdout or automatic model winner.",
        "method_correction": audit["method_note"], "audit_checks": len(audit["checks"])}
    (EXPERIMENT / "protocols/provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    materials = {"fixed-result": EXPERIMENT / "others/computation_result.json",
        "online-result": EXPERIMENT / "others/online_result.json", "annual": EXPERIMENT / "others/annual.csv",
        "online-annual": EXPERIMENT / "others/online_annual.csv", "calendar-sensitivity": EXPERIMENT / "others/calendar_interval_sensitivity.json",
        "audit": EXPERIMENT / "others/audit.json", "audit-program": EXPERIMENT / "src/audit.py",
        "publication-program": Path(__file__), "provenance": EXPERIMENT / "protocols/provenance.json",
        "design-publication": EXPERIMENT / "protocols/published_design.json",
        "followup-publication": EXPERIMENT / "protocols/followup_published.json"}
    materials.update({p.stem.replace("_", "-"): p for p in RUN.glob("*.csv")})
    for name, path in materials.items():
        refs[name] = publish_evidence(context, MaterialEvidenceWrite(experiment, name, path.read_bytes(),
            {"json": "application/json", "csv": "text/csv", "py": "text/x-python"}[path.suffix[1:]], path.suffix[1:]))
    facts = tuple(replace(f, fact_id=f"prior-{f.fact_id}") for f in previous.facts)
    entries = [replace(entry, tests=tuple(replace(test, fact_ids=tuple(f"prior-{name}" for name in test.fact_ids)) for test in entry.tests))
               for entry in previous.payload.components]
    for component, role, status, explanation in (
        ("holding-structure", "行情价格结构对继续持有的增量信息", ComponentTestStatus.INEFFECTIVE,
         "固定结构表达在三个期限相对简单岭基线的合并增量均负，完整线性/树组合未解决；仅否定本次表达的净收益增量。"),
        ("holding-participation", "成交参与代理对继续持有的增量信息", ComponentTestStatus.INSUFFICIENT_DATA,
         "5日期限有弱线索，但其他期限为负，剔除2026后线索消失；未建立稳定持有用途。"),
        ("holding-path", "已知盈利回吐路径对继续持有的增量信息", ComponentTestStatus.INSUFFICIENT_DATA,
         "10日相对基线约+0.067个百分点，其他期限为负且相对继续固定持有仍负；没有充分证据支持净收益用途。"),
        ("adaptive-response", "仅使用已到期结果更新入场收益响应", ComponentTestStatus.INEFFECTIVE,
         "126/252日固定遗忘表达在5/10日均弱于同记忆长度无条件均值；2026相对年度拟合改善伴随其他年份代价。"),
    ):
        adaptive = component == "adaptive-response"
        test = ComponentTestResult(f"{component}-fixed-comparisons", experiment.experiment_id,
            refs["followup-design" if adaptive else "design"], status, explanation,
            (refs["online-result" if adaptive else "fixed-result"], refs["online-annual" if adaptive else "annual"], refs["audit"], refs["calendar-sensitivity"]),
            ("round-model-solves", "round-strategy-accounts"))
        entries.append(ComponentEntry(component,
            ExperimentDefinitionRef(refs["online" if adaptive else "components"], "src/online.py::weighted_predict" if adaptive else "src/components.py::market_features,holding_features"),
            role, "原生独立入场扣费净收益，未成交0" if adaptive else "原固定退出扣费净收益减下一TXE可执行退出净收益，同股数/100000",
            "5/10交易日" if adaptive else "原持有5/10/20日中点独立检查",
            "年度冻结、每日扩展、相同126/252日记忆无条件均值" if adaptive else "简单量价及当前浮盈、单组/完整/消融、固定树和朴素结构/支撑",
            "完成T日及更早；训练标签到期索引严格早于T；源发布时间与修订历史未验证",
            "HFQ_RESEARCH归一化单位，SRT计划股数与原始涨跌停/价位折算，双侧0.1%费用",
            "600722.SH已见2020..2026-10-15开发池，2023..2026测试；独立重叠尝试，非账户或独立验证",
            explanation, (test,)))
    conclusion = "阶段二完成：新增4项机制定义但未确认新增收益用途，保留2项基础辅助信息。建议阶段三仅做一个近期支撑/再入场假设的三个连续账户对照；不开展广泛搜索。阶段三尚未批准，年度经济目标未验收。"
    panel = ComponentPanel(tuple(entries), conclusion)
    for name, value, unit in (("round-model-solves", fixed["fits"] + online["fits"], "solves including repeated annual fits"),
        ("round-strategy-accounts", 0, "accounts"), ("round-new-source-calls", 0, "calls"),
        ("round-fixed-observations", fixed["observations"], "holding observations"),
        ("round-online-test-observations", online["rows"], "signal observations"),
        ("round-audit-checks", len(audit["checks"]), "checks"), ("round-panel-definitions", len(entries), "definitions")):
        facts += (FactValue(name, value, unit, FactStatus.AVAILABLE, (refs["provenance"], refs["audit"])),)
    receipt = assemble_delivery(repository, DeliveryDefinition(context.batch, DeliveryStage.COMPONENTS, 4, (mandate_ref, prior_ref)),
        DeliveryContent(panel, DeliveryStatus.COMPLETE, facts=facts, explanations=(),
            report=(EXPERIMENT / "protocols/report.md").read_text(encoding="utf-8"),
            evidence=tuple(dict.fromkeys((*previous.evidence, *refs.values())))))
    validation = validate_delivery(repository, receipt.reference)
    if validation.status is not ValidationStatus.PASS:
        raise RuntimeError(validation.issues)
    public = ROOT / "research/S014/deliveries/COMPONENTS/4/report.md"
    copied = EXPERIMENT / "others/report.md"
    copied.write_bytes(public.read_bytes())
    verification = {"formal_report": public.relative_to(ROOT).as_posix(), "experiment_report": copied.relative_to(ROOT).as_posix(),
        "bytes": public.stat().st_size, "sha256": sha256(public.read_bytes()).hexdigest(), "status": "PASS"}
    assert public.read_bytes() == copied.read_bytes()
    (EXPERIMENT / "protocols/report_copy_verification.json").write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
    result = {"experiment": experiment.to_dict(), "delivery": receipt.reference.to_dict(), "validation": validation.to_dict(),
        "status": "COMPLETE", "evidence": {key: ref.to_dict() for key, ref in refs.items()},
        "inherited_evidence": [ref.to_dict() for ref in previous.evidence], "report_copy": verification,
        "phase_two_complete": True, "phase_three_recommended": True, "phase_three_approved": False,
        "new_supported_return_components": 0, "supported_context_components": 2, "component_definitions": len(entries), "strategy_accounts": 0}
    (EXPERIMENT / "others/result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    intent = json.loads((ROOT / "research/registrations/S014/family.json").read_text(encoding="utf-8"))["research_intent"]
    intent.update(stage="阶段二完成：建议进入受限阶段三连续账户验证，待用户批准", components=receipt.reference.to_dict(),
        pending=["审阅COMPONENTS/4；批准或调整阶段三一个假设、三个账户的确定性首轮方案"],
        supported_components=2, supported_return_entry_components=0, strategy_accounts=0, conclusion=conclusion)
    intent["diagnostic_feedback"].update(closure_delivery=receipt.reference.to_dict(),
        result="结构/参与/持仓路径及近期响应更新未形成清楚增益；不继续邻近扫描。",
        judgment_update="信息表达研究已收口；再入场、持仓占用及年度风险收益取舍必须由完整账户检验，现有收益支持弱。",
        routing_after_result="建议阶段三仅先做近期支撑/再入场的A/B/C账户，未获批准，不展开搜索。")
    update_research_intent(repository, context.batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
        reason="按用户自主完成阶段二的授权收口，保存新增机制负面结果和反证，提出具体受限阶段三方案待批准")
    print(json.dumps({"delivery": receipt.reference.to_dict(), "validation": validation.to_dict(),
        "definitions": len(entries), "checks": len(audit["checks"]), "phase_three_approved": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
