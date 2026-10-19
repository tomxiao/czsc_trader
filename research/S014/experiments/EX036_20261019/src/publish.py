"""Publish the fixed financial tests without changing historical eligibility."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, assemble_delivery, create_research_context,
    publish_evidence, update_research_intent, validate_delivery,
)
from czsc_trader.research_tools import (
    ComponentEntry, ComponentPanel, ComponentTestResult, ComponentTestStatus,
    DeliveryContent, DeliveryDefinition, DeliveryReference, DeliveryStage, DeliveryStatus,
    EvidenceRef, ExperimentDefinitionRef, ExperimentRef, FactStatus, FactValue,
    MaterialEvidenceWrite, ResearchBatchRef, ValidationStatus,
)

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    assert not (EX / "others/result.json").exists()
    review = read(EX / "others/independent_review.json")
    assert review["status"] == "PASS"
    for path, expected in review["source_hashes"].items():
        assert sha256((ROOT / path).read_bytes()).hexdigest() == expected, path
    report_review = read(EX / "others/report_review.json")
    assert report_review["status"] == "PASS"
    for name in ("report", "judgment"):
        path = EX / ("protocols/report.md" if name == "report" else "others/judgment.json")
        assert sha256(path.read_bytes()).hexdigest() == report_review[name + "_sha256"]
    judgment = read(EX / "others/judgment.json")
    stats = read(EX / "others/statistics.json")
    assert stats["events"] == 25 and len(stats["dependency_blocks"]) == 21
    assert stats["models"]["actual_successful_fits"] == 70
    family = ROOT / "research/registrations/S014/family.json"
    intent = read(family)["research_intent"]
    allowed = {"stage", "pending", "conclusion", "components", "component_definitions", "financial_fixed_tests"}
    protected = {k: deepcopy(v) for k, v in intent.items() if k not in allowed}
    assert intent["strategy_accounts"] == 66 and intent["all_targets_pass_count"] == 0
    repo = RepositoryContext.discover(ROOT)
    ctx = create_research_context(repo, ResearchBatchRef("S014"))
    experiment = ExperimentRef("S014", EX.name)
    prior = DeliveryReference.from_dict(intent["components"])
    mandate = DeliveryReference.from_dict(intent["mandate"])
    assert prior.revision == 18 and prior.stage is DeliveryStage.COMPONENTS
    for reference in (prior, mandate):
        assert validate_delivery(repo, reference).status is ValidationStatus.PASS
    old = DeliveryContent.from_dict(read(ROOT / "research/S014/assets/deliveries/COMPONENTS/18/delivery.json")["content"])
    assert isinstance(old.payload, ComponentPanel) and len(old.payload.components) == 26
    refs = {}
    for path, payload in read(EX / "protocols/published_design.json").items():
        ref = EvidenceRef.from_dict(payload)
        assert ref.resolve(ROOT).read_bytes() == (ROOT / path).read_bytes()
        refs[path] = ref
    media = {".py": "text/x-python", ".csv": "text/csv", ".json": "application/json", ".md": "text/markdown"}
    for path in sorted(EX.rglob("*")):
        if not path.is_file() or path.suffix not in media or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if relative in refs:
            continue
        ref = publish_evidence(ctx, MaterialEvidenceWrite(
            experiment, "ex036-" + path.relative_to(EX).as_posix().replace("/", "-").replace(".", "-"),
            path.read_bytes(), media[path.suffix], path.suffix[1:],
        ))
        assert ref.resolve(ROOT).read_bytes() == path.read_bytes()
        refs[relative] = ref
    # The observed earlier guidance is not a new F3 feature; retain its exact source.
    guidance = ROOT / "research/S014/materials/20261018_financial_feasibility/responses/call_05.json"
    guidance_ref = publish_evidence(ctx, MaterialEvidenceWrite(
        experiment, "ex036-existing-guidance-observations-unverified", guidance.read_bytes(), "application/json", "json"
    ))
    refs[guidance.relative_to(ROOT).as_posix()] = guidance_ref
    prefix = EX.relative_to(ROOT).as_posix() + "/"
    def get(name):
        return refs[prefix + name]
    supporting = tuple(get(k) for k in (
        "others/statistics.json", "others/event_panel.csv", "others/independent_review.json", "others/judgment.json"
    ))
    design = get("protocols/design.json")
    definition = ExperimentDefinitionRef(get("src/financial_features.py"), "build_financial_features")
    tests1 = (
        ComponentTestResult("F1_RETURN", EX.name, design, ComponentTestStatus.INSUFFICIENT_DATA,
                            "行业超额差+3.165个百分点，区间[-4.544,+10.706]，小样本不足确认稳定收益信息。", supporting),
        ComponentTestResult("F1_VS_PARENT", EX.name, design, ComponentTestStatus.REDUNDANT,
                            "8个F1正向中7个与利润对照重合，选择均值差-0.061个百分点；本固定表达未见增量，不证明严格信息等价。", supporting),
        ComponentTestResult("F1_FORWARD", EX.name, design, ComponentTestStatus.INEFFECTIVE,
                            "13共同前推事件中MAE/RMSE比量价基线增加0.041/0.398个百分点。", supporting),
    )
    tests2 = (
        ComponentTestResult("F2_RISK_WITHIN_F1", EX.name, design, ComponentTestStatus.INEFFECTIVE,
                            "主用途4对4的最差价格差-1.345个百分点，观察方向相反且区间宽，不支持此固定风险用途。", supporting),
        ComponentTestResult("F2_RISK_ALL", EX.name, design, ComponentTestStatus.INSUFFICIENT_DATA,
                            "全事件差+2.071个百分点，区间跨零，删极端事件或2026后明显改变，证据不稳定。", supporting),
        ComponentTestResult("F2_FORWARD", EX.name, design, ComponentTestStatus.INEFFECTIVE,
                            "13共同前推事件中MAE/RMSE比量价基线增加0.180/0.171个百分点。", supporting),
    )
    common = {"horizon": "预先固定20个上交所交易日，不扫描期限",
              "availability": "公开原文支持日与公告日最晚者后第一个交易日15:00；执行再下一交易日；供应商历史到达未知",
              "price_basis": "HFQ价格标签及原始价限价/整手/费用执行标签；非连续账户",
              "applicability": "600722.SH已见开发池25披露事件、21依赖块；无封存验证"}
    additions = (
        ComponentEntry("financial-operating-improvement-f1", definition, "研究收益信息，未获支持",
                       "20日行业超额收益", control="归母利润改善及个股/行业过去20日量价基线",
                       judgment=judgment["F1"], tests=tests1, **common),
        ComponentEntry("financial-cash-support-f2", definition, "研究F1成立时的风险过滤，未获支持",
                       "20日全窗口最差价格跌幅", control="F1内F2否/全事件F2否及量价基线",
                       judgment=judgment["F2_primary"], tests=tests2, **common),
    )
    facts = old.facts + tuple(FactValue("ex036-" + key, value, unit, FactStatus.AVAILABLE, supporting)
                             for key, value, unit in (
                                 ("events", 25, "events"), ("reports", 27, "reports"),
                                 ("dependency-blocks", 21, "blocks"), ("successful-fits", 70, "fits"),
                                 ("new-calls", 0, "calls"), ("new-accounts", 0, "accounts"),
                                 ("new-supported-components", 0, "components"), ("new-candidates", 0, "candidates"),
                             ))
    receipt = assemble_delivery(repo, DeliveryDefinition(ctx.batch, DeliveryStage.COMPONENTS, 19, (mandate, prior)),
                                DeliveryContent(ComponentPanel(old.payload.components + additions, judgment["conclusion"]),
                                                DeliveryStatus.COMPLETE, facts=facts, explanations=(), incomplete_items=(),
                                                report=(EX / "protocols/report.md").read_text(encoding="utf-8"),
                                                evidence=tuple(dict.fromkeys((*old.evidence, *refs.values())))))
    validation = validate_delivery(repo, receipt.reference)
    assert validation.status is ValidationStatus.PASS, validation
    formal = ROOT / "research/S014/deliveries/COMPONENTS/19/report.md"
    report = formal.read_bytes()
    assert report == (EX / "protocols/report.md").read_bytes()
    with (EX / "others/report.md").open("xb") as stream:
        stream.write(report)
    copy = {"status": "PASS", "byte_identical": True, "sha256": sha256(report).hexdigest(), "bytes": len(report),
            "formal": formal.relative_to(ROOT).as_posix(), "copy": (EX / "others/report.md").relative_to(ROOT).as_posix()}
    write(EX / "protocols/report_copy_verification.json", copy)
    intent = read(family)["research_intent"]
    assert all(intent.get(k) == v for k, v in protected.items())
    intent.update(stage="阶段二财务固定双机制检验完成：本轮无新增获支持组件，等待下一研究问题决定",
                  components=receipt.reference.to_dict(), component_definitions=28,
                  conclusion=judgment["conclusion"], pending=[judgment["next_step"]])
    intent["financial_fixed_tests"] = {
        "status": judgment["status"], "authorization": "用户继续；承接先前固定F1/F2提案",
        "experiment": experiment.to_dict(), "delivery": receipt.reference.to_dict(),
        "judgment": get("others/judgment.json").to_dict(), "statistics": get("others/statistics.json").to_dict(),
        "actual_budget": judgment["actual_budget"], "new_supported_components": 0,
        "new_qualified_candidates": 0, "phase_three_recommended": False,
        "future_execution_authorized": False, "next_step": judgment["next_step"],
        "historical_phase_flags": {k: protected.get(k) for k in ("phase_two_complete", "phase_three_ready", "phase_three_approved")},
        "phase_flag_scope": "保留早前研究轮次的全局阶段标记；不表示本轮财务机制支持或新的阶段三授权，当前财务结论以本对象为准",
        "historical_eligibility_changed": False,
    }
    update_research_intent(repo, ctx.batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
                          reason="完成获批固定F1/F2阶段二研究及负面证据交付；新增2定义但0支持、0账户、0候选；历史资格、经济目标与预算保持")
    assert all(read(family)["research_intent"].get(k) == v for k, v in protected.items())
    write(EX / "others/result.json", {
        "status": "COMPLETE", "experiment": experiment.to_dict(), "delivery": receipt.reference.to_dict(),
        "validation": validation.to_dict(), "report_copy": copy,
        "evidence": {k: v.to_dict() for k, v in refs.items()},
        "actual_budget": judgment["actual_budget"], "conclusion": judgment["conclusion"],
        "new_supported_components": 0, "component_definitions": 28, "historical_accounts": 66,
        "historical_all_targets_pass_count": 0, "historical_eligibility_changed": False,
        "phase_three_recommended": False, "future_execution_authorized": False, "next_step": judgment["next_step"],
    })
    print(json.dumps({"delivery": receipt.reference.to_dict(), "validation": validation.to_dict(),
                      "evidence": len(refs), "components": 28, "new_supported": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
