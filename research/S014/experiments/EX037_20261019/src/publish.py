"""Publish the bounded diagnosis and preserve all historical component entries."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, assemble_delivery, create_research_context,
    publish_evidence, update_research_intent, validate_delivery,
)
from czsc_trader.research_tools import (
    ComponentPanel, DeliveryContent, DeliveryDefinition, DeliveryReference, DeliveryStage,
    DeliveryStatus, EvidenceRef, ExperimentRef, FactStatus, FactValue, MaterialEvidenceWrite,
    ResearchBatchRef, ValidationStatus,
)

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    assert not (EX / "others/result.json").exists()
    judgment = read(EX / "others/judgment.json")
    results = read(EX / "others/information_results.json")
    review = read(EX / "others/independent_review.json")
    report_review = read(EX / "others/report_review.json")
    assert review["status"] == report_review["status"] == "PASS"
    for name, folder, suffix in (("report", "protocols", "md"), ("judgment", "others", "json")):
        assert digest(EX / folder / f"{name}.{suffix}") == report_review[name + "_sha256"]
    for path, expected in review["source_hashes"].items():
        assert digest(ROOT / path) == expected, path
    for path, expected in results["source_hashes"].items():
        assert digest(ROOT / path) == expected, path
    assert results["report_class_counts"] == {
        "no_prior_in_scoped_catalogue": 19, "approximate_point_estimate": 5, "unknown": 3}
    assert read(EX / "others/first_news_audit.json")["status"] == "PASS"
    family = ROOT / "research/registrations/S014/family.json"
    before = read(family)
    intent = before["research_intent"]
    allowed = {"stage", "components", "conclusion", "pending", "financial_information_increment_diagnosis"}
    protected = {k: deepcopy(v) for k, v in intent.items() if k not in allowed}
    assert intent["component_definitions"] == 28 and intent["strategy_accounts"] == 66
    assert intent["all_targets_pass_count"] == 0
    prior = DeliveryReference.from_dict(intent["components"])
    assert prior.stage is DeliveryStage.COMPONENTS and prior.revision == 19
    old = DeliveryContent.from_dict(read(ROOT / "research/S014/assets/deliveries/COMPONENTS/19/delivery.json")["content"])
    assert len(old.payload.components) == 28
    repo = RepositoryContext.discover(ROOT)
    ctx = create_research_context(repo, ResearchBatchRef("S014"))
    experiment = ExperimentRef("S014", EX.name)
    refs = {}
    for name in ("published_design", "published_retrieval_amendment", "published_coverage_interpretation"):
        for path, payload in read(EX / f"protocols/{name}.json").items():
            ref = EvidenceRef.from_dict(payload)
            assert ref.resolve(ROOT).read_bytes() == (ROOT / path).read_bytes()
            refs[path] = ref
    media = {".py": "text/x-python", ".json": "application/json", ".csv": "text/csv",
             ".md": "text/markdown", ".pdf": "application/pdf"}
    for path in sorted(EX.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in media or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if relative in refs:
            continue
        ref = publish_evidence(ctx, MaterialEvidenceWrite(
            experiment, "ex037-" + path.relative_to(EX).as_posix().replace("/", "-").replace(".", "-"),
            path.read_bytes(), media[path.suffix.lower()], path.suffix.lower()[1:],
        ))
        assert ref.resolve(ROOT).read_bytes() == path.read_bytes()
        refs[relative] = ref
    prefix = EX.relative_to(ROOT).as_posix() + "/"

    def get(name):
        return refs[prefix + name]

    support = tuple(get(name) for name in (
        "others/information_results.json", "others/guidance_facts.json", "others/catalogue_audit_v3.json",
        "others/independent_review.json", "others/first_news_audit.json", "others/judgment.json"))
    facts = old.facts + tuple(FactValue("ex037-" + key, value, unit, FactStatus.AVAILABLE, support)
                             for key, value, unit in (
                                 ("reports", 27, "reports"), ("events", 25, "events"),
                                 ("prefix-certified-reports", 24, "reports"), ("earlier-guidance-reports", 5, "reports"),
                                 ("no-earlier-in-certified-chain", 19, "reports"), ("source-unknown-reports", 3, "reports"),
                                 ("residual-missing-catalogue-records", 5, "records"),
                                 ("catalogue-calls", 64, "calls"), ("pdf-calls", 6, "calls"),
                                 ("new-vendor-calls", 0, "calls"), ("new-fits", 0, "fits"),
                                 ("first-news-descriptive-labels", 5, "labels"),
                                 ("new-accounts", 0, "accounts"), ("new-supported-components", 0, "components"),
                                 ("new-candidates", 0, "candidates"),
                             ))
    facts += tuple(FactValue("ex037-" + key, None, "return_difference", FactStatus.INSUFFICIENT_DATA, support,
                             "近似单点不构成明确范围，实际没有必要比较组；效果未估计，不能写成0或被证伪。")
                   for key in ("positive-breakout-effect", "negative-breakout-effect"))
    print(json.dumps({"phase": "EVIDENCE_SAVED", "references": len(refs)}), flush=True)
    receipt = assemble_delivery(repo, DeliveryDefinition(ctx.batch, DeliveryStage.COMPONENTS, 20, (prior,)),
                                DeliveryContent(ComponentPanel(old.payload.components, judgment["conclusion"]),
                                                DeliveryStatus.PARTIAL, facts=facts, explanations=(),
                                                incomplete_items=(
                                                    "2026-04-01至04-23官方目录尚缺5条，依赖其的3期较早披露链保持未知。",
                                                    "本轮只有近似点预告，无明确区间比较组，两项主要效果不可估计。",
                                                    "公司公开预告不是全部市场预期；5事件历史描述不能验证独立可交易机制。"),
                                                report=(EX / "protocols/report.md").read_text(encoding="utf-8"),
                                                evidence=tuple(dict.fromkeys((*old.evidence, *refs.values())))))
    print(json.dumps({"phase": "DELIVERY_SAVED", "reference": receipt.reference.to_dict()}), flush=True)
    validation = validate_delivery(repo, receipt.reference)
    assert validation.status is ValidationStatus.PASS, validation
    formal = ROOT / "research/S014/deliveries/COMPONENTS/20/report.md"
    payload = formal.read_bytes()
    assert payload == (EX / "protocols/report.md").read_bytes()
    with (EX / "others/report.md").open("xb") as stream:
        stream.write(payload)
    copy = {"status": "PASS", "byte_identical": True, "sha256": sha256(payload).hexdigest(), "bytes": len(payload),
            "formal": formal.relative_to(ROOT).as_posix(), "copy": (EX / "others/report.md").relative_to(ROOT).as_posix()}
    write(EX / "protocols/report_copy_verification.json", copy)
    current = read(family)
    intent = current["research_intent"]
    assert all(intent.get(k) == v for k, v in protected.items())
    assert current["research_state"] == before["research_state"]
    intent.update(stage="阶段二财务披露增量诊断完成：直接财务入场路线建议停止追加，三期来源未知保留",
                  components=receipt.reference.to_dict(), conclusion=judgment["conclusion"], pending=[judgment["next_step"]])
    intent["financial_information_increment_diagnosis"] = {
        "status": judgment["status"], "authorization": "同意，研究后用人话解释结论",
        "experiment": experiment.to_dict(), "delivery": receipt.reference.to_dict(),
        "judgment": get("others/judgment.json").to_dict(), "results": get("others/information_results.json").to_dict(),
        "catalogue_complete": False, "certified_prefix_reports": 24, "unknown_reports": 3,
        "primary_effects": "UNAVAILABLE_NOT_ZERO_OR_FALSIFIED", "new_supported_components": 0,
        "recommendation": judgment["recommendation"], "actual_budget": judgment["actual_budget"],
        "future_execution_authorized": False, "phase_three_recommended": False,
        "historical_eligibility_changed": False, "batch_pause_or_retirement": "NOT_REQUESTED_OR_CHANGED",
        "historical_phase_flags_scope": "旧轮次全局阶段字段保留；不得当作本轮财务路线支持或新阶段三授权",
        "next_step": judgment["next_step"],
    }
    update_research_intent(repo, ctx.batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
                          reason="完成用户同意的财报相对预告/快报新信息诊断；来源24期可核/3期未知，点预告无主比较组；建议停止当前直接财务入场路线，保留28组件/66账户/0全目标达标及历史资格")
    after = read(family)
    assert all(after["research_intent"].get(k) == v for k, v in protected.items())
    assert after["research_state"] == before["research_state"]
    write(EX / "others/result.json", {
        "status": "COMPLETE_BOUNDED_DIAGNOSIS", "delivery_status": "PARTIAL",
        "experiment": experiment.to_dict(), "delivery": receipt.reference.to_dict(),
        "validation": validation.to_dict(), "report_copy": copy,
        "evidence": {k: v.to_dict() for k, v in refs.items()}, "actual_budget": judgment["actual_budget"],
        "conclusion": judgment["conclusion"], "recommendation": judgment["recommendation"],
        "new_supported_components": 0, "component_definitions": 28, "historical_accounts": 66,
        "historical_all_targets_pass_count": 0, "historical_eligibility_changed": False,
        "phase_three_recommended": False, "future_execution_authorized": False,
        "next_step": judgment["next_step"],
    })
    print(json.dumps({"phase": "COMPLETE", "delivery": receipt.reference.to_dict(),
                      "validation": validation.to_dict(), "references": len(refs)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
