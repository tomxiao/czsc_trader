"""Independently summarize complete, published neighborhoods without replay or SE row replacement.

Run only after both neighborhood directories contain every planned point. This
script verifies publication envelopes and immutable plans, not all ledger
artifacts. Its numeric results are RSCH analysis, never a whole-request TDR FULL
certification. Old batch joint_pass fields are deliberately never consumed.
"""
# ruff: noqa: E402
from __future__ import annotations

from collections import Counter
from decimal import Context, Decimal, localcontext
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".tmp/s017-stage4-final-calmar-v2"
sys.pycache_prefix = str(SCRATCH / "pycache")

import numpy as np
from czsc_trader import research_tools as d
from strategy_evaluator import research_models as m
from strategy_runtime import EquityStrategyDefinition

KEYS = ("C0338", "C0339", "C0340", "C0341", "C0342", "C0352")
PLANS = WORK / "others/parameter_plans"
BATCHES = (WORK / "others/neighborhood_batches", WORK / "others/neighborhood_batches_v2")
NONPARAMETER_FIELDS = (
    "window", "history_start", "instrument", "specification", "specification_hash",
    "initial_cash", "input_binding", "data_manifest", "sources", "warmup_bars",
    "benchmark", "benchmark_sha256", "frequency_window_days", "drawdown_basis", "concentration_basis",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open("rb") as stream:
        return sha256(stream.read()).hexdigest()


def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, f"Duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    return json.loads(path.read_bytes(), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"Nonfinite JSON: {value}")))


def relative(path):
    return path.resolve().relative_to(ROOT).as_posix()


def calmar(annual, drawdown):
    if drawdown <= 1e-12:
        return None
    value = annual / drawdown
    return value if math.isfinite(value) else None


def numeric_metrics(value):
    annual = value["annualized_return"]
    dd = value["drawdown"] if "drawdown" in value else value["bar_max_drawdown"]
    require(type(annual) in (float, int) and type(dd) in (float, int)
            and math.isfinite(annual) and math.isfinite(dd) and 0 <= dd <= 1,
            "Invalid finite performance summary")
    ratio = calmar(annual, dd)
    for name in ("calmar", "net_calmar"):
        if name in value:
            require(value[name] == ratio, f"Stored {name} differs from raw R/DD")
    return {"NET_ANNUAL_RETURN": annual, "DRAWDOWN_MAGNITUDE": dd, "NET_CALMAR": ratio}


def combine(checks):
    statuses = [item["status"] for item in checks]
    if "FAILED" in statuses:
        return "FAILED"
    if "INDETERMINATE" in statuses:
        return "INDETERMINATE"
    return "PASSED" if "PASSED" in statuses else "INDETERMINATE"


def scalar(target, values, benchmark, cost):
    result = {"target_id": target.target_id, "metric": target.metric.value,
              "observed": values.get(target.metric.value), "status": "INDETERMINATE",
              "resolved_lower": None, "resolved_upper": None, "condition_observed": None}
    if target.one_way_cost is not None and cost != target.one_way_cost:
        return {**result, "reason": "TARGET_COST_DIFFERS_OR_MISSING"}
    if target.when is not None:
        observed = benchmark.get(target.when.metric.value)
        result["condition_observed"] = observed
        if observed is None:
            return {**result, "reason": "MISSING_CONDITION_BENCHMARK"}
        condition = {"LT": lambda a, b: a < b, "LE": lambda a, b: a <= b,
                     "GT": lambda a, b: a > b, "GE": lambda a, b: a >= b}[target.when.operator.value]
        if not condition(observed, target.when.value):
            return {**result, "status": "NOT_APPLICABLE", "reason": "CONDITION_FALSE"}
    value = result["observed"]
    if value is None:
        return {**result, "reason": "UNAVAILABLE_METRIC"}
    for name, bound in (("resolved_lower", target.lower), ("resolved_upper", target.upper)):
        if isinstance(bound, m.BenchmarkBound):
            baseline = benchmark.get(target.metric.value)
            if baseline is None:
                return {**result, "reason": "MISSING_BOUND_BENCHMARK"}
            with localcontext(Context(prec=40)):
                result[name] = float(Decimal(str(baseline)) * Decimal(str(bound.multiplier)))
            require(math.isfinite(result[name]), "Nonfinite benchmark boundary")
        elif bound is not None:
            result[name] = bound.value
    lower, upper = result["resolved_lower"], result["resolved_upper"]
    passed = ((lower is None or (value >= lower if target.lower.inclusive else value > lower))
              and (upper is None or (value <= upper if target.upper.inclusive else value < upper)))
    return {**result, "status": "PASSED" if passed else "FAILED",
            "reason": None if passed else "TARGET_NOT_MET"}


def envelope(reference, candidate, identity, evaluation_id, request_hash):
    ref = d.EvidenceRef.from_dict(reference)
    require(ref.experiment.strategy_id == "S017" and ref.schema == "equity_research" and ref.schema_version == 4,
            "Only same-batch published V4 envelopes are allowed")
    # resolve verifies the publication bytes. No materialize/build-assessment or
    # ledger artifact resolver is invoked anywhere in this script.
    path = ref.resolve(ROOT)
    value = read(path)
    request = value["request"]
    require(value["schema_version"] == 4 and value["evaluation_id"] == evaluation_id
            and value["request_hash"] == request_hash, "Published envelope identity differs")
    require(request["candidate_id"] == candidate and request["implementation_hash"] == identity,
            "Published candidate content differs")
    require(request["experiment"]["strategy_id"] == "S017", "Envelope belongs to another batch")
    return value, request


def same_nonparameter(request, center):
    require(all(request[name] == center[name] for name in NONPARAMETER_FIELDS),
            "Window/input/execution/benchmark contract changed")


def point_identity(plan, index):
    child = plan.children[index]
    payload = json.loads(child.payload_json)
    definition = EquityStrategyDefinition.from_dict(payload["equity_definition"])
    identity = definition.content_identity.content_sha256
    require(child.candidate.content_sha256 == child.runtime_identity_sha256 == identity,
            "Planned point payload identity differs")
    parameters = {item.name: item.value for item in plan.design.points[index].values}
    require(json.loads(definition.parameters_json) == parameters, "Point parameters differ from complete design")
    return child, definition, sha256(child.payload_json.encode("utf-8")).hexdigest()


def quantile(values, level):
    require(values and all(value is not None and math.isfinite(value) for value in values),
            "Incomplete/unavailable values must never be dropped from a quantile")
    with np.errstate(over="ignore", invalid="ignore"):
        result = float(np.quantile(values, level, method="linear"))
    return result if math.isfinite(result) else None


def read_inputs():
    paths = [WORK / "others/calmar_v2_targets.json", PLANS / "index.json",
             ROOT / "research/S017/experiments/EX074_20261102/others/analysis.json",
             WORK / "others/pressure.json", WORK / "others/calmar_v2_acceptance_panel.json",
             WORK / "others/calmar_v2_rsch_acceptance.json",
             WORK / "others/neighborhood_execution_v2.json", Path(__file__).resolve()]
    hashes = {relative(path): digest(path) for path in paths}
    rules = m.ResearchTargets.from_dict(read(paths[0]))
    groups = [target for target in rules.requirements if isinstance(target, m.ParameterNeighborhoodTarget)]
    require(len(groups) == 1, "Exactly one declared parameter-neighborhood target is required")
    allowed = {"NET_CALMAR", "NET_ANNUAL_RETURN", "DRAWDOWN_MAGNITUDE", "FREQUENCY_MEDIAN"}
    for target in rules.requirements:
        atoms = (*target.joint_targets, *target.all_point_targets) if isinstance(target, m.ParameterNeighborhoodTarget) else (target,)
        for atom in atoms:
            require(isinstance(atom, (m.ResearchTarget, m.FrequencyCoverageTarget)), "Unsupported target type")
            if isinstance(atom, m.ResearchTarget):
                require(atom.metric.value in allowed, "Unsupported explicit scalar target; no approximation allowed")
    centers = {row["candidate_id"]: row for row in read(paths[2])["results"] if row["candidate_id"] in KEYS}
    pressure = read(paths[3])["records"]
    panel = m.AssessmentPanel.from_dict(read(paths[4]))
    require(panel.formula_version == "research-assessment-v8", "Calmar acceptance panel must remain v8")
    accepted = read(paths[5])
    require(accepted["status"] == "PASS_CALCULATION_CAPABILITY_ACCEPTANCE", "Prior RSCH calculation acceptance missing")
    execution = read(paths[6])
    require(execution["status"] == "ALL_2829_POINTS_COMPLETED_CALMAR_V2" and not execution["failed_batches"],
            "Final statistics require the completed Calmar-v2 execution and no failed batches")
    return rules, groups[0], centers, pressure, panel, accepted, execution, hashes


def load_plans(centers, hashes):
    catalog = read(PLANS / "index.json")
    require(set(catalog["plans"]) == set(KEYS), "Prospective plan catalog center scope differs")
    contract = m.CommonNeighborhoodComparisonContract(m.RelativeChangeLimit(.05), tuple(
        m.ZeroCenterAbsoluteLimit(name, m.AbsoluteChangeLimit(.05))
        for name in ("g_when_u", "g_when_other", "g_when_mf")))
    plans, references, headers = {}, {}, {}
    common = None
    for key in KEYS:
        path, ref_path = PLANS / (key + ".json"), PLANS / (key + "-reference.json")
        hashes.update({relative(path): digest(path), relative(ref_path): digest(ref_path)})
        description = read(ref_path)
        require(description == catalog["plans"][key], "Plan reference differs from prospective index")
        reference = d.EvidenceRef.from_dict(description["reference"])
        require(reference.experiment.strategy_id == "S017", "Plan belongs to another batch")
        require(reference.resolve(ROOT).read_bytes() == path.read_bytes(), "Published plan bytes changed")
        plan = d.ParameterEvaluationPlan.from_dict(read(path))
        require(plan.design.center == plan.center.candidate and plan.design.center.candidate_id == "S017-" + key,
                "Plan center identity differs")
        require(plan.design.point_count == description["N"] and plan.design.sha256 == description["design_sha256"],
                "True design N/hash changed")
        semantic = contract.authenticate(plan.design)
        require(common is None or semantic == common, "Common construction contract changed")
        common = semantic
        original = centers[key]["record"]
        require(description["center_reused"] == original["evidence"]
                and plan.center_request_sha256 == original["request_hash"], "Plan no longer reuses original center")
        _, header = envelope(original["evidence"], key, plan.center.candidate.content_sha256,
                             original["evaluation_id"], original["request_hash"])
        require(header["candidate_definition"] == json.loads(plan.center.payload_json)["equity_definition"],
                "Center definition differs from prospective plan")
        plans[key], references[key], headers[key] = plan, reference, header
    require(sum(plan.design.point_count for plan in plans.values()) == catalog["point_count"], "Plan catalog N differs")
    return plans, references, headers, contract


def collect_points(plans, references, headers, parameter_target, hashes):
    covered = {key: {} for key in KEYS}
    counts = Counter()
    evaluation_ids, request_hashes, candidate_ids = set(), set(), set()
    for folder in BATCHES:
        for path in sorted(folder.glob("*.json")):
            batch = read(path)
            hashes[relative(path)] = digest(path)
            if batch["status"] == "PREPARATION_TYPE_COMPARISON_FAILED_ZERO_ACCOUNTS":
                require(not batch.get("records"), "A zero-account preparation failure contains account records")
                continue
            require(batch["status"] == "COMPLETED", f"Unfinished/failed batch blocks final analysis: {relative(path)}")
            key = batch["center"]
            require(key in plans and batch["full_N"] == plans[key].design.point_count, "Batch center/N differs")
            require(batch["point_count"] == len(batch["records"]) == len(batch["indices"]), "Batch count differs")
            require(sorted(row["index"] for row in batch["records"]) == sorted(batch["indices"]), "Batch indices differ")
            plan, reference = plans[key], references[key]
            for row in batch["records"]:
                index = row["index"]
                require(type(index) is int and 0 <= index < plan.design.point_count and index not in covered[key],
                        f"Duplicate/out-of-range planned point: {key}/{index}")
                child, definition, payload_sha = point_identity(plan, index)
                require(child.candidate.candidate_id == "S017-" + row["candidate"]
                        and child.candidate.content_sha256 == row["identity"], "Point candidate identity differs")
                binding = d.ParameterEvaluationBinding.from_dict(row["parameter_binding"])
                require(binding.plan == reference and binding.point == plan.design.bind_point(index),
                        "Point binding changed from prospective plan")
                meta, header = envelope(row["evidence"], row["candidate"], row["identity"],
                                        row["evaluation_id"], row["request_hash"])
                same_nonparameter(header, headers[key])
                require(header["fee_rate"] == headers[key]["fee_rate"]
                        and (header["window_id"], header["scenario_id"], header["measurement_tier"])
                        == (headers[key]["window_id"], headers[key]["scenario_id"], headers[key]["measurement_tier"]),
                        "Point cost/scenario differs from its standard center")
                require(header["candidate_definition"] == json.loads(child.payload_json)["equity_definition"],
                        "Executed definition differs from point payload")
                require(header["lineage"]["parameter_binding"] == row["parameter_binding"], "Envelope parameter binding differs")
                derivation = header["lineage"]["derivation"]
                require(derivation["kind"] == "PARAMETERS" and derivation["parent"]["candidate_id"] == key
                        and derivation["parent_content_sha256"] == plan.center.candidate.content_sha256
                        and derivation["child"]["candidate_id"] == row["candidate"]
                        and derivation["child_content_sha256"] == row["identity"]
                        and derivation["changes"] == json.loads(definition.parameters_json), "Executed parameter derivation differs")
                for value, seen in ((row["evaluation_id"], evaluation_ids), (row["request_hash"], request_hashes),
                                    (row["candidate"], candidate_ids)):
                    require(value not in seen, "Duplicate account identity across neighborhoods")
                    seen.add(value)
                candidate_values, benchmark_values = numeric_metrics(row["candidate_metrics"]), numeric_metrics(row["benchmark_metrics"])
                joint = [scalar(target, candidate_values, benchmark_values, header["fee_rate"])
                         for target in parameter_target.joint_targets]
                all_points = [scalar(target, candidate_values, benchmark_values, header["fee_rate"])
                              for target in parameter_target.all_point_targets]
                covered[key][index] = {
                    "center": key, "index": index, "candidate": row["candidate"], "identity": row["identity"],
                    "point_payload_bytes_sha256": payload_sha, "runtime_identity_sha256": child.runtime_identity_sha256,
                    "evidence": row["evidence"], "evaluation_id": row["evaluation_id"], "request_hash": row["request_hash"],
                    "parameter_binding": row["parameter_binding"], "candidate_metrics": candidate_values,
                    "benchmark_metrics": benchmark_values, "joint_checks": joint, "all_point_checks": all_points,
                    "joint_status": combine(joint), "all_point_status": combine(all_points),
                    "batch": relative(path), "candidate_artifact": meta["candidate_ref"],
                    "benchmark_artifact": meta["benchmark_ref"], "input_artifact": meta["input_ref"],
                }
                counts[folder.name] += 1
                processed = sum(counts.values())
                if processed % 64 == 0:
                    print("CALMAR_V2_ANALYSIS_METADATA_POINTS", processed,
                          sum(item.design.point_count for item in plans.values()), flush=True)
    for key, plan in plans.items():
        missing = sorted(set(range(plan.design.point_count)) - set(covered[key]))
        require(not missing, f"Incomplete N for {key}: {len(missing)} missing; first indices {missing[:12]}")
    return covered, dict(counts)


def verify_reuse(points, plans, execution, counts, hashes):
    """Cold-audit receipts corroborate old points; they never add another point."""
    expected = {(key, index) for key in KEYS for index, item in points[key].items()
                if item["batch"].startswith(relative(BATCHES[0]) + "/")}
    checked = set()
    for path in sorted((WORK / "others/neighborhood_reuse_v2").glob("*.json")):
        value = read(path)
        hashes[relative(path)] = digest(path)
        require(value["status"] == "COMPLETED" and value["mode"] == "REUSE", "Incomplete cold-reuse audit")
        key = value["center"]
        require(key in plans and value["full_N"] == plans[key].design.point_count, "Reuse plan/N differs")
        require(value["point_count"] == len(value["records"]) == len(value["indices"]), "Reuse count differs")
        require(sorted(row["index"] for row in value["records"]) == sorted(value["indices"]), "Reuse indices differ")
        for record in value["records"]:
            coordinate = (key, record["index"])
            require(coordinate in expected and coordinate not in checked, "Unexpected/duplicate cold-reuse point")
            original = points[key][record["index"]]
            require(all(record[name] == original[name] for name in (
                "candidate", "identity", "evidence", "evaluation_id", "request_hash", "parameter_binding")),
                "Cold-reuse account identity differs")
            require(numeric_metrics(record["candidate_metrics"]) == original["candidate_metrics"]
                    and numeric_metrics(record["benchmark_metrics"]) == original["benchmark_metrics"],
                    "Cold-reuse financial metrics differ")
            checked.add(coordinate)
    require(checked == expected, "Not all old points have completed independent cold-reuse audit receipts")
    total = sum(len(value) for value in points.values())
    require(execution["reuse_verified_points"] == len(checked) == counts.get(BATCHES[0].name, 0),
            "Reuse execution count differs")
    require(execution["new_published_points"] == counts.get(BATCHES[1].name, 0)
            and execution["completed_points"] == execution["total_points"] == total,
            "Completed/new published count differs")
    return len(checked)


def summarize(rules, parameter_target, centers, pressure, panel, accepted, plans, headers, points):
    rows = {row.candidate.candidate_id.removeprefix("S017-"): row for row in panel.rows}
    diagnostics = {item["candidate"].removeprefix("S017-"): item for item in accepted["independently_verified_centers"]}
    results = {}
    for key in KEYS:
        row, standard, tested = rows[key], centers[key], pressure[key]
        values, benchmark = numeric_metrics(standard["candidate"]), numeric_metrics(standard["benchmark"])
        values["FREQUENCY_MEDIAN"] = standard["candidate"]["rolling_60_closed_cycle_median"]
        coverage = row.frequency_coverage
        require(coverage is not None and row.frequency_window_days == rules.frequency_window_days,
                "Standard frequency evidence/window differs")
        require((coverage.total_windows, coverage.covered_windows) == (
            standard["candidate"]["frequency_windows"], standard["candidate"]["covered_windows"]), "Frequency counts differ")
        require(row.candidate == plans[key].center.candidate, "Accepted baseline identity changed")
        meta, stress_header = envelope(tested["evidence"], key, row.candidate.content_sha256,
                                       tested["evaluation_id"], tested["request_hash"])
        same_nonparameter(stress_header, headers[key])
        require(stress_header["candidate_definition"] == headers[key]["candidate_definition"]
                and stress_header["scenario_id"] != headers[key]["scenario_id"]
                and stress_header["measurement_tier"] == "STRESS"
                and stress_header["fee_rate"] > headers[key]["fee_rate"], "Pressure contract is incompatible")
        require(tested["evaluation_identity"]["content_sha256"] == row.candidate.content_sha256,
                "Pressure candidate identity changed")
        stress_values, stress_benchmark = numeric_metrics(tested["candidate"]), numeric_metrics(tested["benchmark"])
        checks = []
        for target in rules.requirements:
            if isinstance(target, m.ParameterNeighborhoodTarget):
                continue
            if isinstance(target, m.FrequencyCoverageTarget):
                require((target.window_days, target.minimum_closed_cycles)
                        == (coverage.window_days, coverage.minimum_closed_cycles), "Coverage contract changed")
                status = "INDETERMINATE" if coverage.total_windows == 0 else (
                    "PASSED" if coverage.covered_windows * target.minimum_denominator
                    >= coverage.total_windows * target.minimum_numerator else "FAILED")
                checks.append({"target_id": target.target_id, "status": status,
                               "covered_windows": coverage.covered_windows, "total_windows": coverage.total_windows})
            elif target.scope is m.TargetScope.STRESS:
                checks.append(scalar(target, stress_values, stress_benchmark, stress_header["fee_rate"]))
            else:
                checks.append(scalar(target, values, benchmark, headers[key]["fee_rate"]))
        ordered = [points[key][index] for index in range(plans[key].design.point_count)]
        n = len(ordered)
        minimum = (n * parameter_target.minimum_numerator + parameter_target.minimum_denominator - 1) // parameter_target.minimum_denominator
        joint = sum(item["joint_status"] == "PASSED" for item in ordered)
        all_failures = [item["index"] for item in ordered if item["all_point_status"] == "FAILED"]
        unavailable = [item["index"] for item in ordered if "INDETERMINATE" in (item["joint_status"], item["all_point_status"])]
        parameter_status = "FAILED" if all_failures else "INDETERMINATE" if unavailable else "PASSED" if joint >= minimum else "FAILED"
        checks.append({"target_id": parameter_target.target_id, "status": parameter_status,
                       "N": n, "minimum_joint_passes": minimum, "joint_passes": joint,
                       "all_point_failures": all_failures, "unavailable_indices": unavailable})
        calmars = [item["candidate_metrics"]["NET_CALMAR"] for item in ordered]
        unavailable_calmar = [index for index, value in enumerate(calmars) if value is None]
        calmar_q10 = None if unavailable_calmar else quantile(calmars, .1)
        dd_q90 = quantile([item["candidate_metrics"]["DRAWDOWN_MAGNITUDE"] for item in ordered], .9)
        rolling = diagnostics[key]
        require(row.rolling_calmar_excess_q10 is not None
                and row.rolling_calmar_excess_q10.value == rolling["rolling_excess_calmar_q10"], "Accepted rolling value changed")
        require(quantile(rolling["rolling_excess_calmar_windows"], .1) == rolling["rolling_excess_calmar_q10"],
                "Accepted rolling windows/Q10 differ")
        loss = None if values["NET_CALMAR"] is None or stress_values["NET_CALMAR"] is None else values["NET_CALMAR"] - stress_values["NET_CALMAR"]
        require(loss is None or math.isfinite(loss), "Pressure Calmar difference overflow")
        require(loss is not None and math.isclose(loss, rolling["pressure_calmar_loss"], rel_tol=1e-12, abs_tol=1e-12),
                "Pressure summary differs from prior independent account acceptance")
        concentration = next(x for x in row.diagnostics if x.metric is m.ResearchMetric.PROFIT_CONCENTRATION)
        results[key] = {
            "identity": row.candidate.to_dict(), "N": n, "design_sha256": plans[key].design.sha256,
            "comparison_sha256": plans[key].design.comparison_sha256,
            "center_metrics": values, "benchmark_metrics": benchmark,
            "pressure_metrics": stress_values, "pressure_benchmark_metrics": stress_benchmark,
            "target_checks": checks, "full_declared_economic_targets_status": combine(checks),
            "parameter_joint_passes": joint, "parameter_minimum_joint_passes": minimum,
            "parameter_all_point_failure_indices": all_failures,
            "parameter_calmar_unavailable_indices": unavailable_calmar,
            "parameter_calmar_q10_status": "AVAILABLE" if calmar_q10 is not None else "INSUFFICIENT_DATA",
            "parameter_calmar_q10_reason": None if calmar_q10 is not None else (
                "UNAVAILABLE_POINT_CALMAR" if unavailable_calmar else "NONFINITE_QUANTILE"),
            "ranking_inputs": {"NET_CALMAR": values["NET_CALMAR"], "DRAWDOWN_MAGNITUDE": values["DRAWDOWN_MAGNITUDE"],
                "PARAMETER_CALMAR_Q10": calmar_q10, "PARAMETER_DRAWDOWN_Q90": dd_q90,
                "ROLLING_EXCESS_CALMAR_Q10": rolling["rolling_excess_calmar_q10"], "STRESS_CALMAR_LOSS": loss,
                "PROFIT_CONCENTRATION": concentration.value, "FREQUENCY_MEDIAN": values["FREQUENCY_MEDIAN"]},
            "center_evidence": standard["record"]["evidence"], "pressure_evidence": tested["evidence"],
            "pressure_candidate_artifact": meta["candidate_ref"],
        }
    return results


def write_outputs(values):
    encoded = {path: (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
               for path, value in values.items()}
    for path, data in encoded.items():
        require(not path.exists() or path.read_bytes() == data, f"Refusing to overwrite different final analysis: {path}")
    SCRATCH.mkdir(parents=True, exist_ok=True)
    for path, data in encoded.items():
        if path.exists():
            continue
        temporary = SCRATCH / (path.name + ".staging")
        temporary.write_bytes(data)
        os.replace(temporary, path)


def main():
    rules, parameter, centers, pressure, panel, accepted, execution, hashes = read_inputs()
    plans, references, headers, contract = load_plans(centers, hashes)
    points, counts = collect_points(plans, references, headers, parameter, hashes)
    reused = verify_reuse(points, plans, execution, counts, hashes)
    results = summarize(rules, parameter, centers, pressure, panel, accepted, plans, headers, points)
    require(all(digest(ROOT / path) == expected for path, expected in hashes.items()), "An input changed during finalization")
    index_path = WORK / "others/complete_calmar_v2_account_index.json"
    index = {"schema": "s017-complete-calmar-v2-account-index/v1", "status": "COMPLETE_METADATA_VERIFIED",
             "point_count": sum(len(value) for value in points.values()), "batch_directory_counts": counts,
             "plans": {key: references[key].to_dict() for key in KEYS},
             "points": [points[key][i] for key in KEYS for i in sorted(points[key])],
             "independent_cold_reuse_audit_receipts_verified": reused,
             "ledger_artifacts_reaudited_by_this_script": False}
    summary = {"schema": "s017-complete-calmar-v2-rsch-analysis/v1", "status": "COMPLETE_RSCH_NUMERIC_ANALYSIS",
        "source_hashes": hashes, "targets": rules.to_dict(), "common_comparison_contract": contract.to_dict(),
        "point_count": index["point_count"], "batch_directory_counts": counts, "centers": results,
        "independent_cold_reuse_audit_receipts_verified": reused,
        "all_N_complete": True, "quantile_method": "LINEAR_ALL_POINTS_EQUAL_WEIGHT",
        "account_index": relative(index_path),
        "qualified_under_declared_economic_targets": [key for key in KEYS if results[key]["full_declared_economic_targets_status"] == "PASSED"],
        "new_account_replays": 0, "new_searches": 0, "sealed_prices_accessed": False,
        "research_readiness": "DECLARED_ECONOMIC_CONDITIONS_ONLY_NOT_FINAL_SELECTION",
        "official_SE_ranking_run": False, "whole_request_TDR_FULL_claimed": False,
        "verification_scope": "RSCH independent scalar target/quantile arithmetic over previously published TDR outcomes; envelope hashes, complete plans, point payloads and bindings verified sequentially; no ledger artifact loading or SE panel replacement",
        "remaining_formal_limit": "This independent analysis does not invoke SE ranking. The separately accepted performance-input SE API can compute numeric ranking; neither output is a whole-request TDR journal FULL certification or an automatic final selection."}
    write_outputs({index_path: index, WORK / "others/complete_calmar_v2_analysis.json": summary})
    print("COMPLETE_CALMAR_V2_RSCH_ANALYSIS", index["point_count"], summary["qualified_under_declared_economic_targets"], flush=True)


if __name__ == "__main__":
    main()
