"""Explicit eight-account FULL equivalence; approval requires the completed formal REX chain."""
from __future__ import annotations

import argparse
import gzip
from hashlib import sha256
import importlib.util
from io import StringIO
import json
from math import isclose
from pathlib import Path
import tarfile

import pandas as pd
from dataflows import Dataflows, DataSpace, ProviderConfig
from strategy_runtime import ParameterSet, StrategyInputBinding


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def verify_selection(root, exp, audit):
    """Authenticate explicit four-account frontier and original screening bytes."""
    selection_path = exp / "selection.json"
    selection = audit.read(selection_path)
    audit.require(len(selection["selected"]) == 4, "EX028 requires exactly four selected frontiers")
    checks, receipts, authenticated, selected_tables, evidence = [], {}, {}, {}, []
    formal = audit.receipt_chain(root, "EX027_20261006", checks, receipts)
    legacy_exp = root / "experiments/S012/EX026_20261006"
    legacy_manifest = audit.read(legacy_exp / "experiment_manifest.json")
    audit.require(legacy_manifest["outcome"] == "FAIL", "legacy failure status differs")
    legacy_binding = audit.read(legacy_exp / "experiment_binding.json")
    audit.require(audit.source_digest(legacy_exp, legacy_binding["source_files"]) == legacy_binding["source_sha256"],
                  "legacy source closure differs")
    bundle = audit.checked_file(formal["workspace"], "inherited_search_bundle.tar.gz",
                                formal["artifact_sha256"]["inherited_search_bundle.tar.gz"], checks)
    needed = {"search.json"}
    for row in selection["selected"]:
        if row["search_experiment_id"] == "EX026_20261006":
            needed.add(row["raw_summary"]["path"])
            needed.update(x["path"] for x in row["raw_ledgers"].values())
    bundle_hashes = {}
    with tarfile.open(bundle, "r:gz") as archive:
        for member in archive:
            if member.name in needed:
                audit.require(member.isfile(), "inherited evidence is not a regular file")
                bundle_hashes[member.name] = sha256(archive.extractfile(member).read()).hexdigest()
    audit.require(set(bundle_hashes) == needed, "inherited bundle evidence incomplete")
    for eid, reference in selection["searches"].items():
        audit.require(eid in {"EX026_20261006", "EX027_20261006"}, "unexpected search source")
        path = audit.checked_file(root, reference["path"], reference["sha256"], checks)
        audit.require(path == root / "experiments/S012" / eid / "artifacts/rex/search.json",
                      "search source path differs")
        if eid == "EX027_20261006":
            audit.require(formal["artifact_sha256"]["search.json"] == reference["sha256"],
                          "search source absent from receipt")
        else:
            audit.require(legacy_manifest["files"]["artifacts/rex/search.json"]["sha256"]
                          == bundle_hashes["search.json"] == reference["sha256"],
                          "legacy search differs from sealed manifest or formal inherited bundle")
        search = audit.read(path)
        authenticated[eid] = search.get("proposals", search.get("trials", []))
    for number, selected in enumerate(selection["selected"]):
        eid = selected["search_experiment_id"]
        matching = [r for r in authenticated[eid] if r["proposal_id"] == selected["proposal_id"]]
        audit.require(len(matching) == 1 and matching[0] == {
            k: v for k, v in selected.items() if k != "search_experiment_id"},
            "selected proposal differs from complete original search row")
        audit.require(selected["status"] == "COMPLETE", "selected screening failed")
        audit.require(audit.canonical(selected["parameters"]) == selected["parameter_sha256"],
                      "selected parameter SHA differs")
        workspace = root / "experiments/S012" / eid / "artifacts/rex"
        if eid == "EX026_20261006":
            for reference in (selected["raw_summary"], *selected["raw_ledgers"].values()):
                audit.require(reference["sha256"] == bundle_hashes[reference["path"]]
                              == legacy_manifest["files"]["artifacts/rex/" + reference["path"]]["sha256"],
                              "legacy selected raw differs from manifest or inherited bundle")
        summary_path = audit.checked_file(workspace, selected["raw_summary"]["path"],
                                          selected["raw_summary"]["sha256"], checks)
        summary = audit.read(summary_path)
        audit.require(all(selected[k] == value for k, value in summary.items()),
                      "original screening summary differs from selection")
        tables = {}
        for name, reference in selected["raw_ledgers"].items():
            path = audit.checked_file(workspace, reference["path"], reference["sha256"], checks)
            raw = gzip.decompress(path.read_bytes())
            audit.require(sha256(raw).hexdigest() == reference["uncompressed_sha256"],
                          "screening uncompressed ledger SHA differs")
            value = pd.read_json(StringIO(raw.decode("utf-8")), orient="table")
            audit.require(len(value) == reference["rows"] and list(value.columns) == reference["columns"],
                          "screening ledger shape differs")
            tables[name] = value
        audit.reconcile_fills(tables["account_daily"], tables["fills"], .001)
        metrics = audit.account_metrics(tables["account_daily"], tables["trades"], tables["fills"])
        metrics.update(orders=len(tables["orders"]), fills=len(tables["fills"]),
                       evaluation_sessions=len(tables["account_daily"]), frequency_denominator=1535)
        benchmark = selected["metrics"]["benchmark"]
        goals = [metrics["net_cagr"] >= benchmark["cagr"] * 1.5,
                 abs(metrics["max_drawdown"]) < abs(benchmark["max_drawdown"]), metrics["frequency"] >= 5]
        for name in metrics.keys() & selected["metrics"].keys():
            audit.require(isclose(metrics[name], selected["metrics"][name], rel_tol=1e-10, abs_tol=1e-8),
                          f"selected original {name} differs from independent screening ledger")
        audit.require(goals == selected["metrics"]["goals"] and all(goals) == selected["passed_all"],
                      "selected original goal flags differ")
        cid = f"S012-C{3000 + number:04d}"
        selected_tables[cid] = (selected, tables)
        evidence.append({"candidate_id": cid, "search_experiment_id": eid,
                         "proposal_id": selected["proposal_id"], "status": "PASS",
                         "independent_screening_metrics": metrics, "goals": goals})
    return {"status": "PASS", "selection_sha256": sha256(selection_path.read_bytes()).hexdigest(),
            "receipts": {eid: r["receipt_sha256"] for eid, r in receipts.items()},
            "legacy_search_provenance": {"experiment_id": "EX026_20261006", "formal_rex_complete": False,
                "sealed_outcome": "FAIL", "manifest_sha256": sha256((legacy_exp / "experiment_manifest.json").read_bytes()).hexdigest(),
                "authenticated_by": "EX027_20261006 formal inherited_search_bundle.tar.gz",
                "inherited_bundle_sha256": sha256(bundle.read_bytes()).hexdigest()},
            "selected": evidence, "files_checked": len(checks)}, selected_tables



def verify_witness50_originals(root, exp, audit):
    options_path = exp / "witness_options.json"
    options = audit.read(options_path)
    audit.require("witness_options.json" in audit.read(exp / "experiment_binding.json")["source_files"],
                  "frozen choice is not bound source")
    source = options["source_search"]
    receipt = audit.receipt_chain(root, source["experiment_id"], [], {})
    audit.require(receipt["receipt_sha256"] == source["receipt_sha256"], "wrong original search receipt")
    workspace = root / "experiments/S012" / source["experiment_id"] / "artifacts/rex"
    search_path = audit.checked_file(root, source["search"]["path"], source["search"]["sha256"], [])
    audit.require(receipt["artifact_sha256"]["search.json"] == source["search"]["sha256"], "unreceipted original search")
    search = audit.read(search_path)
    audit.require(len(search["proposals"]) == 1040 and all(row["status"] == "COMPLETE" for row in search["proposals"]),
                  "original search is incomplete")
    selected_tables, evidence = {}, []
    for label, candidate_id in (("primary", "S012-C4600"), ("feasible", "S012-C4601")):
        selected = options["choices"][label]["row"]
        matches = [row for row in search["proposals"] if row["proposal_id"] == selected["proposal_id"]]
        audit.require(len(matches) == 1 and matches[0] == selected, "frozen original row changed")
        audit.require(audit.canonical(selected["parameters"]) == selected["parameter_sha256"], "parameter identity differs")
        summary_ref = selected["raw_summary"]
        summary = audit.read(audit.checked_file(workspace, summary_ref["path"], summary_ref["sha256"], []))
        audit.require(all(selected[key] == value for key, value in summary.items()), "original raw summary differs")
        tables = {}
        for name, ref in selected["raw_ledgers"].items():
            audit.require(receipt["artifact_sha256"][ref["path"]] == ref["sha256"], "unreceipted original ledger")
            path = audit.checked_file(workspace, ref["path"], ref["sha256"], [])
            raw = gzip.decompress(path.read_bytes())
            audit.require(sha256(raw).hexdigest() == ref["uncompressed_sha256"], "uncompressed ledger differs")
            table = pd.read_json(StringIO(raw.decode()), orient="table")
            audit.require(len(table) == ref["rows"] and list(table.columns) == ref["columns"], "original ledger shape differs")
            tables[name] = table
        audit.reconcile_fills(tables["account_daily"], tables["fills"], .001)
        selected_tables[candidate_id] = (selected, tables)
        evidence.append({"candidate_id": candidate_id, "proposal_id": selected["proposal_id"], "status": "PASS"})
    return {"status": "PASS", "original_search_receipt_sha256": receipt["receipt_sha256"],
            "frozen_options_sha256": sha256(options_path.read_bytes()).hexdigest(), "rows": evidence}, selected_tables

def compare(root, eid):
    here = Path(__file__).resolve().parent
    accelerator_sha256 = sha256((here / "accelerator.py").read_bytes()).hexdigest()
    model_file_sha256 = {}
    audit = module("s012_independent_metrics", here / "independent_account_check.py")
    accelerator = module("s012_accelerator_compare", here / "accelerator.py")
    exp = root / "experiments/S012" / eid
    exp.resolve().relative_to((root / "experiments/S012").resolve())
    raw = here / eid / "execution"
    completed = exp / "artifacts/rex"
    workspace = completed if (completed / "execution_receipt.json").exists() else raw
    binding = audit.read(exp / "experiment_binding.json")
    audit.require(audit.source_digest(exp, binding["source_files"]) == binding["source_sha256"],
                  "experiment source byte closure changed")
    selection_evidence, selected_tables = None, {}
    if eid == "EX028_20261006":
        audit.require("selection.json" in binding["source_files"], "selection not in bound source closure")
        selection_evidence, selected_tables = verify_selection(root, exp, audit)
    if eid == "EX050_20261006":
        selection_evidence, selected_tables = verify_witness50_originals(root, exp, audit)
    trials = audit.read(workspace / "trials.json") if (workspace / "trials.json").exists() else []
    by_attempt = {t["record"]["attempt_id"]: t for t in trials}
    rows = []
    flows = Dataflows(base_dir=root, space=DataSpace(Path("data/backtest")),
                      providers=ProviderConfig(bindings={}))
    for folder in sorted((workspace / "evaluations").glob("*")):
        if not folder.is_dir():
            continue
        started = audit.read(folder / "started.json")
        row = {"attempt_id": folder.name, "candidate_id": started["candidate_id"]}
        record_path = folder / "record.json"
        if not record_path.exists():
            rows.append({**row, "status": "PARTIAL", "reason": "FULL evaluation not terminal"})
            continue
        record = audit.read(record_path)
        for field in ("attempt_id", "candidate_id", "content_sha256", "request_hash"):
            audit.require(record[field] == started[field], "started/record identity differs")
        if record["status"] != "SUCCEEDED":
            rows.append({**row, "status": "FAIL", "reason": record.get("error_message")})
            continue
        if folder.name not in by_attempt:
            rows.append({**row, "status": "PARTIAL", "reason": "result successful; trial source parameters not yet published"})
            continue
        try:
            trial = by_attempt[folder.name]
            if row["candidate_id"] in selected_tables:
                audit.require(trial["parameters"] == selected_tables[row["candidate_id"]][0]["parameters"],
                              "FULL trial differs from frozen selected parameters")
            artifact = record["result_artifact"]
            path = audit.checked_file(workspace, artifact["path"], artifact["sha256"], [])
            result = audit.read(path)
            audit.require(result["schema_version"] == 4 and result["request_identity"]["execution_mode"] == "FULL",
                          "not a schema-v4 FULL result")
            audit.require(result["request_hash"] == record["request_hash"] == audit.canonical(result["request_identity"]),
                          "request identity differs")
            runtime = trial["payload"]["runtime"]
            source_root = (root / trial["source_root"]).resolve()
            source_root.relative_to((root / "experiments/S012").resolve())
            audit.require(audit.source_digest(source_root, runtime["source_files"])
                          == runtime["source_sha256"], "candidate source changed")
            source = module("s012_equivalence_source", source_root / "strategies/s012.py")
            model_file_sha256[(source_root / "strategies/s012.py").relative_to(root).as_posix()] = sha256(
                (source_root / "strategies/s012.py").read_bytes()).hexdigest()
            strategy = source.S012PlannedCycle(ParameterSet(trial["payload"]["parameters"]))
            comparisons = []
            for run in result["runs"]:
                audit.require(audit.canonical(run["identity"]) in record["evaluation_ids"], "run identity differs")
                plan = StrategyInputBinding.from_mapping(run["signal_support"]["input_binding"])
                prepared_features = flows.fetch(plan.plan.requests["features"], prepared=plan.prepared)
                audit.require(prepared_features.ready, "bound features unreadable")
                frames = {}
                for name, raw_request in run["signal_support"]["execution_requests"].items():
                    data = flows.fetch(audit.request_from_support(raw_request), prepared=plan.prepared)
                    audit.require(data.ready, f"bound execution unreadable: {name}")
                    audit.require(data.identity.content_sha256 == run["signal_support"]["execution_input_identities"][name],
                                  f"execution identity differs: {name}")
                    frames[name] = data.dataframe
                fast = accelerator.simulate(strategy, prepared_features.dataframe,
                                            frames["execution_daily"], frames["execution_30m"])
                full = {name: audit.table(table, workspace) for name, table in run["ledgers"].items()}
                economics = accelerator.compare_economics(fast, full)
                screening_comparison = None
                if row["candidate_id"] in selected_tables:
                    selected, screening = selected_tables[row["candidate_id"]]
                    screening_comparison = accelerator.compare_economics(fast, screening)
                    for name in ("signals", "decisions"):
                        left, right = fast[name].copy(), screening[name].copy()
                        if name == "signals":
                            audit.require(pd.DatetimeIndex(left.index).as_unit("ns").equals(
                                pd.DatetimeIndex(right.index).as_unit("ns")), "screening signal dates differ")
                        for field in left.columns:
                            if field.endswith("date"):
                                left[field] = pd.to_datetime(left[field]).astype("datetime64[ns]")
                                right[field] = pd.to_datetime(right[field]).astype("datetime64[ns]")
                        pd.testing.assert_frame_equal(left.reset_index(drop=True), right.reset_index(drop=True),
                                                      check_dtype=False, atol=1e-8, rtol=1e-12)
                    benchmark = audit.account_metrics(audit.table(run["buyhold"]["account_daily"], workspace),
                                                       pd.DataFrame(), pd.DataFrame())
                    for original, independent in (("cagr", "net_cagr"), ("max_drawdown", "max_drawdown")):
                        audit.require(isclose(selected["metrics"]["benchmark"][original], benchmark[independent],
                                              rel_tol=1e-10, abs_tol=1e-10), "screening benchmark differs from FULL")
                full_signals = audit.table(run["signals"], workspace)
                signal_dates = pd.DatetimeIndex(pd.to_datetime(full_signals.signal_date))
                targets = fast["signals"].target_position.reindex(signal_dates).to_numpy()
                audit.require((targets == full_signals.target_position.to_numpy()).all(), "FULL signal targets differ")
                comparisons.append({"window_id": run["window_id"], "scenario_id": run["scenario_id"],
                                    "signal_rows": len(full_signals), "economics": economics,
                                    "original_screening_equivalence": screening_comparison,
                                    "full_result_artifact": {"path": path.relative_to(root).as_posix(),
                                                             "sha256": artifact["sha256"]},
                                    "full_signal_table": run["signals"],
                                    "full_ledgers": run["ledgers"],
                                    "accelerated_signal_table": json.loads(fast["signals"].reset_index()
                                          .to_json(orient="table", date_format="iso", index=False)),
                                    "accelerated_ledgers": {name: json.loads(fast[name].to_json(
                                          orient="table", date_format="iso", double_precision=15, index=False))
                                          for name in ("account_daily", "orders", "fills", "trades")},
                                    "prepared_manifest_sha256": plan.prepared.manifest_sha256})
            rows.append({**row, "status": "PASS", "source_sha256": runtime["source_sha256"],
                         "result_file_sha256": artifact["sha256"],
                         "record_file_sha256": sha256(record_path.read_bytes()).hexdigest(), "comparisons": comparisons})
        except (ValueError, KeyError, AssertionError, TypeError) as error:
            rows.append({**row, "status": "FAIL", "reason": str(error)})
    observed_attempts = len(rows)
    expected_ids = ({f"S012-C{i:04d}" for i in range(12, 23)} if eid == "EX023_20261005" else
                    {f"S012-C{i:04d}" for i in range(100, 104)} if eid == "EX025_20261005" else
                    set(selected_tables) if eid == "EX028_20261006" else
                    {f"S012-C{i:04d}" for i in range(4600, 4608)} if eid == "EX050_20261006" else set())
    if expected_ids:
        observed_ids = {r["candidate_id"] for r in rows}
        audit.require(observed_ids <= expected_ids, "unexpected witness candidate")
        for candidate_id in sorted(expected_ids - observed_ids):
            rows.append({"candidate_id": candidate_id, "status": "PARTIAL",
                         "reason": "expected explicit witness; no terminal trial yet"})
    passed = sum(r["status"] == "PASS" for r in rows)
    failed = sum(r["status"] == "FAIL" for r in rows)
    expected_configs = {"EX023_20261005": 11, "EX025_20261005": 4, "EX028_20261006": 4, "EX050_20261006": 8}.get(eid)
    audit.require(expected_configs is not None, "experiment has no explicit bounded equivalence witness contract")
    all_expected = len(rows) == expected_configs and passed == expected_configs and len(trials) == expected_configs
    if eid == "EX025_20261005":
        audit.require({r["candidate_id"] for r in rows} == {f"S012-C{i:04d}" for i in range(100, 104)},
                      "EX025 witness candidate closure differs")
    receipt_status = "NOT_COMPLETE_REX"
    if (completed / "execution_receipt.json").exists():
        receipt = audit.receipt_chain(root, eid, [], {})
        audit.require(len(receipt["trace"]["evaluations"]) == expected_configs,
                      "receipt trial count differs from witness contract")
        for row in trials:
            audit.require(row["record"] in receipt["trace"]["evaluations"],
                          "trial record absent from signed receipt trace")
        receipt_status = "COMPLETE_REX_CHAIN_PASS"
    audit.require(sha256((here / "accelerator.py").read_bytes()).hexdigest() == accelerator_sha256,
                  "accelerator source changed during comparison")
    return {"schema_version": 2, "experiment_id": eid,
            "scope": "completed formal witness comparison" if receipt_status == "COMPLETE_REX_CHAIN_PASS" else "operational partial evidence only",
            "status": "FAIL" if failed else "PASS" if all_expected else "PARTIAL",
            "expected_configs": expected_configs, "passed": passed, "observed_attempts": observed_attempts, "rows": rows,
            "all_expected_semantic_ledgers_equivalent": all_expected,
            "all_11_semantic_ledgers_equivalent": all_expected if eid == "EX023_20261005" else None,
            "receipt_status": receipt_status,
            "complete_formal_witness_pass": all_expected and receipt_status == "COMPLETE_REX_CHAIN_PASS",
            "approved_for_research_comparison": all_expected and receipt_status == "COMPLETE_REX_CHAIN_PASS",
            "accelerator_sha256": accelerator_sha256,
            "model_file_sha256": model_file_sha256,
            "bound_model_sha256": next(iter(set(model_file_sha256.values())))
                if len(set(model_file_sha256.values())) == 1 else None,
            "comparison_atol": 1e-8, "comparison_rtol": 1e-12,
            "original_selection_audit": selection_evidence,
            "source_bound": binding["source_sha256"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", default="EX050_20261006")
    parser.add_argument("--output", default=".tmp/s012-stage3-native-20261006/accelerator_comparison.json")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    result = compare(root, args.experiment)
    target = (root / args.output).resolve()
    target.relative_to(root / ".tmp")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "passed": result["passed"],
                      "observed_attempts": result["observed_attempts"],
                      "approved_for_research_comparison": result["approved_for_research_comparison"]}))


if __name__ == "__main__":
    main()
