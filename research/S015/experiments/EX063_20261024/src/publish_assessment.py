"""Explicit EX063 report and ASSESSMENT/2 publication; never runs accounts.

Run ``check`` after the researcher writes report.md. It prints a frozen-input
digest without writing. After reviewing it, use ``publish --reviewed-input-sha
<digest> --receipt .tmp/<fresh-name>.json``. Public assembly supplies FULL
verification; no duplicate FULL call is made. All account sources are retained.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from hashlib import sha256
import json
import sys

sys.dont_write_bytecode = True
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from stage4 import (  # noqa: E402
    BATCH,
    CENTERS,
    EX,
    HOME,
    OUT,
    ROOT,
    assert_protocol,
    ctx,
    d,
    m,
    predecessor,
    read,
    save,
    EvidenceRef,
    ExecutionResources,
    MaterialEvidenceWrite,
    RepositoryContext,
    publish_evidence,
)
from czsc_trader.application import assemble_delivery, validate_experiment  # noqa: E402
from czsc_trader.research_tools import (  # noqa: E402
    ExperimentOutcome,
    ExperimentReportWrite,
    ExperimentValidationRequest,
    ExperimentValidationScope,
)


REQUIRED = (
    "assessment_request.json",
    "assessment_panel.json",
    "comparison_request.json",
    "comparison.json",
    "target_bindings.json",
    "summary.json",
    "authenticated_sources.json",
    "protocol_refs.json",
    "stress_audit.json",
    "family_summary.json",
    "geometry.json",
    "centers.json",
    "stress_results.json",
    "serial_fee_x2.json",
    "descriptive_checks.json",
)
RECOMMENDATION = (
    "本轮16个中心均缺少可行的32点参数设计，不能形成完整合格结论或正式排序。"
    "建议留在阶段四，讨论适合当前混合离散参数空间的自检方法；"
    "未经用户确认不改半径、参数域、点数或验收目标，不进行选型。"
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def short(candidate):
    return candidate.candidate_id.removeprefix("S015-")


def reference(raw):
    ref = EvidenceRef.from_dict(raw)
    require(ref.experiment.strategy_id == "S015", "Reference outside authorized S015")
    require(sha256(ref.resolve(ROOT).read_bytes()).hexdigest() == ref.sha256, "Evidence changed")
    return ref


def unique_refs(refs):
    result = {}
    for ref in refs:
        result.setdefault((ref.experiment, ref.evidence_id, ref.sha256), ref)
    return tuple(result.values())


def delivery_objects(data, materials, all_refs, report):
    """Build the same typed definition/content before any publication is possible."""
    bindings = data["bindings"]
    geometry_ref = materials[(OUT / "geometry.json").relative_to(ROOT).as_posix()]
    summary_ref = materials[(OUT / "summary.json").relative_to(ROOT).as_posix()]
    payload = d.CandidateAssessmentDelivery(
        data["predecessors"][0],
        data["predecessors"][1],
        data["request"],
        data["panel"],
        data["comparison_request"],
        data["comparison"],
        tuple(d.TargetMandateBinding(k, v) for k, v in sorted(bindings["bindings"].items())),
        bindings["frequency"],
        bindings["benchmark"],
        RECOMMENDATION,
        unique_refs((geometry_ref, *data["refs"])),
        ("请用户讨论并确认适合混合离散参数空间的自检方法；当前留在阶段四，不选型、不进入阶段五。",),
        parameter_plans=(),
    )
    facts = (
        d.FactValue(
            "parameter_valid_designs",
            0,
            "candidate_designs",
            d.FactStatus.AVAILABLE,
            (geometry_ref,),
        ),
        d.FactValue("qualified", 0, "candidate_identities", d.FactStatus.AVAILABLE, (summary_ref,)),
        d.FactValue(
            "parameter_diagnostics",
            None,
            "32_point_design",
            d.FactStatus.INSUFFICIENT_DATA,
            (geometry_ref,),
            "16个中心的固定5%球面均无法产生32个唯一有效点；参数自检及完整资格未完成。",
        ),
    )
    # COMPLETE describes completion of this assessment delivery, not qualification.
    content = d.DeliveryContent(
        payload,
        d.DeliveryStatus.COMPLETE,
        facts,
        (),
        incomplete_items=(),
        report=report.decode("utf-8")
        .replace("](protocols/", "](../../../experiments/EX063_20261024/protocols/")
        .replace("](others/", "](../../../experiments/EX063_20261024/others/")
        .replace("](../../deliveries/", "](../../"),
        evidence=all_refs,
    )
    definition = d.DeliveryDefinition(
        BATCH, d.DeliveryStage.ASSESSMENT, 2, data["predecessors"], schema_version=8
    )
    return definition, content


def prepare():
    require((HOME / "report.md").is_file(), "Researcher-authored report.md is required")
    for name in REQUIRED:
        require((OUT / name).is_file(), f"Required completed evidence missing: {name}")
    assert_protocol()
    cr, candidates = predecessor(
        "CANDIDATES", 6, "9e021c2a0ed2361ed7f06b916a0935ac4a08de73c9519fbeea7f477af0c2b9e1"
    )
    mr, _ = predecessor(
        "MANDATE", 3, "5563c98c1a2ed876b6d75b775437f35ec2c31777818ad0f9b67e89c90d30d90a"
    )
    require(
        {x["candidate_id"] for x in candidates["handoff"]} == set(CENTERS), "Handoff scope changed"
    )
    request = m.CandidateAssessmentRequest.from_dict(read(OUT / "assessment_request.json"))
    panel = m.AssessmentPanel.from_dict(read(OUT / "assessment_panel.json"))
    comparison_request = m.CandidateComparisonRequest.from_dict(
        read(OUT / "comparison_request.json")
    )
    comparison = m.CandidateComparison.from_dict(read(OUT / "comparison.json"))
    sources = read(OUT / "authenticated_sources.json")
    summary = read(OUT / "summary.json")
    bindings = read(OUT / "target_bindings.json")
    require(bindings["reference"] == mr.to_dict(), "Mandate binding differs")
    require(
        len(request.centers) == 16 and {short(x) for x in request.centers} == set(CENTERS),
        "Exact16 centers required",
    )
    require(
        not request.parameter_designs and not request.perturbations,
        "No successful parameter designs were authorized",
    )
    require(
        request.protocol.parameter_protocol == m.ParameterPerturbationProtocol(),
        "Fixed default32-point protocol changed",
    )
    require(
        panel.request_sha256 == request.sha256 and panel.protocol_sha256 == request.protocol.sha256,
        "Panel request differs",
    )
    require(
        comparison_request.panel == panel
        and comparison.request_sha256 == comparison_request.sha256,
        "Comparison identity differs",
    )
    require(
        set(comparison_request.candidates) == set(request.centers),
        "Comparison center scope differs",
    )
    require(
        comparison_request.policy.missing_evidence_policy
        is m.MissingEvidencePolicy.REQUIRE_COMPLETE,
        "Complete-evidence policy required",
    )
    for collection in (panel.rows, comparison.rows):
        require(
            len(collection) == 16 and {x.candidate for x in collection} == set(request.centers),
            "Panel must retain all16 centers",
        )
    require(
        not any(x.acceptance_status.value == "PASSED" for x in comparison.rows),
        "Missing parameter evidence cannot pass",
    )
    require(
        not any(x.status.value in ("RANKED", "TIED", "PARTIALLY_ORDERED") for x in comparison.rows),
        "No formal ranking is allowed",
    )
    for row in comparison.rows:
        groups = [x for x in row.target_checks if isinstance(x, m.ParameterGroupCheck)]
        require(
            bool(groups)
            and all(x.valid_points == 0 and x.status.value == "INDETERMINATE" for x in groups),
            "Parameter gap must remain indeterminate",
        )
    require(
        dict(Counter(x.status.value for x in comparison.rows)) == summary["status_counts"],
        "Status summary differs",
    )
    require(
        dict(Counter(x.acceptance_status.value for x in comparison.rows))
        == summary["acceptance_counts"],
        "Acceptance summary differs",
    )
    require(
        len(sources) == len(request.evidence) == 192,
        "All176 original plus16 stress account projections required",
    )
    require(
        {x["evaluation_id"] for x in sources} == {x.evaluation_id for x in request.evidence},
        "Source coverage differs",
    )
    by_evaluation = {x.evaluation_id: x for x in request.evidence}
    refs = []
    for source in sources:
        item = by_evaluation[source["evaluation_id"]]
        require(
            short(item.candidate) == source["candidate_id"]
            and item.candidate.content_sha256 == source["content_sha256"],
            "Source candidate identity differs",
        )
        refs.append(reference(source["evidence"]))
    require(len(unique_refs(refs)) == 192, "Must preserve192 distinct original account references")
    standard = [x for x in request.evidence if x.scenario_id == "standard"]
    require(len(standard) == 176, "Family standard account scope differs")
    require(
        request.family_returns is not None
        and request.family_returns.raw_trial_count == 176
        and set(request.family_returns.candidates) == {x.candidate for x in standard},
        "Declared176-column selection family differs",
    )
    for center in request.centers:
        base = [x for x in standard if x.candidate == center]
        stress = [
            x for x in request.evidence if x.candidate == center and x.scenario_id == "fee_x2"
        ]
        require(
            len(base) == len(stress) == 1,
            "Each center needs exactly one paired full standard/stress account",
        )
        base, stress = base[0], stress[0]
        require(
            base.window_id == stress.window_id == "full" and base.candidate == stress.candidate,
            "Paired window/identity differs",
        )
        require(
            base.context_sha256 == stress.context_sha256
            and base.metric_version == stress.metric_version,
            "Single-window stress differs from reused full projection",
        )
        require(
            base.scenario_context.one_way_cost == 0.001
            and stress.scenario_context.one_way_cost == 0.002
            and stress.scenario_context.measurement_tier == "STRESS"
            and replace(
                stress.scenario_context,
                one_way_cost=0.001,
                measurement_tier=base.scenario_context.measurement_tier,
            )
            == base.scenario_context,
            "Stress must differ only in declared cost and measurement tier",
        )
    geometry = read(OUT / "geometry.json")
    require(
        len(geometry["rows"]) == 16
        and {x["candidate_id"] for x in geometry["rows"]} == set(CENTERS),
        "Geometry center scope differs",
    )
    require(
        all(
            x["result"]["status"] == "DESIGN_FAILED" and x["result"]["design"] is None
            for x in geometry["rows"]
        ),
        "Expected failed geometry must be explicit",
    )
    audit = read(OUT / "stress_audit.json")
    require(
        audit["status"] == "ARITHMETIC_CHECKS_PASS" and audit["formal_accounts"] == 16,
        "Complete independent stress audit required",
    )
    require(
        len(audit["technical_accounts"]) == 1
        and audit["technical_accounts"][0]["formal_result_and_all_ledgers_equal"] is True,
        "Serial equivalence must be verified",
    )
    refs.extend(reference(x) for x in read(OUT / "protocol_refs.json").values())
    refs.append(reference(read(OUT / "serial_fee_x2.json")["evidence"]))
    # Retain every completed JSON diagnosis and source, without copying redundant
    # authenticated_accounts (already fully embedded in assessment_request).
    paths = sorted(
        {
            HOME / "report.md",
            *list((HOME / "src").glob("*.py")),
            *[
                p
                for p in OUT.glob("*.json")
                if not p.name.startswith("publication_") and p.name != "authenticated_accounts.json"
            ],
        }
    )
    manifest = {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for p in paths}
    digest = sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    data = {
        "request": request,
        "panel": panel,
        "comparison_request": comparison_request,
        "comparison": comparison,
        "bindings": bindings,
        "refs": unique_refs(refs),
        "predecessors": (cr, mr),
        "paths": paths,
        "manifest": manifest,
        "digest": digest,
    }
    materials, writes = {}, []
    for path in paths:
        if path.name == "report.md":
            continue
        relative = path.relative_to(ROOT).as_posix()
        raw = path.read_bytes()
        require(sha256(raw).hexdigest() == manifest[relative], "Material changed during preflight")
        suffix = path.suffix[1:]
        mime = "text/x-python" if suffix == "py" else "application/json"
        write = MaterialEvidenceWrite(EX, path.stem, raw, mime, suffix)
        ref = EvidenceRef(EX, f"{manifest[relative]}.{suffix}", manifest[relative], mime, path.stem)
        materials[relative] = ref
        writes.append((relative, write))
    report = (HOME / "report.md").read_bytes()
    require(
        sha256(report).hexdigest() == manifest[(HOME / "report.md").relative_to(ROOT).as_posix()],
        "Report changed during preflight",
    )
    all_refs = unique_refs((*data["refs"], *materials.values()))
    definition, content = delivery_objects(data, materials, all_refs, report)
    report_request = ExperimentReportWrite(
        EX, sha256(report).hexdigest(), ExperimentOutcome.COMPLETED, all_refs
    )
    data.update(
        {
            "materials": materials,
            "writes": writes,
            "definition": definition,
            "content": content,
            "report_request": report_request,
        }
    )
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "publish"))
    parser.add_argument("--reviewed-input-sha")
    parser.add_argument("--receipt")
    args = parser.parse_args()
    data = prepare()
    if args.mode == "check":
        print(
            json.dumps(
                {
                    "status": "READ_ONLY_READY",
                    "input_sha256": data["digest"],
                    "centers": 16,
                    "source_account_references": 192,
                    "typed_delivery_status": data["content"].status.value,
                    "typed_delivery_incomplete_items": list(data["content"].incomplete_items),
                    "typed_delivery_facts": {x.fact_id: x.value for x in data["content"].facts},
                    "recommendation": RECOMMENDATION,
                },
                ensure_ascii=False,
            )
        )
        return
    require(args.reviewed_input_sha == data["digest"], "Review digest absent or inputs changed")
    require(bool(args.receipt), "Fresh .tmp receipt path required")
    output = (ROOT / args.receipt).resolve()
    require(
        output.is_relative_to(ROOT / ".tmp") and not output.exists(),
        "Receipt must be a fresh .tmp path",
    )
    require(
        not (ROOT / "research/S015/deliveries/ASSESSMENT/2").exists(),
        "Existing ASSESSMENT/2 cannot be overwritten",
    )
    context = ctx(4)
    journal = {
        "status": "STARTED",
        "input_sha256": data["digest"],
        "inputs": data["manifest"],
        "materials": {},
    }
    save(output, journal)
    for relative, write in data["writes"]:
        require(
            sha256((ROOT / relative).read_bytes()).hexdigest() == data["manifest"][relative],
            "Reviewed material changed",
        )
        ref = publish_evidence(context, write)
        require(ref == data["materials"][relative], "Published material differs from preflight")
        journal["materials"][relative] = ref.to_dict()
    save(output, journal)
    report = (HOME / "report.md").read_bytes()
    require(
        sha256(report).hexdigest()
        == data["manifest"][(HOME / "report.md").relative_to(ROOT).as_posix()],
        "Reviewed report changed",
    )
    report_ref = publish_evidence(context, data["report_request"])
    repository = RepositoryContext.discover(ROOT)
    experiment_check = validate_experiment(
        repository, ExperimentValidationRequest(EX, ExperimentValidationScope.REPORT_PUBLICATION)
    )
    journal.update(
        {"report": report_ref.to_dict(), "experiment_validation": experiment_check.to_dict()}
    )
    save(output, journal)
    require(experiment_check.status.value == "PASS", "Report validation failed")
    content = replace(
        data["content"], evidence=unique_refs((*data["content"].evidence, report_ref))
    )
    result = assemble_delivery(
        repository,
        data["definition"],
        content,
        resources=ExecutionResources(4, 1, 13),
    )
    require(
        result.validation.status is d.ValidationStatus.PASS
        and result.validation.scope is d.DeliveryValidationScope.FULL,
        "ASSESSMENT requires FULL PASS",
    )
    journal.update({"assembly": result.to_dict(), "status": "ASSESSMENT_FULL_PASS"})
    save(output, journal)
    print(
        json.dumps(
            {
                "status": journal["status"],
                "reference": result.receipt.reference.to_dict(),
                "research_qualified": 0,
                "selected": 0,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
