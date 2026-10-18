"""Publish EX031 fixed study without changing historical components or accounts."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
from czsc_trader.application import (
    RepositoryContext,
    create_research_context,
    publish_evidence,
    assemble_delivery,
    validate_delivery,
    update_research_intent,
    ResearchIntentUpdate,
)
from czsc_trader.research_tools import (
    ResearchBatchRef,
    ExperimentRef,
    MaterialEvidenceWrite,
    DeliveryContent,
    DeliveryDefinition,
    DeliveryReference,
    DeliveryStage,
    DeliveryStatus,
    ComponentPanel,
    FactValue,
    FactStatus,
    ValidationStatus,
    EvidenceRef,
)

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def write(p, obj):
    p.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main():
    assert not (EX / "others/result.json").exists()
    a = read(EX / "others/analysis.json")
    fits = read(EX / "others/fit_receipt.json")
    audit = read(EX / "others/independent_audit.json")
    stats = read(EX / "others/independent_statistics_audit.json")
    review = read(EX / "others/report_review.json")
    j = read(EX / "others/judgment.json")
    assert (
        a["status"] == fits["status"] == "COMPLETE"
        and audit["status"] == stats["status"] == review["status"] == "PASS"
    )
    assert fits["fits_completed"] == fits["fits_reserved"] == 12 and fits["failed_fits"] == 0
    assert (
        len(list((EX / "others/fits").glob("reserved_*.json")))
        == len(list((EX / "others/fits").glob("fit_*.json")))
        == 12
    )
    assert audit["new_model_fits"] == stats["new_model_fits"] == a["fits"] == 0
    for rel, h in audit["inputs_sha256"].items():
        assert sha256((ROOT / rel).read_bytes()).hexdigest() == h, rel
    for key, path in [
        ("analysis_sha256", "others/analysis.json"),
        ("environment_annual_sha256", "others/environment_annual.json"),
        ("label_inventory_sha256", "others/label_inventory.json"),
        ("audit_script_sha256", "src/audit_statistics.py"),
    ]:
        assert sha256((EX / path).read_bytes()).hexdigest() == stats[key]
    assert sha256((EX / "src/audit.py").read_bytes()).hexdigest() == audit["audit_script_sha256"]
    assert (
        sha256((EX / "others/predictions.csv").read_bytes()).hexdigest()
        == fits["prediction_sha256"]
    )
    assert review["report_sha256"] == sha256((EX / "protocols/report.md").read_bytes()).hexdigest()
    for rel, ref in read(EX / "protocols/published_design.json").items():
        assert EvidenceRef.from_dict(ref).resolve(ROOT).read_bytes() == (ROOT / rel).read_bytes()
    assert (
        EvidenceRef.from_dict(read(EX / "protocols/analysis_lock.json")).resolve(ROOT).read_bytes()
        == (EX / "src/analyze.py").read_bytes()
    )
    family = ROOT / "research/registrations/S014/family.json"
    intent = read(family)["research_intent"]
    protected = {
        k: deepcopy(v)
        for k, v in intent.items()
        if k
        not in {
            "stage",
            "pending",
            "conclusion",
            "components",
            "methanol_mechanism_design",
            "methanol_information_test",
        }
    }
    assert (
        intent["strategy_accounts"] == 66
        and intent["all_targets_pass_count"] == 0
        and intent["stage_three_autonomous_budget"]["remaining_unallocated_rounds"] == 0
    )
    repo = RepositoryContext.discover(ROOT)
    ctx = create_research_context(repo, ResearchBatchRef("S014"))
    experiment = ExperimentRef("S014", EX.name)
    previous = DeliveryReference.from_dict(
        read(EX.parent / "EX030_20261018/others/result.json")["delivery"]
    )
    old = DeliveryContent.from_dict(
        read(ROOT / "research/S014/assets/deliveries/COMPONENTS/13/delivery.json")["content"]
    )
    assert isinstance(old.payload, ComponentPanel) and len(old.payload.components) == 26
    refs = {}
    for path in sorted(
        p
        for p in EX.rglob("*")
        if p.is_file()
        and p.suffix in {".py", ".json", ".csv", ".md"}
        and "__pycache__" not in p.parts
    ):
        name = path.relative_to(EX).as_posix()
        ref = publish_evidence(
            ctx,
            MaterialEvidenceWrite(
                experiment,
                "ex031-" + name.replace("/", "-").replace(".", "-"),
                path.read_bytes(),
                {
                    ".py": "text/x-python",
                    ".json": "application/json",
                    ".csv": "text/csv",
                    ".md": "text/markdown",
                }[path.suffix],
                path.suffix[1:],
            ),
        )
        assert ref.resolve(ROOT).read_bytes() == path.read_bytes()
        refs[name] = ref
    inherited = tuple(
        EvidenceRef.from_dict(v)
        for v in read(EX / "others/inputs.json")["source_evidence"].values()
    )
    evidence = tuple(dict.fromkeys((*old.evidence, *inherited, *refs.values())))
    facts = old.facts + tuple(
        FactValue("ex031-" + name, value, unit, FactStatus.AVAILABLE, tuple(refs.values()))
        for name, value, unit in [
            ("fixed-fits", 12, "fits"),
            ("new-calls", 0, "calls"),
            ("new-accounts", 0, "accounts"),
            ("new-supported-components", 0, "components"),
            ("parent-opportunities", 216, "attempts"),
            ("D1", a["main"]["D1"], "net_fraction"),
            ("D2", a["main"]["D2"], "net_fraction"),
        ]
    )
    delivery = assemble_delivery(
        repo,
        DeliveryDefinition(ctx.batch, DeliveryStage.COMPONENTS, 14, (previous,)),
        DeliveryContent(
            ComponentPanel(old.payload.components, j["conclusion"]),
            DeliveryStatus.COMPLETE,
            facts=facts,
            explanations=(),
            incomplete_items=(),
            report=(EX / "protocols/report.md").read_text(encoding="utf-8"),
            evidence=evidence,
        ),
    )
    check = validate_delivery(repo, delivery.reference)
    assert check.status is ValidationStatus.PASS, check
    formal = ROOT / "research/S014/deliveries/COMPONENTS/14/report.md"
    assert formal.read_bytes() == (EX / "protocols/report.md").read_bytes()
    (EX / "others/report.md").write_bytes(formal.read_bytes())
    write(
        EX / "protocols/report_copy_verification.json",
        {
            "status": "PASS",
            "formal": formal.relative_to(ROOT).as_posix(),
            "mirror": (EX / "others/report.md").relative_to(ROOT).as_posix(),
            "sha256": sha256(formal.read_bytes()).hexdigest(),
            "bytes": formal.stat().st_size,
            "byte_identical": formal.read_bytes() == (EX / "others/report.md").read_bytes(),
        },
    )
    write(
        EX / "others/result.json",
        {
            "status": "COMPLETE",
            "research_readiness": "PARTIAL",
            "experiment": experiment.to_dict(),
            "delivery": delivery.reference.to_dict(),
            "validation": check.to_dict(),
            "evidence": {k: v.to_dict() for k, v in refs.items()},
            "formal_fits": 12,
            "remaining_fits": 0,
            "new_supported_components": 0,
            "component_definitions": 26,
            "new_accounts": 0,
            "new_data_calls": 0,
            "new_labels": 0,
            "historical_candidates": 66,
            "all_targets_pass_count": 0,
            "conclusion": j["conclusion"],
            "next_step": j["next_step"],
        },
    )
    intent = read(family)["research_intent"]
    assert all(intent.get(k) == v for k, v in protected.items())
    intent.update(
        stage="阶段二甲醇固定检验完成：主增量未获支持，局部低环境线索待诊断评审",
        components=delivery.reference.to_dict(),
        conclusion=j["conclusion"],
        pending=[j["next_step"]],
    )
    intent["methanol_mechanism_design"].update(
        status="AUTHORIZED_STUDY_COMPLETED",
        execution_authorized=True,
        actual_new_model_fits=12,
        actual_new_data_calls=0,
        actual_new_accounts=0,
        result=refs["others/judgment.json"].to_dict(),
        delivery=delivery.reference.to_dict(),
    )
    intent["methanol_information_test"] = {
        "status": "COMPLETE_RESEARCH_PARTIAL",
        "authorization": read(EX / "protocols/design.json")["authorization"],
        "experiment": experiment.to_dict(),
        "delivery": delivery.reference.to_dict(),
        "fits_cap": 12,
        "fits_used": 12,
        "fits_remaining": 0,
        "new_data_calls": 0,
        "new_labels": 0,
        "new_accounts": 0,
        "new_supported_components": 0,
        "primary_hypothesis": "NOT_SUPPORTED",
        "low_environment": "LIMITED_DIAGNOSTIC_CLUE_NOT_COMPONENT",
        "fees_execution_annual_targets": "UNCHANGED",
        "next_step": j["next_step"],
    }
    update_research_intent(
        repo,
        ctx.batch,
        ResearchIntentUpdate(research_intent=intent),
        actor="RSCH",
        reason="完成获准甲醇阶段二12次固定拟合及反证：主增量未获支持，保留低环境有限线索；未新增数据、标签、账户或有效组件，经济目标及历史账户预算不变",
    )
    after = read(family)["research_intent"]
    assert all(after.get(k) == v for k, v in protected.items())
    print(
        json.dumps(
            {
                "delivery": delivery.reference.to_dict(),
                "validation": check.to_dict(),
                "published_evidence": len(refs),
                "fits": 12,
                "new_supported_components": 0,
                "new_accounts": 0,
                "new_calls": 0,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
