"""Replace center provenance with exact plan-request replays, preserving v1 evidence.

This successor performs a real public SE assessment and comparison. It does not
reuse an old request hash or turn technical replay into a selection trial.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256

from stage4 import ROOT, OUT, CACHE, EX, read, save, assert_protocol
from czsc_trader.research_tools import EvidenceRef, ParameterEvaluationPlan
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from strategy_evaluator import assess_candidates, compare_candidates
from strategy_evaluator import research_models as m


def require(condition, message):
    if not condition:
        raise ValueError(message)


def without_provenance(value):
    """Permit only authentic source-ID/request-ID changes, never numeric changes."""
    if isinstance(value, dict):
        return {k: without_provenance(v) for k, v in value.items()
                if k not in {"evaluation_id", "evaluation_ids", "request_sha256"}}
    if isinstance(value, list):
        return [without_provenance(v) for v in value]
    return value


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def new_centers(old_request):
    replay_record = read(OUT / "center_replays.json")
    require(replay_record["status"] == "PASS" and replay_record["new_accounts"] == 29,
            "Complete exact replay and ledger audit required")
    require(digest(CACHE / "center_accounts.json") == replay_record["projection_sha256"],
            "Audited center projection cache changed")
    rows = replay_record["rows"]
    require(len(rows) == 29 and len({x["candidate_id"] for x in rows}) == 29,
            "Exactly 29 center replay sources required")
    originals = {x.candidate: x for x in old_request.evidence
                 if x.candidate in old_request.centers and x.scenario_id == "standard"}
    plans = {}
    for row in read(OUT / "plan_refs.json"):
        reference = EvidenceRef.from_dict(row["plan_reference"])
        plan = ParameterEvaluationPlan.from_dict(read(reference.resolve(ROOT)))
        require(plan.to_dict() == row["plan"], "Published plan snapshot changed")
        plans[row["candidate_id"]] = plan
    require(len(plans) == 29, "Exactly 29 plans required")
    cached = tuple(m.AssessmentEvidence.from_dict(x) for x in read(CACHE / "center_accounts.json"))
    require(len(cached) == 29 and len({x.candidate for x in cached}) == 29,
            "Center projection cache must cover 29 distinct identities")
    cache_by_candidate = {x.candidate: x for x in cached}
    result, substitutions = {}, []
    for row in rows:
        require(all(row[k] is True for k in (
            "exact_five_ledgers", "signals_equal", "plan_request_matches")),
            "Exact five-ledger, signal and plan-request equality required")
        reference = EvidenceRef.from_dict(row["evidence"])
        require(reference.experiment == EX and row["source_role"] == "center_replay",
                "Only this experiment's exact center replays are accepted")
        payload = read(reference.resolve(ROOT))
        validate_evaluation_evidence(payload)
        require(all(payload[k] == row[k] for k in ("request_hash", "result_hash")),
                "Center replay source identity changed")
        require(len(payload["assessment_evidence"]) == len(payload["runs"]) == 1,
                "The bound center request has one full standard account")
        item = m.AssessmentEvidence.from_dict(payload["assessment_evidence"][0])
        plan = plans[row["candidate_id"]]
        require(item.candidate == plan.design.center and item.candidate in originals,
                "Replay is outside the original handoff or plan center")
        require(payload["request_hash"] == plan.center_request_sha256,
                "Center evidence must authenticate the plan's exact original request")
        require(item == cache_by_candidate[item.candidate], "Center projection cache changed")
        require(item.parent is None and item.parameter_point is None
                and item.window_id == "full" and item.scenario_id == "standard",
                "A center replay cannot be a parameter point or pressure scenario")
        prior = originals[item.candidate]
        for field in ("candidate", "context_sha256", "metric_version", "scenario_context",
                      "initial_cash", "opening_cash", "opening_quantity", "frequency_window_days",
                      "account", "fills", "closed_cycles", "benchmark_equity", "behavior_sha256"):
            require(getattr(item, field) == getattr(prior, field),
                    f"Center economic projection changed: {row['candidate_id']} / {field}")
        require(item.candidate not in result, "Duplicate center replay")
        result[item.candidate] = item
        substitutions.append({
            "candidate_id": row["candidate_id"], "evidence": reference.to_dict(),
            "old_evaluation_id": prior.evaluation_id, "new_evaluation_id": item.evaluation_id,
            "old_request_sha256": prior.request_sha256,
            "new_request_sha256": item.request_sha256,
            "plan_center_request_sha256": plan.center_request_sha256,
            "economic_projection_equal": True,
        })
    require(set(result) == set(old_request.centers), "Center replacement coverage differs")
    return result, substitutions


def main():
    assert_protocol()
    outputs = ("assessment_request_v2.json", "assessment_panel_v2.json",
               "comparison_request_v2.json", "comparison_v2.json", "summary_v2.json",
               "group_summary_v2.json", "provenance_correction_v2.json")
    require(not any((OUT / name).exists() for name in outputs), "Preserve existing v2 results")
    old_request = m.CandidateAssessmentRequest.from_dict(read(OUT / "assessment_request.json"))
    old_panel = m.AssessmentPanel.from_dict(read(OUT / "assessment_panel.json"))
    old_comparison_request = m.CandidateComparisonRequest.from_dict(read(OUT / "comparison_request.json"))
    old_comparison = m.CandidateComparison.from_dict(read(OUT / "comparison.json"))
    require(old_panel.request_sha256 == old_request.sha256
            and old_comparison_request.panel == old_panel
            and old_comparison.request_sha256 == old_comparison_request.sha256,
            "Original v1 request/panel/comparison provenance differs")
    replacements, substitutions = new_centers(old_request)
    evidence = tuple(replacements[item.candidate]
                     if item.candidate in replacements and item.scenario_id == "standard"
                     else item for item in old_request.evidence)
    request = replace(old_request, evidence=evidence)
    require(len(request.evidence) == 812 and len(request.perturbations) == 177
            and len(request.parameter_designs) == 29
            and request.family_returns.raw_trial_count == 606,
            "The complete stage-four scope must remain fixed")
    require(request.family_returns == old_request.family_returns
            and request.parameter_designs == old_request.parameter_designs
            and request.perturbations == old_request.perturbations,
            "Replay cannot change family, plans or parameter links")
    require(request.sha256 != old_request.sha256, "New sources require a genuine successor request")
    print("ASSESS_V2_EXACT_CENTER_PROVENANCE", 29, 812, flush=True)
    panel = assess_candidates(request)
    require(without_provenance(panel.to_dict()) == without_provenance(old_panel.to_dict()),
            "A provenance correction changed numeric/semantic assessment facts")
    require(panel.family_diagnostics == old_panel.family_diagnostics
            and panel.family_limitations == old_panel.family_limitations,
            "Fixed technical replay cannot change selection-family statistics")
    comparison_request = replace(old_comparison_request, panel=panel)
    comparison = compare_candidates(comparison_request)
    require(without_provenance(comparison.to_dict()) == without_provenance(old_comparison.to_dict()),
            "A provenance correction changed acceptance, ranking or sensitivity facts")
    summary = deepcopy(read(OUT / "summary.json"))
    by_candidate = {row.candidate.candidate_id.removeprefix("S015-"): row for row in panel.rows}
    for row in summary["rows"]:
        current = by_candidate[row["candidate_id"]]
        row["diagnostics"] = {x.metric.value: x.to_dict() for x in current.diagnostics}
        row["uncertainty"] = current.uncertainty.to_dict()
        row["coverage_gaps"] = list(current.coverage_gaps)
    summary.update({
        "new_center_accounts": 29,
        "authenticated_raw_account_sources": 833,
        "historical_center_sources_superseded_for_plan_binding": 29,
        "cumulative_authenticated_raw_sources_including_superseded_centers": 862,
        "formal_new_accounts_in_experiment": 230,
        "technical_duplicate_accounts_in_experiment": 2,
        "total_new_account_computations_in_experiment": 232,
        "assessment_request_sha256": request.sha256,
        "comparison_request_sha256": comparison_request.sha256,
        "provenance_revision": "v2 exact single-full plan center requests",
        "numeric_results_equal_v1": True,
        "source_scope": "29 original standard center projections replaced by exact plan-request replays; 606 family columns and 177 parameter links unchanged. Historical originals remain immutable, not extra selection trials.",
    })
    old_groups = read(OUT / "group_summary.json")
    group_summary = {
        "status": "REUSED_NUMERIC_CONCLUSIONS_AFTER_EXACT_EQUIVALENCE",
        "disclosure": "No supplemental group assessment was rerun. Each retained group request hash below belongs to the original v1 evidence, not to the new v2 center sources. The complete v2 public assessment and comparison reproduce every v1 numeric and semantic fact after removing only evaluation IDs and request IDs. Thus the prior group-level numeric conclusions are retained without claiming new group request identities.",
        "source_group_summary": {"path": (OUT / "group_summary.json").relative_to(ROOT).as_posix(),
                                 "sha256": digest(OUT / "group_summary.json")},
        "source_group_comparisons": {"path": (OUT / "group_comparisons.json").relative_to(ROOT).as_posix(),
                                     "sha256": digest(OUT / "group_comparisons.json")},
        "original_assessment_request_sha256": old_request.sha256,
        "successor_assessment_request_sha256": request.sha256,
        "group_count": old_groups["group_count"], "new_accounts": 0,
        "selected": None, "groups": old_groups["groups"],
    }
    proof = {
        "status": "PASS", "reason": "PARAMETER_CENTER: previous double-window source request was not the single-full center request frozen in the parameter plan.",
        "old_assessment_request_sha256": old_request.sha256,
        "new_assessment_request_sha256": request.sha256,
        "old_comparison_request_sha256": old_comparison_request.sha256,
        "new_comparison_request_sha256": comparison_request.sha256,
        "allowed_comparison_differences": ["evaluation_id", "evaluation_ids", "request_sha256"],
        "all_other_panel_and_comparison_fields_exactly_equal": True,
        "new_center_accounts": 29, "new_selection_trials": 0,
        "substitutions": substitutions,
        "source_hashes": {name: digest(OUT / name) for name in (
            "assessment_request.json", "assessment_panel.json", "comparison_request.json",
            "comparison.json", "center_replays.json", "plan_refs.json")},
    }
    for name, value in (
        ("assessment_request_v2.json", request.to_dict()),
        ("assessment_panel_v2.json", panel.to_dict()),
        ("comparison_request_v2.json", comparison_request.to_dict()),
        ("comparison_v2.json", comparison.to_dict()),
        ("summary_v2.json", summary), ("group_summary_v2.json", group_summary),
        ("provenance_correction_v2.json", proof),
    ):
        save(OUT / name, value)
    print("ASSESSMENT_V2_PASS", dict(Counter(x.acceptance_status.value for x in comparison.rows)), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    main()
