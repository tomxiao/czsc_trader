"""Authenticate the fixed S015 sources and assess complete finite neighborhoods.

Entrypoints: ``authenticate --workers 8`` then ``build``. Neither runs accounts
nor publishes evidence. Expanded family includes authenticated EX065 search history with explicit duplicate exclusions.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from hashlib import sha256
from multiprocessing import get_context
import json

from stage4 import ROOT, EX, HOME, OUT, read, save, predecessor, CENTERS, VERSION, assert_protocol
import numpy as np
from czsc_trader.research_tools import EvidenceRef, ParameterEvaluationPlan
from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from strategy_evaluator import research_models as m
from strategy_evaluator import (
    assess_candidates,
    compare_candidates,
    annualized_sharpe,
    effective_trial_count,
)
from strategy_evaluator.parameter_neighborhood import ParameterNeighborhoodProtocol

OLD = HOME.parent / "EX063_20261024/others"
FAMILY_EX = (*range(52, 57), *range(58, 63))
S011_RETURN = 0.9158029150000013
S011_DRAWDOWN = 0.07248663749114126


def require(condition, message):
    if not condition:
        raise ValueError(message)


def short(candidate):
    return candidate.candidate_id.removeprefix("S015-")


def source_rows():
    rows = [
        dict(row, source_role="historical_family")
        for number in FAMILY_EX
        for row in read(HOME.parent / f"EX{number:03}_20261024/others/results.json")["rows"]
    ]
    require(len(rows) == 176, "Original selection family must retain 176 columns")
    rows += [
        dict(row, source_role="historical_family")
        for row in read(HOME.parent / "EX065_20261024/others/results.json")["rows"]
    ]
    require(len(rows) == 383, "Original176 plus207 new sources required")
    return rows


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
        len(rows) == 16 and {x["candidate_id"] for x in rows} == set(CENTERS),
        "Exact 16 plans required",
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
    require(sum(len(x.design.points) for _, _, x in result) == 24, "Frozen 24-point scope differs")
    return tuple(result)


def performance(item):
    equity = np.r_[item.initial_cash, [x.equity for x in item.account]]
    return {
        "net_return": float(equity[-1] / equity[0] - 1),
        "drawdown": float(np.max(1 - equity / np.maximum.accumulate(equity))),
    }


def authenticate(row):
    ref = EvidenceRef.from_dict(row["evidence"])
    require(ref.experiment.strategy_id == "S015", "Source outside authorized S015")
    raw = ref.resolve(ROOT).read_bytes()
    require(sha256(raw).hexdigest() == ref.sha256, "Published source changed")
    value = json.loads(raw)
    validate_evaluation_evidence(value)
    require(
        all(value[k] == row[k] for k in ("request_hash", "result_hash")),
        "Account result identity differs",
    )
    items = [m.AssessmentEvidence.from_dict(x) for x in value["assessment_evidence"]]
    full = [x for x in items if x.window_id == "full"]
    require(len(full) == 1, "Exactly one full projection required")
    item = full[0]
    require(short(item.candidate) == row["candidate_id"], "Candidate identity differs")
    require(
        item.initial_cash == 100000
        and item.opening_quantity == 0
        and item.frequency_window_days == 60
        and len(item.account) == 434,
        "Account contract differs",
    )
    require(
        item.account[0].session == "2025-01-02" and item.account[-1].session == "2026-10-21",
        "Approved development window differs",
    )
    role = row["source_role"]
    common = None
    if role == "historical_family":
        require(
            len(items) == 2 and item.scenario_id == "standard" and item.parameter_point is None,
            "Historical two-window source differs",
        )
        if row["candidate_id"] in CENTERS:
            other = [x for x in items if x.window_id == "s011_common"]
            require(
                len(other) == 1 and len(other[0].account) == 415, "415-session projection missing"
            )
            common = performance(other[0])
            common.update(
                {
                    "evaluation_id": other[0].evaluation_id,
                    "sessions": 415,
                    "return_threshold": S011_RETURN,
                    "drawdown_threshold": S011_DRAWDOWN,
                    "return_pass": common["net_return"] > S011_RETURN,
                    "drawdown_pass": common["drawdown"] < S011_DRAWDOWN,
                }
            )
            common["passed"] = common["return_pass"] and common["drawdown_pass"]
            require(
                abs(common["net_return"] - row["runs"]["s011_common"]["net_return"]) < 1e-10
                and abs(common["drawdown"] - row["runs"]["s011_common"]["dd"]) < 1e-10,
                "Historical common-window summary differs from authenticated ledger",
            )
    elif role == "historical_stress":
        require(
            len(items) == 1 and item.scenario_id == "fee_x2" and item.parameter_point is None,
            "Historical stress source differs",
        )
    else:
        require(
            ref.experiment == EX and len(items) == 1 and item.scenario_id == "standard",
            "New full-only source differs",
        )
        parent = row["parent_candidate_id"]
        require(
            (parent is None) == (item.parameter_point is None), "Parameter binding presence differs"
        )
        if parent is not None:
            require(
                item.parent is not None
                and short(item.parent) == parent
                and item.derivation_sha256 is not None,
                "Parameter lineage differs",
            )
    require(
        item.scenario_context.one_way_cost == (0.002 if role == "historical_stress" else 0.001),
        "Cost contract differs",
    )
    if "identity" in row:
        require(
            item.candidate.content_sha256 == row["identity"]["content_sha256"],
            "Historical content differs",
        )
    meta = {
        "candidate_id": row["candidate_id"],
        "source_role": role,
        "evidence": ref.to_dict(),
        "evaluation_id": item.evaluation_id,
        "request_hash": value["request_hash"],
        "result_hash": value["result_hash"],
        "content_sha256": item.candidate.content_sha256,
        "scenario": item.scenario_id,
        "context_sha256": item.context_sha256,
        "scenario_context": item.scenario_context.to_dict(),
        "common_415": common,
    }
    return item.to_dict(), meta


def authenticate_all(workers=8):
    assert_protocol()
    plans()
    require(
        not (OUT / "authenticated_accounts.json").exists(), "Authentication output already exists"
    )
    fresh = read(OUT / "results.json")["rows"]
    require(
        len(fresh) == 40 and sum(x["parent_candidate_id"] is None for x in fresh) == 16,
        "All 16 center and 24 point accounts must be complete",
    )
    rows = source_rows() + [
        dict(x, source_role="historical_stress") for x in read(OLD / "stress_results.json")
    ]
    rows += [
        dict(x, source_role="new_center" if x["parent_candidate_id"] is None else "parameter")
        for x in fresh
    ]
    require(len(rows) == 439, "Original 192 plus new 40 account sources required")
    evidence, metadata = [], []
    with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as pool:
        for index, (item, meta) in enumerate(pool.map(authenticate, rows)):
            evidence.append(item)
            metadata.append(meta)
            if index % 16 == 15:
                print("AUTHENTICATED", index + 1, len(rows), flush=True)
    save(OUT / "authenticated_accounts.json", evidence)
    save(OUT / "authenticated_sources.json", metadata)
    save(
        OUT / "common_415_checks.json",
        [
            dict(candidate_id=x["candidate_id"], **x["common_415"])
            for x in metadata
            if x["common_415"] is not None
        ],
    )


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


def family_evidence(old_evidence):
    standards = [x for x in old_evidence if x.scenario_id == "standard"]
    require(
        len(standards) == 383, "All source accounts retained before explicit identity deduplication"
    )
    prior = standards[:176]
    old_by_hash = {x.candidate.content_sha256: x for x in prior}
    aliases = read(HOME.parent / "EX065_20261024/others/summary.json")[
        "source_proven_inactive_parameter_aliases"
    ]
    byid = {short(x.candidate): x for x in standards}
    retained = list(prior)
    excluded = []
    for item in standards[176:]:
        duplicate = old_by_hash.get(item.candidate.content_sha256)
        cid = short(item.candidate)
        if cid in aliases:
            duplicate = byid[aliases[cid]]
        if duplicate is not None:
            require(
                item.account == duplicate.account
                and item.benchmark_equity == duplicate.benchmark_equity,
                "Excluded previous identity must reproduce same economic path",
            )
            excluded.append(
                {
                    "excluded": cid,
                    "retained": short(duplicate.candidate),
                    "reason": "same content or previously source-proven inactive fields; exact daily account verified",
                }
            )
        else:
            retained.append(item)
    sessions = tuple(x.session for x in retained[0].account)
    require(
        all(tuple(x.session for x in item.account) == sessions for item in retained),
        "Family calendar differs",
    )
    require(
        len({(x.context_sha256, x.metric_version, x.scenario_context) for x in retained}) == 1,
        "Family context differs",
    )
    matrix = np.array(
        [
            np.array([x.equity for x in item.account])
            / np.r_[item.initial_cash, [x.equity for x in item.account[:-1]]]
            - 1
            for item in retained
        ]
    ).T
    sharpes = np.array([annualized_sharpe(x) for x in matrix.T])
    require(np.isfinite(sharpes).all(), "Nonfinite family Sharpe")
    selected = int(np.argmax(sharpes))
    limitations = (
        "Retain original176 historical columns including prior path dependence; append EX065 unique actual configurations after excluding verified previous identities/inactive-field aliases.17 repeated Optuna proposals do not become columns.",
        "Distinct configurations and raw trial count are not independent hypotheses; effective count is a correlation-based diagnostic, not recovered complete research history.",
        "Earlier S015 signals/components/mechanisms/adaptive selection influenced this family and remain outside this comparable matrix. This is a measured subset with incomplete history.",
        "All434 and overlapping415 development sessions repeatedly seen. No independent validation or future success probability.",
        "Highest sample Sharpe selects the DSR diagnostic only, not the recommended strategy.",
        "EX063/064 and EX066 fixed selfcheck points are not promoted to centers or included as new strategy-selection trials; their negative findings remain disclosed.",
    )
    family = m.FamilyReturnEvidence(
        tuple(x.candidate for x in retained),
        sessions,
        tuple(tuple(float(v) for v in row) for row in matrix),
        retained[selected].candidate,
        len(retained),
        limitations,
    )
    save(
        OUT / "family_summary.json",
        {
            "raw_trial_count": len(retained),
            "old_columns": 176,
            "EX065_configurations": 207,
            "EX065_proposals": 224,
            "duplicate_proposal_reuses": 17,
            "excluded_previous_identities": excluded,
            "distinct_exact_return_paths": len({x.tobytes() for x in matrix.T}),
            "effective_trial_count": {
                "status": "AVAILABLE",
                "value": effective_trial_count(matrix),
            },
            "selected_for_dsr": retained[selected].candidate.to_dict(),
            "limitations": list(limitations),
        },
    )
    return family


def build():
    assert_protocol()
    planned = plans()
    all_evidence = tuple(
        m.AssessmentEvidence.from_dict(x) for x in read(OUT / "authenticated_accounts.json")
    )
    metadata = read(OUT / "authenticated_sources.json")
    require(
        len(all_evidence) == len(metadata) == 439, "Authentication must retain every raw source"
    )
    require(
        all(x.evaluation_id == y["evaluation_id"] for x, y in zip(all_evidence, metadata)),
        "Authentication ordering differs",
    )
    old = tuple(
        x for x, y in zip(all_evidence, metadata) if y["source_role"].startswith("historical_")
    )
    fresh = tuple(x for x, y in zip(all_evidence, metadata) if y["source_role"] == "new_center")
    children = tuple(x for x, y in zip(all_evidence, metadata) if y["source_role"] == "parameter")
    byid = {short(x.candidate): x for x in fresh}
    centers = tuple(byid[cid].candidate for cid in CENTERS)
    evidence = (
        tuple(x for x in old if not (x.scenario_id == "standard" and short(x.candidate) in CENTERS))
        + fresh
        + children
    )
    require(len(evidence) == 423, "New standard centers must replace historical projections")
    for center in fresh:
        prior = next(
            x for x in old if x.candidate == center.candidate and x.scenario_id == "standard"
        )
        require(
            center.account == prior.account
            and center.fills == prior.fills
            and center.closed_cycles == prior.closed_cycles
            and center.benchmark_equity == prior.benchmark_equity,
            "Center replay must reproduce original economic ledgers exactly",
        )
    links = tuple(
        m.PerturbationLink(x.parent, x.candidate, 1.0, x.derivation_sha256, x.parameter_point)
        for x in children
    )
    request = m.CandidateAssessmentRequest(
        centers,
        protocol(),
        links,
        evidence,
        family_returns=family_evidence(old),
        parameter_designs=tuple(x.design for _, _, x in planned),
    )
    save(OUT / "assessment_request.json", request.to_dict())
    print("ASSESS_CANDIDATES", len(centers), len(evidence), flush=True)
    panel = assess_candidates(request)
    save(OUT / "assessment_panel.json", panel.to_dict())
    comparison_request = m.CandidateComparisonRequest(centers, targets(), panel, policy())
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
        "centers": 16,
        "new_center_accounts": 16,
        "retained_stress_accounts": 16,
        "authenticated_raw_account_sources": 439,
        "assessment_full_account_projections": 423,
        "parameter_design_count": 16,
        "parameter_accounts": 24,
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
                "assessment_request": subgroup.to_dict(),
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
        sum(len(x["centers"]) for x in summaries) == 16, "Grouping must retain every handoff center"
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
            {"group_count": len(summaries), "centers": 16, "new_accounts": 0}, ensure_ascii=False
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("authenticate", "build", "groups"))
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=8)
    args = parser.parse_args()
    if args.action == "authenticate":
        authenticate_all(args.workers)
    else:
        {"build": build, "groups": groups}[args.action]()
