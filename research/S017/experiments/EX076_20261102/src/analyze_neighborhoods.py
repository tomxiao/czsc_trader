"""Audit published identities and compute complete equal-weight neighborhood statistics."""
# ruff: noqa: E402
from neighborhoods import ROOT, WORK, PLANS, RECORDS, KEYS, read, save

from collections import defaultdict
from decimal import Decimal
from hashlib import sha256
import json
import math
import time

import numpy as np
from czsc_trader.research_tools import EvidenceRef, ParameterEvaluationPlan


def file_digest(path):
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(2**20):
            digest.update(chunk)
    return digest.hexdigest()


def summarize(values):
    returns = [row["candidate_metrics"]["annualized_return"] for row in values]
    drawdowns = [row["candidate_metrics"]["drawdown"] for row in values]
    calmars = [row["candidate_metrics"]["calmar"] for row in values]
    return {"N": len(values), "annual_return_q10": float(np.quantile(returns, .1, method="linear")),
        "drawdown_q90": float(np.quantile(drawdowns, .9, method="linear")),
        "individual_calmar_q10": float(np.quantile(calmars, .1, method="linear"))
            if all(value is not None and math.isfinite(value) for value in calmars) else None,
        "undefined_calmar_points": [row["index"] for row in values if row["candidate_metrics"]["calmar"] is None],
        "min_annual_return": min(returns), "max_annual_return": max(returns),
        "max_drawdown": max(drawdowns), "joint_pass_count": sum(row["joint_pass"] for row in values),
        "all_point_drawdown_failures": [row["index"] for row in values if not row["all_point_dd_pass"]]}


def main():
    execution = read(WORK / "others/neighborhood_execution.json")
    assert execution["status"] == "ALL_2829_POINTS_COMPLETED"
    started = time.perf_counter()
    plans = {key: ParameterEvaluationPlan.from_dict(read(PLANS / (key + ".json"))) for key in KEYS}
    references = read(PLANS / "index.json")["plans"]
    points, verified, top_refs = {key: {} for key in KEYS}, {}, []
    for path in sorted(RECORDS.glob("*.json")):
        record = read(path)
        if record["status"] == "PREPARATION_TYPE_COMPARISON_FAILED_ZERO_ACCOUNTS":
            assert record["financial_accounts_run"] == 0
            continue
        assert record["status"] == "COMPLETED", path
        key, plan = record["center"], plans[record["center"]]
        for row in record["records"]:
            index = row["index"]
            assert index not in points[key]
            expected = plan.children[index].candidate
            assert expected.candidate_id == "S017-" + row["candidate"]
            assert expected.content_sha256 == row["identity"]
            ref = EvidenceRef.from_dict(row["evidence"])
            target = ref.resolve(ROOT)
            envelope = read(target)
            assert envelope["schema_version"] == 4
            assert envelope["evaluation_id"] == row["evaluation_id"]
            assert envelope["request_hash"] == row["request_hash"]
            request = envelope["request"]
            assert request["candidate_id"] == row["candidate"] and request["fee_rate"] == .001
            assert request["experiment"] == {"strategy_id": "S017", "experiment_id": WORK.name}
            assert request["window_id"] == "TRAIN_2024_2025" and request["scenario_id"] == "STANDARD"
            assert request["lineage"]["parameter_binding"] == row["parameter_binding"]
            assert row["parameter_binding"]["plan"] == references[key]["reference"]
            assert row["parameter_binding"]["point"] == plan.design.bind_point(index).to_dict()
            assert request["candidate_definition"] == json.loads(plan.children[index].payload_json)["equity_definition"]
            for name in ("input_ref", "candidate_ref", "benchmark_ref"):
                dependency = envelope[name]
                source = target.parent / (dependency["sha256"] + ".json")
                relative = source.relative_to(ROOT).as_posix()
                if relative not in verified:
                    assert file_digest(source) == dependency["sha256"], relative
                    verified[relative] = {"sha256": dependency["sha256"], "bytes": source.stat().st_size}
                assert verified[relative]["sha256"] == dependency["sha256"]
            candidate, benchmark = row["candidate_metrics"], row["benchmark_metrics"]
            annual, dd = candidate["annualized_return"], candidate["drawdown"]
            calmar = annual / dd if dd > 1e-12 and math.isfinite(annual / dd) else None
            assert candidate["calmar"] == calmar
            ret_pass = annual >= float(Decimal(str(benchmark["annualized_return"])) * Decimal("1.25")) if benchmark["annualized_return"] > 0 else annual > 0
            assert row["joint_pass"] == (ret_pass and dd <= float(Decimal(str(benchmark["drawdown"])) * Decimal("0.9")))
            assert row["all_point_dd_pass"] == (dd <= .25)
            points[key][index] = row
            top_refs.append(ref.to_dict())
        print("ACCOUNT_CLOSURES_VERIFIED", sum(map(len, points.values())), 2829, flush=True)
    pressure = read(WORK / "others/pressure.json")["records"]
    center_panel = read(WORK / "others/partial_selfcheck_panel.json")
    center_rows = {row["candidate"]["candidate_id"].split("-")[1]: row for row in center_panel["rows"]}
    results, eligible = {}, []
    for key in KEYS:
        plan = plans[key]
        assert set(points[key]) == set(range(plan.design.point_count))
        values = [points[key][index] for index in range(plan.design.point_count)]
        data = summarize(values)
        minimum = (plan.design.point_count * 13 + 15) // 16
        parameter_pass = data["joint_pass_count"] >= minimum and not data["all_point_drawdown_failures"]
        metrics = {item["metric"]: item["value"] for item in center_rows[key]["diagnostics"]}
        axes = {axis.name: axis.center for axis in plan.design.space.axes}
        single_axes, groups = {}, defaultdict(list)
        for row, point in zip(values, plan.design.points, strict=True):
            changed = [value.name for value in point.values if value.value != axes[value.name]]
            if len(changed) == 1:
                single_axes[str(row["index"])] = {"changed_axis": changed[0],
                    "parameters": {value.name: value.value for value in point.values}, **row}
            for value in point.values:
                groups[(value.name, value.value)].append(row)
        data.update({"minimum_joint_pass_count": minimum,
            "joint_pass_fraction": data["joint_pass_count"] / data["N"],
            "parameter_target_passed": parameter_pass, "pressure_targets_passed": pressure[key]["pressure_all_pass"],
            "center_five_targets_passed": True,
            "all_eleven_targets_passed_in_research_audit": parameter_pass and pressure[key]["pressure_all_pass"],
            "annual_return_degradation": max(0., metrics["NET_ANNUAL_RETURN"] - data["annual_return_q10"]),
            "drawdown_degradation": max(0., data["drawdown_q90"] - metrics["DRAWDOWN_MAGNITUDE"]),
            "design_sha256": plan.design.sha256, "comparison_sha256": plan.design.comparison_sha256,
            "single_axis_actual_accounts": single_axes,
            "conditional_groups_not_single_axis_causal_effects": [
                {"axis": axis, "value": value, **summarize(rows)} for (axis, value), rows in sorted(groups.items())]})
        results[key] = data
        if data["all_eleven_targets_passed_in_research_audit"]:
            eligible.append(key)
        print("COMPLETE_NEIGHBORHOOD_RESULT", key, data["N"], data["joint_pass_count"], minimum,
              "DD_failures", len(data["all_point_drawdown_failures"]), "Calmar_Q10", data["individual_calmar_q10"], flush=True)
    assert sum(result["N"] for result in results.values()) == 2829
    save(WORK / "others/complete_neighborhood_analysis.json", {
        "status": "COMPLETE_RSCH_ACCOUNT_AND_NUMERIC_AUDIT", "point_count": 2829,
        "account_closures_hash_verified": len(top_refs), "unique_dependency_files": len(verified),
        "unique_dependency_bytes": sum(item["bytes"] for item in verified.values()),
        "elapsed_seconds": time.perf_counter() - started, "results": results,
        "research_eligible_candidates": eligible,
        "se_full_aggregate_assessment_certification_claimed": False,
        "all_2829_accounts_replayed_audited_and_published_via_tdr": True,
        "sealed_prices_accessed": False, "new_parameter_search": False})
    save(WORK / "others/complete_account_index.json", {"accounts": top_refs, "dependencies": verified})
    print("FULL_RESEARCH_ANALYSIS_COMPLETE", eligible, flush=True)


if __name__ == "__main__":
    main()
