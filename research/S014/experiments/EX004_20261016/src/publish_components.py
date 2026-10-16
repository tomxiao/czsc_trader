"""Publish the bounded component conclusion and immutable evidence via public APIs."""
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
RUN = ROOT / "research/S014/assets/runs/EX004_20261016/first"


def main():
    if (EXPERIMENT / "others/result.json").exists():
        raise RuntimeError("Components already published; preserve immutable delivery")
    repository = RepositoryContext.discover(ROOT)
    context = create_research_context(repository, ResearchBatchRef("S014"))
    experiment = ExperimentRef("S014", "EX004_20261016")
    mandate = json.loads((ROOT / "research/S014/experiments/EX003_20261016/others/result.json").read_text(encoding="utf-8"))
    previous = DeliveryReference.from_dict(mandate["delivery"])
    if validate_delivery(repository, previous).status is not ValidationStatus.PASS:
        raise RuntimeError("Mandate validation failed")
    audit = json.loads((EXPERIMENT / "others/audit.json").read_text(encoding="utf-8"))
    if audit["status"] != "PASS":
        raise RuntimeError("Audit failed")
    for item in audit["manifest"]:
        if sha256((ROOT / item["path"]).read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("Audited run output changed")
    refs = {}
    for name in ("published_design", "published_followup"):
        for key, value in json.loads((EXPERIMENT / f"protocols/{name}.json").read_text(encoding="utf-8")).items():
            ref = EvidenceRef.from_dict(value)
            if sha256(ref.resolve(ROOT).read_bytes()).hexdigest() != ref.sha256:
                raise RuntimeError("Previously published design evidence changed")
            refs[key] = ref
    for key in ("input-readiness", "confirmed-contract", "authorization"):
        refs[key] = EvidenceRef.from_dict(mandate["evidence"][key])
    provenance = {"python": platform.python_version(), "packages": {
        name: importlib.metadata.version(name) for name in ("numpy", "pandas", "tsfresh", "scikit-learn")},
        "platform_base_commit": "b457fa2b219548ddb17c9611d215b97d521b279a",
        "workers": 2, "native_threads_per_worker": 1, "seed": 13,
        "fit_count": 192, "comparison_count": 32, "account_count": 0, "parameter_search_count": 0,
        "new_source_calls_components": 0, "source_calls_recovery": 44, "remaining_source_budget": 6,
        "supported_component_count": 0, "scope": "S014 first component round; no strategy-stage authorization"}
    (EXPERIMENT / "protocols/provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    materials = {
        "features": RUN / "features.csv", "labels": RUN / "labels.csv",
        "initial-predictions": RUN / "predictions.csv", "coefficients": RUN / "coefficients.csv",
        "initial-annual": RUN / "annual_comparisons.csv", "followup-predictions": RUN / "followup_predictions.csv",
        "followup-annual": RUN / "followup_annual.csv", "followup-result": EXPERIMENT / "others/followup_result.json",
        "precheck": EXPERIMENT / "others/precheck.json", "audit": EXPERIMENT / "others/audit.json",
        "comparisons32": EXPERIMENT / "others/comparisons_32.csv", "descriptive-controls": EXPERIMENT / "others/descriptive_controls.csv",
        "audit-program": EXPERIMENT / "src/audit_results.py", "publication-program": Path(__file__),
        "provenance": EXPERIMENT / "protocols/provenance.json",
        "design-publication": EXPERIMENT / "protocols/published_design.json",
        "followup-publication": EXPERIMENT / "protocols/published_followup.json",
    }
    for name, path in materials.items():
        suffix = path.suffix[1:]
        refs[name] = publish_evidence(context, MaterialEvidenceWrite(experiment, name, path.read_bytes(),
            {"json": "application/json", "csv": "text/csv", "py": "text/x-python"}[suffix], suffix))
    shared = (refs["initial-result"], refs["followup-result"], refs["comparisons32"], refs["descriptive-controls"], refs["audit"])
    judgments = {
        "trend": ("趋势延续", ComponentTestStatus.INEFFECTIVE,
                  "本次固定设计中线性及树表达的四个期限增量均值均为负，未支持趋势组在简单量价基线上的增量；不推广至全部趋势机制。"),
        "reversal": ("短期反转入场信息", ComponentTestStatus.INSUFFICIENT_DATA,
                     "3日线性增量+0.544个百分点但区间跨0，较长期限为负；2026年相对改善仍为负绝对收益，单项与剔除对照未形成稳定归因。"),
        "risk": ("持有风险过滤", ComponentTestStatus.INSUFFICIENT_DATA,
                 "短期树风险普通区间正向，但2026年3/5日各只有1个选中样本；线性表达未支持，跨期限及年度不稳定，尚不能证明稳定风险用途。"),
    }
    components = []
    for key, (role, status, judgment) in judgments.items():
        tests = (
            ComponentTestResult(f"{key}-initial", experiment.experiment_id, refs["protocol"], status,
                                judgment, shared, ("model-fits", "comparisons")),
            ComponentTestResult(f"{key}-followup", experiment.experiment_id, refs["followup-protocol"], status,
                                "补充固定非线性表达与适应性诊断沿用已见开发池；风险及反转的正向线索不足以支持稳定组件。", shared),
        )
        components.append(ComponentEntry(
            key, ExperimentDefinitionRef(refs["component_study.py"], "src/component_study.py::features"), role,
            "入场双侧费用后净现金收益/100000；风险组为入场相对最不利收盘/退出价跌幅",
            "入场后3/5/10/20个交易日；右侧截断剔除，退出受TXE约束可延迟",
            "相同模型、训练期及测试日期的5项简单量价基线；阈值在训练期固定，实际选择比例分别披露",
            "已完成T日日线，T+1执行；历史发布时间和修订未验证，程序前缀因果检查通过",
            "HFQ_RESEARCH，以首日复权因子5.892归一化，原始涨跌停及价位按当日比例转换",
            "600722.SH已见开发池，2020起训练、2023至2026分年外推；当前数据全日状态均TRADING，非连续账户",
            judgment, tests))
    panel = ComponentPanel(tuple(components),
        "首轮组件研究完成，SUPPORTED数量0；保留趋势负面及反转/风险证据不足的结果。建议阶段二补证状态变化与覆盖，不自动进入阶段三。")
    facts = tuple(FactValue(name, value, unit, FactStatus.AVAILABLE, (refs["provenance"], refs["audit"]))
                  for name, value, unit in (("model-fits", 192, "fits"), ("comparisons", 32, "comparisons"),
                                            ("supported-components", 0, "components"), ("strategy-accounts", 0, "accounts")))
    report = (EXPERIMENT / "protocols/component_report.md").read_text(encoding="utf-8")
    receipt = assemble_delivery(repository, DeliveryDefinition(context.batch, DeliveryStage.COMPONENTS, 1, (previous,)),
        DeliveryContent(panel, DeliveryStatus.COMPLETE, facts=facts, explanations=(), report=report, evidence=tuple(refs.values())))
    validation = validate_delivery(repository, receipt.reference)
    if validation.status is not ValidationStatus.PASS:
        raise RuntimeError(validation.issues)
    public = ROOT / "research/S014/deliveries/COMPONENTS/1/report.md"
    copied = EXPERIMENT / "others/report.md"
    copied.write_bytes(public.read_bytes())
    check = {"formal_report": public.relative_to(ROOT).as_posix(), "experiment_report": copied.relative_to(ROOT).as_posix(),
             "bytes": public.stat().st_size, "sha256": sha256(public.read_bytes()).hexdigest(), "status": "PASS"}
    if copied.read_bytes() != public.read_bytes():
        raise RuntimeError("Published report copy differs")
    (EXPERIMENT / "protocols/report_copy_verification.json").write_text(json.dumps(check, indent=2) + "\n", encoding="utf-8")
    result = {"experiment": experiment.to_dict(), "delivery": receipt.reference.to_dict(), "status": "COMPLETE",
              "validation": validation.to_dict(), "evidence": {key: ref.to_dict() for key, ref in refs.items()},
              "report_copy": check, "supported_components": 0, "strategy_accounts": 0,
              "next_recommendation": "阶段二补证状态变化和信号覆盖；呈现本轮结果后由用户决定下一轮或阶段推进"}
    (EXPERIMENT / "others/result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    intent = json.loads((ROOT / "research/registrations/S014/family.json").read_text(encoding="utf-8"))["research_intent"]
    intent.update(stage="阶段二首轮已完成，等待用户决定补证或阶段推进", components=receipt.reference.to_dict(),
                  supported_components=0, strategy_accounts=0,
                  pending=["用户决定是否批准阶段二状态变化与覆盖补证；未自动进入阶段三"],
                  conclusion=panel.conclusion)
    update_research_intent(repository, context.batch, ResearchIntentUpdate(research_intent=intent),
                           actor="RSCH", reason="阶段二首轮及补充反证完成，正式交付负面和证据不足结论，等待用户决定")
    print(json.dumps({"delivery": receipt.reference.to_dict(), "validation": validation.status.value, "supported": 0}))


if __name__ == "__main__":
    main()
