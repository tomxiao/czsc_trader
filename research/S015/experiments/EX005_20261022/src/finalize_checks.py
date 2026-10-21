"""Independently check the completed S015 assessment from compact saved records.

No account execution or full account-evidence reread is performed. Numeric input
provenance is joined to build_assessment's authenticated_sources manifest; the
public evidence authentication and FULL delivery validation remain separate.
"""
from collections import Counter
from decimal import Decimal
from hashlib import sha256
import json
import math
from pathlib import Path
import subprocess
import sys

from czsc_trader.research_tools import EvidenceRef


ROOT = Path(__file__).resolve().parents[5]
EROOT = ROOT / "research/S015/experiments/EX005_20261022"
WORK = ROOT / "research/S015/assets/runs/EX005_20261022/assessment"
PROTOCOL_SHA256 = "3e605e9761c39d541bb928d4f677e49e9e84c9ec0c62bb2cdd6374893fdaa416"
MAPPING_SHA256 = "8e7cdf43cf0157c7e0170fda5df6eaae7363bb16112c0023cda42d7862105ef2"
CONSTRAINTS_SHA256 = "b14bee89e8a0349c3505cacca77c4edb9b610b613da1fd45a7584de316bfe441"
UNAVAILABLE = {"C0030", "C0062"}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def close(actual, expected, label):
    require(isinstance(actual, (int, float)) and math.isfinite(actual), f"{label}: not finite")
    require(math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12),
            f"{label}: {actual} != {expected}")


def product(value, multiplier):
    return float(Decimal(str(value)) * Decimal(str(multiplier)))


def quantile(values, probability):
    """Linear interpolation on the ordered sample, independently of SE/NumPy."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])


def status(passed):
    return "PASSED" if passed else "FAILED"


def facts(row):
    observation = row["observation"]
    annual = observation["net_cagr"]
    drawdown = -observation["max_drawdown"]
    benchmark_annual = row["benchmark_cagr"]
    benchmark_drawdown = -row["benchmark_metrics"]["max_drawdown"]
    require(all(math.isfinite(value) for value in (annual, drawdown, benchmark_annual, benchmark_drawdown)),
            f"{row['candidate_id']}: nonfinite account metric")
    require(0 <= drawdown <= 1 and 0 <= benchmark_drawdown <= 1, "invalid drawdown magnitude")
    close(benchmark_annual, (1 + row["benchmark_metrics"]["return"]) ** (252 / 434) - 1,
          f"{row['candidate_id']} benchmark CAGR")
    return annual, drawdown, benchmark_annual, benchmark_drawdown


def center_checks(row):
    annual, drawdown, benchmark_annual, benchmark_drawdown = facts(row)
    frequency = row["frequency"]
    return {
        "center-positive": status(annual >= product(benchmark_annual, 1.5)) if benchmark_annual > 0 else "NOT_APPLICABLE",
        "center-nonpositive": status(annual > 0) if benchmark_annual <= 0 else "NOT_APPLICABLE",
        "center-relative-dd": status(drawdown <= product(benchmark_drawdown, .8)),
        "center-cap": status(drawdown <= .25),
        "median": status(frequency["median"] >= 6),
        "coverage": status(frequency["windows_at_least_3"] * 10 >= frequency["windows"] * 9),
    }


def stress_checks(row):
    annual, drawdown, benchmark_annual, benchmark_drawdown = facts(row)
    require(row["actual_cost"] == .002, "stress is not the prescribed actual cost")
    return {
        "stress-profit": status(annual > 0),
        "stress-excess": status(annual > benchmark_annual),
        "stress-dd-positive": status(drawdown < benchmark_drawdown) if benchmark_drawdown > 0 else "NOT_APPLICABLE",
        "stress-dd-zero": status(drawdown <= 0) if benchmark_drawdown <= 0 else "NOT_APPLICABLE",
        "stress-cap": status(drawdown <= .25),
    }


def point_checks(row):
    annual, drawdown, benchmark_annual, benchmark_drawdown = facts(row)
    require(row["actual_cost"] == .001, "parameter point changed standard cost")
    joint = {
        "point-positive": status(annual >= product(benchmark_annual, 1.25)) if benchmark_annual > 0 else "NOT_APPLICABLE",
        "point-nonpositive": status(annual > 0) if benchmark_annual <= 0 else "NOT_APPLICABLE",
        "point-relative-dd": status(drawdown <= product(benchmark_drawdown, .9)),
    }
    return joint, {"point-cap": status(drawdown <= .25)}


def checks_by_id(checks):
    return {item["target"]["target_id"]: item for item in checks}


def diagnostic(row, name, expected):
    value = row["diagnostics"][name]
    require(value["status"] == "AVAILABLE", f"{row['candidate_id']} {name}: unavailable")
    close(value["value"], expected, f"{row['candidate_id']} {name}")


def run_checks(report):
    watched = []

    def tracked(path):
        watched.append(path)
        return load(path)

    protocol_ref = EvidenceRef.from_dict(tracked(EROOT / "others/protocol_ref.json"))
    require(protocol_ref.sha256 == PROTOCOL_SHA256, "prospective protocol hash changed")
    protocol = tracked(protocol_ref.resolve(ROOT))
    for key, expected, filename in (("mapping", MAPPING_SHA256, "parameter_map.py"),
                                    ("constraints", CONSTRAINTS_SHA256, "parameter_constraints.py")):
        reference = EvidenceRef.from_dict(protocol[key])
        require(reference.sha256 == expected, f"{key} protocol reference changed")
        reference.resolve(ROOT)
        source = EROOT / "src" / filename
        require(sha256(source.read_bytes()).hexdigest() == expected, f"{key} source bytes changed")
        watched.append(source)
    require(protocol["parameter_protocol"]["point_count"] == 32
            and protocol["parameter_protocol"]["radius"] == .05
            and protocol["parameter_protocol"]["seed"] == 13, "parameter protocol changed")
    report["checks"].append("published protocol, mapping and feasibility source hashes unchanged")
    resource_ref = EvidenceRef.from_dict(tracked(EROOT / "others/resource_addendum_ref.json"))
    resource = tracked(resource_ref.resolve(ROOT))
    require(resource == tracked(EROOT / "others/resource_addendum.json"),
            "resource addendum differs from its immutable publication")
    require(resource["aggregate_max_workers"] == 16 and resource["workers_per_pool"] == 8
            and resource["native_threads_per_worker"] == 1, "resource authorization changed")
    tail_state = tracked(WORK / "parallel_tail_state.json")
    require(tail_state["status"] == "COMPLETE" and tail_state["boundary_cache_restored"]
            and tail_state["centers"] == 27 and tail_state["account_scenarios"] == 891,
            "parallel tail or cache restoration incomplete")
    require((ROOT / ".tmp/s015_stage4/requests/C0307.pkl").exists()
            and not (ROOT / ".tmp/s015_stage4/parallel_tail/C0307.pkl").exists(),
            "temporary boundary reservation remains held")
    require(not (WORK / "parallel_tail_failure.json").exists(), "parallel tail recorded failure")
    report["checks"].append("authorized16-worker aggregate, disjoint tail completion and temporary cache restoration")
    recovery_ref = EvidenceRef.from_dict(tracked(EROOT / "others/recovery_01_ref.json"))
    recovery = tracked(recovery_ref.resolve(ROOT))
    require(recovery == tracked(EROOT / "others/recovery_01.json"), "recovery record changed")
    require(recovery["successful_evaluations_without_retained_publication"] == 16
            and recovery["published_account_matches"] == 0, "retry scope changed")
    for key in ("failure", "previous_orchestration"):
        EvidenceRef.from_dict(recovery[key]).resolve(ROOT)
    require(not (WORK / "publication_failure.json").exists()
            and not (WORK / "failure.json").exists(), "unresolved producer failure")
    retried = next(row for row in tracked(WORK / "results/C0243.json")
                   if row["kind"] == "parameter" and row["point_index"] == 0)
    require(retried["request_hash"] == recovery["first_request_hash"]
            and retried["result_hash"] == recovery["first_result_hash"],
            "known pre-failure result differs after explicit same-point retry")
    report["checks"].append("16-point explicit retry retained; first known request/result hashes exactly reproduced")
    recovery_two_ref = EvidenceRef.from_dict(tracked(EROOT / "others/recovery_02_ref.json"))
    recovery_two = tracked(recovery_two_ref.resolve(ROOT))
    require(recovery_two == tracked(EROOT / "others/recovery_02.json"), "second recovery record changed")
    require(recovery_two["aggregate_max_workers"] == 8
            and recovery_two["published_account_matches"] == 0, "second recovery scope changed")
    for reference in recovery_two["failure_references"].values():
        EvidenceRef.from_dict(reference).resolve(ROOT)
    require(tail_state["additional_pool_completed_centers"] == 22
            and tail_state["forward_resumed_centers"] == 5, "actual tail execution split changed")
    retried_two = next(row for row in tracked(WORK / "results/C0400.json")
                       if row["kind"] == "parameter" and row["point_index"] == 0)
    require(retried_two["request_hash"] == recovery_two["unknown_evaluation_batch"]["first_request_hash"],
            "second recovery changed the known original request identity")
    report["checks"].append("second UNKNOWN batch retained; same requests retried at aggregate8; actual completed count not invented")

    source = tracked(ROOT / "research/S015/assets/deliveries/CANDIDATES/2/delivery.json")["content"]["payload"]
    entries = {item["identity"]["key"]["candidate_id"]: item for item in source["candidates"]}
    allowed = {item["candidate_id"] for item in source["handoff"]}
    centers = tracked(WORK / "centers.json")
    require(len(centers) == len(allowed) == 98 and {row["candidate_id"] for row in centers} == allowed,
            "original98-center handoff changed")
    require(resource["forward_centers"] == [row["candidate_id"] for row in centers[:71]]
            and resource["tail_centers"] == [row["candidate_id"] for row in centers[71:]],
            "parallel partitions differ from the declared candidate order")
    summary = tracked(WORK / "summary.json")
    summarized = {row["candidate_id"].removeprefix("S015-"): row for row in summary["rows"]}
    comparison = tracked(WORK / "comparison.json")
    compared = {row["candidate"]["candidate_id"].removeprefix("S015-"): row for row in comparison["rows"]}
    require(len(summary["rows"]) == len(comparison["rows"]) == 98
            and set(summarized) == set(compared) == allowed, "SE output center coverage changed")
    source_manifest = tracked(WORK / "authenticated_sources.json")
    authenticated = {row["evaluation_id"]: row for row in source_manifest["accounts"]}
    require(len(authenticated) == len(source_manifest["accounts"]) == 3351,
            "authenticated source coverage must be181+3072+98")
    comparison_request = tracked(WORK / "comparison_request.json")
    mandate = tracked(ROOT / "research/S015/assets/deliveries/MANDATE/2/delivery.json")["content"]["payload"]
    requirements = [target for item in mandate["items"]
                    if (item.get("requirement") or {}).get("type") == "PerformanceRequirement"
                    for target in item["requirement"]["targets"]]
    require(comparison_request["targets"]["requirements"] == requirements
            and comparison_request["targets"]["frequency_window_days"] == 60,
            "comparison target binding differs from the original mandate")
    del comparison_request
    geometry = {item["candidate_id"]: item for item in protocol["geometry"]}
    all_evaluation_ids, all_child_ids, all_result_refs = [], [], []
    checked_rows, plan_count, unavailable = [], 0, set()
    for center in sorted(centers, key=lambda row: row["candidate_id"]):
        cid = center["candidate_id"]
        identity = entries[cid]["identity"]["content_sha256"]
        require(summarized[cid]["content_sha256"] == compared[cid]["candidate"]["content_sha256"] == identity,
                f"{cid}: center content identity changed")
        require(any(item["evidence"] == center["evidence"] and center["evaluation_id"] in item["evaluation_ids"]
                    for item in entries[cid]["evaluations"]), f"{cid}: original center evidence substituted")
        require(center["frequency"]["windows"] == 375, f"{cid}: incomplete frequency windows")
        plan = tracked(WORK / "plans" / f"{cid}.json")
        if cid in UNAVAILABLE:
            require(plan["status"] == geometry[cid]["status"] == "NOT_APPLICABLE",
                    f"{cid}: must retain its unavailable design")
            unavailable.add(cid)
        else:
            require(plan["status"] == "COMPLETE" and plan["design"] == geometry[cid]["design"],
                    f"{cid}: plan geometry changed")
            require(plan["plan"]["center_request_sha256"] == center["request_hash"],
                    f"{cid}: plan substituted center request")
            plan_count += 1
        rows = tracked(WORK / "results" / f"{cid}.json")
        children = sorted((row for row in rows if row["kind"] == "parameter"), key=lambda row: row["point_index"])
        stressed = [row for row in rows if row["kind"] == "stress"]
        require(len(rows) == (1 if cid in UNAVAILABLE else 33) and len(stressed) == 1,
                f"{cid}: incorrect scenario coverage")
        require(len(children) == (0 if cid in UNAVAILABLE else 32), f"{cid}: incorrect parameter coverage")
        for row in rows:
            require(row["parent_id"] == cid, "result parent identity differs")
            eid = row["evaluation_id"]
            require(eid in authenticated and authenticated[eid]["evidence"] == row["evidence"]
                    and authenticated[eid]["candidate"]["candidate_id"] == f"S015-{row['candidate_id']}"
                    and authenticated[eid]["request_hash"] == row["request_hash"]
                    and authenticated[eid]["result_hash"] == row["result_hash"],
                    f"{cid}: compact row is not in the authenticated result manifest")
            require(authenticated[eid]["closed_cycles"] == row["observation"]["closed_trades"],
                    f"{cid}: completed-cycle count differs from authenticated account")
            all_evaluation_ids.append(eid)
            all_result_refs.append(row["evidence"]["sha256"])
        expected_checks = center_checks(center)
        expected_checks.update(stress_checks(stressed[0]))
        require(stressed[0]["candidate_id"] == cid
                and stressed[0]["parameters"] == center["parameters"], f"{cid}: stress changed parameters")
        actual_checks = checks_by_id(compared[cid]["target_checks"])
        short_checks = {item["target_id"]: item for item in summarized[cid]["target_checks"]}
        require(set(actual_checks) == set(short_checks) == {*expected_checks, "parameters"},
                f"{cid}: target coverage changed")
        for key, value in expected_checks.items():
            require(actual_checks[key]["status"] == short_checks[key]["status"] == value,
                    f"{cid}/{key}: independent target result differs")
        diagnostic(summarized[cid], "NET_ANNUAL_RETURN", center["observation"]["net_cagr"])
        diagnostic(summarized[cid], "DRAWDOWN_MAGNITUDE", -center["observation"]["max_drawdown"])
        diagnostic(summarized[cid], "FREQUENCY_MEDIAN", center["frequency"]["median"])
        diagnostic(summarized[cid], "STRESS_ANNUAL_LOSS",
                   center["observation"]["net_cagr"] - stressed[0]["observation"]["net_cagr"])
        group = actual_checks["parameters"]
        joint_count = cap_count = 0
        if cid in UNAVAILABLE:
            require(group["status"] == short_checks["parameters"]["status"] == "INDETERMINATE"
                    and group["valid_points"] == group["joint_passes"] == 0,
                    f"{cid}: unavailable design was treated as passed")
            require(compared[cid]["status"] not in {"RANKED", "TIED", "PARTIALLY_ORDERED"},
                    f"{cid}: unavailable design entered ranking")
            for metric in ("PARAMETER_RETURN_Q10", "PARAMETER_DRAWDOWN_Q90"):
                require(summarized[cid]["diagnostics"][metric]["status"] != "AVAILABLE",
                        f"{cid}: missing parameter metric filled in")
        else:
            require([row["point_index"] for row in children] == list(range(32)), f"{cid}: duplicate/missing points")
            point_results = {item["point_index"]: item for item in group["points"]}
            require(set(point_results) == set(range(32)), f"{cid}: SE point checks incomplete")
            for row in children:
                index = row["point_index"]
                spec = geometry[cid]["children"][index]
                require(row["candidate_id"] == spec["candidate_id"] and row["parameters"] == spec["parameters"],
                        f"{cid}/{index}: executed child differs from prospective payload mapping")
                all_child_ids.append(row["candidate_id"])
                joint, cap = point_checks(row)
                joint_count += int("FAILED" not in joint.values())
                cap_count += int(cap["point-cap"] == "PASSED")
                actual = point_results[index]
                require(actual["evaluation_id"] == row["evaluation_id"], f"{cid}/{index}: SE evaluation differs")
                for label, expected in (("joint_checks", joint), ("all_point_checks", cap)):
                    require({key: value["status"] for key, value in checks_by_id(actual[label]).items()} == expected,
                            f"{cid}/{index}: {label} differs")
            expected_group = status(joint_count >= 26 and cap_count == 32)
            require(group["valid_points"] == short_checks["parameters"]["valid_points"] == 32
                    and group["joint_passes"] == short_checks["parameters"]["joint_passes"] == joint_count
                    and group["status"] == short_checks["parameters"]["status"] == expected_group,
                    f"{cid}: 26/32 joint or32/32 cap acceptance differs")
            diagnostic(summarized[cid], "PARAMETER_RETURN_Q10", quantile([facts(row)[0] for row in children], .1))
            diagnostic(summarized[cid], "PARAMETER_DRAWDOWN_Q90", quantile([facts(row)[1] for row in children], .9))
        expected_checks["parameters"] = group["status"]
        combined = ("FAILED" if "FAILED" in expected_checks.values() else "INDETERMINATE"
                    if "INDETERMINATE" in expected_checks.values() else "PASSED")
        require(compared[cid]["acceptance_status"] == summarized[cid]["acceptance_status"] == combined,
                f"{cid}: aggregate target acceptance differs")
        checked_rows.append({"candidate_id": cid, "parameter_joint_passes": joint_count,
                             "parameter_cap_passes": cap_count, "parameter_points": len(children),
                             "parameter_status": group["status"], "stress_checks": stress_checks(stressed[0]),
                             "aggregate_acceptance": combined})
    require(plan_count == 96 and unavailable == UNAVAILABLE, "96plan+2NA coverage differs")
    require(len(all_child_ids) == len(set(all_child_ids)) == 3072
            and not set(all_child_ids) & allowed, "parameter identities duplicated or overlap centers")
    require(len(all_evaluation_ids) == len(set(all_evaluation_ids)) == 3170
            and len(set(all_result_refs)) == 3170, "3170 new result identities are not unique")
    require(summary["parameter_account_count"] == 3072 and summary["stress_account_count"] == 98
            and summary["authenticated_account_count"] == 3351, "summary account totals differ")
    report["checks"].extend([
        "98 original center identities/evidence references and original mandate target bindings preserved",
        "96 original plans plus2 explicit NOT_APPLICABLE;3072 unique children and3170 unique new evaluations",
        "all96 centers32 point joint checks,26/32 acceptance,32/32 risk caps andLINEAR Q10/Q90 independently matched",
        "all98 centers actual0.002 stress, unchanged parameters, five stress hard gates and pressure annual loss matched",
        "all98 center economic/frequency target results and aggregate acceptance matched",
    ])
    report["rows"] = checked_rows
    report["counts"] = {"centers": 98, "complete_plans": plan_count, "not_applicable": 2,
                        "parameter_accounts": 3072, "stress_accounts": 98,
                        "unique_new_evaluations": 3170,
                        "acceptance": dict(Counter(row["aggregate_acceptance"] for row in checked_rows))}
    report["checked_file_sha256"] = {path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()).hexdigest()
                                    for path in watched}
    lint = subprocess.run([sys.executable, "-m", "ruff", "check", str(EROOT / "src"), "--output-format", "json"],
                          cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)
    report["ruff"] = {"returncode": lint.returncode, "findings": json.loads(lint.stdout) if lint.stdout else [],
                      "stderr": lint.stderr}
    require(lint.returncode == 0, "EX005 source Ruff did not pass")
    report["checks"].append("Ruff allEX005 source files passed")


def main():
    report = {"status": "RUNNING", "checks": [], "rows": [],
              "scope": "Independent compact-result numerical audit; no account execution and no full-account evidence reread.",
              "tolerance": {"numeric_relative": 1e-12, "numeric_absolute": 1e-12, "target_decisions": "exact"},
              "limitations": ["Provenance relies on the separate public authentication manifest from build_assessment.",
                              "This check does not rerun bootstrap, family statistics or pairwise ranking. FULL delivery validation independently recomputes SE."]}
    try:
        run_checks(report)
    except Exception as error:
        report["status"] = "FAIL"
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    else:
        report["status"] = "PASS"
    output = EROOT / "others/final_checks.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                      encoding="utf-8", newline="\n")
    print(json.dumps({"status": report["status"], "counts": report.get("counts"), "error": report.get("error")},
                     ensure_ascii=False), flush=True)
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
