"""Review then explicitly publish EX066 and ASSESSMENT/4; never runs accounts.

Use ``check`` after report.md and audit.json are complete. Publication requires
that exact digest via ``publish --reviewed-input-sha ... --receipt .tmp/...``.
Public assembly supplies FULL validation, without a duplicate validation run.
"""

from __future__ import annotations
# ruff: noqa: E402

import argparse
from collections import Counter
from dataclasses import replace
from hashlib import sha256
import json
import sys

sys.dont_write_bytecode = True
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from stage4 import (
    ROOT,
    EX,
    HOME,
    OUT,
    BATCH,
    CENTERS,
    ctx,
    read,
    save,
    predecessor,
    assert_protocol,
)
from assessment import require, short, plans, protocol
from czsc_trader.application import (
    RepositoryContext,
    publish_evidence,
    assemble_delivery,
    validate_experiment,
)
from czsc_trader.research_tools import (
    EvidenceRef,
    ExecutionResources,
    MaterialEvidenceWrite,
    ExperimentOutcome,
    ExperimentReportWrite,
    ExperimentValidationRequest,
    ExperimentValidationScope,
)
from czsc_trader.research_tools import delivery as d
from strategy_evaluator import research_models as m

REQUIRED = (
    "assessment_request.json",
    "assessment_panel.json",
    "comparison_request.json",
    "comparison.json",
    "target_bindings.json",
    "summary.json",
    "authenticated_sources.json",
    "common_415_checks.json",
    "protocol_refs.json",
    "family_summary.json",
    "centers.json",
    "results.json",
    "plan_refs.json",
    "mandate_reference.json",
    "protocol.json",
    "audit.json",
    "equivalence.json",
    "neighborhood_points.csv",
    "group_comparisons.json",
    "group_summary.json",
)


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


def recommendation(summary):
    return (
        f"阶段四新限幅自检完成，16个中心中按全部授权目标合格{summary['qualified_count']}个。"
        "合格性与跨不同邻域排序分开解释；正式总体比较及同形组补充排名均保留，不强行产生总体第一。"
        "建议优先审阅C6105，其中心收益/回撤组合有依据；最终选型由用户决定。"
        "已纳入EX065选择历史，原超限时间扰动失败及末期依赖仍有效；新资格来自已批准的方法适用范围变化，不是策略改善或独立验证。"
        "本交付未选型、未进入阶段五、未冻结或操作PTE。"
    )


def delivery_objects(data, materials, all_refs, report):
    bindings, summary = data["bindings"], data["summary"]
    summary_ref = materials[(OUT / "summary.json").relative_to(ROOT).as_posix()]
    audit_ref = materials[(OUT / "audit.json").relative_to(ROOT).as_posix()]
    family_ref = materials[(OUT / "family_summary.json").relative_to(ROOT).as_posix()]
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
        recommendation(summary),
        unique_refs((summary_ref, audit_ref, family_ref, *data["refs"])),
        ("是否选择C6105进入阶段五技术检验；冻结须另行批准精确计划？",),
        parameter_plans=data["plan_refs"],
    )
    facts = (
        d.FactValue(
            "parameter_valid_designs",
            16,
            "candidate_designs",
            d.FactStatus.AVAILABLE,
            data["plan_refs"],
        ),
        d.FactValue(
            "parameter_accounts",
            24,
            "local_sensitivity_accounts",
            d.FactStatus.AVAILABLE,
            (summary_ref, audit_ref),
        ),
        d.FactValue(
            "qualified",
            summary["qualified_count"],
            "candidate_identities",
            d.FactStatus.AVAILABLE,
            (summary_ref,),
        ),
        d.FactValue(
            "expanded_selection_family",
            data["request"].family_returns.raw_trial_count,
            "configuration_columns",
            d.FactStatus.AVAILABLE,
            (family_ref,),
        ),
    )
    content = d.DeliveryContent(
        payload,
        d.DeliveryStatus.COMPLETE,
        facts,
        (),
        incomplete_items=(),
        report=report.decode("utf-8")
        .replace("](protocols/", "](../../../experiments/EX066_20261024/protocols/")
        .replace("](others/", "](../../../experiments/EX066_20261024/others/")
        .replace("](../../deliveries/", "](../../"),
        evidence=all_refs,
    )
    return d.DeliveryDefinition(BATCH, d.DeliveryStage.ASSESSMENT, 4, data["predecessors"]), content


def prepare():
    assert_protocol()
    require((HOME / "report.md").is_file(), "Researcher-authored report.md required")
    for name in REQUIRED:
        require((OUT / name).is_file(), f"Required completed evidence missing: {name}")
    cr, candidates = predecessor(
        "CANDIDATES", 7, "b614f360e2d5448e5ad81a5c3f47b6f2271ddfff5b8b7639f3337bc8bedeb4e1"
    )
    require(
        {x["candidate_id"] for x in candidates["handoff"]} == set(CENTERS), "Handoff scope changed"
    )
    mr = d.DeliveryReference.from_dict(read(OUT / "mandate_reference.json"))
    authenticated_mr, _ = predecessor("MANDATE", mr.revision, mr.content_sha256)
    require(
        mr == authenticated_mr and mr.stage is d.DeliveryStage.MANDATE, "Mandate reference differs"
    )
    request = m.CandidateAssessmentRequest.from_dict(read(OUT / "assessment_request.json"))
    panel = m.AssessmentPanel.from_dict(read(OUT / "assessment_panel.json"))
    comparison_request = m.CandidateComparisonRequest.from_dict(
        read(OUT / "comparison_request.json")
    )
    comparison = m.CandidateComparison.from_dict(read(OUT / "comparison.json"))
    sources, summary = read(OUT / "authenticated_sources.json"), read(OUT / "summary.json")
    bindings, planned = read(OUT / "target_bindings.json"), plans()
    require(bindings["reference"] == mr.to_dict(), "Mandate binding differs")
    require(
        len(request.centers) == 16 and {short(x) for x in request.centers} == set(CENTERS),
        "Exact 16 centers required",
    )
    require(
        request.protocol == protocol()
        and len(request.perturbations) == 24
        and len(request.parameter_designs) == 16,
        "Complete new parameter evidence required",
    )
    require(
        set(request.parameter_designs) == {x.design for _, _, x in planned},
        "Published designs differ",
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
        set(comparison_request.candidates) == set(request.centers)
        and comparison_request.policy.missing_evidence_policy
        is m.MissingEvidencePolicy.REQUIRE_COMPLETE,
        "Complete comparison scope required",
    )
    for collection in (panel.rows, comparison.rows):
        require(
            len(collection) == 16 and {x.candidate for x in collection} == set(request.centers),
            "Panel center scope differs",
        )
    for row in comparison.rows:
        checks = [x for x in row.target_checks if isinstance(x, m.ParameterNeighborhoodCheck)]
        require(
            len(checks) == 1 and checks[0].required_points == checks[0].valid_points > 0,
            "Every finite-neighborhood point must have valid evidence",
        )
        require(
            (checks[0].target.minimum_numerator, checks[0].target.minimum_denominator) == (13, 16),
            "Approved pass fraction differs",
        )
    require(
        dict(Counter(x.status.value for x in comparison.rows)) == summary["status_counts"]
        and dict(Counter(x.acceptance_status.value for x in comparison.rows))
        == summary["acceptance_counts"],
        "Comparison summary differs",
    )
    common = {x["candidate_id"]: x for x in read(OUT / "common_415_checks.json")}
    require(set(common) == set(CENTERS), "All historical common-window checks required")
    qualified = sum(
        x.acceptance_status.value == "PASSED" and common[short(x.candidate)]["passed"]
        for x in comparison.rows
    )
    require(
        qualified == summary["qualified_count"], "All-authorized-target qualification count differs"
    )
    require(
        len(sources) == 439 and len(request.evidence) == 423,
        "Original and new source scope differs",
    )
    by_evaluation = {x.evaluation_id: x for x in request.evidence}
    require(len(by_evaluation) == 423, "Duplicate projection identity")
    require(
        set(by_evaluation).issubset({x["evaluation_id"] for x in sources}),
        "Source projection coverage differs",
    )
    refs = []
    for source in sources:
        item = by_evaluation.get(source["evaluation_id"])
        if item is not None:
            require(
                short(item.candidate) == source["candidate_id"]
                and item.candidate.content_sha256 == source["content_sha256"],
                "Source candidate identity differs",
            )
        else:
            require(
                source["source_role"] == "historical_family" and source["candidate_id"] in CENTERS,
                "Only old center projections may be replaced",
            )
        refs.append(reference(source["evidence"]))
    require(len(unique_refs(refs)) == 439, "Every original and new account reference required")
    data_family = read(OUT / "family_summary.json")
    require(
        request.family_returns is not None
        and request.family_returns.raw_trial_count == data_family["raw_trial_count"]
        and len(request.family_returns.candidates) == data_family["raw_trial_count"],
        "Expanded selection family must match explicit retained columns",
    )
    family_ids = {x["candidate_id"] for x in sources if x["source_role"] == "historical_family"} - {
        x["excluded"] for x in data_family["excluded_previous_identities"]
    }
    require(
        {short(x) for x in request.family_returns.candidates} == family_ids,
        "Expanded family membership differs",
    )
    for center in request.centers:
        base = [
            x for x in request.evidence if x.candidate == center and x.scenario_id == "standard"
        ]
        stress = [
            x for x in request.evidence if x.candidate == center and x.scenario_id == "fee_x2"
        ]
        require(len(base) == len(stress) == 1, "Exactly one paired center standard/stress required")
        base, stress = base[0], stress[0]
        require(
            base.window_id == stress.window_id == "full"
            and base.context_sha256 == stress.context_sha256
            and base.metric_version == stress.metric_version,
            "Historical stress context differs",
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
    require(
        read(OUT / "audit.json")["status"] == "PASS", "Independent complete audit PASS required"
    )
    equivalence = read(OUT / "equivalence.json")
    require(
        len(equivalence) == 2
        and all(x["status"] == "PASS" and x["ledgers"] == 5 for x in equivalence),
        "Both serial-versus-parallel controls must pass every ledger comparison",
    )
    refs.extend(reference(x["evidence"]) for x in equivalence)
    refs.extend(reference(x) for x in read(OUT / "protocol_refs.json").values())
    refs.extend(ref for _, ref, _ in planned)
    # Preserve original published technical controls, diagnoses, source histories,
    # and failed geometry rather than rewriting or silently discarding them.
    old_delivery = read(ROOT / "research/S015/assets/deliveries/ASSESSMENT/3/delivery.json")
    # Prior assessments remain in their own provenance scope. Do not flatten
    # old center replays into the current evaluation-id map.
    refs.extend(
        reference(x)
        for x in old_delivery["content"]["evidence"]
        if x.get("schema") != "account_evaluation"
    )
    old_assessment = d.DeliveryReceipt.from_dict(
        read(ROOT / "research/S015/deliveries/ASSESSMENT/3/receipt.json")
    ).reference
    paths = sorted(
        {
            HOME / "report.md",
            OUT / "publication_attempt1.json",
            *list((HOME / "src").glob("*.py")),
            *[
                p
                for p in (HOME / "protocols").rglob("*")
                if p.is_file() and p.suffix in (".json", ".csv", ".md")
            ],
            *[
                p
                for p in OUT.iterdir()
                if p.is_file()
                and p.suffix in (".json", ".csv", ".md")
                and not p.name.startswith(("publication_", "notes"))
                and p.name != "authenticated_accounts.json"
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
        "summary": summary,
        "refs": unique_refs(refs),
        "plan_refs": tuple(ref for _, ref, _ in planned),
        "predecessors": (cr, mr, old_assessment),
        "paths": paths,
        "manifest": manifest,
        "digest": digest,
    }
    materials, writes = {}, []
    for path in paths:
        if path.name == "report.md":
            continue
        relative, raw = path.relative_to(ROOT).as_posix(), path.read_bytes()
        require(sha256(raw).hexdigest() == manifest[relative], "Material changed during preflight")
        suffix = path.suffix[1:]
        mime = {
            "py": "text/x-python",
            "json": "application/json",
            "csv": "text/csv",
            "md": "text/markdown",
        }[suffix]
        materials[relative] = EvidenceRef(
            EX, f"{manifest[relative]}.{suffix}", manifest[relative], mime, path.stem
        )
        writes.append((relative, MaterialEvidenceWrite(EX, path.stem, raw, mime, suffix)))
    report = (HOME / "report.md").read_bytes()
    require(
        sha256(report).hexdigest() == manifest[(HOME / "report.md").relative_to(ROOT).as_posix()],
        "Report changed",
    )
    all_refs = unique_refs((*data["refs"], *materials.values()))
    saved = {}
    for ref in data["refs"]:
        if ref.schema == "account_evaluation":
            for raw in read(ref.resolve(ROOT))["assessment_evidence"]:
                item = m.AssessmentEvidence.from_dict(raw)
                previous = saved.setdefault(item.evaluation_id, item)
                require(previous == item, "Conflicting direct account provenance")
    require(
        all(saved.get(x.evaluation_id) == x for x in request.evidence),
        "Current projections must bind exact direct account provenance",
    )
    definition, content = delivery_objects(data, materials, all_refs, report)
    data.update(
        materials=materials,
        writes=writes,
        definition=definition,
        content=content,
        report_request=ExperimentReportWrite(
            EX,
            sha256(report).hexdigest(),
            ExperimentOutcome.COMPLETED,
            all_refs,
            previous=EvidenceRef.from_dict(
                read(OUT / "publication_attempt1.json")["previous_report"]
            ),
        ),
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
                    "parameter_plans": 16,
                    "parameter_accounts": 24,
                    "source_account_references": 439,
                    "typed_delivery_status": data["content"].status.value,
                    "typed_delivery_facts": {x.fact_id: x.value for x in data["content"].facts},
                    "recommendation": recommendation(data["summary"]),
                },
                ensure_ascii=False,
            ),
            flush=True,
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
        not (ROOT / "research/S015/deliveries/ASSESSMENT/4").exists(),
        "Existing ASSESSMENT/4 cannot be overwritten",
    )
    context = ctx(8)
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
    require(
        sha256((HOME / "report.md").read_bytes()).hexdigest()
        == data["manifest"][(HOME / "report.md").relative_to(ROOT).as_posix()],
        "Reviewed report changed",
    )
    report_ref = publish_evidence(context, data["report_request"])
    repository = RepositoryContext.discover(ROOT)
    experiment_check = validate_experiment(
        repository, ExperimentValidationRequest(EX, ExperimentValidationScope.REPORT_PUBLICATION)
    )
    journal.update(report=report_ref.to_dict(), experiment_validation=experiment_check.to_dict())
    save(output, journal)
    require(experiment_check.status.value == "PASS", "Report validation failed")
    print("ASSEMBLE_ASSESSMENT_FULL", 4, flush=True)
    content = replace(
        data["content"], evidence=unique_refs((*data["content"].evidence, report_ref))
    )

    def progress(event):
        if event.completed % 64 == 0 or event.completed == event.total:
            print("VALIDATION", event.phase.value, event.completed, event.total, flush=True)

    result = assemble_delivery(
        repository,
        data["definition"],
        content,
        resources=ExecutionResources(8, 1, 13),
        on_progress=progress,
    )
    require(
        result.validation.status is d.ValidationStatus.PASS
        and result.validation.scope is d.DeliveryValidationScope.FULL,
        "ASSESSMENT requires FULL PASS",
    )
    journal.update(assembly=result.to_dict(), status="ASSESSMENT_FULL_PASS")
    save(output, journal)
    print(
        json.dumps(
            {
                "status": journal["status"],
                "reference": result.receipt.reference.to_dict(),
                "research_qualified": data["summary"]["qualified_count"],
                "selected": 0,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
