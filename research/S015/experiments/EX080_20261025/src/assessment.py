"""Complete fixed EX080 assessment; no strategy replay or candidate selection."""
from __future__ import annotations
import argparse
import json
from collections import Counter, defaultdict
from dataclasses import replace
from hashlib import sha256

from stage4 import ROOT, EX, HOME, OUT, CACHE, read, save, predecessor, centers, VERSION, assert_protocol
from czsc_trader.research_tools import EvidenceRef, ParameterEvaluationPlan
from czsc_trader.research_tools import delivery as d
from strategy_evaluator import research_models as m
from strategy_evaluator import assess_candidates, compare_candidates
from strategy_evaluator.parameter_neighborhood import ParameterNeighborhoodProtocol

OLD = HOME.parent / "EX063_20261024/others"

def require(condition, message):
    if not condition:
        raise ValueError(message)

def short(candidate):
    return candidate.candidate_id.removeprefix("S015-")


def nonparameter_facts(row):
    """Compare all retained center facts, excluding only the repaired coverage."""
    value = row.to_dict()
    for field in ("parameter_context", "parameter_performances"):
        value.pop(field)
    parameter_metrics = {
        "PARAMETER_RETURN_DEGRADATION", "PARAMETER_DRAWDOWN_DEGRADATION",
        "PARAMETER_RETURN_Q10", "PARAMETER_DRAWDOWN_Q90",
    }
    value["diagnostics"] = [
        x for x in value["diagnostics"] if x["metric"] not in parameter_metrics
    ]
    value["coverage_gaps"] = [
        x for x in value["coverage_gaps"] if x != "INCOMPLETE_OR_INCOMPARABLE_PERTURBATIONS"
    ]
    return value

def protocol():
    return m.NeighborhoodSelfCheckProtocol(
        version=VERSION,
        baseline_window="full",
        standard_scenario="standard",
        stress_scenario="fee_x2",
        rolling_window_days=252,
        rolling_step_days=21,
        quantile_method=m.QuantileMethod.LINEAR,
        minimum_rolling_windows=1,
        bootstrap_repetitions=2000,
        bootstrap_block_length=10,
        seed=13,
        reconciliation_tolerance=1e-7,
        parameter_protocol=ParameterNeighborhoodProtocol(),
        pbo_blocks=10,
        frequency_min_closed_cycles=3,
    )


def policy():
    # Preserve the exact established comparison bins and sensitivity variants.
    old = m.CandidateComparisonRequest.from_dict(read(OLD / "comparison_request.json"))
    return replace(old.policy, version=VERSION, formula_version="research-ranking-v4")


def plans():
    rows = read(OUT / "plan_refs.json")
    require(
        len(rows) == 29 and {x["candidate_id"] for x in rows} == set(centers()),
        "Exact 29 plans required",
    )
    result = []
    for row in rows:
        ref = EvidenceRef.from_dict(row["plan_reference"])
        require(
            ref.experiment == EX
            and sha256(ref.resolve(ROOT).read_bytes()).hexdigest() == ref.sha256,
            "Published plan identity differs",
        )
        plan = ParameterEvaluationPlan.from_dict(read(ref.resolve(ROOT)))
        require(
            plan.to_dict() == row["plan"] and plan.design.to_dict() == row["design"],
            "Plan snapshot differs",
        )
        require(short(plan.design.center) == row["candidate_id"], "Plan center differs")
        require(
            plan.schema_version == 3 and plan.design.protocol == protocol().parameter_protocol,
            "New finite-neighborhood plan required",
        )
        result.append((row["candidate_id"], ref, plan))
    require(sum(len(x.design.points) for _, _, x in result) == 177, "Frozen 177-point scope differs")
    return tuple(result)


def targets():
    reference = d.DeliveryReference.from_dict(read(OUT / "mandate_reference.json"))
    require(
        reference.batch.strategy_id == "S015" and reference.stage is d.DeliveryStage.MANDATE,
        "S015 mandate required",
    )
    ref, payload = predecessor("MANDATE", reference.revision, reference.content_sha256)
    mandate = d.ResearchMandate.from_dict(payload)
    values = tuple(
        t
        for item in mandate.items
        if isinstance(item.requirement, d.PerformanceRequirement)
        for t in item.requirement.targets
    )
    bindings = {
        t.target_id: item.item_id
        for item in mandate.items
        if isinstance(item.requirement, d.PerformanceRequirement)
        for t in item.requirement.targets
    }
    frequency = [
        item
        for item in mandate.items
        if isinstance(item.requirement, d.NumericRequirement)
        and item.requirement.metric == "frequency_window_days"
    ]
    benchmark = [
        item.item_id
        for item in mandate.items
        if isinstance(item.requirement, d.BenchmarkRequirement)
    ]
    require(
        len(frequency) == len(benchmark) == 1
        and (frequency[0].requirement.lower, frequency[0].requirement.upper) == (60.0, 60.0),
        "Mandate frequency differs",
    )
    neighborhoods = [x for x in values if isinstance(x, m.ParameterNeighborhoodTarget)]
    require(
        len(neighborhoods) == 1
        and (neighborhoods[0].minimum_numerator, neighborhoods[0].minimum_denominator) == (13, 16),
        "Approved 13/16 neighborhood target required",
    )
    save(
        OUT / "target_bindings.json",
        {
            "reference": ref.to_dict(),
            "bindings": bindings,
            "frequency": frequency[0].item_id,
            "benchmark": benchmark[0],
        },
    )
    return m.ResearchTargets(values, 60)


def build():
    assert_protocol()
    require(not (OUT / "assessment_panel.json").exists(), "Preserve completed assessment")
    planned = plans()
    audit = read(OUT / "audit.json")
    require(audit["status"] == "PASS" and len(audit["accounts"]) == 177,
            "Complete parameter arithmetic audit required")
    cached = CACHE / "parameter_accounts.json"
    require(sha256(cached.read_bytes()).hexdigest() == audit["parameter_projection_sha256"],
            "Authenticated parameter cache changed")
    children = tuple(m.AssessmentEvidence.from_dict(x) for x in read(cached))
    base = m.CandidateAssessmentRequest.from_dict(read(CACHE / "nonparameter_request.json"))
    prior_panel = m.AssessmentPanel.from_dict(read(OUT / "nonparameter_panel.json"))
    require(base.sha256 == read(OUT / "nonparameter_summary.json")["source_request_sha256"],
            "Prior authenticated nonparameter request changed")
    require(base.protocol == protocol() and base.family_returns.raw_trial_count == 606,
            "Original protocol and 606-column selection family required")
    require(len(base.evidence) == 635 and len(base.centers) == 29,
            "606 standard family and 29 pressure projections required")
    require(tuple(short(x) for x in base.centers) == centers(), "Handoff center order differs")
    require(tuple(x.design.center for _, _, x in planned) == base.centers,
            "Plan identities differ from original centers")
    links = tuple(m.PerturbationLink(x.parent, x.candidate, 1.0,
                                    x.derivation_sha256, x.parameter_point) for x in children)
    request = replace(base, perturbations=links, evidence=base.evidence + children,
                      parameter_designs=tuple(x.design for _, _, x in planned))
    require(len(request.evidence) == 812 and len(links) == 177, "Full scope differs")
    save(OUT / "assessment_request.json", request.to_dict())
    print("ASSESS_CANDIDATES", len(base.centers), len(request.evidence), flush=True)
    panel = assess_candidates(request)
    require(panel.family_diagnostics == prior_panel.family_diagnostics,
            "Adding fixed neighbors cannot change selection family statistics")
    prior_rows = {x.candidate: x for x in prior_panel.rows}
    require(set(prior_rows) == {x.candidate for x in panel.rows}, "Center coverage changed")
    for row in panel.rows:
        require(nonparameter_facts(row) == nonparameter_facts(prior_rows[row.candidate]),
                f"Nonparameter diagnostics, uncertainty or center facts changed: {short(row.candidate)}")
    save(OUT / "assessment_panel.json", panel.to_dict())
    comparison_request = m.CandidateComparisonRequest(base.centers, targets(), panel, policy())
    save(OUT / "comparison_request.json", comparison_request.to_dict())
    comparison = compare_candidates(comparison_request)
    save(OUT / "comparison.json", comparison.to_dict())
    assessments = {x.candidate: x for x in panel.rows}
    designs = {x.design.center: x.design for _, _, x in planned}
    common = {x["candidate_id"]: x for x in read(OUT / "common_415_checks.json")}
    rows, groups = [], defaultdict(list)
    for row in comparison.rows:
        assessment = assessments[row.candidate]
        (check,) = [x for x in row.target_checks if isinstance(x, m.ParameterNeighborhoodCheck)]
        perfs = assessment.parameter_performances
        failures = [
            {
                "point_index": x.point_index,
                "candidate_id": short(x.candidate),
                "values": [
                    v.to_dict() for v in designs[row.candidate].points[x.point_index].values
                ],
                "joint_failed": [
                    c.target.target_id
                    for c in x.joint_checks
                    if c.status.value in ("FAILED", "INDETERMINATE")
                ],
                "all_point_failed": [
                    c.target.target_id
                    for c in x.all_point_checks
                    if c.status.value in ("FAILED", "INDETERMINATE")
                ],
            }
            for x in check.points
            if any(
                c.status.value in ("FAILED", "INDETERMINATE")
                for c in (*x.joint_checks, *x.all_point_checks)
            )
        ]
        groups[designs[row.candidate].comparison_sha256].append(short(row.candidate))
        rows.append(
            {
                "candidate_id": short(row.candidate),
                "content_sha256": row.candidate.content_sha256,
                "status": row.status.value,
                "acceptance_status": row.acceptance_status.value,
                "all_authorized_targets_pass": row.acceptance_status.value == "PASSED"
                and common[short(row.candidate)]["passed"],
                "rank_min": row.rank_min,
                "rank_max": row.rank_max,
                "pareto_layer": row.pareto_layer,
                "floor_metrics": [x.value for x in row.floor_metrics],
                "reasons": list(row.reasons),
                "coverage_gaps": list(assessment.coverage_gaps),
                "common_415": common[short(row.candidate)],
                "parameter": {
                    "required_points": check.required_points,
                    "valid_points": check.valid_points,
                    "minimum_joint_passes": check.minimum_joint_passes,
                    "joint_passes": check.joint_passes,
                    "status": check.status.value,
                    "reason": check.reason,
                    "min_drawdown": min(x.drawdown for x in perfs),
                    "max_drawdown": max(x.drawdown for x in perfs),
                    "min_annual_return": min(x.annual_return for x in perfs),
                    "max_annual_return": max(x.annual_return for x in perfs),
                    "all_point_failed_points": sum(bool(x["all_point_failed"]) for x in failures),
                    "failures": failures,
                    "comparison_sha256": designs[row.candidate].comparison_sha256,
                },
                "diagnostics": {x.metric.value: x.to_dict() for x in assessment.diagnostics},
                "uncertainty": assessment.uncertainty.to_dict(),
                "target_checks": [
                    {"target_id": x.target.target_id, "status": x.status.value, "reason": x.reason}
                    for x in row.target_checks
                ],
            }
        )
    summary = {
        "centers": 29,
        "new_center_accounts": 0,
        "reused_stress_accounts": 5,
        "new_stress_accounts": 24,
        "authenticated_raw_account_sources": 833,
        "assessment_full_account_projections": 812,
        "parameter_design_count": 29,
        "parameter_accounts": 177,
        "family_columns": request.family_returns.raw_trial_count,
        "new_points_are_selection_family": False,
        "status_counts": dict(Counter(x.status.value for x in comparison.rows)),
        "acceptance_counts": dict(Counter(x.acceptance_status.value for x in comparison.rows)),
        "qualified_count": sum(x["all_authorized_targets_pass"] for x in rows),
        "family_diagnostics": [x.to_dict() for x in panel.family_diagnostics],
        "rows": rows,
        "comparability_groups": dict(groups),
        "sensitivities": [
            {
                "name": v.name,
                "rows": [
                    {
                        "candidate_id": short(x.candidate),
                        "status": x.status.value,
                        "rank_min": x.rank_min,
                        "rank_max": x.rank_max,
                    }
                    for x in v.rows
                ],
            }
            for v in comparison.sensitivities
        ],
    }
    save(OUT / "summary.json", summary)
    print(
        json.dumps(
            {
                k: summary[k]
                for k in ("centers", "status_counts", "acceptance_counts", "qualified_count")
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

def groups():
    """Deterministic within-shape comparisons; preserve the all-center result."""
    assert_protocol()
    require(
        (OUT / "summary.json").is_file(), "Complete full assessment before supplemental grouping"
    )
    require(
        not (OUT / "group_comparisons.json").exists(), "Supplemental group evidence already exists"
    )
    request = m.CandidateAssessmentRequest.from_dict(read(OUT / "assessment_request.json"))
    original = m.AssessmentPanel.from_dict(read(OUT / "assessment_panel.json"))
    full_comparison = m.CandidateComparisonRequest.from_dict(read(OUT / "comparison_request.json"))
    by_candidate = {x.candidate: x for x in original.rows}
    memberships = defaultdict(list)
    for design in request.parameter_designs:
        memberships[design.comparison_sha256].append(design.center)
    documents, summaries = [], []
    for index, (key, members) in enumerate(sorted(memberships.items()), 1):
        chosen = set(members)
        links = tuple(x for x in request.perturbations if x.parent in chosen)
        identities = chosen | {x.child for x in links}
        subgroup = replace(
            request,
            centers=tuple(x for x in request.centers if x in chosen),
            perturbations=links,
            evidence=tuple(
                x
                for x in request.evidence
                if x.candidate in identities
                or (x.parameter_point is None and x.scenario_id == "standard")
            ),
            incomplete=tuple(x for x in request.incomplete if x.candidate in identities),
            parameter_designs=tuple(x for x in request.parameter_designs if x.center in chosen),
        )
        require(
            subgroup.family_returns == request.family_returns,
            "Grouping cannot reset original selection history",
        )
        print(
            "ASSESS_COMPARABILITY_GROUP",
            index,
            len(memberships),
            [short(x) for x in members],
            flush=True,
        )
        panel = assess_candidates(subgroup)
        require(
            all(x == by_candidate[x.candidate] for x in panel.rows),
            "Grouping changed candidate diagnostics",
        )
        require(
            panel.family_diagnostics == original.family_diagnostics,
            "Grouping changed original family diagnostics",
        )
        comparison_request = m.CandidateComparisonRequest(
            subgroup.centers, full_comparison.targets, panel, full_comparison.policy
        )
        comparison = compare_candidates(comparison_request)
        documents.append(
            {
                "comparison_sha256": key,
                "source_assessment_request_sha256": request.sha256,
                "assessment_request_sha256": subgroup.sha256,
                "centers": [x.to_dict() for x in subgroup.centers],
                "reconstruction": "Filter the published full request exactly as groups() declares; retain every standard family projection and the unchanged family_returns.",
                "assessment_panel": panel.to_dict(),
                "comparison_request": comparison_request.to_dict(),
                "comparison": comparison.to_dict(),
            }
        )
        summaries.append(
            {
                "comparison_sha256": key,
                "centers": [short(x) for x in subgroup.centers],
                "assessment_request_sha256": subgroup.sha256,
                "comparison_request_sha256": comparison_request.sha256,
                "status_counts": dict(Counter(x.status.value for x in comparison.rows)),
                "acceptance_counts": dict(
                    Counter(x.acceptance_status.value for x in comparison.rows)
                ),
                "rows": [
                    {
                        "candidate_id": short(x.candidate),
                        "status": x.status.value,
                        "acceptance_status": x.acceptance_status.value,
                        "pareto_layer": x.pareto_layer,
                        "rank_min": x.rank_min,
                        "rank_max": x.rank_max,
                        "reasons": list(x.reasons),
                    }
                    for x in comparison.rows
                ],
                "sensitivities": [
                    {
                        "name": variant.name,
                        "rows": [
                            {
                                "candidate_id": short(x.candidate),
                                "status": x.status.value,
                                "rank_min": x.rank_min,
                                "rank_max": x.rank_max,
                            }
                            for x in variant.rows
                        ],
                    }
                    for variant in comparison.sensitivities
                ],
            }
        )
    require(
        sum(len(x["centers"]) for x in summaries) == 29, "Grouping must retain every handoff center"
    )
    disclosure = (
        "Supplemental deterministic comparisons of every center within its exact public-generator "
        "comparison_sha256. No new accounts, parameter selection, altered target or fabricated comparison identity. "
        "All-center comparison and expanded selection family remain unchanged within supplemental groups. "
        "Ranks are local to each group; a singleton rank1 is not a best-overall claim. No candidate selected."
    )
    save(
        OUT / "group_comparisons.json",
        {
            "disclosure": disclosure,
            "source_assessment_request_sha256": request.sha256,
            "groups": documents,
        },
    )
    save(
        OUT / "group_summary.json",
        {
            "disclosure": disclosure,
            "group_count": len(summaries),
            "new_accounts": 0,
            "selected": None,
            "groups": summaries,
        },
    )
    print(
        json.dumps(
            {"group_count": len(summaries), "centers": 29, "new_accounts": 0}, ensure_ascii=False
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "groups"))
    args = parser.parse_args()
    {"build": build, "groups": groups}[args.action]()
