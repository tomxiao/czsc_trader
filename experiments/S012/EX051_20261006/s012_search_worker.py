"""Ordinary importable S012 screening worker for Windows spawn.

This worker emits research ledgers, never a TDR FULL EvaluationRecord.
"""
from __future__ import annotations

import gzip
from hashlib import sha256
import json
from pathlib import Path
import traceback

import pandas as pd
from strategy_runtime import ParameterSet

from s012_accelerator import simulate
from s012_bound_model import S012PlannedCycle
from scope_contract import proposal_scope

_INPUTS = None


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def initialize(features, daily, intraday, source, output, benchmark, delivery_scope_base, gate_sha256):
    global _INPUTS
    _INPUTS = (features, daily, intraday, source, Path(output), benchmark, delivery_scope_base, gate_sha256)


def evaluate(number, parameters):
    if _INPUTS is None:
        raise RuntimeError("screening worker requires authenticated initializer")
    features, daily, intraday, source, output, benchmark, base, gate_sha256 = _INPUTS
    proposal_id = f"OPTUNA_{number:04d}"
    folder = output / "screening_ledgers" / proposal_id
    folder.mkdir(parents=True, exist_ok=False)
    parameter_sha = sha256(canonical(parameters)).hexdigest()
    scope = None
    try:
        strategy = S012PlannedCycle(ParameterSet({**parameters, "rule": {"data_source": source}}))
        scope = proposal_scope(strategy,base,gate_sha256)
        result = simulate(strategy, features, daily, intraday)
        result["mode"] = "RESEARCH_SCREENING_EQUIVALENT_SUBSET_NOT_FULL"
        ledgers = {}
        for name, value in result.items():
            if isinstance(value, pd.DataFrame):
                # orient=table retains every row, field and datetime schema. NaN
                # for an OPEN trade is JSON null, not an invented closed result.
                raw = value.to_json(orient="table", date_format="iso", date_unit="ns",
                                    double_precision=15, force_ascii=False).encode("utf-8")
                path = folder / f"{name}.json.gz"
                with path.open("wb") as stream:
                    with gzip.GzipFile(filename="", mode="wb", fileobj=stream,
                                       compresslevel=6, mtime=0) as compressed:
                        compressed.write(raw)
                ledgers[name] = {"path": path.relative_to(output).as_posix(),
                                 "sha256": sha256(path.read_bytes()).hexdigest(),
                                 "uncompressed_sha256": sha256(raw).hexdigest(),
                                 "rows": len(value), "columns": list(value.columns),
                                 "bytes": path.stat().st_size}
        account, trades = result["account_daily"], result["trades"]
        equity = account.equity.astype(float)
        closed = int(trades.status.eq("CLOSED").sum())
        cagr = float((equity.iloc[-1] / 100000.) ** (252. / len(equity)) - 1.)
        max_drawdown = float((equity / equity.cummax().clip(lower=100000.) - 1.).min())
        frequency = closed * 60. / 1535.
        goals = [cagr >= benchmark["cagr"] * 1.5,
                 abs(max_drawdown) < abs(benchmark["max_drawdown"]), frequency >= 5.]
        metrics = {"net_cagr": cagr, "max_drawdown": max_drawdown,
                   "closed_trades": closed, "frequency": frequency,
                   "benchmark": benchmark, "goals": goals, "passed_all": all(goals),
                   "evaluation_sessions": len(equity), "frequency_denominator": 1535,
                   "final_equity": float(equity.iloc[-1]),
                   "final_quantity": int(account.quantity.iloc[-1]),
                   "total_fees": float(result["fills"].fees.sum()),
                   "exposure": float(account.quantity.gt(0).mean()),
                   "orders": len(result["orders"]), "fills": len(result["fills"]),
                   "mode": result["mode"]}
        # Account-independent behavior fingerprint combines complete causal
        # signals with execution policy. It is diagnostic, never pruning by PNL.
        signal_policy_sha = sha256(canonical({"signals": ledgers["signals"]["uncompressed_sha256"],
                                             "entry_premium": parameters["entry_premium"],
                                             "allocation": parameters["allocation"]})).hexdigest()
        economic_columns = {
            "account_daily": ["date", "signal_date", "target_position", "cash_before", "quantity_before",
                              "cash", "quantity", "close", "equity"],
            "orders": ["signal_date", "execution_date", "side", "quantity", "order_type", "limit_price", "status"],
            "fills": ["signal_date", "fill_time", "side", "quantity", "price", "fees", "trigger"],
            "trades": ["status", "entry_date", "exit_date", "quantity", "entry_price", "exit_price", "net_return"],
        }
        behavior_sha = sha256(canonical({
            name: json.loads(result[name][columns].to_json(
                orient="table", date_format="iso", date_unit="ns", double_precision=15, index=False))
            for name, columns in economic_columns.items()
        })).hexdigest()
        summary = {"proposal_id": proposal_id, "trial_number": number,
                   "parameters": parameters, "parameter_sha256": parameter_sha,
                   "scope": scope,
                   "behavior_sha256": behavior_sha, "signal_policy_sha256": signal_policy_sha,
                   "metrics": metrics,
                   "raw_ledgers": ledgers, "candidate": None,
                   "status": "COMPLETE", "mode": result["mode"]}
        summary['reason']='New scoped equivalence-gated research account; successor FULL required'
        summary['passed_all']=metrics['passed_all']
        raw = canonical(summary)
        path = folder / "summary.json"
        path.write_bytes(raw + b"\n")
        summary["raw_summary"] = {"path": path.relative_to(output).as_posix(),
                                  "sha256": sha256(path.read_bytes()).hexdigest()}
        return summary
    except Exception as error:
        record = {"proposal_id": proposal_id, "trial_number": number,
                  "parameters": parameters, "parameter_sha256": parameter_sha,
                  "candidate": None, "status": "FAILED", "reason": repr(error),
                  "traceback": traceback.format_exc(), "mode": "RESEARCH_SCREENING_NOT_FULL"}
        if scope is not None:record['scope']=scope
        path = folder / "failure.json"
        path.write_bytes(canonical(record) + b"\n")
        record["raw_failure"] = {"path": path.relative_to(output).as_posix(),
                                  "sha256": sha256(path.read_bytes()).hexdigest()}
        return record
