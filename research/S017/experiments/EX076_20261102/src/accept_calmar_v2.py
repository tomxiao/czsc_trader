"""RSCH acceptance of new calculations using published accounts, without replay."""
# ruff: noqa: E402
from partial_selfcheck import ROOT, WORK, KEYS, read, save, authenticate

from dataclasses import replace
from decimal import Decimal, ROUND_FLOOR
from hashlib import sha256
import json
import math

import numpy as np
from strategy_evaluator import assess_candidates, compare_candidates
from strategy_evaluator import research_models as m
from strategy_evaluator.equity_assessment import EquityCertificationScope


def targets():
    old = m.ResearchTargets.from_dict(read(ROOT / "research/S017/materials/STAGE1_FINAL_CONTRACT_20261102.json")["targets"])
    values = []
    for target in old.requirements:
        if isinstance(target, m.ParameterNeighborhoodTarget):
            drawdown = next(item for item in target.joint_targets if item.metric is m.ResearchMetric.DRAWDOWN_MAGNITUDE)
            target = replace(target, joint_targets=(m.ResearchTarget("point-net-calmar", m.ResearchMetric.NET_CALMAR,
                lower=m.BenchmarkBound(1.25, True)), drawdown))
        elif target.target_id == "stress-positive-return":
            continue
        elif target.target_id == "stress-relative-return":
            target = m.ResearchTarget("stress-net-calmar", m.ResearchMetric.NET_CALMAR,
                lower=m.BenchmarkBound(1.0, False), scope=m.TargetScope.STRESS, one_way_cost=.002)
        values.append(target)
    result = m.ResearchTargets(tuple(values), 60)
    for target in result.requirements:
        conditions = (*target.joint_targets, *target.all_point_targets) if isinstance(target, m.ParameterNeighborhoodTarget) else (target,)
        assert all(not isinstance(item, m.ResearchTarget) or item.metric is not m.ResearchMetric.NET_ANNUAL_RETURN for item in conditions)
    return result


def calmar(curve, opening, sessions):
    annual = (curve[-1] / opening) ** (252 / sessions) - 1
    peak, dd = opening, 0.
    for equity in curve:
        peak = max(peak, equity)
        dd = max(dd, 1 - equity / peak)
    value = annual / dd if dd > 1e-12 else None
    return value if value is not None and math.isfinite(value) else None


def independent_rolls(fact):
    candidate, benchmark = (json.loads(value) for value in (
        fact.equity.candidate_ledger, fact.equity.benchmark_ledger))
    sessions = [point.session for point in fact.account]
    daily = tuple({row["session"]: row["equity"] for row in ledger["account_points"]}
                  for ledger in (candidate, benchmark))
    values = []
    for start in range(0, len(sessions) - 252 + 1, 21):
        first, last = sessions[start], sessions[start + 251]
        pair = []
        for ledger, ending in zip((candidate, benchmark), daily, strict=True):
            opening = fact.initial_cash if start == 0 else ending[sessions[start - 1]]
            curve = [row["equity"] for row in ledger["account_points"] if first <= row["session"] <= last]
            pair.append(calmar(curve, opening, 252))
        assert all(value is not None for value in pair)
        values.append(pair[0] - pair[1])
    assert len(values) == 12
    return float(np.quantile(values, .1, method="linear")), values


def independent_full(fact):
    curve = [row["equity"] for row in json.loads(fact.equity.candidate_ledger)["account_points"]]
    return calmar(curve, fact.initial_cash, len(fact.account))


def main():
    assert read(WORK / "others/neighborhood_execution.json")["status"] == "PAUSED_BY_USER_SELF_CHECK_STANDARD_REVIEW"
    original = read(ROOT / "research/S017/experiments/EX072_20261102/others/all_accounts.json")
    pressure = read(WORK / "others/pressure.json")["records"]
    selected = [row for key in ("C0338", "C0339")
                for row in read(WORK / "others/neighborhood_batches" / ("pilot2-" + key + ".json"))["records"]]
    assert len(selected) == 4 and all(not row["joint_pass"] for row in selected)
    sources = [(key, "STANDARD", .001, original[key]["evidence"]) for key in KEYS]
    sources += [(key, "PRESSURE", .002, pressure[key]["evidence"]) for key in KEYS]
    sources += [(row["candidate"], "STANDARD", .001, row["evidence"]) for row in selected]
    preserved = {key: sha256((ROOT / key).read_bytes()).hexdigest() for key in (
        "research/S017/materials/STAGE1_FINAL_CONTRACT_20261102.json",
        "research/S017/experiments/EX076_20261102/others/pressure.json",
        "research/S017/experiments/EX076_20261102/others/partial_comparison.json")}
    with EquityCertificationScope() as certification:
        facts = tuple(authenticate(ref, key, scenario, cost) for key, scenario, cost, ref in sources)
        standards, stresses, neighbors = facts[:6], facts[6:12], facts[12:]
        designs = tuple(m.ParameterNeighborhoodDesign.from_dict(read(
            WORK / "others/parameter_plans" / (key + ".json"))["design"]) for key in KEYS)
        protocol = m.CalmarSelfCheckProtocol("s017-calmar-selfcheck-v2", "TRAIN_2024_2025", "STANDARD", "PRESSURE",
            252, 21, m.QuantileMethod.LINEAR, 1, 1000, 20, 17, 1e-7,
            parameter_protocol=m.ParameterNeighborhoodProtocol(), pbo_blocks=10, frequency_min_closed_cycles=3)
        links = tuple(m.PerturbationLink(fact.parent, fact.candidate, 1., fact.derivation_sha256,
                                        fact.parameter_point) for fact in neighbors)
        request = m.CandidateAssessmentRequest(tuple(fact.candidate for fact in standards), protocol,
            links, facts, parameter_designs=designs)
        panel = assess_candidates(request)
        assert panel.formula_version == "research-assessment-v8"
        rules = targets()
        metrics = (m.ResearchMetric.NET_CALMAR, m.ResearchMetric.DRAWDOWN_MAGNITUDE,
            m.ResearchMetric.PARAMETER_CALMAR_Q10, m.ResearchMetric.PARAMETER_DRAWDOWN_Q90,
            m.ResearchMetric.ROLLING_EXCESS_CALMAR_Q10, m.ResearchMetric.STRESS_CALMAR_LOSS,
            m.ResearchMetric.PROFIT_CONCENTRATION, m.ResearchMetric.FREQUENCY_MEDIAN)
        bins = tuple(m.MetricBinSpec(metric, .5 if metric is m.ResearchMetric.FREQUENCY_MEDIAN else .0001,
                                    0., m.BinRounding.FLOOR) for metric in metrics)
        policy = m.ComparisonPolicy("s017-calmar-selfcheck-v2", bins, m.ParetoBasis.RAW,
            m.MissingEvidencePolicy.REQUIRE_COMPLETE, formula_version="research-ranking-v6")
        common = m.CommonNeighborhoodComparisonContract(m.RelativeChangeLimit(.05), tuple(
            m.ZeroCenterAbsoluteLimit(name, m.AbsoluteChangeLimit(.05))
            for name in ("g_when_u", "g_when_other", "g_when_mf")))
        comparison_request = m.CalmarComparisonRequest(request.centers, rules, panel, policy, designs, common)
        comparison = compare_candidates(comparison_request)
        ranks = {row.candidate: row for row in comparison.rows}
        checked = []
        point_checks = []
        for fact, stress, row in zip(standards, stresses, panel.rows, strict=True):
            rank = ranks[row.candidate]
            checks = {check.target.target_id: check for check in rank.target_checks}
            rolling, windows = independent_rolls(fact)
            assert row.rolling_calmar_excess_q10.status is m.DiagnosticStatus.AVAILABLE
            assert math.isclose(row.rolling_calmar_excess_q10.value, rolling, rel_tol=1e-12, abs_tol=1e-12)
            loss = independent_full(fact) - independent_full(stress)
            for index, value in ((2, rolling), (3, loss)):
                expected = int((Decimal(str(value)) / Decimal("0.0001")).to_integral_value(rounding=ROUND_FLOOR))
                assert rank.bin_values[index] == expected
            assert checks["stress-net-calmar"].status is m.TargetCheckStatus.PASSED
            assert math.isclose(checks["stress-net-calmar"].observed, independent_full(stress), rel_tol=1e-12)
            assert checks["parameters"].status is m.TargetCheckStatus.INDETERMINATE
            assert rank.pareto_layer is None and rank.acceptance_status is m.TargetCheckStatus.INDETERMINATE
            for point in checks["parameters"].points:
                scalar = next(check for check in point.joint_checks if check.target.metric is m.ResearchMetric.NET_CALMAR)
                assert scalar.status is m.TargetCheckStatus.PASSED
                point_checks.append({"candidate": point.candidate.candidate_id, "index": point.point_index,
                                     "net_calmar": scalar.observed, "lower": scalar.resolved_lower,
                                     "status": scalar.status.value})
            checked.append({"candidate": fact.candidate.candidate_id,
                "rolling_excess_calmar_q10": rolling, "rolling_excess_calmar_windows": windows,
                "pressure_calmar_loss": loss, "pressure_calmar": checks["stress-net-calmar"].observed,
                "pressure_calmar_target": "PASSED", "full_strategy_acceptance": rank.acceptance_status.value})
        assert len(point_checks) == 4
        save(WORK / "others/calmar_v2_targets.json", rules.to_dict())
        save(WORK / "others/calmar_v2_acceptance_panel.json", panel.to_dict())
        save(WORK / "others/calmar_v2_acceptance_comparison.json", comparison.to_dict())
        save(WORK / "others/calmar_v2_rsch_acceptance.json", {"status": "PASS_CALCULATION_CAPABILITY_ACCEPTANCE",
            "new_research_accounts": 0, "reused_published_accounts": 16,
            "only_four_existing_neighbor_accounts_in_acceptance_panel": True,
            "independently_verified_centers": checked, "legacy_annual_fail_new_calmar_pass_points": point_checks,
            "authenticated_unique_ledgers": certification.audit_count,
            "request_sha256": request.sha256, "protocol": protocol.to_dict(), "policy": policy.to_dict(),
            "sources": [{"candidate": key, "scenario": scenario, "cost": cost, "evidence": ref}
                        for key, scenario, cost, ref in sources],
            "stage_four_complete": False, "strategy_qualification_claimed": False,
            "remaining_replays_resumed": False, "sealed_prices_accessed": False})
    assert all(sha256((ROOT / key).read_bytes()).hexdigest() == value for key, value in preserved.items())
    print("RSCH_CALMAR_V2_CAPABILITY_ACCEPTANCE_PASS", len(checked), len(point_checks), flush=True)


if __name__ == "__main__":
    main()
