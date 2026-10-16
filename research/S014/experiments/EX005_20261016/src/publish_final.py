"""Publish completed phase two with bounded roles and all material counterevidence."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import importlib.metadata
import json
import platform

from czsc_trader.application import (
    RepositoryContext, create_research_context, publish_evidence, assemble_delivery,
    validate_delivery, update_research_intent, ResearchIntentUpdate,
)
from czsc_trader.research_tools import (
    ResearchBatchRef, ExperimentRef, MaterialEvidenceWrite, EvidenceRef, DeliveryReference,
    DeliveryContent, DeliveryDefinition, DeliveryStage, DeliveryStatus, ValidationStatus,
    ComponentPanel, ComponentEntry, ComponentTestResult, ComponentTestStatus,
    ExperimentDefinitionRef, FactValue, FactStatus,
)

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]


def main():
    if (EXPERIMENT / "others/result.json").exists():
        raise RuntimeError("Final delivery already published; preserve it")
    repository = RepositoryContext.discover(ROOT)
    context = create_research_context(repository, ResearchBatchRef("S014"))
    experiment = ExperimentRef("S014", "EX005_20261016")
    prior_result = json.loads((ROOT / "research/S014/experiments/EX004_20261016/others/result.json").read_text(encoding="utf-8"))
    prior_ref = DeliveryReference.from_dict(prior_result["delivery"])
    mandate_result = json.loads((ROOT / "research/S014/experiments/EX003_20261016/others/result.json").read_text(encoding="utf-8"))
    mandate_ref = DeliveryReference.from_dict(mandate_result["delivery"])
    for reference in (prior_ref, mandate_ref):
        if validate_delivery(repository, reference).status is not ValidationStatus.PASS:
            raise RuntimeError("Predecessor validation failed")
    previous = DeliveryContent.from_dict(json.loads((ROOT / "research/S014/assets/deliveries/COMPONENTS/1/delivery.json").read_text(encoding="utf-8"))["content"])
    audit = json.loads((EXPERIMENT / "others/audit.json").read_text(encoding="utf-8"))
    if audit["status"] != "PASS":
        raise RuntimeError("Audit is not PASS")
    for item in audit["manifest"]:
        if sha256((ROOT / item["path"]).read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("Audited output changed")
    refs = {}
    for name in ("published_design", "published_roles", "published_robustness"):
        for key, value in json.loads((EXPERIMENT / f"protocols/{name}.json").read_text(encoding="utf-8")).items():
            reference = EvidenceRef.from_dict(value)
            reference.resolve(ROOT)
            refs[key] = reference
    # Validate current decision/implementation sources against their preregistration.
    for key, relative in (("design", "protocols/design.json"), ("methods", "src/methods.py"), ("study", "src/study.py"),
                          ("role-protocol", "protocols/role_followup.json"), ("role-methods", "src/role_methods.py"), ("role-study", "src/role_study.py"),
                          ("robustness-protocol", "protocols/robustness.json"), ("robustness-methods", "src/robustness_methods.py"), ("robustness-study", "src/robustness_study.py")):
        if sha256((EXPERIMENT / relative).read_bytes()).hexdigest() != refs[key].sha256:
            raise RuntimeError("Preregistered source changed")
    provenance = {"authorization": "你来主导完成阶段二，我看结果", "source": "current human-user conversation",
        "scope": "S014 phase two only; no phase-three account/strategy construction",
        "python": platform.python_version(), "packages": {name: importlib.metadata.version(name) for name in ("numpy", "pandas", "scikit-learn", "tsfresh")},
        "prior_commit": "46c8c0200b45ee02c7bd4555e7c3942fa40e8662", "new_fits": 56,
        "replications": 32, "new_fixed_amplitude_fits": 24, "history_fits_including_replications": 248,
        "new_nominal_comparisons": 30, "history_nominal_comparisons": 62,
        "comparison_note": "Includes repeated controls and adaptive questions; not independent discoveries; secondary descriptive diagnostics additional",
        "workers": 2, "native_threads_per_worker": 1, "seed": 13, "new_source_calls": 0,
        "remaining_source_budget": 6, "parameter_searches": 0, "strategy_accounts": 0,
        "supported_context_components": 2, "supported_incremental_return_entry_components": 0}
    (EXPERIMENT / "protocols/provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    materials = {
        "audit": EXPERIMENT / "others/audit.json", "audit-program": EXPERIMENT / "src/audit.py",
        "component-definition": EXPERIMENT / "src/components.py", "publication-program": Path(__file__),
        "robustness-result": EXPERIMENT / "others/robustness_result.json", "persistence-controls": EXPERIMENT / "others/persistence_controls.csv",
        "descriptive-mean-reference": EXPERIMENT / "others/descriptive_mean_control.csv",
        "weighted-errors": EXPERIMENT / "others/weighted_amplitude_errors.csv", "provenance": EXPERIMENT / "protocols/provenance.json",
    }
    for folder_name in ("first", "roles"):
        folder = ROOT / f"research/S014/assets/runs/EX005_20261016/{folder_name}"
        for path in sorted(folder.glob("*.csv")):
            materials[f"{folder_name}-{path.stem.replace('_', '-')}"] = path
    for name, path in materials.items():
        suffix = path.suffix[1:]
        refs[name] = publish_evidence(context, MaterialEvidenceWrite(experiment, name, path.read_bytes(),
            {"json": "application/json", "py": "text/x-python", "csv": "text/csv"}[suffix], suffix))
    evidence = tuple(dict.fromkeys((*previous.evidence, *refs.values())))
    entries = []
    for entry in previous.payload.components:
        if entry.component_id == "trend":
            entries.append(entry)
            continue
        if entry.component_id == "reversal":
            judgment = "分布变化和覆盖失配存在，但过去63日校准后3日净收益增量降至0.066个百分点，排序及状态外推不稳定；仍不足以支持稳定入场。"
        else:
            judgment = "旧短期损失改善受2026单样本影响，恢复覆盖后增量小且区间跨0；双向波动与单侧亏损应分开，原损失过滤用途证据不足。"
        test = ComponentTestResult(f"{entry.component_id}-state-coverage", experiment.experiment_id, refs["design"],
            ComponentTestStatus.INSUFFICIENT_DATA, judgment,
            (refs["diagnostic-result"], refs["first-annual"], refs["first-states"], refs["first-ranks"], refs["audit"]))
        entries.append(replace(entry, judgment=judgment, tests=(*entry.tests, test)))

    def add(component_id, role, label, horizon, control, judgment, status, definition_ref, protocol, supports):
        test = ComponentTestResult(f"{component_id}-closure", experiment.experiment_id, protocol, status,
                                   judgment, tuple(supports), ("this-round-fixed-fits", "primary-comparison-history"))
        entries.append(ComponentEntry(component_id, definition_ref, role, label, horizon, control,
            "完成T日及更早的本批次数据；T+1用途；发布时间与修订历史尚未验证，程序前缀因果检查通过",
            "HFQ_RESEARCH量价及同日原始涨停价，涨停容差为半个原始价位，源数据身份固定",
            "600722.SH已见开发池，2023至2026逐年训练外检验；非完整策略、非独立封存验证",
            judgment, (test,)))

    rule_definition = ExperimentDefinitionRef(refs["study"], "src/study.py::comparisons")
    for component_id, role, status, judgment in (
        ("pullback-turn", "回落后收阳确认", ComponentTestStatus.INEFFECTIVE, "3/5/10日相对父条件增量均为负；本次固定确认规则无稳定改善。"),
        ("breakout-volume", "突破成交量确认", ComponentTestStatus.REDUNDANT, "大部分父条件已满足成交量确认，三个期限没有正向年度差值，未形成有利区分。"),
        ("shock-close", "急跌后收盘修复", ComponentTestStatus.INSUFFICIENT_DATA, "2023和2025无选中样本、2024仅2次；2026较大均值不足以证明稳定用途。"),
    ):
        add(component_id, role, "SRT/TXE固定入场及退出对应的双侧0.1%费用后净现金收益/100000", "3/5/10个交易日",
            "事前声明的更简单父条件，期限、日期、费用相同，覆盖及成交分别披露", judgment, status,
            rule_definition, refs["design"], (refs["diagnostic-result"], refs["first-annual"], refs["first-observations"], refs["audit"]))
    context_definition = ExperimentDefinitionRef(refs["component-definition"], "src/components.py::observe_completed_session")
    add("current-true-range", "次日双向市场波动尺度参考", "未来一日真实波幅，不是净收益、持仓亏损或账户年度最大回撤", "下一交易所交易日",
        "当前真实波幅直接预测、训练均值事后描述参考、原拟合基线及ATR20拟合的简单对照",
        "SUPPORTED仅限基础风险上下文：四年次日波幅排序相关性0.388/0.522/0.578/0.578；次日MAE约1.603个百分点，不能视为可靠价格边界，不主张独立信息增量或方向收益。",
        ComponentTestStatus.SUPPORTED, context_definition, refs["role-protocol"],
        (refs["role-result"], refs["robustness-result"], refs["persistence-controls"], refs["descriptive-mean-reference"], refs["audit"]))
    add("atr20-fitted-scale", "新增20日波幅模型的必要性", "未来1/3/5日平均真实波幅预测误差", "1/3/5个交易所交易日",
        "原5特征同模型基线、直接当天真实波幅、直接20日均值",
        "相对指定拟合基线有增量，但1日弱于直接当天波幅，跨年份及更强简单对照的必要性不充分；保留结果，不引入必须依赖的复杂模块。",
        ComponentTestStatus.INSUFFICIENT_DATA, ExperimentDefinitionRef(refs["role-study"], "src/role_study.py::main"), refs["role-protocol"],
        (refs["role-result"], refs["robustness-result"], refs["persistence-controls"], refs["roles-amplitude-forecasts"], refs["audit"]))
    add("upper-limit-close-awareness", "次日固定限价买入成交风险提示", "SRT/TXE固定上浮1%限价买入次日未成交标记", "下一交易所交易日",
        "同年其他信号日；训练及分年测试，缺事件年份不填0，保留剔除各年份反证",
        "SUPPORTED仅限条件性风险提示：训练7/23、测试10/36未成交，其他测试日11/877；2024为0/6、2023无事件，调整区间跨0，不是禁买规则或利润改善证据。",
        ComponentTestStatus.SUPPORTED, context_definition, refs["role-protocol"],
        (refs["role-result"], refs["robustness-result"], refs["roles-execution-observations"], refs["roles-execution-summary"], refs["audit"]))
    panel = ComponentPanel(tuple(entries),
        "阶段二完成：2项基础辅助上下文用途获得限定支持，稳定净收益增量入场组件0；阈值失配、少样本和更强简单对照已核验。整体经济目标未验收，阶段三未获批准。")
    facts = tuple(item for item in previous.facts if item.fact_id in ("model-fits", "comparisons"))
    facts += tuple(FactValue(name, value, unit, FactStatus.AVAILABLE, (refs["provenance"], refs["audit"])) for name, value, unit in (
        ("this-round-fixed-fits", 56, "fits including32replications"), ("history-fixed-fits", 248, "fits including replications"),
        ("primary-comparison-history", 62, "nominal comparisons including repeated controls"),
        ("supported-context-components", 2, "components"), ("supported-return-entry-components", 0, "components"), ("strategy-accounts", 0, "accounts")))
    report = (EXPERIMENT / "protocols/final_report.md").read_text(encoding="utf-8")
    receipt = assemble_delivery(repository, DeliveryDefinition(context.batch, DeliveryStage.COMPONENTS, 2, (mandate_ref, prior_ref)),
        DeliveryContent(panel, DeliveryStatus.COMPLETE, facts=facts, explanations=(), report=report, evidence=evidence))
    checked = validate_delivery(repository, receipt.reference)
    if checked.status is not ValidationStatus.PASS:
        raise RuntimeError(checked.issues)
    public = ROOT / "research/S014/deliveries/COMPONENTS/2/report.md"
    copied = EXPERIMENT / "others/report.md"
    copied.write_bytes(public.read_bytes())
    verification = {"formal_report": public.relative_to(ROOT).as_posix(), "experiment_report": copied.relative_to(ROOT).as_posix(),
        "bytes": public.stat().st_size, "sha256": sha256(public.read_bytes()).hexdigest(), "status": "PASS"}
    assert public.read_bytes() == copied.read_bytes()
    (EXPERIMENT / "protocols/report_copy_verification.json").write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
    result = {"experiment": experiment.to_dict(), "delivery": receipt.reference.to_dict(), "status": "COMPLETE",
        "validation": checked.to_dict(), "evidence": {key: ref.to_dict() for key, ref in refs.items()},
        "inherited_evidence": [ref.to_dict() for ref in previous.evidence], "report_copy": verification,
        "phase_two_complete": True, "supported_context_components": ["current-true-range", "upper-limit-close-awareness"],
        "supported_return_entry_components": [], "strategy_accounts": 0,
        "remaining_source_calls": 6, "next": "呈现阶段二结果，由用户决定是否批准阶段三小规模连续账户验证"}
    (EXPERIMENT / "others/result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    intent = json.loads((ROOT / "research/registrations/S014/family.json").read_text(encoding="utf-8"))["research_intent"]
    intent.update(stage="阶段二已完成，等待用户审阅并决定阶段三", components=receipt.reference.to_dict(),
        supported_components=2, supported_return_entry_components=0, strategy_accounts=0,
        pending=["用户审阅COMPONENTS/2后决定是否进入阶段三小规模账户验证"], conclusion=panel.conclusion)
    update_research_intent(repository, context.batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
                           reason="按用户授权主导完成阶段二，保留2项限定辅助用途及完整反证，未自动推进阶段三")
    print(json.dumps({"delivery": receipt.reference.to_dict(), "validation": checked.to_dict(), "supported_context": 2, "supported_return_entry": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
