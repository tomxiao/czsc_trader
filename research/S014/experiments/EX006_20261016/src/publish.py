"""Close the approved attribution round and return its learning to phase two."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import json
import platform

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
RUN = ROOT / "research/S014/assets/runs/EX006_20261016/first"


def main():
    if (EXPERIMENT / "others/result.json").exists():
        raise RuntimeError("Already published; preserve immutable delivery")
    repository = RepositoryContext.discover(ROOT)
    context = create_research_context(repository, ResearchBatchRef("S014"))
    experiment = ExperimentRef("S014", "EX006_20261016")
    previous_result = json.loads((ROOT / "research/S014/experiments/EX005_20261016/others/result.json").read_text(encoding="utf-8"))
    mandate_result = json.loads((ROOT / "research/S014/experiments/EX003_20261016/others/result.json").read_text(encoding="utf-8"))
    previous_ref = DeliveryReference.from_dict(previous_result["delivery"])
    mandate_ref = DeliveryReference.from_dict(mandate_result["delivery"])
    for reference in (previous_ref, mandate_ref):
        if validate_delivery(repository, reference).status is not ValidationStatus.PASS:
            raise RuntimeError("Predecessor validation failed")
    previous = DeliveryContent.from_dict(json.loads((ROOT / "research/S014/assets/deliveries/COMPONENTS/2/delivery.json").read_text(encoding="utf-8"))["content"])
    audit = json.loads((EXPERIMENT / "others/audit.json").read_text(encoding="utf-8"))
    computation = json.loads((EXPERIMENT / "others/computation_result.json").read_text(encoding="utf-8"))
    if audit["status"] != "PASS":
        raise RuntimeError("Audit failed")
    for item in audit["manifest"]:
        if sha256((ROOT / item["path"]).read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("Audited run changed")
    refs = {name: EvidenceRef.from_dict(value) for name, value in json.loads((EXPERIMENT / "protocols/published_design.json").read_text(encoding="utf-8")).items()}
    for name, relative in (("design", "protocols/design.json"), ("attribution", "src/attribution.py"), ("paired", "src/paired.py"), ("study", "src/study.py")):
        if (EXPERIMENT / relative).read_bytes() != refs[name].resolve(ROOT).read_bytes():
            raise RuntimeError("Preregistered source changed")
    provenance = {"authorization": "User agreed to return to phase two for one attribution round", "python": platform.python_version(),
        "prior_commit": "2cbb2e78", "symbol": "600722.SH", "research_window": ["2020-01-01", "2026-10-15"],
        "experiment_allocated": "2026-10-16", "closure_date": "2026-10-17", "workers": 2, "native_threads_per_worker": 1, "seed": 13,
        "new_source_calls": 0, "remaining_source_calls": 6, "new_model_fits": 0, "parameter_searches": 0,
        "strategy_accounts": 0, "common_signals": 1601, "closed_per_horizon": 1569, "unfilled_per_horizon": 32,
        "primary_comparisons": 16, "nominal_history_comparisons": 78, "audit_checks": len(audit["checks"]),
        "supported_context_components": 2, "new_supported_return_components": 0,
        "limits": "Independent overlapping attempts and hindsight path diagnostics; not investable account performance or annual acceptance"}
    (EXPERIMENT / "protocols/provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    materials = {"attribution-result": EXPERIMENT / "others/computation_result.json",
        "summary": EXPERIMENT / "others/attribution_summary.csv", "exit-annual": EXPERIMENT / "others/exit_condition_annual.csv",
        "concentration": EXPERIMENT / "others/concentration.csv", "year-contribution": EXPERIMENT / "others/year_contribution.json",
        "audit": EXPERIMENT / "others/audit.json", "audit-program": EXPERIMENT / "src/audit.py",
        "publication-program": Path(__file__), "provenance": EXPERIMENT / "protocols/provenance.json",
        "design-publication": EXPERIMENT / "protocols/published_design.json"}
    for path in sorted(RUN.glob("*.csv")):
        materials[path.stem.replace("_", "-")] = path
    for name, path in materials.items():
        suffix = path.suffix[1:]
        refs[name] = publish_evidence(context, MaterialEvidenceWrite(experiment, name, path.read_bytes(),
            {"json": "application/json", "csv": "text/csv", "py": "text/x-python"}[suffix], suffix))
    facts = tuple(replace(value, fact_id=f"previous-{value.fact_id}") for value in previous.facts)
    entries = []
    for entry in previous.payload.components:
        tests = tuple(replace(test, fact_ids=tuple(f"previous-{name}" for name in test.fact_ids)) for test in entry.tests)
        updated = replace(entry, tests=tests)
        if entry.component_id in ("pullback-turn", "breakout-volume"):
            explanation = ("相同1601成熟队列中，附加确认的四期限合并增量均负；父条件存在阶段性机会及亏损，确认失败不等于父机会不存在。")
            status = ComponentTestStatus.INEFFECTIVE if entry.component_id == "pullback-turn" else ComponentTestStatus.REDUNDANT
            test = ComponentTestResult(f"{entry.component_id}-matched-attribution", experiment.experiment_id, refs["design"], status,
                explanation, (refs["attribution-result"], refs["summary"], refs["audit"]), ("attribution-primary-comparisons",))
            updated = replace(updated, judgment=explanation, tests=(*tests, test))
        elif entry.component_id == "upper-limit-close-awareness":
            test = ComponentTestResult("upper-limit-opportunity-context", experiment.experiment_id, refs["design"], ComponentTestStatus.SUPPORTED,
                "成交风险提示保留；未成交后的价格路径偏强，但这不是持仓收益或追价依据，必须同时披露真实未成交0收益。",
                (refs["summary"], refs["paths"], refs["audit"]))
            updated = replace(updated, tests=(*tests, test))
        entries.append(updated)
    test = ComponentTestResult("profitable-weakening-checkpoints", experiment.experiment_id, refs["design"], ComponentTestStatus.INEFFECTIVE,
        "四期限两个检查点的合并增量比较均为负；已观察回吐空间不能证明该条件可事前识别退出。仅否定本次条件的稳定净收益改善，未评价账户回撤取舍。",
        (refs["attribution-result"], refs["exit-annual"], refs["decisions"], refs["audit"]),
        ("attribution-primary-comparisons", "attribution-exit-comparisons"))
    entries.append(ComponentEntry("profitable-weakening-exit", ExperimentDefinitionRef(refs["attribution"], "src/attribution.py::horizon_study"),
        "持有期间浮盈后单日走弱的提前退出信息", "下一可执行开盘净收益减原固定退出净收益，原股数、双侧0.1%费用",
        "入场日收盘及固定持有中点收盘独立检查；原持有3/5/10/20日",
        "同检查点已有扣费浮盈但当日未走弱；比较绝对提前退出差额及组间差额",
        "条件只用已完成D日价格与已知持仓，D+1或之后最早TXE可退出时执行；无未来特征",
        "HFQ_RESEARCH归一化价格，按实际日涨跌停与原始价位转换约束，固定实际股数",
        "已见S014开发池共同成熟队列；2023至2026决策年主比较；独立重叠尝试，非完整退出策略或账户",
        "本次条件未形成稳定净收益改善，强上涨阶段存在明显过早退出代价；收益持续性与行情失效仍需研究。", (test,)))
    panel = ComponentPanel(tuple(entries),
        "本轮数据归因完成：普遍入场过晚解释未获支持；买后收益集中于强行情阶段；有盈利回吐但朴素提前退出未获支持。保留2项基础辅助用途，新增收益组件0。主要回传阶段二的行情持续性/持有决策信息研究，阶段三未批准。")
    facts += tuple(FactValue(name, value, unit, FactStatus.AVAILABLE, (refs["provenance"], refs["audit"])) for name, value, unit in (
        ("attribution-common-signals", 1601, "signals"), ("attribution-filled-per-horizon", 1569, "attempts"),
        ("attribution-primary-comparisons", 16, "nominal comparisons"), ("attribution-exit-comparisons", 8, "comparisons"),
        ("attribution-history-comparisons", 78, "nominal comparisons including repeats"),
        ("attribution-model-fits", 0, "new fits"), ("attribution-source-calls", 0, "calls"), ("attribution-accounts", 0, "accounts")))
    evidence = tuple(dict.fromkeys((*previous.evidence, *refs.values())))
    report = (EXPERIMENT / "protocols/report.md").read_text(encoding="utf-8")
    receipt = assemble_delivery(repository, DeliveryDefinition(context.batch, DeliveryStage.COMPONENTS, 3, (mandate_ref, previous_ref)),
        DeliveryContent(panel, DeliveryStatus.COMPLETE, facts=facts, explanations=(), report=report, evidence=evidence))
    validation = validate_delivery(repository, receipt.reference)
    if validation.status is not ValidationStatus.PASS:
        raise RuntimeError(validation.issues)
    public = ROOT / "research/S014/deliveries/COMPONENTS/3/report.md"
    copied = EXPERIMENT / "others/report.md"
    copied.write_bytes(public.read_bytes())
    verification = {"formal_report": public.relative_to(ROOT).as_posix(), "experiment_report": copied.relative_to(ROOT).as_posix(),
        "bytes": public.stat().st_size, "sha256": sha256(public.read_bytes()).hexdigest(), "status": "PASS"}
    assert public.read_bytes() == copied.read_bytes()
    (EXPERIMENT / "protocols/report_copy_verification.json").write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
    result = {"experiment": experiment.to_dict(), "delivery": receipt.reference.to_dict(), "status": "COMPLETE",
        "validation": validation.to_dict(), "evidence": {key: ref.to_dict() for key, ref in refs.items()},
        "inherited_evidence": [ref.to_dict() for ref in previous.evidence], "report_copy": verification,
        "approved_attribution_complete": True, "phase_two_reopened": True, "strategy_accounts": 0,
        "supported_context_components": 2, "new_supported_return_components": 0,
        "next_recommendation": "阶段二：行情持续性/失效与持有决策信息，先区分暂时回落和行情结束；不是直接增加通用止盈或推进阶段三"}
    (EXPERIMENT / "others/result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    intent = json.loads((ROOT / "research/registrations/S014/family.json").read_text(encoding="utf-8"))["research_intent"]
    intent.update(stage="阶段二：数据归因完成，主问题转向行情持续性与持有决策信息", components=receipt.reference.to_dict(),
        pending=["审阅COMPONENTS/3归因结果与阶段二后续方向；阶段三未获批准"],
        supported_components=2, supported_return_entry_components=0, strategy_accounts=0, conclusion=panel.conclusion)
    intent["diagnostic_feedback"].update(attribution_delivery=receipt.reference.to_dict(),
        result="普遍入场过晚未获支持；买后强行情收益、未成交选择性及回吐已量化；朴素浮盈走弱退出未获稳定改善。",
        judgment_update="优先识别持有中的行情持续性与失效，现有单日走弱/20日涨跌状态不足以区分；新增信息需求尚未建立。",
        routing_after_result="阶段二：持有决策信息与相应标签；不立即进入阶段三或扩展数据。")
    update_research_intent(repository, context.batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
        reason="完成获批数据归因并回收诊断结论，保留支持与反证，阶段二主问题转向行情持续性与持有决策信息")
    print(json.dumps({"delivery": receipt.reference.to_dict(), "validation": validation.to_dict(), "checks": len(audit["checks"]),
                      "common_signals": computation["common_signals"], "new_accounts": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
