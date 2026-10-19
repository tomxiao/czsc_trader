"""Publish reviewed EX039 fixed E/O/J evidence; never execute source or fits.

Required final review schema follows EX038 with two additional hash bindings:
report_review.independent_review_sha256 and publisher_sha256. Final independent
review must PASS and bind its audited source_hashes. Rawrefs and published_*.json
maps are resolved and reused, including the explicitly authorized ETF repair.
"""

from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import socket

from dataflows import ProviderConfig
from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, assemble_delivery, create_research_context,
    publish_evidence, update_research_intent, validate_delivery,
)
from czsc_trader.research_tools import (
    ComponentPanel, DeliveryContent, DeliveryDefinition, DeliveryReference, DeliveryStage,
    DeliveryStatus, DeliveryValidationScope, EvidenceRef, ExperimentRef, Explanation,
    ExplanationKind, FactStatus, FactValue, MaterialEvidenceWrite, ResearchBatchRef,
    ValidationStatus,
)


ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
MEDIA = {".py": "text/x-python", ".json": "application/json", ".md": "text/markdown",
         ".csv": "text/csv", ".gz": "application/gzip"}
GENERATED = {"others/result.json", "others/report.md", "protocols/report_copy_verification.json"}
INTENT_KEY = "option_etf_fixed_study"


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
    return {path.relative_to(ROOT).as_posix(): digest(path) for path in sorted(EX.rglob("*"))
            if path.is_file() and path.suffix.lower() in MEDIA and "__pycache__" not in path.parts
            and path.relative_to(EX).as_posix() not in GENERATED}


def verify_sources(expected):
    require(source_snapshot() == expected, "EX039 source set or bytes changed during publication")


def verify_hash_map(mapping):
    require(isinstance(mapping, dict) and mapping, "Missing independent source hashes")
    for relative, expected in mapping.items():
        path = (ROOT / relative).resolve()
        require(path.is_relative_to(ROOT / "research/S014") or path.is_relative_to(ROOT / ".tmp"),
                "Audited source outside authorized S014/.tmp scope")
        require(digest(path) == expected, f"Audited source hash mismatch: {relative}")


def existing_refs():
    """Reuse formal material identities; publishing the map itself remains explicit."""
    manifests = [EX / "others/rawrefs.json", *sorted((EX / "protocols").glob("published_*.json")),
                 *sorted((EX / "others").glob("published_*.json"))]
    require(manifests[0].is_file(), "Raw public EvidenceRef manifest is required")
    require((EX / "protocols/published_design.json").is_file(), "Published design lock required")
    require((EX / "protocols/published_etf_repair.json").is_file(), "Published ETF repair lock required")
    refs = {}
    for manifest in manifests:
        mapping = read(manifest)
        mapping = mapping.get("evidence", mapping)
        require(isinstance(mapping, dict) and mapping, "Empty/invalid published evidence map")
        for relative, value in mapping.items():
            path = (ROOT / relative).resolve()
            require(path.is_relative_to(ROOT / "research/S014"), "Published input outside S014")
            ref = EvidenceRef.from_dict(value)
            require(ref.experiment.strategy_id == "S014", "Published input belongs to another batch")
            require(digest(path) == ref.sha256 and digest(ref.resolve(ROOT)) == ref.sha256,
                    f"Published reference/source mismatch: {relative}")
            if relative in refs:
                require(ref.sha256 == refs[relative].sha256 and ref.evidence_id == refs[relative].evidence_id,
                        "Conflicting published source identities")
            else:
                refs[relative] = ref
    return refs


def source_counts():
    receipts = {lane: read(EX / "others" / f"{lane}_source_receipt.json")
                for lane in ("collect", "etf", "etfrepair")}
    count = 0
    seen = set()
    for lane, receipt in receipts.items():
        results = receipt["results"]
        require(len(results) == receipt["http_reservations"] <= receipt["cap"], "HTTP receipt count/cap mismatch")
        require(receipt["automatic_retry"] is False and receipt["redirects"] is False,
                "Unexpected source retry/redirect policy")
        for result in results:
            ident = result["id"]
            require(ident.startswith(lane + "_") and ident not in seen, "Duplicate/wrong lane source reservation")
            seen.add(ident)
            request = EX / "others/raw/requests" / f"{ident}.json"
            saved = EX / "others/raw/results" / f"{ident}.json"
            require(request.is_file() and canonical(read(saved)) == canonical(result), "Raw receipt identity mismatch")
            raw = read(request)
            require(raw["id"] == ident and raw["api_name"] == result["api_name"], "Raw request/result mismatch")
            if "response_sha256" in result:
                require(digest(ROOT / raw["response_path"]) == result["response_sha256"], "Raw response hash changed")
        count += len(results)
    require(receipts["collect"]["cap"] == 1100 and receipts["etf"]["cap"] == 24
            and receipts["etfrepair"]["cap"] == 22, "Fixed source lane caps changed")
    etf_count = receipts["etf"]["http_reservations"] + receipts["etfrepair"]["http_reservations"]
    require(etf_count <= 24 and count <= 1124, "Combined original+repair source budget exceeded")
    requests = {path.stem for path in (EX / "others/raw/requests").glob("*.json")}
    require(requests == seen, "Unaccounted raw source reservation")
    return {"http_reservations": count, "option_event_http": receipts["collect"]["http_reservations"],
            "etf_http_including_repair": etf_count,
            "result_status_counts": dict(Counter(row["status"] for item in receipts.values() for row in item["results"]))}


def check_reviews():
    judgment = read(EX / "others/judgment.json")
    for key in ("status", "conclusion", "next_step"):
        require(isinstance(judgment.get(key), str) and judgment[key].strip(), f"Missing judgment.{key}")
    independent = read(EX / "others/independent_review.json")
    reviewed = read(EX / "others/report_review.json")
    require(independent["status"] == reviewed["status"] == "PASS", "Final independent/report reviews must PASS")
    for field, relative in (("report_sha256", "protocols/report.md"), ("judgment_sha256", "others/judgment.json"),
                            ("publisher_sha256", "src/publish.py"), ("independent_review_sha256", "others/independent_review.json")):
        require(reviewed[field] == digest(EX / relative), f"Final reviewed bytes changed: {relative}")
    verify_hash_map(independent["source_hashes"])
    required = ["protocols/design.json", "src/analyze_fixed.py", "src/build_option_features.py",
                "src/prepare_etf.py", "src/resume_etf.py", "others/fixed_analysis/analysis.json",
                "others/fixed_analysis/predictions.csv", "others/model_inputs.csv", "others/calendar.csv", "others/labels.csv"]
    slot_paths = sorted((EX / "others/fixed_analysis/fit_slots").glob("*.json"))
    require(len(slot_paths) == 28, "Final review requires all 28 counted slot receipts")
    required.extend(path.relative_to(EX).as_posix() for path in slot_paths)
    for relative in required:
        require((EX / relative).relative_to(ROOT).as_posix() in independent["source_hashes"],
                f"Final independent review did not bind {relative}")
    return judgment, independent


def derived_facts(old, analysis, counts, support):
    values = [("http-reservations", counts["http_reservations"], "calls"),
              ("option-event-http", counts["option_event_http"], "calls"),
              ("etf-http-with-repair", counts["etf_http_including_repair"], "calls"),
              ("counted-model-slots", analysis["reserved_slots"], "slots"),
              ("completed-model-fits", analysis["completed_fits"], "fits"),
              ("technical-fit-failures", analysis["technical_failures"], "fits"),
              ("new-return-labels", 0, "labels"), ("new-accounts", 0, "accounts"),
              ("new-candidates", 0, "candidates"), ("new-component-definitions", 0, "components")]
    facts = old.facts + tuple(FactValue("ex039-" + key, value, unit, FactStatus.AVAILABLE, support)
                              for key, value, unit in values)
    keys = ("n", "mse_improvement", "allocation_difference_per_evaluable_A", "reduced_losses_removed",
            "foregone_positive_removed", "added_positive", "added_losses", "base_keep_rate", "new_keep_rate")
    for family, comparison in (("ETF", "E1_minus_E0"), ("OPTION", "O1_minus_O0"), ("JOINT", "J1_minus_J0")):
        data = analysis["families"][family].get("comparisons", {}).get("all_evaluation", {}).get(comparison, {})
        for key in keys:
            value = data.get(key)
            status = FactStatus.AVAILABLE if value is not None else FactStatus.INSUFFICIENT_DATA
            reason = None if value is not None else "该固定族/同样本主比较未取得可估计结果；不以零替代。"
            unit = "opportunities" if key == "n" else "squared_return" if key == "mse_improvement" else "ratio" if "keep_rate" in key else "decimal_attempt_return"
            facts += (FactValue(f"ex039-{family.lower()}-{key.replace('_', '-')}", value, unit, status, support, reason),)
    facts += (FactValue("ex039-strict-historical-pit", None, "certification", FactStatus.INSUFFICIENT_DATA,
                        support, "历史真实首次入库/修订与完整份额或期权调整版本链未认证，当前检验为有明确滞后约定的条件性代理研究。"),)
    return facts


def main():
    def blocked(*args, **kwargs):
        raise RuntimeError("Publisher forbids external source calls")

    socket.socket.connect = blocked
    socket.create_connection = blocked
    require(not any((EX / name).exists() for name in GENERATED), "Publication outputs already exist")
    judgment, _ = check_reviews()
    analysis = read(EX / "others/fixed_analysis/analysis.json")
    require(analysis["reserved_slots"] == 28 and len(analysis["fit_statuses"]) == 28,
            "All 28 fixed slots must have an explicit final status")
    statuses = Counter(analysis["fit_statuses"].values())
    require(statuses["SUCCESS"] == analysis["completed_fits"] and statuses["TECHNICAL_FAILURE"] == analysis["technical_failures"],
            "Analysis fit counts disagree")
    slot_records = [read(path) for path in sorted((EX / "others/fixed_analysis/fit_slots").glob("*.json"))]
    require({record["slot"] for record in slot_records} == set(range(1, 29)), "Counted slot sequence differs")
    require({record["key"]: record["status"] for record in slot_records} == analysis["fit_statuses"],
            "Analysis status map differs from immutable per-slot receipts")
    require(analysis["continuous_accounts"] == 0 and analysis["independent_validation"] is False,
            "Unexpected account or independent-validation claim")
    counts = source_counts()
    refs = existing_refs()
    report_path = EX / "protocols/report.md"
    report = report_path.read_text(encoding="utf-8")
    require(report.encode("utf-8") == report_path.read_bytes(), "Report needs stable UTF-8/LF bytes")
    snapshot = source_snapshot()
    family_path = ROOT / "research/registrations/S014/family.json"
    before = read(family_path)
    intent_before = deepcopy(before["research_intent"])
    require(INTENT_KEY not in intent_before, "Fixed-study intent already exists")
    require((intent_before["component_definitions"], intent_before["strategy_accounts"],
             intent_before["all_targets_pass_count"]) == (28, 66, 0), "Historical research counts changed")
    prior = DeliveryReference.from_dict(intent_before["components"])
    require(prior.stage is DeliveryStage.COMPONENTS and prior.revision == 21, "Expected exact COMPONENTS/21 predecessor")
    old_result = read(ROOT / "research/S014/experiments/EX038_20261019/others/result.json")
    require(prior.to_dict() == old_result["delivery"], "COMPONENTS/21 reference differs from EX038 formal result")
    prior_path = ROOT / "research/S014/assets/deliveries/COMPONENTS/21/delivery.json"
    prior_hash = digest(prior_path)
    raw_old = read(prior_path)["content"]
    old = DeliveryContent.from_dict(raw_old)
    require(isinstance(old.payload, ComponentPanel) and len(old.payload.components) == 28, "Expected inherited 28 component definitions")
    components = [item.to_dict() for item in old.payload.components]
    require(canonical(components) == canonical(raw_old["payload"]["components"]), "Historical component roundtrip changed")
    repo = RepositoryContext.discover(ROOT)
    ctx = create_research_context(repo, ResearchBatchRef("S014"), providers=ProviderConfig(bindings={}))
    experiment = ExperimentRef("S014", EX.name)
    by_content = {(ref.sha256, ref.evidence_id.rsplit(".", 1)[1]): ref for ref in refs.values()}
    verify_sources(snapshot)
    print(json.dumps({"phase": "EVIDENCE_BEGIN", "reuse_refs": len(refs), "source_files": len(snapshot)}), flush=True)
    for relative, expected_hash in snapshot.items():
        if relative in refs:
            continue
        path = ROOT / relative
        key = (expected_hash, path.suffix.lower()[1:])
        if key in by_content:
            ref = by_content[key]
        else:
            ref = publish_evidence(ctx, MaterialEvidenceWrite(
                experiment, "ex039-" + path.relative_to(EX).as_posix().replace("/", "-").replace(".", "-"),
                path.read_bytes(), MEDIA[path.suffix.lower()], path.suffix.lower()[1:]))
            by_content[key] = ref
        require(ref.resolve(ROOT).read_bytes() == path.read_bytes(), "Published material differs from source")
        refs[relative] = ref
    verify_sources(snapshot)
    prefix = EX.relative_to(ROOT).as_posix() + "/"

    def get(relative):
        return refs[prefix + relative]

    support = tuple(get(relative) for relative in ("protocols/design.json", "others/fixed_analysis/analysis.json",
                    "others/judgment.json", "others/independent_review.json", "others/report_review.json"))
    facts = derived_facts(old, analysis, counts, support)
    status = DeliveryStatus(judgment.get("delivery_status", "PARTIAL"))
    require(status in (DeliveryStatus.PARTIAL, DeliveryStatus.BLOCKED), "Historical incomplete items require PARTIAL/BLOCKED delivery")
    incomplete = old.incomplete_items + tuple(judgment.get("incomplete_items", [
        "本轮条件性风险信息研究不认证历史真实入库/修订及完整调整链；不等于可直接上线使用。",
        "本轮未建立新完整策略账户，未证明原年度经济目标达成，未改变历史候选资格。",
    ]))
    panel = ComponentPanel(old.payload.components, judgment["conclusion"])
    require(read(family_path)["research_intent"] == intent_before, "Concurrent intent change before delivery")
    receipt = assemble_delivery(repo, DeliveryDefinition(ctx.batch, DeliveryStage.COMPONENTS, 22, (prior,)),
        DeliveryContent(panel, status, facts=facts,
            explanations=old.explanations + (Explanation(ExplanationKind.RESEARCH_JUDGMENT,
                judgment["conclusion"], supporting=support),), incomplete_items=incomplete,
            report=report, evidence=tuple(dict.fromkeys((*old.evidence, *refs.values())))))
    validation = validate_delivery(repo, receipt.reference, scope=DeliveryValidationScope.FULL)
    require(validation.status is ValidationStatus.PASS, "FULL delivery validation failed")
    saved = read(ROOT / "research/S014/assets/deliveries/COMPONENTS/22/delivery.json")["content"]
    require(canonical(saved["payload"]["components"]) == canonical(components), "Formal inherited definitions changed")
    require(saved["facts"][:len(raw_old["facts"])] == raw_old["facts"], "Historical facts changed")
    require(all(item in saved["evidence"] for item in raw_old["evidence"]), "Historical evidence lost")
    formal = ROOT / "research/S014/deliveries/COMPONENTS/22/report.md"
    payload = formal.read_bytes()
    require(payload == report_path.read_bytes(), "Formal report differs from reviewed bytes")
    with (EX / "others/report.md").open("xb") as handle:
        handle.write(payload)
    require((EX / "others/report.md").read_bytes() == payload, "Formal report copy differs")
    copy = {"status": "PASS", "byte_identical": True, "sha256": sha256(payload).hexdigest(), "bytes": len(payload),
            "formal": formal.relative_to(ROOT).as_posix(), "copy": (EX / "others/report.md").relative_to(ROOT).as_posix()}
    write(EX / "protocols/report_copy_verification.json", copy)
    verify_sources(snapshot)
    current = read(family_path)
    require(current["research_intent"] == intent_before and current["research_state"] == before["research_state"],
            "Concurrent governance change; stop before intent update")
    intent = deepcopy(intent_before)
    intent["components"] = receipt.reference.to_dict()
    intent[INTENT_KEY] = {
        "status": judgment["status"], "experiment": experiment.to_dict(), "delivery": receipt.reference.to_dict(),
        "conclusion": judgment["conclusion"], "next_step": judgment["next_step"],
        "judgment": get("others/judgment.json").to_dict(), "analysis": get("others/fixed_analysis/analysis.json").to_dict(),
        "historical_publication_and_adjustment_certified": False, "predictive_value_tested": True,
        "actual_budget": {**counts, "counted_fit_slots": 28, "successful_fits": analysis["completed_fits"],
                          "technical_fit_failures": analysis["technical_failures"]},
        "new_component_definitions": 0, "new_candidates": 0, "new_accounts": 0,
        "historical_eligibility_changed": False, "future_execution_authorized": False,
    }
    update_research_intent(repo, ctx.batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
        reason="保存已授权ETF份额与同K期权持仓固定E/O/J检验及原件保留的技术修复；保留28组件定义/66账户/0全目标达标、全部历史事实和资格；不新增完整账户或阶段推进")
    after = read(family_path)
    require(after["research_intent"] == intent, "Saved intent differs")
    require({key: value for key, value in intent.items() if key != INTENT_KEY}
            == {**intent_before, "components": receipt.reference.to_dict()}, "Protected intent keys changed")
    require(after["research_state"] == before["research_state"] and digest(prior_path) == prior_hash,
            "Historical delivery/state changed")
    verify_sources(snapshot)
    write(EX / "others/result.json", {"status": "COMPLETE_FIXED_STUDY_DELIVERY", "delivery_status": status.value,
        "experiment": experiment.to_dict(), "delivery": receipt.reference.to_dict(), "validation": validation.to_dict(),
        "report_copy": copy, "source_hashes": snapshot, "evidence": {path: ref.to_dict() for path, ref in refs.items()},
        "actual_budget": {**counts, "counted_fit_slots": 28, "successful_fits": analysis["completed_fits"]},
        "component_definitions": 28, "historical_accounts": 66, "historical_all_targets_pass_count": 0,
        "new_component_definitions": 0, "new_accounts": 0, "new_candidates": 0,
        "historical_eligibility_changed": False, "research_state_unchanged": True, "protected_intent_unchanged": True,
        "conclusion": judgment["conclusion"], "next_step": judgment["next_step"]})
    print(json.dumps({"phase": "COMPLETE", "delivery": receipt.reference.to_dict(), "validation": validation.to_dict()}), flush=True)


if __name__ == "__main__":
    main()
