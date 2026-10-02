"""Independent numerical and contract checks for the completed S011 deliveries."""

import argparse
from collections import Counter
from dataclasses import replace
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm
from research_experiment import load_experiment_input
from strategy_runtime import StrategyRuntime, ImplementationDependency
from strategy_manager import CandidateKey
from czsc_trader.application import (
    RepositoryContext,
    load_candidate,
    validate_delivery,
    validate_archives,
)
from czsc_trader.research_tools import DeliveryReference, ValidationStatus

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
CTX = RepositoryContext.discover(REPO)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def returns(item):
    eq = np.array([x["equity"] for x in item["account"]])
    return eq / np.r_[item["initial_cash"], eq[:-1]] - 1


def stats(item):
    equity = np.r_[item["initial_cash"], [x["equity"] for x in item["account"]]]
    return (
        (equity[-1] / equity[0]) ** (252 / (len(equity) - 1)) - 1,
        float(-min(equity / np.maximum.accumulate(equity) - 1)),
    )


def account_checks(request, panel):
    rows = {(x["candidate"]["candidate_id"], x["scenario_id"]): x for x in request["evidence"]}
    maximum_error = 0.0
    for result in panel["rows"]:
        name = result["candidate"]["candidate_id"]
        item = rows[(name, "standard")]
        ann, dd = stats(item)
        children = [
            x["child"]["candidate_id"]
            for x in request["perturbations"]
            if x["parent"]["candidate_id"] == name
        ]
        assert len(children) == 16
        neighbors = np.array([stats(rows[(x, "standard")]) for x in children])
        equity = np.r_[item["initial_cash"], [x["equity"] for x in item["account"]]]
        benchmark = np.r_[item["initial_cash"], item["benchmark_equity"]]
        rolling = equity[60:] / equity[:-60] - benchmark[60:] / benchmark[:-60]
        # Rebuild closed-cycle cash flow directly, including round-trip costs.
        flows = {}
        for fill in item["fills"]:
            sign = -1 if fill["side"] == "BUY" else 1
            flows[fill["cycle_id"]] = (
                flows.get(fill["cycle_id"], 0.0)
                + sign * fill["quantity"] * fill["price"]
                - fill["fees"]
            )
        pnl = [flows[x["cycle_id"]] for x in item["closed_cycles"]]
        winning = sorted([x for x in pnl if x > 0], reverse=True)
        concentration = sum(winning[: int(np.ceil(0.1 * len(winning)))]) / sum(winning)
        expected = {
            "NET_ANNUAL_RETURN": ann,
            "DRAWDOWN_MAGNITUDE": dd,
            "FULL_SAMPLE_FREQUENCY": 60 * len(item["closed_cycles"]) / len(item["account"]),
            "PARAMETER_RETURN_DEGRADATION": max(0.0, ann - np.quantile(neighbors[:, 0], 0.1)),
            "PARAMETER_DRAWDOWN_DEGRADATION": max(0.0, np.quantile(neighbors[:, 1], 0.9) - dd),
            "ROLLING_EXCESS_Q10": np.quantile(rolling, 0.1),
            "STRESS_ANNUAL_LOSS": ann - stats(rows[(name, "fee_20bp")])[0],
            "PROFIT_CONCENTRATION": concentration,
        }
        for value in result["diagnostics"]:
            if value["metric"] in expected:
                error = abs(value["value"] - expected[value["metric"]])
                assert error < 1e-10, (name, value["metric"], error)
                maximum_error = max(maximum_error, error)
        assert result["uncertainty"]["status"] == "AVAILABLE" and not result["coverage_gaps"]
    return {"centers_checked": 36, "metrics_per_center": 8, "maximum_metric_error": maximum_error}


def independent_family(request):
    family = read(ROOT / "artifacts/expanded_family_statistics.json")
    audit = read(ROOT / "artifacts/historical_account_audit.json")
    data = {}
    for item in audit["accounts"]:
        a = pd.read_csv(
            REPO / item["evidence"] / "account_daily.csv.gz", float_precision="round_trip"
        )
        eq = a.equity.to_numpy(float)
        data[item["reference"]] = eq / np.r_[1e6, eq[:-1]] - 1
    for item in request["evidence"]:
        if item["experiment_id"] == ROOT.name and item["parent"] is not None:
            data[item["candidate"]["candidate_id"]] = returns(item)
    assert len(data) == 1284
    paths = list(dict.fromkeys(x["statistical_path"] for x in family["mapping"]))
    matrix = np.column_stack([data[k] for k in paths])
    for item in family["mapping"]:
        assert np.allclose(
            data[item["proposal"]], data[item["statistical_path"]], rtol=0, atol=1e-14
        )
    assert set(data) == {x["proposal"] for x in family["mapping"]} | set(
        family["constant_exclusions"]
    )
    assert all(np.std(data[x], ddof=1) == 0 for x in family["constant_exclusions"])
    corr = np.corrcoef(matrix, rowvar=False)
    effective = np.trace(corr) ** 2 / np.square(corr).sum()
    assert abs(effective - family["effective_trial_count"]) < 1e-10
    split_count = 0
    for pbo in family["pbo"]:
        blocks = np.array_split(np.arange(403), pbo["block_count"])
        expected_combinations = list(
            combinations(range(pbo["block_count"]), pbo["block_count"] // 2)
        )
        assert [tuple(x["training_blocks"]) for x in pbo["splits"]] == expected_combinations
        adverse = 0
        for split in pbo["splits"]:
            train_idx = np.concatenate([blocks[x] for x in split["training_blocks"]])
            test_idx = np.concatenate([blocks[x] for x in split["validation_blocks"]])
            assert not set(train_idx) & set(test_idx) and len(train_idx) + len(test_idx) == 403
            train, test = matrix[train_idx], matrix[test_idx]

            def ratios(values):
                sd = np.std(values, axis=0, ddof=1)
                mean = np.mean(values, axis=0)
                out = np.divide(np.sqrt(252) * mean, sd, out=np.zeros(len(paths)), where=sd > 0)
                out[(sd == 0) & (mean != 0)] = np.nan
                return out

            tr, te = ratios(train), ratios(test)
            winner = min(np.flatnonzero(np.isfinite(tr)), key=lambda i: (-tr[i], paths[i]))
            order = sorted(np.flatnonzero(np.isfinite(te)), key=lambda i: (-te[i], paths[i]))
            rank = order.index(winner) + 1
            percentile = (len(order) - rank) / (len(order) - 1)
            assert paths[winner] == split["selected_candidate"] and rank == split["validation_rank"]
            assert abs(percentile - split["validation_percentile"]) < 1e-12
            adverse += percentile < 0.5
            split_count += 1
        assert abs(adverse / len(pbo["splits"]) - pbo["pbo"]) < 1e-12
    sharpes = np.sqrt(252) * np.mean(matrix, axis=0) / np.std(matrix, axis=0, ddof=1)
    current = {
        x["candidate"]["candidate_id"]: x
        for x in request["evidence"]
        if x["scenario_id"] == "standard"
    }
    for result in family["dsr"]:
        r = returns(current[result["candidate_id"]])
        observed = np.mean(r) / np.std(r, ddof=1)
        centered = (r - np.mean(r)) / np.std(r, ddof=1)
        variance = (
            1 - np.mean(centered**3) * observed + (np.mean(centered**4) - 1) / 4 * observed**2
        )
        for mode, count in [("raw", result["raw_count"]), ("effective", effective)]:
            gamma = np.euler_gamma
            threshold = np.mean(sharpes) + np.std(sharpes, ddof=1) * (
                (1 - gamma) * norm.ppf(1 - 1 / count) + gamma * norm.ppf(1 - 1 / (count * np.e))
            )
            z = (observed - threshold / np.sqrt(252)) * np.sqrt(len(r) - 1) / np.sqrt(variance)
            assert abs(norm.cdf(z) - result["result"][mode]["probability"]) < 1e-12
    return {
        "historical_and_new_proposals": len(data),
        "unique_nonconstant_paths": len(paths),
        "pbo_splits_checked": split_count,
        "dsr_bundles_checked": len(family["dsr"]),
        "effective_count_trace_check": True,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sealed", action="store_true")
    args = parser.parse_args()
    inputs = read(ROOT / "inputs.json")
    for name, expected in inputs["historical_sources"].items():
        assert sha256((REPO / name).read_bytes()).hexdigest() == expected, name
    for name, expected in read(
        REPO / "research/S011/historical_deliveries/revision_01/sources.json"
    ).items():
        assert sha256((REPO / name).read_bytes()).hexdigest() == expected, name
    if args.sealed:
        # The manifest authenticates the previously checked numerical inputs/results;
        # repeat the public delivery check against the newly sealed owner state.
        for name in ("20261002_S011_EX35", "20261002_S011_EX36", ROOT.name):
            assert validate_archives(CTX, archive=ROOT.parent / name).status == "PASS"
        reference = DeliveryReference.from_dict(
            read(ROOT / "delivery_index.json")["references"][-1]
        )
        checked = validate_delivery(CTX, reference)
        assert checked.status is ValidationStatus.PASS, checked
        report = read(ROOT / "focused_verification.json")
        assert report["status"] == "PASS"
        report.update(
            sealed_archives_verified=True,
            public_delivery_validation=checked.status.value,
            numerical_revalidation="Prior independent checks retained; their inputs and outputs authenticated by the sealed manifest.",
        )
        (REPO / ".tmp/s011-completion-postseal.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        print(json.dumps(report, ensure_ascii=False), flush=True)
        return
    receipt = read(ROOT / "artifacts/execution_receipt.json")
    load_experiment_input(ROOT / "artifacts", expected_receipt_sha256=receipt["receipt_sha256"])
    evaluations = receipt["trace"]["evaluations"]
    assert len(evaluations) == 513 and all(x["status"] == "SUCCEEDED" for x in evaluations)
    assert sum(len(x["evaluation_ids"]) for x in evaluations) == 514
    trials = read(ROOT / "artifacts/trial_states.json")["trials"]
    assert len(trials) == 512 and all(
        x["number"] == x["slot"] == i and x["state"] == "COMPLETE" for i, x in enumerate(trials)
    )
    deps = tuple(ImplementationDependency(**x) for x in inputs["dependencies"])
    parents = {
        x["config_id"]: load_candidate(CTX, CandidateKey("S011", x["candidate_id"]))
        for x in inputs["centers"]
    }
    for spec in inputs["neighbors"]:
        registered = read(ROOT / "artifacts/registrations" / (spec["candidate_id"] + ".json"))
        loaded = load_candidate(CTX, CandidateKey("S011", spec["candidate_id"]))
        assert dict(loaded.payload["parameters"]) == spec["parameters"]
        assert loaded.payload["runtime"] == parents[spec["center_config_id"]].payload["runtime"]
        assert (
            StrategyRuntime().identify(loaded, dependencies=deps).content_sha256
            == registered["content_sha256"]
        )
    request = read(ROOT / "assessment_request.json")
    panel = read(ROOT / "assessment_panel.json")
    numerical = account_checks(request, panel)
    statistical = independent_family(request)
    comparison = read(ROOT / "comparison.json")
    old_comparison = read(ROOT.parent / "20261002_S011_EX33/comparison.json")
    old_layers = {x["candidate"]["candidate_id"]: x["pareto_layer"] for x in old_comparison["rows"]}
    assert {
        x["candidate"]["candidate_id"]: x["pareto_layer"] for x in comparison["rows"]
    } == old_layers
    assert read(ROOT / "coverage_summary.json")["standard_193_exactly_matches_EX33"]
    unchanged = [x for x in request["evidence"] if x["experiment_id"] == "20261002_S011_EX33"]
    old_request = read(ROOT.parent / "20261002_S011_EX33/assessment_request.json")
    assert unchanged == old_request["evidence"]
    old_intervals = {
        x["candidate"]["candidate_id"]: x["uncertainty"]
        for x in read(ROOT.parent / "20261002_S011_EX33/assessment_panel.json")["rows"]
    }
    assert all(
        x["uncertainty"] == old_intervals[x["candidate"]["candidate_id"]] for x in panel["rows"]
    )
    assert Counter(x["status"] for r in comparison["rows"] for x in r["target_checks"]) == {
        "PASSED": 108,
        "NOT_APPLICABLE": 72,
    }
    refs = [
        DeliveryReference.from_dict(x) for x in read(ROOT / "delivery_index.json")["references"]
    ]
    published = read(ROOT / "publication_validation.json")
    assert published["status"] == "PASS" and published["reference"] == refs[-1].to_dict()
    wrong = validate_delivery(CTX, replace(refs[-1], content_sha256="0" * 64))
    assert wrong.status is ValidationStatus.FAIL
    assert all(
        read(ROOT / f"deliveries/{stage}/1/delivery.json")["content"]["status"] == "COMPLETE"
        for stage in ("COMPONENTS", "CANDIDATES", "ASSESSMENT")
    )
    report = {
        "status": "PASS",
        "scope": "Focused research evidence and numerical verification; no repository full regression.",
        "managed_calls": 513,
        "accounts": 514,
        "current_assessment_evidence": 648,
        "registered_perturbations": 512,
        "trial_states": "512 COMPLETE",
        "numerical": numerical,
        "family_statistics": statistical,
        "public_delivery_validation": published["status"],
        "public_delivery_validation_source": "Publication called assemble_delivery and validate_delivery; archived call result is bound to this reference.",
        "wrong_delivery_hash_rejected": True,
        "historical_sources_unchanged": True,
        "sealed_archives_verified": args.sealed,
        "stage_five_started": False,
    }
    path = (
        REPO / ".tmp/s011-completion-postseal.json"
        if args.sealed
        else ROOT / "focused_verification.json"
    )
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
