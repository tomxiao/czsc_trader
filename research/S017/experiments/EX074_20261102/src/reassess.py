"""Authenticate and reinterpret existing public training accounts; never replay them."""
# Thread and cache settings must precede numerical/runtime imports.
# ruff: noqa: E402
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".tmp/s017-stage2-calmar-20261102"
SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ["TEMP"] = os.environ["TMP"] = str(SCRATCH)
sys.pycache_prefix = str(SCRATCH / "pycache")
for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[variable] = "1"

from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from decimal import Decimal, localcontext
from hashlib import sha256
import json
import math
from statistics import median
from zoneinfo import ZoneInfo

from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.equity_replay import materialize_equity, build_equity_assessment
from strategy_evaluator import assess_candidates, compare_candidates
from strategy_evaluator import research_models as m
from strategy_runtime import EquityStrategyDefinition, equity_source_hash

PRIOR = ROOT / "research/S017/experiments/EX072_20261102"
CENTER_IDS = {"center-net-calmar", "center-relative-dd", "center-absolute-dd", "frequency-median", "frequency-coverage"}


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def summary(run):
    points, daily = run["account_points"], run["account_daily"]
    sessions = [row["session"] for row in daily]
    assert len(points) == 6490 and len(daily) == 502
    assert sessions[0] == "2024-01-02" and sessions[-1] == "2025-12-31"
    assert all("2024-01-02" <= p["session"] <= "2025-12-31" for p in points)
    high, dd = 100000.0, 0.0
    for point in points:
        high = max(high, point["equity"])
        dd = max(dd, 1 - point["equity"] / high)
    closed = [t for t in run["trades"] if t["status"] == "CLOSED"]
    counts = Counter(datetime.fromisoformat(t["exit_at"].replace("Z", "+00:00"))
                     .astimezone(ZoneInfo("America/New_York")).date().isoformat() for t in closed)
    assert all(sessions[0] <= day <= sessions[-1] for day in counts)
    windows = [sum(counts[s] for s in sessions[i - 59:i + 1]) for i in range(59, 502)]
    assert len(windows) == 443
    covered = sum(n >= 3 for n in windows)
    annual = (points[-1]["equity"] / 100000.0) ** (252 / 502) - 1
    result = {"annualized_return": annual, "bar_max_drawdown": dd,
              "closed_cycles": len(closed), "rolling_60_closed_cycle_median": median(windows),
              "frequency_windows": len(windows), "covered_windows": covered,
              "coverage_at_least_three": covered / len(windows),
              "ending_equity": points[-1]["equity"], "ending_quantity": points[-1]["quantity"],
              "net_calmar": annual / dd if dd > 1e-12 and math.isfinite(annual / dd) else None}
    for key in ("annualized_return", "bar_max_drawdown", "closed_cycles", "rolling_60_closed_cycle_median"):
        assert math.isclose(result[key], run["metrics"][key], rel_tol=1e-11, abs_tol=1e-10), key
    assert windows == run["metrics"]["rolling_60_closed_cycle_counts"]
    return result


def authenticate(cid):
    record = read(PRIOR / "others/all_accounts.json")[cid]
    ref = EvidenceRef.from_dict(record["evidence"])
    assert ref.experiment.strategy_id == "S017" and ref.schema == "equity_research" and ref.schema_version == 4
    path = ref.resolve(ROOT)
    data = path.read_bytes()
    envelope = json.loads(data)
    owned = {(envelope[k]["kind"], envelope[k]["sha256"]) for k in ("input_ref", "candidate_ref", "benchmark_ref")}

    def resolver(item):
        assert (item["kind"], item["sha256"]) in owned
        value = (path.parent / (item["sha256"] + ".json")).read_bytes()
        assert sha256(value).hexdigest() == item["sha256"]
        return value

    view = materialize_equity(data, resolver)
    payload = view.payload
    for key in ("evaluation_identity", "evaluation_id", "request_hash"):
        assert payload[key] == record[key], (cid, key)
    request = payload["request"]
    assert request["window"] == {"start": "2024-01-02T14:30:00+00:00", "end": "2025-12-31T21:00:00+00:00"}
    assert request["history_start"] == "2023-11-01"
    assert request["fee_rate"] == 0.001 and request["initial_cash"] == 100000.0
    assert request["drawdown_basis"] == "BAR_CLOSE" and request["frequency_window_days"] == 60
    assert request["window_id"] == "TRAIN_2024_2025" and request["scenario_id"] == "STANDARD"
    definition = EquityStrategyDefinition.from_dict(request["candidate_definition"])
    assert request["candidate_definition"]["execution_spec"] == request["benchmark"]["execution"]["execution_spec"]
    assert definition.source_sha256 == equity_source_hash(PRIOR / "src", tuple(definition.source_files))
    assert json.loads(definition.parameters_json) == record["parameters"]
    independent = summary(payload["runs"]["candidate"])
    benchmark = summary(payload["runs"]["buy_hold"])
    with localcontext() as decimal_context:
        decimal_context.prec = 40
        boundary = float(Decimal(str(benchmark["net_calmar"])) * Decimal("1.5"))
    checks = {
        "center-net-calmar": independent["net_calmar"] is not None and independent["net_calmar"] > boundary,
        "center-relative-dd": independent["bar_max_drawdown"] <= float(Decimal(str(benchmark["bar_max_drawdown"])) * Decimal("0.8")),
        "center-absolute-dd": independent["bar_max_drawdown"] <= 0.25,
        "frequency-median": independent["rolling_60_closed_cycle_median"] >= 6,
        "frequency-coverage": independent["covered_windows"] * 10 >= independent["frequency_windows"] * 9,
    }
    evidence, = build_equity_assessment(view)
    assert evidence.evaluation_id == record["evaluation_id"]
    definition_pack = {"schema": "s017-prototype-restoration/v1", "candidate_id": cid,
        "definition": definition.to_dict(), "evaluation_identity": record["evaluation_identity"],
        "source_directory": PRIOR.relative_to(ROOT).as_posix() + "/src",
        "source_files": [{"path": name, "sha256": digest(PRIOR / "src" / name),
                          "utf8_content": (PRIOR / "src" / name).read_text(encoding="utf-8")}
                         for name in definition.source_files],
        "parameters": record["parameters"], "source_account": record["evidence"]}
    save(WORK / "others/definitions" / (cid + ".json"), definition_pack)
    return {"candidate_id": cid, "record": record, "candidate": independent, "benchmark": benchmark,
            "calmar_boundary": boundary, "center_checks": checks,
            "center_all_pass": all(checks.values()), "assessment_evidence": evidence.to_dict(),
            "new_account_compute": 0, "original_result_sha256": ref.sha256}


def run():
    source = read(PRIOR / "others/search_trials.json")
    assert source["status"] == "COMPLETED_PARAMETER_SEARCH"
    successful = {row["candidate_id"]: row for row in source["unique_results"] if row["status"] == "SUCCEEDED"}
    assert len(successful) == 25 and set(successful) == set(read(PRIOR / "others/all_accounts.json"))
    print("AUTHENTICATING_25_PUBLIC_TRAINING_ACCOUNTS workers=4 native_threads=1 new_compute=0", flush=True)
    results = []
    with ProcessPoolExecutor(max_workers=4) as executor:
        for result in executor.map(authenticate, sorted(successful)):
            results.append(result)
            print("AUTHENTICATED", result["candidate_id"], result["center_all_pass"], flush=True)
    evidence = tuple(m.AssessmentEvidence.from_dict(item["assessment_evidence"]) for item in results)
    protocol = m.NeighborhoodSelfCheckProtocol("s017-ex074-diagnostic-only", "TRAIN_2024_2025", "STANDARD", "PRESSURE",
        252, 21, m.QuantileMethod.LINEAR, 1, 1000, 20, 17, 1e-7,
        parameter_protocol=m.ParameterNeighborhoodProtocol(), pbo_blocks=10, frequency_min_closed_cycles=3)
    request = m.CandidateAssessmentRequest(tuple(e.candidate for e in evidence), protocol, (), evidence,
        tuple(m.IncompleteEvaluation(e.candidate, "TRAIN_2024_2025", "PRESSURE", m.IncompleteEvaluationStatus.NOT_RUN,
                                    "Formal stress and neighborhood self-checks are not part of this stage-two reuse") for e in evidence))
    panel = assess_candidates(request)
    targets = m.ResearchTargets.from_dict(read(ROOT / "research/S017/materials/STAGE1_FINAL_CONTRACT_20261102.json")["targets"])
    bins = tuple(m.MetricBinSpec(metric, .5 if metric is m.ResearchMetric.FREQUENCY_MEDIAN else .0001,
                                0., m.BinRounding.FLOOR) for metric in (
                                    *m.BENCHMARK_METRICS, *m.WITHIN_LAYER_METRICS,
                                    m.ResearchMetric.FREQUENCY_MEDIAN))
    policy = m.ComparisonPolicy("s017-existing-standard-no-selection", bins, m.ParetoBasis.RAW,
                                m.MissingEvidencePolicy.REQUIRE_COMPLETE)
    comparison_request = m.CandidateComparisonRequest(tuple(e.candidate for e in evidence), targets, panel, policy)
    comparison = compare_candidates(comparison_request)
    indexed = {row.candidate.candidate_id.split("-")[-1]: row for row in comparison.rows}
    for row in results:
        checked = indexed[row["candidate_id"]]
        got = {c.target.target_id: c.status is m.TargetCheckStatus.PASSED for c in checked.target_checks
               if c.target.target_id in CENTER_IDS}
        assert got == row["center_checks"], (row["candidate_id"], got, row["center_checks"])
        assert checked.acceptance_status is not m.TargetCheckStatus.PASSED
        row["se_center_checks_match"] = True
        row["full_target_status"] = checked.acceptance_status.value
        row["all_target_checks"] = [check.to_dict() for check in checked.target_checks]
        row["old_five_gate_results_unchanged"] = successful[row["candidate_id"]]["goals"]
        del row["assessment_evidence"]
    qualified = [row["candidate_id"] for row in results if row["center_all_pass"]]
    assert qualified == ["C0338", "C0339", "C0340", "C0341", "C0342", "C0352"]
    # Full V4 facts duplicate the immutable original ledgers; keep that cache out of Git.
    save(SCRATCH / "assessment_evidence.json", [e.to_dict() for e in evidence])
    save(SCRATCH / "se_request.json", request.to_dict())
    save(WORK / "others/se_panel.json", panel.to_dict())
    save(WORK / "others/se_comparison_request.json", comparison_request.to_dict())
    save(WORK / "others/se_comparison.json", comparison.to_dict())
    save(WORK / "others/analysis.json", {"status": "PASS", "new_training_center_qualifiers": qualified,
        "source_experiment": "EX072_20261102", "authenticated_unique_accounts": 25,
        "new_account_computes": 0, "new_searches": 0, "new_candidates": 0,
        "formal_stage_four_executed": False, "sealed_test_accessed": False,
        "resources": {"max_workers": 4, "native_threads_per_worker": 1, "seed": 17},
        "results": results, "source_hashes": {"search_trials": digest(PRIOR / "others/search_trials.json"),
                                               "all_accounts": digest(PRIOR / "others/all_accounts.json")}})
    print("TRAINING_CENTER_QUALIFIERS", qualified, "ALL_11_TARGET_ACCEPTANCE_STILL_INCOMPLETE", flush=True)


if __name__ == "__main__":
    run()
