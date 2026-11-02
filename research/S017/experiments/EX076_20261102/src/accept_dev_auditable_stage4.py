"""RSCH capability acceptance using sixteen existing 2024-2025 publications only.

No account replay, independent accounting audit, protocol adoption or stage-four
continuation is permitted here. Historical acceptance files remain unchanged.
"""
# ruff: noqa: E402
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".tmp/s017-auditable-stage4-acceptance"
SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ["TMP"] = os.environ["TEMP"] = str(SCRATCH)
sys.pycache_prefix = str(SCRATCH / "pycache")
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[name] = "1"

from dataclasses import replace
from hashlib import sha256
import json
from time import perf_counter

from strategy_evaluator import (
    CandidatePerformanceAssessmentRequest, DeclaredParameterPointSet,
    DeclaredPointSetComparisonContract, assessment_benchmark_fingerprint,
    assess_candidates, compare_candidates, project_parameter_performance,
)
from strategy_evaluator import equity, equity_assessment, research_models as m
from czsc_trader.research_tools import ParameterEvaluationPlan
from czsc_trader.research_tools import equity_replay
from czsc_trader.research_tools.evaluation_access import EvaluationAccess
from partial_selfcheck import KEYS, authenticate, read
from complete_calmar_v2_ranking import projection, published, comparison_for, remove_panel_identity


def require(condition, message):
    if not condition:
        raise ValueError(message)


def dev_verification():
    relative = "research/S017/experiments/EX076_20261102/others/dev_auditable_stage4_completion.json"
    content = (ROOT / relative).read_bytes()
    delivery = json.loads(content)
    tests = delivery["focused_tests"]
    require(delivery["status"] == "IMPLEMENTED_FOCUSED_TESTS_PASS_PENDING_RSCH_ACCEPTANCE"
            and tests["tests"] > 0 and tests["failures"] == tests["errors"] == tests["skipped"] == 0,
            "DEV focused-test completion evidence must pass before RSCH accepts")
    sources = delivery["source_sha256"]
    require(all(sha256((ROOT / path).read_bytes()).hexdigest() == value for path, value in sources.items()),
            "DEV tested implementation bytes changed")
    return {"dev_commit": "7e521fd4e", "completion_record": relative,
        "completion_record_sha256": sha256(content).hexdigest(),
        "tested_source_files_checked": len(sources), "focused_tests": tests,
        "static_checks": delivery["static_checks"]}


def memory_observation():
    import psutil
    current = psutil.Process()
    memory = current.memory_info()
    return {"rss_bytes": memory.rss, "peak_working_set_to_sample_bytes": memory.peak_wset,
        "peak_private_to_sample_bytes": memory.peak_pagefile,
        "sample_stage": "after numerical checks, before saving this report",
        "scope": "single-process existing-account reading and SE acceptance; not concurrent research replay"}


def main():
    started = perf_counter()
    verified_dev = dev_verification()
    control_path = WORK / "others/neighborhood_execution_v2_control.json"
    require(read(control_path)["pause_requested"] is True, "Research must remain paused")
    preserved_paths = (
        "others/calmar_v2_rsch_acceptance.json",
        "others/complete_numeric_aggregation_rsch_acceptance.json",
        "others/calmar_v2_acceptance_panel.json",
        "others/calmar_v2_acceptance_comparison.json",
        "others/neighborhood_execution_v2_control.json",
        "others/bounded_parameter_check_proposal.json",
        "protocols/confirmed_calmar_selfcheck_v2.json",
    )
    preserved = {name: sha256((WORK / name).read_bytes()).hexdigest() for name in preserved_paths}
    calls = {"independent_audit": 0, "account_replay": 0}

    def forbidden_audit(*args, **kwargs):
        calls["independent_audit"] += 1
        raise AssertionError("RSCH acceptance must not independently audit accounts")

    def forbidden_replay(*args, **kwargs):
        calls["account_replay"] += 1
        raise AssertionError("RSCH acceptance must not replay accounts")

    equity.audit_equity_account = forbidden_audit
    equity_assessment.audit_equity_account = forbidden_audit
    equity_assessment.certify_equity_ledger = forbidden_audit
    equity_replay._compute_account = forbidden_replay
    EvaluationAccess.evaluate_many = forbidden_replay

    accepted = read(WORK / "others/calmar_v2_rsch_acceptance.json")
    historical = read(WORK / "others/complete_numeric_aggregation_rsch_acceptance.json")
    protocol = m.CalmarSelfCheckProtocol.from_dict(accepted["protocol"])
    plans = {key: ParameterEvaluationPlan.from_dict(read(
        WORK / "others/parameter_plans" / (key + ".json"))) for key in KEYS}
    designs = tuple(plans[key].design for key in KEYS)
    standards = read(ROOT / "research/S017/experiments/EX072_20261102/others/all_accounts.json")
    pressures = read(WORK / "others/pressure.json")["records"]
    records = [(key, row) for key in ("C0338", "C0339") for row in read(
        WORK / "others/neighborhood_batches" / ("pilot2-" + key + ".json"))["records"]]
    require(len(records) == 4, "Exactly four existing neighbor accounts are in scope")

    facts = tuple(authenticate(standards[key]["evidence"], key, "STANDARD", .001) for key in KEYS)
    stresses = tuple(authenticate(pressures[key]["evidence"], key, "PRESSURE", .002) for key in KEYS)
    metadata = {key: published(standards[key]["evidence"])[1] for key in KEYS}
    baselines = dict(zip(KEYS, facts, strict=True))
    fingerprints = {key: assessment_benchmark_fingerprint(fact) for key, fact in baselines.items()}
    projections = tuple(projection(row, key, plans[key], baselines[key], metadata[key], fingerprints[key])
                        for key, row in records)
    neighbors = tuple(authenticate(row["evidence"], row["candidate"], "STANDARD", .001)
                      for _, row in records)
    require(tuple(project_parameter_performance(item) for item in neighbors) == projections,
            "Published parameter projections differ from raw ledger facts")
    links = tuple(m.PerturbationLink(item.parent, item.candidate, 1., item.derivation_sha256,
                                    item.parameter_point) for item in projections)
    base = m.CandidateAssessmentRequest(tuple(fact.candidate for fact in facts), protocol,
        links, (*facts, *stresses), parameter_designs=designs)
    numeric = CandidatePerformanceAssessmentRequest(base, projections)
    raw = replace(base, evidence=(*base.evidence, *neighbors))
    panel, raw_panel = assess_candidates(numeric), assess_candidates(raw)
    require(remove_panel_identity(panel) == remove_panel_identity(raw_panel),
            "All performance projection rows must equal raw journal rows")
    require(numeric.sha256 == historical["numeric_request_sha256"]
            and raw.sha256 == historical["raw_request_sha256"],
            "Historical acceptance input facts changed")
    compared = comparison_for(base, panel, accepted, designs)
    raw_compared = comparison_for(raw, raw_panel, accepted, designs)
    left, right = compared.to_dict(), raw_compared.to_dict()
    left.pop("request_sha256")
    right.pop("request_sha256")
    require(left == right, "Hard gates or ranking differ between raw and compact facts")
    old_panel = read(WORK / "others/calmar_v2_acceptance_panel.json")
    old_panel.pop("request_sha256")
    old_panel.pop("input_kind", None)
    require(remove_panel_identity(panel) == old_panel, "Historical research numerical panel changed")
    old_compared = read(WORK / "others/calmar_v2_acceptance_comparison.json")
    old_compared.pop("request_sha256")
    require(left == old_compared, "Historical hard gates or ranking changed")

    # A capability example only: three fixed original coordinates per design.
    # Selection is independent of performance; this does not adopt the 257-point proposal.
    construction = m.digest(("RSCH_CAPABILITY_ACCEPTANCE_ONLY", "0, floor(N/2)+1, N-1"))
    selected = tuple(DeclaredParameterPointSet(design,
        (0, design.point_count // 2 + 1, design.point_count - 1), construction) for design in designs)
    by_parent = {design.center: design for design in selected}
    selected_projections = tuple(item for item in projections
        if item.parameter_point.point_index in by_parent[item.parent].point_indices)
    selected_links = tuple(link for link in links
        if link.parameter_point.point_index in by_parent[link.parent].point_indices)
    selected_base = replace(base, parameter_designs=selected, perturbations=selected_links)
    selected_panel = assess_candidates(CandidatePerformanceAssessmentRequest(selected_base, selected_projections))
    source_scale = m.CommonNeighborhoodComparisonContract(m.RelativeChangeLimit(.05), tuple(
        m.ZeroCenterAbsoluteLimit(name, m.AbsoluteChangeLimit(.05))
        for name in ("g_when_u", "g_when_other", "g_when_mf")))
    declared_comparison = compare_candidates(m.CalmarComparisonRequest(base.centers,
        m.ResearchTargets.from_dict(read(WORK / "others/calmar_v2_targets.json")), selected_panel,
        m.ComparisonPolicy.from_dict(accepted["policy"]), selected,
        DeclaredPointSetComparisonContract(construction, source_scale)))
    declared_checks = []
    for row, result, design in zip(selected_panel.rows, declared_comparison.rows, selected, strict=True):
        require(row.candidate == result.candidate == design.center, "Candidate order differs")
        require(row.parameter_context.point_indices == design.point_indices
                and row.parameter_context.prescribed_points == 3, "Declared denominator or original indices changed")
        for item in selected_projections:
            if item.parent == row.candidate:
                require(item.parameter_point == design.source_design.bind_point(item.parameter_point.point_index),
                        "Old point binding was re-signed")
        check = next(item for item in result.target_checks if item.target.target_id == "parameters")
        require(check.required_points == 3 and check.status is m.TargetCheckStatus.INDETERMINATE
                and result.pareto_layer is None, "Missing points must not shrink denominator or receive a rank")
        declared_checks.append({"candidate": row.candidate.candidate_id,
            "original_point_indices": list(design.point_indices), "required_points": check.required_points,
            "valid_points": check.valid_points, "status": check.status.value})

    require(calls == {"independent_audit": 0, "account_replay": 0}, "Forbidden operation was attempted")
    require(all(sha256((WORK / name).read_bytes()).hexdigest() == value for name, value in preserved.items()),
            "Historical evidence or pause state changed")
    output = {"status": "PASS_RSCH_AUDITABLE_STAGE4_CAPABILITY_ACCEPTANCE",
        "role": "RSCH", "dev_verification": verified_dev,
        "reused_published_accounts": 16, "parameter_accounts": 4,
        "independent_audit_calls": calls["independent_audit"], "new_account_replays": calls["account_replay"],
        "raw_and_compact_all_rows_and_comparison_equal": True,
        "historical_request_hashes_panel_and_comparison_unchanged": True,
        "numeric_request_sha256": numeric.sha256, "raw_request_sha256": raw.sha256,
        "confirmed_calmar_targets_and_ranking_preserved": True,
        "independent_net_annual_return_gate_added": False,
        "declared_point_capability_example": declared_checks,
        "execution_stays_paused": True, "stage_four_complete": False,
        "strategy_qualification_claimed": False, "new_257_point_protocol_approved": False,
        "sealed_2026_market_data_accessed": False,
        "cross_implementation_reuse": {"automatic_resume_allowed": False,
            "old_65_sources_automatically_compatible_with_new_replays": False,
            "new_execution_plans_and_replay_budget_require_rsch_reassessment": True},
        "historical_files_preserved": preserved,
        "elapsed_seconds": perf_counter() - started,
        "memory_observation": memory_observation(),
        "limits": ["This is numerical capability acceptance using old published facts, not a completed stage-four assessment.",
            "Formal schema 15 delivery and shared executor/checkpoint behavior are covered by DEV synthetic focused tests.",
            "Acceptance wall time includes several raw/compact/declared SE panels and historical equivalence checks, not new account replay.",
            "Repeated full-ledger decoding and canonicalization remain observable in SE paths; no end-to-end speedup is claimed.",
            "No end-to-end research duration or 12-worker real-workload memory guarantee is established."]}
    path = WORK / "others/dev_auditable_stage4_rsch_acceptance.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    print(output["status"], f"elapsed_seconds={output['elapsed_seconds']:.3f}", flush=True)


if __name__ == "__main__":
    main()
