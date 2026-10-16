"""Publish partial mechanism evidence without declaring phase-two completion."""
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
RUN = ROOT / "research/S014/assets/runs/EX008_20261017/first"


def main():
    if (EXPERIMENT / "others/result.json").exists():
        raise RuntimeError("Already published; preserve immutable result")
    repository = RepositoryContext.discover(ROOT)
    context = create_research_context(repository, ResearchBatchRef("S014"))
    experiment = ExperimentRef("S014", "EX008_20261017")
    prior_result = json.loads((ROOT / "research/S014/experiments/EX007_20261017/others/result.json").read_text(encoding="utf-8"))
    mandate_result = json.loads((ROOT / "research/S014/experiments/EX003_20261016/others/result.json").read_text(encoding="utf-8"))
    prior_ref, mandate_ref = (DeliveryReference.from_dict(r["delivery"]) for r in (prior_result, mandate_result))
    for ref in (prior_ref, mandate_ref):
        if validate_delivery(repository, ref).status is not ValidationStatus.PASS:
            raise RuntimeError("Predecessor validation failed")
    previous = DeliveryContent.from_dict(json.loads((ROOT / "research/S014/assets/deliveries/COMPONENTS/4/delivery.json").read_text(encoding="utf-8"))["content"])
    audit = json.loads((EXPERIMENT / "others/audit.json").read_text(encoding="utf-8"))
    cap = json.loads((EXPERIMENT / "others/cap_audit.json").read_text(encoding="utf-8"))
    if audit["status"] != "PASS" or cap["status"] != "PASS":
        raise RuntimeError("Audit failed")
    for item in (*audit["manifest"], *cap["manifest"]):
        if sha256((ROOT / item["path"]).read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("Audited material changed")
    refs = {}
    for filename in ("published_design.json", "followup_published.json"):
        refs.update({name: EvidenceRef.from_dict(value) for name, value in json.loads((EXPERIMENT / "protocols" / filename).read_text(encoding="utf-8")).items()})
    for name, ref in refs.items():
        path = EXPERIMENT / ("protocols/design.json" if name == "design" else "protocols/followup_design.json" if name == "followup-design" else f"src/{name}.py")
        if ref.resolve(ROOT).read_bytes() != path.read_bytes():
            raise RuntimeError("Predeclared source changed")
    provenance = {"authorization": "继续阶段二，自主提出并验证新收益机制；不按实验完成或组件数量收口；不足时明确数据扩展及依据",
        "base_commit": "35959b03", "phase_two_complete": False, "phase_three_recommended": False, "phase_three_approved": False,
        "initial_model_fits": 96, "audit_model_recomputations": 96, "nominal_history_comparisons": 296,
        "additional_posthoc_views": "Price-floor parent/recovery/episode/frequency diagnostics inspected adaptively;296 does not enumerate all selection exposure.",
        "new_source_calls": 0, "remaining_source_calls": 6, "strategy_accounts": 0,
        "new_supported_return_components": 0, "supported_auxiliary_components": 2,
        "entry_replications": audit["entry_replications"], "exit_replications": audit["exit_replications"],
        "audit_checks": len(audit["checks"]) + len(cap["checks"]), "workers": 2, "native_threads_per_worker": 1, "seed": 13,
        "next_scope_proposed": "S014上证指数000001.SH日线，同原窗口，使用剩余6次上游调用上限；未批准、未取数。",
        "availability_limit": "Mathematical feature causality checked, historical source publication/revision not proven; public company/report/API pages read as planning background only, not historical features."}
    (EXPERIMENT / "protocols/provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    materials = {
        "computation-result": EXPERIMENT / "others/computation_result.json", "followup-result": EXPERIMENT / "others/followup_result.json",
        "annual": EXPERIMENT / "others/annual.csv", "followup-cells": EXPERIMENT / "others/followup_cells.csv",
        "audit": EXPERIMENT / "others/audit.json", "audit-program": EXPERIMENT / "src/audit.py",
        "cap-audit": EXPERIMENT / "others/cap_audit.json", "cap-audit-program": EXPERIMENT / "src/audit_cap.py",
        "cap-diagnostics-design": EXPERIMENT / "protocols/cap_diagnostics.json", "cap-diagnostics-program": EXPERIMENT / "src/cap_diagnostics.py",
        "cap-diagnostics-result": EXPERIMENT / "others/cap_diagnostics_result.json",
        "data-extension-proposal": EXPERIMENT / "protocols/data_extension_proposal.json",
        "publication-program": Path(__file__), "provenance": EXPERIMENT / "protocols/provenance.json",
        "design-publication": EXPERIMENT / "protocols/published_design.json", "followup-publication": EXPERIMENT / "protocols/followup_published.json",
    }
    materials.update({f"run-{p.stem.replace('_', '-')}": p for p in RUN.glob("*.csv")})
    for name, path in materials.items():
        refs[name] = publish_evidence(context, MaterialEvidenceWrite(experiment, name, path.read_bytes(),
            {"json": "application/json", "csv": "text/csv", "py": "text/x-python"}[path.suffix[1:]], path.suffix[1:]))
    facts = tuple(replace(f, fact_id=f"prior-{f.fact_id}") for f in previous.facts)
    entries = [replace(entry, tests=tuple(replace(test, fact_ids=tuple(f"prior-{name}" for name in test.fact_ids)) for test in entry.tests))
               for entry in previous.payload.components]
    for component, role, explanation in (
        ("upper-bound-delayed-discovery", "涨停约束后的短期价格延续", "不同期限方向不一致，2023无事件且2024/2025各6次，固定限价未成交有选择性；尚未建立可用净收益用途。"),
        ("lower-bound-recovery", "触跌停后回收对应的短期收益修复", "10日相对一般大跌有较强正向证据，但相对仍收在下限的父条件没有一致增量，2025仍亏损；事件稀少且单独频率不足，保留互补线索，不认定策略可用。"),
        ("gap-down-repair", "低开后的盘中修复与短期可执行净收益", "1/3日相对同低开未修复有正向线索，1日去2026仍正；但2025选中尝试亏损，普通收阳/共同支持控制及事件去重存在反例，未区分共同市场冲击与特有重定价。"),
        ("gap-up-rejection", "高开后收阴的机会筛选信息", "短期有相对弱表现线索，跨期限及控制证据不足，10日方向反转；不构成禁买规则或做空策略。"),
    ):
        test = ComponentTestResult(f"{component}-mechanism-and-counterevidence", experiment.experiment_id,
            refs["design"], ComponentTestStatus.INSUFFICIENT_DATA, explanation,
            (refs["computation-result"], refs["followup-result"], refs["annual"], refs["followup-cells"],
             refs["cap-diagnostics-result"], refs["cap-audit"], refs["audit"]), ("current-audit-checks", "current-strategy-accounts"))
        entries.append(ComponentEntry(component, ExperimentDefinitionRef(refs["features"], "src/features.py::features,event_masks"),
            role, "实际SRT股数的TXE退出净现金收益/100000，双侧0.1%，未成交0，截断保留",
            "入场后1/3/5/10日，最早T+2卖出；低开修复追加重点检验1/3日",
            "大涨/大跌父条件、隔夜/盘中四组、原简单量价及残差、固定表达、共同支持和事件簇反证",
            "完成T日及更早；阈值/训练仅使用实际到期严格早于测试起点的标签；源历史修订与发布时间未验证",
            "HFQ_RESEARCH归一化；事件用同日原始涨跌停价与半价位容差；实际成交沿用原始价位折算",
            "600722.SH已见开发池；2023..2026成熟信号，独立重叠尝试；补充匹配仅作解释，不进入信号",
            explanation, (test,)))
    conclusion = "阶段二继续：低开修复短期相对用途和触跌停父机会有正向证据，但关键对照、2025反例及共同冲击解释未解决；不声明新收益组件获支持。建议先批准同窗口上证指数日线的最小扩展，核验上游后继续检验；不进入阶段三。"
    panel = ComponentPanel(tuple(entries), conclusion)
    for name, value, unit in (
        ("current-audit-checks", len(audit["checks"]) + len(cap["checks"]), "checks"),
        ("current-strategy-accounts", 0, "accounts"), ("current-source-calls", 0, "calls"),
        ("current-fixed-model-fits", 96, "fits"), ("current-native-test-observations", 3633, "attempt observations"),
        ("current-low-gap-repair-H1-signals", 217, "signals"), ("current-low-gap-repair-H1-filled", 214, "filled attempts"),
        ("current-low-gap-repair-H1-net", .003928505023041571, "net cash/100000"),
        ("current-full-calendar-lower-touch", cap["all_lower_touch_count"], "signals"),
        ("current-full-calendar-lower-recovery", cap["all_lower_recovery_count"], "signals"),
    ):
        facts += (FactValue(name, value, unit, FactStatus.AVAILABLE, (refs["provenance"], refs["audit"], refs["cap-audit"])),)
    incomplete = ("关键收益用途尚未通过普通收阳、共同支持范围及2025反例的解释性对照；阶段二仍进行中。",
                  "市场共同冲击与个股特有重定价无法由当前单票输入区分；最小指数数据扩展待用户批准及真实上游覆盖/权限验证。")
    receipt = assemble_delivery(repository, DeliveryDefinition(context.batch, DeliveryStage.COMPONENTS, 5, (mandate_ref, prior_ref)),
        DeliveryContent(panel, DeliveryStatus.PARTIAL, facts=facts, explanations=(), incomplete_items=incomplete,
            report=(EXPERIMENT / "protocols/report.md").read_text(encoding="utf-8"),
            evidence=tuple(dict.fromkeys((*previous.evidence, *refs.values())))))
    validation = validate_delivery(repository, receipt.reference)
    if validation.status is not ValidationStatus.PASS:
        raise RuntimeError(validation.issues)
    public = ROOT / "research/S014/deliveries/COMPONENTS/5/report.md"
    copied = EXPERIMENT / "others/report.md"
    copied.write_bytes(public.read_bytes())
    verification = {"formal_report": public.relative_to(ROOT).as_posix(), "experiment_report": copied.relative_to(ROOT).as_posix(),
        "bytes": public.stat().st_size, "sha256": sha256(public.read_bytes()).hexdigest(), "status": "PASS"}
    assert public.read_bytes() == copied.read_bytes()
    (EXPERIMENT / "protocols/report_copy_verification.json").write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8", newline="\n")
    result = {"experiment": experiment.to_dict(), "delivery": receipt.reference.to_dict(), "validation": validation.to_dict(),
        "status": "PARTIAL", "evidence": {name: ref.to_dict() for name, ref in refs.items()},
        "inherited_evidence": [ref.to_dict() for ref in previous.evidence], "report_copy": verification,
        "phase_two_complete": False, "phase_three_recommended": False, "phase_three_approved": False,
        "supported_context_components": 2, "new_supported_return_components": 0, "strategy_accounts": 0,
        "minimum_data_expansion": "上证指数000001.SH日线，2020-01-01至2026-10-15，S014公开prepare/fetch，剩余6次调用上限；待批准。"}
    (EXPERIMENT / "others/result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    intent = json.loads((ROOT / "research/registrations/S014/family.json").read_text(encoding="utf-8"))["research_intent"]
    intent.update(stage="阶段二进行中：新收益线索有反证，最小市场指数扩展待批准", components=receipt.reference.to_dict(),
        phase_two_complete=False, phase_three_approved=False, phase_three_ready=False, component_definitions=len(entries),
        pending=[result["minimum_data_expansion"]], supported_components=2, supported_return_entry_components=0,
        strategy_accounts=0, conclusion=conclusion)
    intent["diagnostic_feedback"].update(authorization="用户授权继续阶段二自主提出/验证新机制，不按实验或组件数量收口，信息不足时明确数据扩展。",
        closure_delivery=receipt.reference.to_dict(), reviewed_delivery=receipt.reference.to_dict(), reviewed_commit="35959b03",
        execution_scope_this_turn="EX008新机制及其线索反证、现金归因和上游接口文档/平台能力核对；无新市场时序、无账户。",
        decision_update="撤回COMPONENTS/4直接推进阶段三建议；当前PARTIAL，阶段二继续。",
        priority_question="低开修复和极端卖压后的收益是否来自共同市场冲击，能否事前区分持续负面重定价？",
        recommended_minimum_design="先批准并核验上证指数同窗口日线，用已完成T的市场/个股相对隔夜和盘中响应做新对照，标签/费用不变。",
        result="低开修复短期相对收益和价格下限父机会有正向证据，但普通收阳/配对/2025反例未解决，新增收益用途不认定。",
        judgment_update="实验完成不等于材料准备充分；关键识别问题需要独立市场观察，不继续同义指标或预先推进账户。",
        routing={"primary":"阶段二：机制辨别与最小数据扩展","stage_three":"未批准且不建议现在进入"},
        routing_after_result="阶段二继续；最小上证指数范围待批准，先验证权限/覆盖，不先扩平台。",
        verified=f"COMPONENTS/5 PARTIAL/FULL/PASS，主审核57+补充4项，{audit['exit_replications']}次退出及96模型复算；证据支持与反证分列。")
    update_research_intent(repository, context.batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
        reason="按新指令继续阶段二，留存新收益机制正向线索与关键反证，撤回过早收口判断，提出可审阅的最小市场数据扩展待批准")
    print(json.dumps({"delivery": receipt.reference.to_dict(), "validation": validation.to_dict(),
        "status": "PARTIAL", "checks": len(audit["checks"]) + len(cap["checks"]), "phase_two_complete": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
