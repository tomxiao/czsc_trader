"""Publish EX033's fixed action test without promoting a component or account."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.application import (
    RepositoryContext,
    ResearchIntentUpdate,
    assemble_delivery,
    create_research_context,
    publish_evidence,
    update_research_intent,
    validate_delivery,
)
from czsc_trader.research_tools import (
    ComponentPanel,
    DeliveryContent,
    DeliveryDefinition,
    DeliveryReference,
    DeliveryStage,
    DeliveryStatus,
    EvidenceRef,
    ExperimentRef,
    FactStatus,
    FactValue,
    MaterialEvidenceWrite,
    ResearchBatchRef,
    ValidationStatus,
)

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def verify_inputs():
    """Fail before any publication if the reviewed identities have changed."""
    a = read(EX / "others/analysis.json")
    inputs = read(EX / "others/inputs.json")
    audit = read(EX / "others/independent_audit.json")
    stats = read(EX / "others/independent_statistics_audit.json")
    review = read(EX / "others/report_review.json")
    judgment = read(EX / "others/judgment.json")
    design = read(EX / "protocols/design.json")
    assert inputs["status"] == audit["status"] == stats["status"] == review["status"] == "PASS"
    assert a["n"] == inputs["paired"] == audit["population"]["matched"] == 100
    assert a["positive_mark_n"] == inputs["positive_pairs"] == 15
    assert inputs["nonpositive_pairs"] == 85 and inputs["early_events"] == 103
    assert inputs["calendar_rows"] == 1642 and inputs["all_inputs_complete"] is True
    assert a["candidate_hold_n"] == audit["candidate_hold_n"] == 10
    assert a["caps_actual"] == {
        "upstream_calls": 0, "fits": 0, "new_return_labels": 0,
        "account_runs": 0, "fixed_rules": 1,
    }
    assert design["caps"] == {
        "data_calls": 0, "model_fits": 0, "new_return_labels": 0,
        "account_runs": 0, "fixed_rules": 1,
    }
    for record in (inputs, audit):
        assert all(record[key] == 0 for key in (
            "new_data_calls", "new_fits", "new_labels", "new_accounts"
        ))
    assert all(stats[key] == 0 for key in ("new_calls", "new_fits", "new_labels", "new_accounts"))
    assert judgment["new_supported_components"] == 0
    for field in ("primary_hypothesis", "conclusion", "next_step"):
        assert isinstance(judgment[field], str) and judgment[field].strip()
    for name in ("preparation_precheck", "analysis_precheck"):
        assert read(EX / f"others/{name}.json")["status"] == "PASS"
    for rel, expected in inputs["source_sha256"].items():
        assert digest(ROOT / rel) == expected, rel
    for rel, expected in audit["audited_hashes"].items():
        assert digest(ROOT / rel) == expected, rel
    statistics_paths = {
        "statistics_audit.py": "src/statistics_audit.py",
        "analysis.json": "others/analysis.json",
        "events.csv": "others/events.csv",
        "calendar.csv": "others/calendar.csv",
    }
    assert set(stats["source_sha256"]) == set(statistics_paths)
    for name, expected in stats["source_sha256"].items():
        assert digest(EX / statistics_paths[name]) == expected, name
    for name, expected in a["input_sha256"].items():
        assert digest(EX / "others" / name) == expected, name
    assert digest(EX / "src/analyze.py") == a["analysis_source_sha256"]
    assert digest(EX / "others/events.csv") == inputs["events_sha256"]
    assert digest(EX / "others/decision_features.csv") == inputs["features_sha256"]
    assert digest(EX / "protocols/report.md") == review["report_sha256"]
    assert digest(EX / "others/judgment.json") == review["judgment_sha256"]
    for name in ("published_design", "preparation_lock", "analysis_lock"):
        lock = read(EX / f"protocols/{name}.json")
        assert lock, name
        for rel, value in lock.items():
            ref = EvidenceRef.from_dict(value)
            assert ref.resolve(ROOT).read_bytes() == (ROOT / rel).read_bytes(), rel
            assert digest(ROOT / rel) == ref.sha256, rel
    return a, judgment


def main():
    for name in ("others/result.json", "others/report.md", "protocols/report_copy_verification.json"):
        assert not (EX / name).exists(), name
    a, judgment = verify_inputs()
    family = ROOT / "research/registrations/S014/family.json"
    intent = read(family)["research_intent"]
    permitted = {"stage", "pending", "conclusion", "components", "c0056_action_test"}
    protected = {key: deepcopy(value) for key, value in intent.items() if key not in permitted}
    authorized_test = deepcopy(intent["c0056_action_test"])
    assert authorized_test["status"] == "AUTHORIZED_NOT_EVALUATED"
    assert authorized_test["caps"] == read(EX / "protocols/design.json")["caps"]
    assert intent["strategy_accounts"] == 66 and intent["all_targets_pass_count"] == 0
    assert intent["stage_three_autonomous_budget"]["remaining_unallocated_rounds"] == 0

    repo = RepositoryContext.discover(ROOT)
    ctx = create_research_context(repo, ResearchBatchRef("S014"))
    experiment = ExperimentRef("S014", EX.name)
    previous = DeliveryReference.from_dict(
        read(EX.parent / "EX032_20261018/others/result.json")["delivery"]
    )
    assert previous.stage is DeliveryStage.COMPONENTS and previous.revision == 15
    old = DeliveryContent.from_dict(
        read(ROOT / "research/S014/assets/deliveries/COMPONENTS/15/delivery.json")["content"]
    )
    assert isinstance(old.payload, ComponentPanel) and len(old.payload.components) == 26
    refs = {}
    media_types = {
        ".py": "text/x-python", ".json": "application/json",
        ".csv": "text/csv", ".md": "text/markdown",
    }
    paths = sorted(path for path in EX.rglob("*") if path.is_file()
                   and path.suffix in media_types and "__pycache__" not in path.parts)
    for path in paths:
        name = path.relative_to(EX).as_posix()
        ref = publish_evidence(ctx, MaterialEvidenceWrite(
            experiment, "ex033-" + name.replace("/", "-").replace(".", "-"),
            path.read_bytes(), media_types[path.suffix], path.suffix[1:],
        ))
        assert ref.resolve(ROOT).read_bytes() == path.read_bytes()
        refs[name] = ref

    # Preserve every historical fact, component definition, test and evidence ref.
    # Scope new facts to their actual supporting evidence, avoiding further growth
    # of the historical all-files-per-fact pattern.
    evidence = tuple(dict.fromkeys((*old.evidence, *refs.values())))
    supporting = tuple(refs[name] for name in (
        "protocols/design.json", "others/inputs.json", "others/analysis.json",
        "others/independent_audit.json", "others/independent_statistics_audit.json",
        "others/judgment.json",
    ))
    facts = old.facts + tuple(FactValue(
        "ex033-" + name, value, unit, FactStatus.AVAILABLE, supporting,
    ) for name, value, unit in (
        ("fixed-rules", 1, "rules"), ("existing-paired-events", 100, "events"),
        ("changed-exits", a["candidate_hold_n"], "events"),
        ("new-calls", 0, "calls"), ("new-fits", 0, "fits"),
        ("new-labels", 0, "labels"), ("new-accounts", 0, "accounts"),
        ("new-supported-components", 0, "components"),
        ("candidate-minus-R", a["actions"]["candidate_minus_R"]["mean"], "mean_event_net_fraction"),
        ("candidate-minus-P", a["actions"]["candidate_minus_P"]["mean"], "mean_event_net_fraction"),
    ))
    print(json.dumps({"phase": "EVIDENCE_PUBLISHED", "files": len(refs)}), flush=True)
    delivery = assemble_delivery(
        repo, DeliveryDefinition(ctx.batch, DeliveryStage.COMPONENTS, 16, (previous,)),
        DeliveryContent(
            ComponentPanel(old.payload.components, judgment["conclusion"]), DeliveryStatus.COMPLETE,
            facts=facts, explanations=(), incomplete_items=(),
            report=(EX / "protocols/report.md").read_text(encoding="utf-8"), evidence=evidence,
        ),
    )
    print(json.dumps({"phase": "DELIVERY_ASSEMBLED", "reference": delivery.reference.to_dict()}), flush=True)
    check = validate_delivery(repo, delivery.reference)
    assert check.status is ValidationStatus.PASS, check
    formal = ROOT / "research/S014/deliveries/COMPONENTS/16/report.md"
    source = EX / "protocols/report.md"
    formal_bytes = formal.read_bytes()
    assert formal_bytes == source.read_bytes()
    copy = EX / "others/report.md"
    with copy.open("xb") as stream:
        stream.write(formal_bytes)
    assert copy.read_bytes() == formal_bytes and digest(copy) == digest(formal)
    write(EX / "protocols/report_copy_verification.json", {
        "status": "PASS", "formal": formal.relative_to(ROOT).as_posix(),
        "source": source.relative_to(ROOT).as_posix(), "copy": copy.relative_to(ROOT).as_posix(),
        "sha256": digest(formal), "bytes": len(formal_bytes), "byte_identical": True,
    })

    intent = read(family)["research_intent"]
    assert all(intent.get(key) == value for key, value in protected.items())
    assert intent["c0056_action_test"] == authorized_test
    intent.update(
        stage="阶段二固定退出动作检验完成：未支持新组件，S014暂停建议待用户决定",
        components=delivery.reference.to_dict(), conclusion=judgment["conclusion"],
        pending=[judgment["next_step"]],
    )
    intent["c0056_action_test"].update(
        status="COMPLETE_NO_SUPPORTED_COMPONENT", delivery=delivery.reference.to_dict(),
        result=refs["others/judgment.json"].to_dict(), fixed_rules_used=1,
        new_data_calls=0, new_fits=0, new_labels=0, new_accounts=0,
        new_supported_components=0, primary_hypothesis=judgment["primary_hypothesis"],
        next_step=judgment["next_step"], pause_authorized=False,
    )
    update_research_intent(
        repo, ctx.batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
        reason="完成获准的一项C0056固定退出动作检验，复用100对既有结果；未支持新组件，保留全部历史资产、预算、费用与目标，暂停S014仅建议待用户决定",
    )
    after = read(family)["research_intent"]
    assert all(after.get(key) == value for key, value in protected.items())
    for key in ("authorization", "caps", "design", "experiment", "fees_execution_annual_targets"):
        assert after["c0056_action_test"][key] == authorized_test[key], key
    write(EX / "others/result.json", {
        "status": "COMPLETE", "research_readiness": "PARTIAL", "experiment": experiment.to_dict(),
        "delivery": delivery.reference.to_dict(), "validation": check.to_dict(),
        "evidence": {key: ref.to_dict() for key, ref in refs.items()},
        "fixed_rules": 1, "existing_paired_events": 100, "changed_exits": a["candidate_hold_n"],
        "formal_fits": 0, "new_data_calls": 0, "new_labels": 0, "new_accounts": 0,
        "new_supported_components": 0, "component_definitions": 26,
        "historical_candidates": 66, "all_targets_pass_count": 0,
        "primary_hypothesis": judgment["primary_hypothesis"], "conclusion": judgment["conclusion"],
        "next_step": judgment["next_step"], "pause_authorized": False,
    })
    print(json.dumps({
        "phase": "COMPLETE", "delivery": delivery.reference.to_dict(), "validation": check.to_dict(),
        "new_components": 0, "new_accounts": 0, "fits": 0, "published_evidence": len(refs),
    }), flush=True)


if __name__ == "__main__":
    main()
