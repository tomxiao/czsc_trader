"""Local evidence and COMPONENTS delivery for the approved E6 method test."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, assemble_delivery,
    create_research_context, publish_evidence, update_research_intent, validate_delivery,
)
from czsc_trader.research_tools import (
    ComponentPanel, DeliveryContent, DeliveryDefinition, DeliveryReference,
    DeliveryStage, DeliveryStatus, EvidenceRef, ExperimentRef, FactStatus,
    FactValue, MaterialEvidenceWrite, ResearchBatchRef, ValidationStatus,
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
    a = read(EX / "others/summary.json")
    audit = read(EX / "others/independent_audit.json")
    review = read(EX / "others/report_review.json")
    judgment = read(EX / "others/judgment.json")
    design = read(EX / "protocols/design.json")
    assert a["status"] == audit["status"] == review["status"] == "PASS"
    assert audit["verified_nodes"] == a["counts"]["success"] == 146
    assert a["counts"]["failed"] == 0 and a["all"]["opposite_sign_n"] == 25
    assert a["actual_budget"] == {
        "node_groups": 146, "primary_action_labels": 146,
        "attribution_differences": 292, "terminal_values": 438,
        "new_upstream_calls": 0, "model_fits": 0, "new_complete_accounts": 0,
        "new_matching_calls": 0, "alternate_endpoints": 0,
    }
    assert design["execution_authorized"] and design["current_authorization"] == "批准执行"
    for path, expected in audit["source_hashes"].items():
        assert digest(ROOT / path) == expected, path
    assert digest(EX / "src/audit.py") == audit["audit_source_sha256"]
    assert digest(EX / "src/analyze.py") == a["source_sha256"]
    assert digest(EX / "protocols/report.md") == review["report_sha256"]
    assert digest(EX / "others/judgment.json") == review["judgment_sha256"]
    locked = EvidenceRef.from_dict(read(EX / "protocols/published_design.json"))
    assert locked.resolve(ROOT).read_bytes() == (EX / "protocols/design.json").read_bytes()
    family = ROOT / "research/registrations/S014/family.json"
    intent = read(family)["research_intent"]
    protected = {k: deepcopy(v) for k,v in intent.items()
                 if k not in {"stage", "pending", "conclusion", "components", "action_value_test"}}
    assert "action_value_test" not in intent
    assert intent["strategy_accounts"] == 66 and intent["all_targets_pass_count"] == 0
    assert intent["stage_three_autonomous_budget"]["remaining_unallocated_rounds"] == 0
    repo = RepositoryContext.discover(ROOT)
    ctx = create_research_context(repo, ResearchBatchRef("S014"))
    experiment = ExperimentRef("S014", EX.name)
    previous = DeliveryReference.from_dict(intent["components"])
    assert previous.stage is DeliveryStage.COMPONENTS and previous.revision == 16
    old = DeliveryContent.from_dict(read(ROOT / "research/S014/assets/deliveries/COMPONENTS/16/delivery.json")["content"])
    assert isinstance(old.payload, ComponentPanel) and len(old.payload.components) == 26
    refs = {}
    media = {".py": "text/x-python", ".json": "application/json", ".md": "text/markdown", ".csv": "text/csv"}
    for path in sorted(EX.rglob("*")):
        if not path.is_file() or path.suffix not in media or "__pycache__" in path.parts:
            continue
        name = path.relative_to(EX).as_posix()
        ref = publish_evidence(ctx, MaterialEvidenceWrite(
            experiment, "ex034-"+name.replace("/", "-").replace(".", "-"),
            path.read_bytes(), media[path.suffix], path.suffix[1:],
        ))
        assert ref.resolve(ROOT).read_bytes() == path.read_bytes()
        refs[name] = ref
    supporting = tuple(refs[k] for k in (
        "protocols/design.json", "others/summary.json", "others/independent_audit.json",
        "others/judgment.json", "others/report_review.json",
    ))
    facts = old.facts + tuple(FactValue("ex034-"+key, value, unit, FactStatus.AVAILABLE, supporting)
        for key,value,unit in (
            ("nodes", 146, "nodes"), ("strict-sign-reversals", 25, "nodes"),
            ("reentry-nodes", 76, "nodes"), ("new-calls", 0, "calls"),
            ("new-fits", 0, "fits"), ("new-accounts", 0, "accounts"),
            ("new-primary-labels", 146, "labels"), ("new-supported-components", 0, "components"),
        ))
    print(json.dumps({"phase": "LOCAL_EVIDENCE_SAVED", "files": len(refs)}), flush=True)
    delivery = assemble_delivery(
        repo, DeliveryDefinition(ctx.batch, DeliveryStage.COMPONENTS, 17, (previous,)),
        DeliveryContent(ComponentPanel(old.payload.components, judgment["conclusion"]),
                        DeliveryStatus.COMPLETE, facts=facts, explanations=(), incomplete_items=(),
                        report=(EX / "protocols/report.md").read_text(encoding="utf-8"),
                        evidence=tuple(dict.fromkeys((*old.evidence, *refs.values())))),
    )
    print(json.dumps({"phase": "DELIVERY_ASSEMBLED", "reference": delivery.reference.to_dict()}), flush=True)
    check = validate_delivery(repo, delivery.reference)
    assert check.status is ValidationStatus.PASS, check
    formal = ROOT / "research/S014/deliveries/COMPONENTS/17/report.md"
    payload = formal.read_bytes()
    assert payload == (EX / "protocols/report.md").read_bytes()
    with (EX / "others/report.md").open("xb") as stream:
        stream.write(payload)
    write(EX / "protocols/report_copy_verification.json", {
        "status": "PASS", "formal": formal.relative_to(ROOT).as_posix(),
        "copy": (EX / "others/report.md").relative_to(ROOT).as_posix(),
        "source": (EX / "protocols/report.md").relative_to(ROOT).as_posix(),
        "bytes": len(payload), "sha256": sha256(payload).hexdigest(), "byte_identical": True,
    })
    intent = read(family)["research_intent"]
    assert all(intent.get(k) == v for k,v in protected.items())
    intent.update(stage="阶段二E6动作价值检验完成：支持测量改进，尚无新预测组件",
                  conclusion=judgment["conclusion"], pending=[judgment["next_step"]],
                  components=delivery.reference.to_dict())
    intent["action_value_test"] = {
        "status": "COMPLETE_METHOD_SUPPORT_NO_NEW_PREDICTOR",
        "authorization": "批准执行", "experiment": experiment.to_dict(),
        "design": refs["protocols/design.json"].to_dict(),
        "result": refs["others/summary.json"].to_dict(),
        "judgment": refs["others/judgment.json"].to_dict(),
        "delivery": delivery.reference.to_dict(), "actual_budget": a["actual_budget"],
        "caps": design["proposed_caps"], "remaining_node_groups": 0,
        "primary_hypothesis": judgment["primary_hypothesis"],
        "new_supported_components": 0, "new_qualified_candidates": 0,
        "future_execution_authorized": False, "pause_authorized": False,
        "fees_execution_annual_targets": "UNCHANGED", "next_step": judgment["next_step"],
    }
    update_research_intent(repo, ctx.batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
                          reason="完成用户批准的146组固定E6三支终值检验；支持局部标签方法改进，未验证新信号，不新增账户或扩大额度，保持历史结果和经济目标")
    assert all(read(family)["research_intent"].get(k) == v for k,v in protected.items())
    write(EX / "others/result.json", {
        "status": "COMPLETE", "experiment": experiment.to_dict(),
        "delivery": delivery.reference.to_dict(), "validation": check.to_dict(),
        "evidence": {k: v.to_dict() for k,v in refs.items()}, "actual_budget": a["actual_budget"],
        "primary_hypothesis": judgment["primary_hypothesis"], "conclusion": judgment["conclusion"],
        "new_supported_components": 0, "historical_components": 26, "historical_accounts": 66,
        "all_targets_pass_count": 0, "next_step": judgment["next_step"],
        "future_execution_authorized": False,
    })
    print(json.dumps({"phase": "COMPLETE", "validation": check.to_dict()}), flush=True)


if __name__ == "__main__":
    main()
