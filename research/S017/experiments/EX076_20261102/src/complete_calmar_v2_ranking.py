"""RSCH sources explicit facts; SE alone constructs the numeric panel and ranking.

The performance-input path is not a whole-request TDR journal FULL audit.
All ledger publications and their individual audit provenance remain separate.
"""
# ruff: noqa: E402
from partial_selfcheck import ROOT, WORK, KEYS, read, save, authenticate

import argparse
from dataclasses import replace
from decimal import Decimal, ROUND_FLOOR
import gc
from hashlib import sha256
import json
import math

from czsc_trader import research_tools as d
from strategy_evaluator import (assess_candidates, compare_candidates,
    CandidatePerformanceAssessmentRequest, ParameterPerformanceEvidence,
    project_parameter_performance, assessment_benchmark_fingerprint)
from strategy_evaluator import research_models as m
from strategy_evaluator.equity_assessment import EquityCertificationScope
from strategy_runtime.equity import equity_hash
from strategy_manager import canonical_sha256

import finalize_calmar_v2_analysis as independent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def published(ref):
    value = d.EvidenceRef.from_dict(ref)
    require(value.experiment.strategy_id == "S017" and value.schema == "equity_research"
            and value.schema_version == 4, "Only published S017 v4 accounts are in scope")
    result = read(value.resolve(ROOT))
    require(result["request_hash"] == equity_hash(result["request"]), "Account request hash differs")
    return value, result


def projection(record, key, plan, fact, baseline, fingerprint):
    ref, envelope = published(record["evidence"])
    request, original = envelope["request"], baseline["request"]
    index = record["index"]
    child, definition, _ = independent.point_identity(plan, index)
    require(child.candidate.content_sha256 == record["identity"]
            and child.candidate.candidate_id == "S017-" + record["candidate"], "Point identity differs")
    require(request["content_sha256"] == record["identity"]
            and request["candidate_definition"] == json.loads(child.payload_json)["equity_definition"],
            "Published point payload differs")
    independent.same_nonparameter(request, original)
    require(envelope["data"] == baseline["data"], "Prepared input metadata differs")
    require(envelope["benchmark_ref"] == baseline["benchmark_ref"]
            and envelope["benchmark_identity"] == baseline["benchmark_identity"],
            "Point benchmark journal differs from authenticated baseline")
    require(request["fee_rate"] == original["fee_rate"]
            and request["window_id"] == fact.window_id and request["scenario_id"] == fact.scenario_id
            and request["measurement_tier"] == fact.scenario_context.measurement_tier,
            "Point scenario differs")
    require(record["evaluation_id"] == envelope["evaluation_id"]
            and record["request_hash"] == envelope["request_hash"], "Point source identity differs")
    binding = d.ParameterEvaluationBinding.from_dict(request["lineage"]["parameter_binding"])
    require(binding.point == plan.design.bind_point(index)
            and request["lineage"]["parameter_binding"] == record["parameter_binding"], "Point binding differs")
    derivation = request["lineage"]["derivation"]
    require(derivation["kind"] == "PARAMETERS" and derivation["parent"]["candidate_id"] == key
            and derivation["parent_content_sha256"] == fact.candidate.content_sha256
            and derivation["child"]["candidate_id"] == record["candidate"]
            and derivation["child_content_sha256"] == record["identity"]
            and derivation["changes"] == json.loads(definition.parameters_json), "Parameter lineage differs")
    values = independent.numeric_metrics(record["candidate_metrics"])
    benchmark = independent.numeric_metrics(record["benchmark_metrics"])
    performance = m.PerformanceFacts(child.candidate, record["evaluation_id"], fact.scenario_context,
        values["NET_ANNUAL_RETURN"], values["DRAWDOWN_MAGNITUDE"], benchmark["NET_ANNUAL_RETURN"],
        benchmark["DRAWDOWN_MAGNITUDE"], index)
    return ParameterPerformanceEvidence(performance, ref.experiment.experiment_id, ref.sha256[:32],
        envelope["request_hash"], ref.sha256, fact.context_sha256, fact.window_id, fact.scenario_id,
        fact.metric_version, fact.initial_cash, fact.frequency_window_days, fingerprint,
        fact.candidate, canonical_sha256(derivation), m.AssessmentDerivationKind.PARAMETERS, binding.point)


def remove_panel_identity(panel):
    value = panel.to_dict()
    value.pop("request_sha256")
    value.pop("input_kind", None)
    return value


def comparison_for(request, panel, accepted, designs):
    targets = m.ResearchTargets.from_dict(read(WORK / "others/calmar_v2_targets.json"))
    policy = m.ComparisonPolicy.from_dict(accepted["policy"])
    common = m.CommonNeighborhoodComparisonContract(m.RelativeChangeLimit(.05), tuple(
        m.ZeroCenterAbsoluteLimit(name, m.AbsoluteChangeLimit(.05))
        for name in ("g_when_u", "g_when_other", "g_when_mf")))
    return compare_candidates(m.CalmarComparisonRequest(request.centers, targets, panel, policy, designs, common))


def independent_ranking(comparison, analysis, policy):
    eligible = {row.candidate.candidate_id.removeprefix("S017-"): row for row in comparison.rows
                if row.acceptance_status is m.TargetCheckStatus.PASSED}
    remaining, layer, checked = set(eligible), 1, {}
    maximize = {m.ResearchMetric.PARAMETER_CALMAR_Q10, m.ResearchMetric.ROLLING_EXCESS_CALMAR_Q10,
                m.ResearchMetric.FREQUENCY_MEDIAN}
    specs = {item.metric: item for item in policy.bins}
    while remaining:
        def dominates(left, right):
            a, b = (analysis["centers"][key]["ranking_inputs"] for key in (left, right))
            return (a["NET_CALMAR"] >= b["NET_CALMAR"] and a["DRAWDOWN_MAGNITUDE"] <= b["DRAWDOWN_MAGNITUDE"]
                    and (a["NET_CALMAR"] > b["NET_CALMAR"] or a["DRAWDOWN_MAGNITUDE"] < b["DRAWDOWN_MAGNITUDE"]))
        front = {key for key in remaining if not any(dominates(other, key) for other in remaining - {key})}
        require(bool(front), "Independent Pareto ordering failed")
        vectors = {}
        for key in front:
            inputs = analysis["centers"][key]["ranking_inputs"]
            vector, bins = [], []
            for metric in policy.ranking_metrics:
                spec = specs[metric]
                value = inputs[metric.value]
                require(value is not None and math.isfinite(value), "Independent rank has an unavailable metric")
                bucket = int(((Decimal(str(value)) - Decimal(str(spec.origin)))
                              / Decimal(str(spec.resolution))).to_integral_value(rounding=ROUND_FLOOR))
                bins.append(bucket)
                vector.append(-bucket if metric in maximize else bucket)
            require(tuple(bins) == eligible[key].bin_values, "Platform rank bin differs")
            vectors[key] = tuple(vector)
        for key in front:
            rank = 1 + sum(vectors[other] < vectors[key] for other in front)
            high = rank + sum(vectors[other] == vectors[key] for other in front) - 1
            row = eligible[key]
            require((row.pareto_layer, row.rank_in_layer, row.rank_min, row.rank_max) == (layer, rank, rank, high),
                    "Platform ranking differs from independent RAW Pareto and lexicographic bins")
            checked[key] = {"pareto_layer": layer, "rank_in_layer": rank, "rank_max": high}
        remaining -= front
        layer += 1
    return checked


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("acceptance", "final"))
    args = parser.parse_args()
    accepted = read(WORK / "others/calmar_v2_rsch_acceptance.json")
    protocol = m.CalmarSelfCheckProtocol.from_dict(accepted["protocol"])
    designs = tuple(m.ParameterNeighborhoodDesign.from_dict(read(
        WORK / "others/parameter_plans" / (key + ".json"))["design"]) for key in KEYS)
    plans = {key: d.ParameterEvaluationPlan.from_dict(read(
        WORK / "others/parameter_plans" / (key + ".json"))) for key in KEYS}
    standards = read(ROOT / "research/S017/experiments/EX072_20261102/others/all_accounts.json")
    pressures = read(WORK / "others/pressure.json")["records"]
    if args.mode == "final":
        require(read(WORK / "others/neighborhood_execution_v2.json")["status"]
                == "ALL_2829_POINTS_COMPLETED_CALMAR_V2", "All points must complete before final ranking")
        analysis = read(WORK / "others/complete_calmar_v2_analysis.json")
        index = read(WORK / "others/complete_calmar_v2_account_index.json")
        require(index["point_count"] == 2829 and analysis["all_N_complete"], "Complete independent analysis missing")
        require(all(sha256((ROOT / path).read_bytes()).hexdigest() == value
                    for path, value in analysis["source_hashes"].items()), "Independent analysis input bytes changed")
        records = index["points"]
        # The independent index uses metric names; retain original batch numeric inputs.
        raw = {}
        for item in records:
            batch = item["batch"]
            if batch not in raw:
                raw[batch] = {row["index"]: row for row in read(ROOT / batch)["records"]}
        records = [(item["center"], raw[item["batch"]][item["index"]]) for item in records]
    else:
        records = [(key, row) for key in ("C0338", "C0339") for row in read(
            WORK / "others/neighborhood_batches" / ("pilot2-" + key + ".json"))["records"]]
        require(len(records) == 4, "Acceptance must reuse exactly four published points")
    with EquityCertificationScope() as certification:
        facts = tuple(authenticate(standards[key]["evidence"], key, "STANDARD", .001) for key in KEYS)
        stresses = tuple(authenticate(pressures[key]["evidence"], key, "PRESSURE", .002) for key in KEYS)
        metadata = {key: published(standards[key]["evidence"])[1] for key in KEYS}
        baselines = dict(zip(KEYS, facts, strict=True))
        fingerprints = {key: assessment_benchmark_fingerprint(fact) for key, fact in baselines.items()}
        projections = tuple(projection(row, key, plans[key], baselines[key], metadata[key], fingerprints[key])
                            for key, row in records)
        links = tuple(m.PerturbationLink(item.parent, item.candidate, 1., item.derivation_sha256,
                                        item.parameter_point) for item in projections)
        base = m.CandidateAssessmentRequest(tuple(fact.candidate for fact in facts), protocol,
            links, (*facts, *stresses), parameter_designs=designs)
        numeric_request = CandidatePerformanceAssessmentRequest(base, projections)
        panel = assess_candidates(numeric_request)
        comparison = comparison_for(base, panel, accepted, designs)
        if args.mode == "acceptance":
            neighbors = tuple(authenticate(row["evidence"], row["candidate"], "STANDARD", .001) for _, row in records)
            require(tuple(project_parameter_performance(item) for item in neighbors) == projections,
                    "RSCH source preparation differs from standard projection of authenticated journals")
            full_request = replace(base, evidence=(*base.evidence, *neighbors))
            full_panel = assess_candidates(full_request)
            full_comparison = comparison_for(full_request, full_panel, accepted, designs)
            require(remove_panel_identity(panel) == remove_panel_identity(full_panel), "Numeric rows differ from raw-journal rows")
            left, right = comparison.to_dict(), full_comparison.to_dict()
            left.pop("request_sha256")
            right.pop("request_sha256")
            require(left == right, "Numeric comparison differs from raw-journal comparison")
            output = {"status": "PASS_RSCH_PERFORMANCE_INPUT_EQUIVALENCE", "replayed_accounts": 0,
                "reused_accounts": 16, "parameter_points": 4, "full_declared_neighborhood_count": 2829,
                "standard_projection_equals_source_preparation": True, "all_numeric_rows_and_comparison_equal": True,
                "request_identity_and_input_kind_intentionally_distinct": True,
                "numeric_request_sha256": numeric_request.sha256, "raw_request_sha256": full_request.sha256,
                "authenticated_unique_ledgers": certification.audit_count,
                "whole_request_TDR_FULL_claimed": False, "stage_four_complete": False}
            save(WORK / "others/complete_numeric_aggregation_rsch_acceptance.json", output)
            print(output["status"], flush=True)
            return
        require(read(WORK / "others/complete_numeric_aggregation_rsch_acceptance.json")["status"]
                == "PASS_RSCH_PERFORMANCE_INPUT_EQUIVALENCE", "Numeric capability must pass RSCH acceptance")
        for row in comparison.rows:
            key = row.candidate.candidate_id.removeprefix("S017-")
            expected = analysis["centers"][key]
            require(row.acceptance_status.value == expected["full_declared_economic_targets_status"], "Independent economic acceptance differs")
            require({check.target.target_id: check.status.value for check in row.target_checks}
                    == {check["target_id"]: check["status"] for check in expected["target_checks"]}, "Independent hard gate status differs")
            parameter_check = next(check for check in row.target_checks if isinstance(check.target, m.ParameterNeighborhoodTarget))
            require(parameter_check.joint_passes == expected["parameter_joint_passes"]
                    and parameter_check.valid_points == parameter_check.required_points == expected["N"]
                    and parameter_check.minimum_joint_passes == expected["parameter_minimum_joint_passes"],
                    "Independent parameter counts differ")
            result = next(item for item in panel.rows if item.candidate == row.candidate)
            require(result.parameter_context.prescribed_points == result.parameter_context.valid_points == expected["N"],
                    "Platform full-N coverage differs")
            metrics = {item.metric.value: item for item in result.diagnostics}
            name = "PARAMETER_DRAWDOWN_Q90"
            require(metrics[name].status is m.DiagnosticStatus.AVAILABLE
                    and math.isclose(metrics[name].value, expected["ranking_inputs"][name], rel_tol=1e-12, abs_tol=1e-12),
                    "Independent complete drawdown quantile differs")
            # Individual-Calmar Q10 belongs to v6 comparison, not the preserved
            # fourteen-item diagnostic schema. Verify its actual point inputs.
            ratios = [independent.calmar(item.annual_return, item.drawdown) for item in result.parameter_performances]
            require(len(ratios) == expected["N"] and all(value is not None for value in ratios),
                    "Full Calmar point inputs are unavailable")
            require(math.isclose(independent.quantile(ratios, .1),
                    expected["ranking_inputs"]["PARAMETER_CALMAR_Q10"], rel_tol=1e-12, abs_tol=1e-12),
                    "Independent complete Calmar quantile differs")
        checked = independent_ranking(comparison, analysis, m.ComparisonPolicy.from_dict(accepted["policy"]))
        require(all(sha256((ROOT / path).read_bytes()).hexdigest() == value
                    for path, value in analysis["source_hashes"].items()), "Independent analysis inputs changed during ranking")
        save(WORK / "others/complete_calmar_v2_performance_inputs.json", {"input_kind": "PERFORMANCE_PROJECTION",
            "numeric_request_sha256": numeric_request.sha256, "protocol": protocol.to_dict(),
            "centers": [item.to_dict() for item in base.centers],
            "baseline_sources": [{"candidate": key, "standard": standards[key]["evidence"], "pressure": pressures[key]["evidence"]} for key in KEYS],
            "parameter_evidence": [item.to_dict() for item in projections],
            "designs_and_sources": "research/S017/experiments/EX076_20261102/others/complete_calmar_v2_account_index.json",
            "whole_request_TDR_FULL_claimed": False})
        save(WORK / "others/complete_calmar_v2_panel.json", panel.to_dict())
        save(WORK / "others/complete_calmar_v2_comparison.json", comparison.to_dict())
        save(WORK / "others/complete_calmar_v2_rsch_verification.json", {"status": "PASS_COMPLETE_NUMERIC_RESEARCH_VERIFICATION",
            "point_count": len(projections), "complete_neighborhoods": {key: plans[key].design.point_count for key in KEYS},
            "independent_target_statuses_equal": True, "independent_quantiles_equal": True,
            "independent_ranking": checked, "formula_version": panel.formula_version,
            "ranking_version": accepted["policy"]["formula_version"], "input_kind": "PERFORMANCE_PROJECTION",
            "whole_request_TDR_FULL_claimed": False, "new_accounts_replayed_by_this_script": 0,
            "authenticated_baseline_unique_ledgers": certification.audit_count,
            "source_script_sha256": sha256((WORK / "src/complete_calmar_v2_ranking.py").read_bytes()).hexdigest(),
            "sealed_prices_accessed": False})
        print("COMPLETE_CALMAR_V2_PLATFORM_NUMERIC_RANKING_RSCH_VERIFIED", len(projections), checked, flush=True)
    gc.collect()


if __name__ == "__main__":
    main()
