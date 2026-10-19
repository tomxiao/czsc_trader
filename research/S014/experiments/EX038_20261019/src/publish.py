"""Publish the authorized EX038 census after formal reviews pass.

judgment.json requires only nonempty status/conclusion/next_step strings.
Counts are read from the audited census_inventory.json schema, never guessed.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from dataflows import ProviderConfig
from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, assemble_delivery, create_research_context,
    publish_evidence, update_research_intent, validate_delivery,
)
from czsc_trader.research_tools import (
    ComponentPanel, DeliveryContent, DeliveryDefinition, DeliveryReference, DeliveryStage,
    DeliveryStatus, DeliveryValidationScope, EvidenceRef, ExperimentRef, FactStatus,
    FactValue, MaterialEvidenceWrite, ResearchBatchRef, ValidationStatus,
)

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
MEDIA = {".py": "text/x-python", ".json": "application/json", ".md": "text/markdown"}
GENERATED = {"others/result.json", "others/report.md", "protocols/report_copy_verification.json"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def source_snapshot():
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(EX.rglob("*"))
            if p.is_file() and p.suffix.lower() in MEDIA and "__pycache__" not in p.parts
            and p.relative_to(EX).as_posix() not in GENERATED}


def verify_sources(expected):
    require(source_snapshot() == expected, "EX038 source set or bytes changed during publication")


def verify_hash_map(mapping):
    require(isinstance(mapping, dict) and mapping, "Missing audited source hashes")
    for relative, expected in mapping.items():
        path = (ROOT / relative).resolve()
        require(path.is_relative_to(ROOT / "research/S014") or path.is_relative_to(ROOT / ".tmp"),
                "Audited source outside authorized S014/.tmp scope")
        require(digest(path) == expected, f"Audited source hash mismatch: {relative}")


def main():
    require(not any((EX / name).exists() for name in GENERATED), "Publication outputs already exist")
    judgment = read(EX / "others/judgment.json")
    for key in ("status", "conclusion", "next_step"):
        require(isinstance(judgment.get(key), str) and judgment[key].strip(), f"Missing judgment.{key}")
    inventory = read(EX / "others/census_inventory.json")
    independent = read(EX / "others/independent_review.json")
    reviewed = read(EX / "others/report_review.json")
    require(independent["status"] == reviewed["status"] == "PASS", "Formal independent/report review must PASS")
    for name, relative in (("report", "protocols/report.md"), ("judgment", "others/judgment.json")):
        require(digest(EX / relative) == reviewed[name + "_sha256"], f"Reviewed {name} changed")
    verify_hash_map(independent["source_hashes"])
    report = (EX / "protocols/report.md").read_text(encoding="utf-8")
    require(report.encode("utf-8") == (EX / "protocols/report.md").read_bytes(), "Report needs stable UTF-8/LF bytes")
    calls = sorted((EX / "others/calls").glob("*.json"))
    budget = inventory["mcp_budget"]
    frozen = read(EX / "others/frozen_calls.json")
    coverage = read(EX / "others/coverage_checks.json")
    require(len(calls) == budget["recorded_call_files"] == frozen["calls"] == 41,
            "Expected this delivery's 41 frozen MCP invocations")
    require(frozen["status"] == "FROZEN_COLLECTION_STOPPED" and budget["cap"] == frozen["max_calls"] == 48,
            "Collection must be frozen within original invocation cap")
    require(coverage["status"] == "PASS", "Coverage cross-check must PASS")
    verify_hash_map(frozen["source_hashes"])
    require(set(frozen["source_hashes"]) == {p.relative_to(ROOT).as_posix() for p in calls}, "Frozen calls set differs")
    call_summary_hash = sha256(json.dumps([(p.name, digest(p)) for p in calls],
                                         ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()
    require(coverage["snapshot"]["summary_sha256"] == call_summary_hash, "Coverage frozen call hash differs")
    require(not budget["missing_ids_to_highest"] and not budget["duplicate_call_ids"], "Call ids incomplete/duplicated")
    require(sum(inventory["call_status_counts"].values()) == len(calls), "Call status denominator mismatch")
    for row in inventory["calls"]:
        require(digest(ROOT / row["saved_call_path"]) == row["saved_call_sha256"], "Raw call changed")
    interfaces = inventory["interfaces"]
    unknown = sorted(row["endpoint"] for row in interfaces
                     if row["permission_conclusion"] == "UNRESOLVED_NO_PERMISSION_CONCLUSION")
    denied = sorted(row["endpoint"] for row in interfaces
                    if row["permission_conclusion"] == "Explicit denial observed; retain request-level scope")
    nonempty = sorted(row["endpoint"] for row in interfaces if row["nonempty_success_calls"] > 0)
    require(len(interfaces) == inventory["interfaces_total"] == 21 and len(unknown) == 5,
            "This reviewed delivery requires 21 interfaces and five unresolved permissions")
    require(len(set(unknown + denied + nonempty)) == 21 and len(unknown + denied + nonempty) == 21,
            "Interface permission groups must partition protocol interfaces")
    snapshot = source_snapshot()
    family = ROOT / "research/registrations/S014/family.json"
    before = read(family)
    original_intent = deepcopy(before["research_intent"])
    require("option_etf_census" not in original_intent, "Existing census intent must not be overwritten")
    require((original_intent["component_definitions"], original_intent["strategy_accounts"],
             original_intent["all_targets_pass_count"]) == (28, 66, 0), "Historical counts changed")
    prior = DeliveryReference.from_dict(original_intent["components"])
    require(prior.stage is DeliveryStage.COMPONENTS and prior.revision == 20, "Expected predecessor COMPONENTS/20")
    prior_path = ROOT / "research/S014/assets/deliveries/COMPONENTS/20/delivery.json"
    prior_hash = digest(prior_path)
    raw_old = read(prior_path)["content"]
    old = DeliveryContent.from_dict(raw_old)
    require(isinstance(old.payload, ComponentPanel) and len(old.payload.components) == 28, "Expected original 28 components")
    original_components = [item.to_dict() for item in old.payload.components]
    require(canonical(original_components) == canonical(raw_old["payload"]["components"]), "Component roundtrip changed values")
    repo = RepositoryContext.discover(ROOT)
    ctx = create_research_context(repo, ResearchBatchRef("S014"), providers=ProviderConfig(bindings={}))
    experiment = ExperimentRef("S014", EX.name)
    refs = {}
    design_path = EX / "protocols/design.json"
    reference = EvidenceRef.from_dict(read(EX / "protocols/published_design.json"))
    require(reference.resolve(ROOT).read_bytes() == design_path.read_bytes(), "Published design differs")
    refs[design_path.relative_to(ROOT).as_posix()] = reference
    verify_sources(snapshot)
    print(json.dumps({"phase": "EVIDENCE_BEGIN", "references": len(refs)}), flush=True)
    for relative in snapshot:
        if relative in refs:
            continue
        path = ROOT / relative
        reference = publish_evidence(ctx, MaterialEvidenceWrite(
            experiment, "ex038-" + path.relative_to(EX).as_posix().replace("/", "-").replace(".", "-"),
            path.read_bytes(), MEDIA[path.suffix.lower()], path.suffix.lower()[1:]))
        require(reference.resolve(ROOT).read_bytes() == path.read_bytes(), "Published evidence differs")
        refs[relative] = reference
    verify_sources(snapshot)
    print(json.dumps({"phase": "EVIDENCE_SAVED", "references": len(refs)}), flush=True)
    prefix = EX.relative_to(ROOT).as_posix() + "/"

    def get(relative):
        return refs[prefix + relative]

    support = tuple(get(name) for name in ("others/census_inventory.json", "others/judgment.json",
                                         "others/independent_review.json", "others/report_review.json"))
    facts = old.facts + tuple(FactValue("ex038-" + key, value, unit, FactStatus.AVAILABLE, support)
                             for key, value, unit in (
                                 ("mcp-invocations", len(calls), "calls"),
                                 ("interfaces", 21, "interfaces"),
                                 ("nonempty-interfaces", len(nonempty), "interfaces"),
                                 ("provider-denied-interfaces", len(denied), "interfaces"),
                                 ("permission-unresolved-interfaces", len(unknown), "interfaces"),
                                 ("new-labels", 0, "labels"), ("new-fits", 0, "fits"),
                                 ("new-accounts", 0, "accounts"), ("new-candidates", 0, "candidates"),
                                 ("new-supported-components", 0, "components")))
    facts += tuple(FactValue("ex038-" + key, None, "certification", FactStatus.INSUFFICIENT_DATA, support, explanation)
                   for key, explanation in (
                       ("historical-availability", "历史全窗覆盖、字段时点及供应商历史到达尚未认证；锚点不能替代。"),
                       ("predictive-value", "仅普查能力和信息语义，未作预测、收益或新组件有效性检验。")))
    panel = ComponentPanel(old.payload.components, judgment["conclusion"])
    require(canonical([item.to_dict() for item in panel.components]) == canonical(original_components), "Components changed")
    verify_sources(snapshot)
    require(read(family)["research_intent"] == original_intent, "Research intent changed before delivery")
    receipt = assemble_delivery(repo, DeliveryDefinition(ctx.batch, DeliveryStage.COMPONENTS, 21, (prior,)),
                                DeliveryContent(panel, DeliveryStatus.PARTIAL, facts=facts,
                                                explanations=old.explanations,
                                                incomplete_items=old.incomplete_items + (
                                                    "5个接口权限未知：" + ", ".join(unknown) + "；审批阻断不能当供应商拒绝。",
                                                    "历史全窗覆盖、真实发布/到达时点及单位/合约调整链尚未认证。",
                                                    "本轮仅接口普查，未做预测检验，未新增获支持组件、候选或账户。"),
                                                report=report,
                                                evidence=tuple(dict.fromkeys((*old.evidence, *refs.values())))))
    print(json.dumps({"phase": "DELIVERY_SAVED_FULL_VALIDATION_START", "delivery": receipt.reference.to_dict()}), flush=True)
    validation = validate_delivery(repo, receipt.reference, scope=DeliveryValidationScope.FULL)
    require(validation.status is ValidationStatus.PASS, "FULL delivery validation failed")
    print(json.dumps({"phase": "FULL_VALIDATION_PASS", "validation": validation.to_dict()}), flush=True)
    formal_raw = read(ROOT / "research/S014/assets/deliveries/COMPONENTS/21/delivery.json")["content"]
    require(canonical(formal_raw["payload"]["components"]) == canonical(original_components), "Formal components changed")
    require(formal_raw["facts"][:len(raw_old["facts"])] == raw_old["facts"], "Historical facts changed")
    require(all(item in formal_raw["evidence"] for item in raw_old["evidence"]), "Historical evidence lost")
    formal = ROOT / "research/S014/deliveries/COMPONENTS/21/report.md"
    payload = formal.read_bytes()
    require(payload == (EX / "protocols/report.md").read_bytes(), "Formal report bytes differ")
    with (EX / "others/report.md").open("xb") as handle:
        handle.write(payload)
    require((EX / "others/report.md").read_bytes() == payload, "Report copy differs")
    copy = {"status": "PASS", "byte_identical": True, "sha256": sha256(payload).hexdigest(), "bytes": len(payload),
            "formal": formal.relative_to(ROOT).as_posix(), "copy": (EX / "others/report.md").relative_to(ROOT).as_posix()}
    write(EX / "protocols/report_copy_verification.json", copy)
    verify_sources(snapshot)
    current = read(family)
    require(current["research_intent"] == original_intent and current["research_state"] == before["research_state"],
            "Concurrent governance change; stop before intent update")
    intent = deepcopy(original_intent)
    intent["components"] = receipt.reference.to_dict()
    intent["option_etf_census"] = {
        "status": judgment["status"], "experiment": experiment.to_dict(), "delivery": receipt.reference.to_dict(),
        "conclusion": judgment["conclusion"], "next_step": judgment["next_step"],
        "judgment": get("others/judgment.json").to_dict(), "inventory": get("others/census_inventory.json").to_dict(),
        "mcp_invocations": len(calls), "permission_unknown": unknown, "provider_denied": denied,
        "historical_coverage_and_availability_certified": False, "predictive_value_tested": False,
        "new_supported_components": 0, "new_candidates": 0, "new_accounts": 0,
        "historical_eligibility_changed": False, "future_execution_authorized": False,
    }
    update_research_intent(repo, ctx.batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
                          reason="保存已授权期权ETF普查PARTIAL交付；5接口权限未知、历史时点覆盖未认证、无预测检验；保留原28组件/66账户/0达标及全部历史资格和原意图字段")
    after = read(family)
    require(after["research_intent"] == intent, "Stored intent differs from complete copied intent")
    require({k: v for k, v in after["research_intent"].items() if k != "option_etf_census"}
            == {**original_intent, "components": receipt.reference.to_dict()}, "Protected intent keys changed")
    require(after["research_state"] == before["research_state"], "Research state changed")
    require(digest(prior_path) == prior_hash, "Historical COMPONENTS/20 changed")
    verify_sources(snapshot)
    write(EX / "others/result.json", {
        "status": "COMPLETE_BOUNDED_CENSUS", "delivery_status": "PARTIAL",
        "experiment": experiment.to_dict(), "delivery": receipt.reference.to_dict(),
        "validation": validation.to_dict(), "report_copy": copy, "source_hashes": snapshot,
        "evidence": {path: ref.to_dict() for path, ref in refs.items()},
        "component_definitions": 28, "historical_accounts": 66, "historical_all_targets_pass_count": 0,
        "new_supported_components": 0, "new_candidates": 0, "historical_eligibility_changed": False,
        "research_state_unchanged": True, "protected_intent_unchanged": True,
        "conclusion": judgment["conclusion"], "next_step": judgment["next_step"],
    })
    print(json.dumps({"phase": "COMPLETE", "delivery": receipt.reference.to_dict(), "validation": validation.to_dict()}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
