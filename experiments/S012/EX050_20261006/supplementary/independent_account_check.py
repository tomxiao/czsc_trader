"""Read-only S012 formal account audit, independent of platform metric code."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from math import isclose, isfinite
from pathlib import Path
import re

import pandas as pd
from dataflows import (
    Dataflows, DataSpace, DataRequest, DataCoverageRequirement,
    EvidenceParameters, NoParameters, ProviderConfig, canonical_frame_sha256,
)
from strategy_runtime import StrategyInputBinding


INITIAL_CASH = 100000.0
FREQUENCY_DENOMINATOR = 1535
EXPECTED_SESSIONS = 1534


def canonical(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def bounded(root, relative):
    path = (root / relative).resolve()
    path.relative_to(root.resolve())
    return path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checked_file(root, relative, expected, checks):
    path = bounded(root, relative)
    digest = sha256(path.read_bytes()).hexdigest()
    require(digest == expected, f"SHA differs: {path}")
    checks.append({"path": str(path), "sha256": digest})
    return path


def source_digest(root, names):
    require(len(set(names)) == len(names), "duplicate source closure")
    digest = sha256()
    for name in sorted(names):
        path = bounded(root, name)
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def receipt_chain(root, eid, checks, seen, expected=None):
    require(re.fullmatch(r"EX\d{3}_\d{8}", eid) is not None, "invalid experiment id")
    if eid in seen:
        require(expected is None or seen[eid]["receipt_sha256"] == expected,
                "predecessor receipt differs")
        return seen[eid]
    exp = root / "experiments/S012" / eid
    workspace = exp / "artifacts/rex"
    envelope = read(workspace / "execution_envelope.json")
    publication = read(workspace / "execution_receipt.json")
    receipt = envelope["receipt"]
    digest = canonical(receipt)
    require(digest == envelope["receipt_sha256"], "receipt canonical SHA differs")
    require(publication == {**receipt, "receipt_sha256": digest}, "receipt/envelope differs")
    require(expected is None or digest == expected, "expected predecessor receipt differs")
    require(receipt["experiment_id"] == eid, "receipt experiment identity differs")
    require(canonical(envelope["result"]) == receipt["result_sha256"], "REX result SHA differs")
    artifacts = {a["path"]: a["sha256"] for a in envelope["result"]["artifacts"]}
    require(artifacts == receipt["artifact_sha256"], "receipt artifact closure differs")
    for relative, digest_value in artifacts.items():
        checked_file(workspace, relative, digest_value, checks)
    binding = read(exp / "experiment_binding.json")
    actual_source = source_digest(exp, binding["source_files"])
    require(actual_source == binding["source_sha256"] == receipt["source_sha256"],
            "experiment source closure differs")
    preflight_path = exp / "artifacts/preflight.json"
    if preflight_path.exists():
        preflight = read(preflight_path)
        require(preflight["status"] == "PASS", "formal preflight did not pass")
        for name in ("definition_sha256", "source_sha256", "resources_sha256"):
            require(preflight["result"][name] == receipt[name], f"preflight {name} differs")
    value = {**receipt, "receipt_sha256": digest, "workspace": workspace,
             "preflight_verification": "PASS" if preflight_path.exists() else "NO_SEPARATE_HISTORICAL_PREFLIGHT_FILE"}
    seen[eid] = value
    for predecessor, predecessor_sha in receipt["predecessor_receipts"].items():
        receipt_chain(root, predecessor, checks, seen, predecessor_sha)
    # Provenance lists exact feature payloads; all remain inside S012.
    provenance_path = exp / "feature_provenance.json"
    if provenance_path.exists():
        provenance = read(provenance_path)
        checked_file(exp, "strategy_runtime/resources/features.csv",
                     provenance["feature_sha256"], checks)
        for name, expected_sha in provenance["inputs"].items():
            prior, relative = name.split("/", 1)
            require(prior in seen, f"feature source outside predecessor closure: {prior}")
            require(seen[prior]["artifact_sha256"].get(relative) == expected_sha,
                    "feature artifact differs from predecessor receipt")
            checked_file(seen[prior]["workspace"], relative, expected_sha, checks)
    return value


def table(value, workspace):
    # Current schema v4 embeds pandas orient=table JSON directly. Explicit file
    # references can also be admitted when they carry their own file SHA.
    if isinstance(value, dict) and "schema" in value and "data" in value:
        return pd.DataFrame(value["data"], columns=[x["name"] for x in value["schema"]["fields"]])
    if isinstance(value, dict) and {"path", "sha256"} <= set(value):
        path = checked_file(workspace, value["path"], value["sha256"], [])
        if path.suffix == ".parquet":
            return pd.read_parquet(path)
        if path.suffix == ".csv":
            return pd.read_csv(path)
    raise ValueError("unrecognized account table schema")


def account_metrics(account, trades, fills):
    require({"date", "equity", "cash", "quantity", "close"} <= set(account),
            "incomplete account columns")
    dates = pd.DatetimeIndex(pd.to_datetime(account["date"], errors="raise"))
    require(not dates.has_duplicates and dates.is_monotonic_increasing, "invalid account dates")
    require(len(account) == EXPECTED_SESSIONS, "account is not the full 1534-day formal window")
    require(str(dates[0].date()) == "2020-06-08" and str(dates[-1].date()) == "2026-09-30",
            "account window endpoints differ")
    equity = account.equity.astype(float)
    require(equity.map(lambda x: isfinite(x) and x > 0).all(), "invalid equity")
    difference = (equity - account.cash.astype(float) - account.quantity.astype(float)
                  * account.close.astype(float)).abs()
    require(float(difference.max()) <= 1e-6, "cash/position equity does not reconcile")
    peak = INITIAL_CASH
    drawdown = 0.0
    for value in equity:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1.0)
    closed = int(trades.status.eq("CLOSED").sum()) if len(trades) else 0
    gross = float((fills.quantity.astype(float) * fills.price.astype(float)).sum()) if len(fills) else 0.0
    fees = float(fills.fees.astype(float).sum()) if len(fills) else 0.0
    annual = []
    opening_equity = INITIAL_CASH
    for year in sorted(set(dates.year)):
        group = account.loc[dates.year == year]
        ending = float(group.equity.iloc[-1])
        annual.append({"year": int(year), "sessions": len(group),
                       "start_date": str(pd.Timestamp(group.date.iloc[0]).date()),
                       "end_date": str(pd.Timestamp(group.date.iloc[-1]).date()),
                       "opening_equity_previous_close": opening_equity,
                       "ending_equity": ending, "period_net_return": ending / opening_equity - 1.0})
        opening_equity = ending
    return {"net_cagr": (float(equity.iloc[-1]) / INITIAL_CASH) ** (252 / len(account)) - 1,
            "max_drawdown": drawdown, "closed_trades": closed,
            "frequency": closed * 60 / FREQUENCY_DENOMINATOR,
            "final_equity": float(equity.iloc[-1]), "final_quantity": int(account.quantity.iloc[-1]),
            "total_fees": fees, "gross_fill_amount": gross,
            "exposure": float(account.quantity.gt(0).mean()),
            "open_cycles": int(trades.status.eq("OPEN").sum()) if len(trades) else 0,
            "annual": annual}


def reconcile_fills(account, fills, fee_rate):
    cash, quantity = INITIAL_CASH, 0
    records = fills.to_dict("records")
    by_date = {}
    account_dates = {pd.Timestamp(x).date() for x in account["date"]}
    for fill in records:
        fill_date = pd.Timestamp(fill["fill_time"]).date()
        require(fill_date in account_dates, "fill lies outside audited account dates")
        by_date.setdefault(fill_date, []).append(fill)
    for row in account.to_dict("records"):
        for fill in by_date.get(pd.Timestamp(row["date"]).date(), []):
            size, price, fee = int(fill["quantity"]), float(fill["price"]), float(fill["fees"])
            require(size > 0 and size % 100 == 0, "fill quantity is not whole 100-share lots")
            require(isclose(fee, size * price * fee_rate, rel_tol=1e-10, abs_tol=1e-8),
                    "fill fee differs from formal cost")
            if fill["side"] == "BUY":
                cash -= size * price + fee
                quantity += size
            else:
                require(fill["side"] == "SELL", "invalid fill side")
                cash += size * price - fee
                quantity -= size
            require(cash >= -1e-6 and quantity >= 0, "fill path exceeds cash/holdings")
        require(isclose(cash, float(row["cash"]), rel_tol=1e-10, abs_tol=1e-6),
                "independent daily cash differs")
        require(quantity == int(row["quantity"]), "independent daily quantity differs")


def request_from_support(raw):
    value = dict(raw)
    parameters = value.get("parameters", {})
    value["parameters"] = (EvidenceParameters(Path(parameters["repository_root"]),
                           parameters["source_path"], parameters["source_sha256"])
                           if parameters else NoParameters())
    if value.get("coverage") is not None:
        value["coverage"] = DataCoverageRequirement(**value["coverage"])
    return DataRequest(**value)


def managed_checks(run, flows):
    support = run["signal_support"]
    binding = StrategyInputBinding.from_mapping(support["input_binding"])
    identities = {}
    execution_daily = None
    for name, raw in support["execution_requests"].items():
        request = request_from_support(raw)
        result = flows.fetch(request, prepared=binding.prepared)
        require(result.ready, f"bound execution input unreadable: {name}: {result.error}")
        digest = canonical_frame_sha256(result.dataframe)
        require(digest == result.identity.content_sha256 == support["execution_input_identities"][name],
                f"execution input SHA differs: {name}")
        identities[name] = digest
        if name == "execution_daily":
            execution_daily = result.dataframe.copy()
    for name, request in binding.plan.requests.items():
        result = flows.fetch(request, prepared=binding.prepared)
        require(result.ready, f"bound strategy input unreadable: {name}: {result.error}")
        digest = canonical_frame_sha256(result.dataframe)
        require(digest == result.identity.content_sha256, f"strategy input hash differs: {name}")
        identities[f"strategy:{name}"] = digest
    require(execution_daily is not None, "execution daily binding absent")
    return {"binding_identity": binding.identity, "prepared_manifest_sha256": binding.prepared.manifest_sha256,
            "input_identities": identities}, execution_daily


def audit(root, experiments, data_space):
    checks, seen, output, failed = [], {}, [], []
    flows = Dataflows(base_dir=root, space=DataSpace(Path(data_space)), providers=ProviderConfig(bindings={}))
    for eid in experiments:
        try:
            require((root / "experiments/S012" / eid / "artifacts/preflight.json").is_file(),
                    "current formal account experiment must retain preflight evidence")
            receipt = receipt_chain(root, eid, checks, seen)
            workspace = receipt["workspace"]
            require("trials.json" in receipt["artifact_sha256"], "formal trials artifact absent")
            trials = read(workspace / "trials.json")
            terminal = {r["attempt_id"]: r for r in receipt["trace"]["evaluations"]}
            for trial in trials:
                record = trial["record"]
                require(terminal.get(record["attempt_id"]) == record, "trial record differs from receipt trace")
                if record["status"] != "SUCCEEDED":
                    output.append({"experiment_id": eid, "candidate_id": trial["candidate_id"],
                                   "status": "UNSUCCESSFUL", "error_code": record.get("error_code")})
                    continue
                result_path = checked_file(workspace, record["result_artifact"]["path"],
                                           record["result_artifact"]["sha256"], checks)
                result = read(result_path)
                require(result["schema_version"] == 4, "unexpected evaluation result schema")
                require(result["result_hash"] == record["result_hash"], "result identity differs")
                require(result["request_hash"] == canonical(result["request_identity"]) == record["request_hash"],
                        "request hash differs")
                request = result["request_identity"]
                require(request["execution_mode"] == "FULL", "successful evaluation is not FULL")
                require(request["initial_cash"] == INITIAL_CASH and request["symbol"] == "518850.SH",
                        "account mandate differs")
                runtime = trial["payload"]["runtime"]
                source_root = bounded(root, trial["source_root"])
                require(source_digest(source_root, runtime["source_files"]) == runtime["source_sha256"],
                        "strategy source closure differs")
                for run in result["runs"]:
                    require(canonical(run["identity"]) in record["evaluation_ids"], "run identity differs")
                    require(run["candidate_id"] == trial["candidate_id"], "run candidate differs")
                    ledgers = {name: table(value, workspace) for name, value in run["ledgers"].items()}
                    cost = next(x["one_way_cost"] for x in request["costs"] if x["scenario_id"] == run["scenario_id"])
                    require(cost == .001, "audit accepts only the mandated base cost .001")
                    reconcile_fills(ledgers["account_daily"], ledgers["fills"], cost)
                    metrics = account_metrics(ledgers["account_daily"], ledgers["trades"], ledgers["fills"])
                    observation = run["observation"]
                    for name in ("net_cagr", "max_drawdown", "closed_trades"):
                        require(isclose(metrics[name], observation[name], rel_tol=1e-10, abs_tol=1e-10),
                                f"independent {name} differs from observation")
                    benchmark = run["buyhold"]
                    require(benchmark is not None, "BuyHold evidence absent")
                    benchmark_account = table(benchmark["account_daily"], workspace)
                    benchmark_orders = table(benchmark["orders"], workspace)
                    benchmark_metrics = account_metrics(benchmark_account, pd.DataFrame(), pd.DataFrame())
                    benchmark_metrics["total_fees"] = float(benchmark_orders.fees.sum())
                    benchmark_metrics["gross_fill_amount"] = float((benchmark_orders["size"] * benchmark_orders.price).sum())
                    benchmark_metrics["open_cycles"] = int(benchmark_account.quantity.iloc[-1] > 0)
                    evidence, source_daily = managed_checks(run, flows)
                    market = source_daily.set_index(pd.to_datetime(source_daily.Date))
                    for account in (ledgers["account_daily"], benchmark_account):
                        expected_close = market.Close.reindex(pd.to_datetime(account.date)).to_numpy()
                        require(all(isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-10)
                                    for a, b in zip(account.close, expected_close)), "ledger close differs from bound market")
                    require(len(benchmark_orders) == 1 and benchmark_orders.side.iloc[0] == "BUY",
                            "NextOpenBuyHold must make one entry")
                    first = market.loc[pd.Timestamp("2020-06-08")]
                    size = int(INITIAL_CASH / (float(first.Open) * (1 + cost))) // 100 * 100
                    require(int(benchmark_orders["size"].iloc[0]) == size, "BuyHold affordable quantity differs")
                    require(isclose(float(benchmark_orders.price.iloc[0]), float(first.Open), abs_tol=1e-10),
                            "BuyHold price differs from first open")
                    buyhold_fee = size * float(first.Open) * cost
                    require(isclose(float(benchmark_orders.fees.iloc[0]), buyhold_fee,
                                    rel_tol=1e-10, abs_tol=1e-8), "BuyHold fee differs")
                    buyhold_cash = INITIAL_CASH - size * float(first.Open) - buyhold_fee
                    require(benchmark_account.quantity.eq(size).all(), "BuyHold quantity varies")
                    require(all(isclose(float(value), buyhold_cash, rel_tol=1e-10, abs_tol=1e-6)
                                for value in benchmark_account.cash), "BuyHold cash differs")
                    goals = [metrics["net_cagr"] >= benchmark_metrics["net_cagr"] * 1.5,
                             abs(metrics["max_drawdown"]) < abs(benchmark_metrics["max_drawdown"]),
                             metrics["frequency"] >= 5]
                    output.append({"experiment_id": eid, "candidate_id": trial["candidate_id"],
                                   "window_id": run["window_id"], "scenario_id": run["scenario_id"],
                                   "status": "PASS", "parameters": trial["parameters"],
                                   "metrics": metrics, "buyhold": benchmark_metrics,
                                   "goals": goals, "passed_all": all(goals),
                                   "managed_evidence": evidence,
                                   "platform_summary_passed_all": trial.get("passed_all")})
        except (ValueError, KeyError, FileNotFoundError, TypeError) as error:
            failed.append({"experiment_id": eid, "error": str(error)})
    passed = [r for r in output if r.get("status") == "PASS" and r.get("passed_all")]
    return {"schema_version": 1, "status": "FAIL" if failed else "PASS", "experiments": experiments,
            "initial_cash": INITIAL_CASH, "formal_sessions": EXPECTED_SESSIONS,
            "frequency_denominator": FREQUENCY_DENOMINATOR, "sha_checked_files": checks,
            "verified_receipt_hashes": {eid: r["receipt_sha256"] for eid, r in seen.items()},
            "receipt_preflight_checks": {eid: r["preflight_verification"] for eid, r in seen.items()},
            "rows": output, "errors": failed,
            "all_qualified_handoff": [{"experiment_id": r["experiment_id"], "candidate_id": r["candidate_id"],
                                       "window_id": r["window_id"], "scenario_id": r["scenario_id"]} for r in passed],
            "schema_notes": [
                "Schema v4 stores account/fill/trade tables inside result JSON, not mandatory separate CSV/Parquet.",
                "REX receipt SHA is canonical object SHA; result_artifact SHA hashes file bytes.",
                "Numerical ledgers serialize at 15 decimal digits; comparisons allow only small serialization roundoff.",
                "Platform result_hash is checked across stored identities; rehash of original DataFrames is not asserted because serialization can lose binary64 precision.",
                "Definition/resources hashes are cross-checked against preflight, not recomputed from a fresh mutable runtime.",
                "Managed input payloads and manifest authentication use the public read-only DFLS fetch contract.",
                "Annual returns use prior-year actual closing equity, retaining continuous account state.",
                "Sealed partial-failure experiments without complete REX receipts cannot pass this formal audit.",
            ]}


def synthetic_selfcheck():
    """Exercise metrics and continuous annual accounting without market reads."""
    dates = pd.bdate_range("2020-06-08", "2026-09-29")[:EXPECTED_SESSIONS - 1]
    dates = dates.append(pd.DatetimeIndex([pd.Timestamp("2026-09-30")]))
    equity = pd.Series(99900.0, index=range(EXPECTED_SESSIONS))
    equity.iloc[-1] = 110000.0
    account = pd.DataFrame({"date": dates, "equity": equity, "cash": equity,
                            "quantity": 0, "close": 10.0})
    trades = pd.DataFrame({"status": ["CLOSED"] * 128 + ["OPEN"]})
    metrics = account_metrics(account, trades, pd.DataFrame())
    require(isclose(metrics["max_drawdown"], -.001, abs_tol=1e-12),
            "synthetic initial-cash drawdown failed")
    require(isclose(metrics["net_cagr"], 1.1 ** (252 / 1534) - 1, abs_tol=1e-12),
            "synthetic CAGR failed")
    require(metrics["closed_trades"] == 128 and metrics["frequency"] >= 5,
            "synthetic closed trade denominator failed")
    require(metrics["open_cycles"] == 1, "synthetic open cycle failed")
    annual = metrics["annual"]
    for before, after in zip(annual, annual[1:]):
        require(after["opening_equity_previous_close"] == before["ending_equity"],
                "annual account reset detected")
    return {"status": "PASS", "checks": ["initial_cash_peak", "actual_n_cagr",
            "closed_status_only", "original_frequency_denominator", "continuous_annual_equity"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiments", nargs="+")
    parser.add_argument("--selfcheck", action="store_true")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--data-space", default="data/backtest")
    parser.add_argument("--output", type=Path, default=Path(".tmp/s012-stage3-20261005/audit.json"))
    args = parser.parse_args()
    if args.selfcheck:
        print(json.dumps(synthetic_selfcheck(), ensure_ascii=False))
        return 0
    require(bool(args.experiments), "--experiments is required for formal audit")
    root = args.root.resolve()
    report = audit(root, args.experiments, args.data_space)
    target = bounded(root / ".tmp", args.output.resolve().relative_to(root / ".tmp"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "rows": len(report["rows"]),
                      "qualified": len(report["all_qualified_handoff"]), "errors": report["errors"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
