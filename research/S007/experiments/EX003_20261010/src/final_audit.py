"""Read-only independent four-dimension checks from published account references."""

from pathlib import Path
from collections import defaultdict
import hashlib
import json
import math
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / "research/S007/assets/runs/EX003_20261010/independent-final"
OUT.mkdir(parents=True, exist_ok=True)
SOURCES = {}


def js(path):
    path = ROOT / path
    raw = path.read_bytes()
    SOURCES[path.relative_to(ROOT).as_posix()] = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }
    return json.loads(raw)


def fact(ref):
    relative = f"research/{ref['experiment']['strategy_id']}/assets/evidence/{ref['experiment']['experiment_id']}/{ref['evidence_id']}"
    raw = js(relative)
    assert SOURCES[relative]["sha256"] == ref["sha256"]
    return raw


def old_csv(relative):
    path = ROOT / relative
    raw = path.read_bytes()
    SOURCES[relative] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    return pd.read_csv(path, float_precision="round_trip")


def original_center_check(raw):
    run = next(x for x in raw["runs"] if x["scenario_id"] == "baseline")
    checks = {}
    targets = {
        "account_daily": [
            "date",
            "cash_before",
            "quantity_before",
            "cash",
            "quantity",
            "close",
            "equity",
            "target_position",
        ],
        "fills": ["fill_time", "signal_date", "side", "quantity", "price", "fees"],
        "trades": ["entry_date", "exit_date", "quantity", "entry_price", "exit_price"],
    }
    for table, cols in targets.items():
        relative = f"experiments/S007/20260915_S007_EX31/artifacts/{table}.csv"
        old = old_csv(relative)
        new = pd.DataFrame(run["ledgers"][table]["data"])
        assert len(old) == len(new)
        for col in cols:
            if col == "date" or col.endswith(("_date", "_time")):
                assert np.array_equal(pd.to_datetime(old[col]), pd.to_datetime(new[col]))
            else:
                assert np.array_equal(old[col].to_numpy(), new[col].to_numpy())
        checks[table] = {"rows": len(old), "economic_columns_exact": cols}
    return checks


def metric(ev):
    wealth = np.r_[ev["initial_cash"], [x["equity"] for x in ev["account"]]]
    return {
        "net_cagr": float((wealth[-1] / wealth[0]) ** (252 / len(ev["account"])) - 1),
        "drawdown_magnitude": float(np.max(1 - wealth / np.maximum.accumulate(wealth))),
    }


def reconcile(ev):
    closed = {x["cycle_id"]: x["exit_session"] for x in ev["closed_cycles"]}
    assert len(closed) == len(ev["closed_cycles"])
    assert ev["opening_quantity"] == 0
    flow = defaultdict(float)
    quantity = defaultdict(int)
    last = {}
    by_date = defaultdict(list)
    for fill in ev["fills"]:
        by_date[fill["session"]].append(fill)
    fee_rate = ev["scenario_context"]["one_way_cost"]
    cash = ev["opening_cash"]
    qty = ev["opening_quantity"]
    max_cash = max_wealth = max_fee = 0.0
    for point in ev["account"]:
        for fill in by_date[point["session"]]:
            sign = 1 if fill["side"] == "BUY" else -1
            cf = -sign * fill["quantity"] * fill["price"] - fill["fees"]
            cash += cf
            qty += sign * fill["quantity"]
            flow[fill["cycle_id"]] += cf
            quantity[fill["cycle_id"]] += sign * fill["quantity"]
            last[fill["cycle_id"]] = point["session"]
            max_fee = max(max_fee, abs(fill["fees"] - fee_rate * fill["quantity"] * fill["price"]))
        max_cash = max(max_cash, abs(cash - point["cash"]))
        max_wealth = max(
            max_wealth, abs(point["equity"] - point["cash"] - point["close"] * point["quantity"])
        )
        assert qty == point["quantity"]
    assert set(by_date).issubset({x["session"] for x in ev["account"]})
    for cid, exit_date in closed.items():
        assert quantity[cid] == 0 and last[cid] == exit_date
    assert all(q > 0 or cid in closed for cid, q in quantity.items())
    closed_pnl = sum(flow[cid] for cid in closed)
    open_pnl = sum(
        flow[cid] + quantity[cid] * ev["account"][-1]["close"] for cid in flow if cid not in closed
    )
    residual = abs(
        closed_pnl
        + open_pnl
        + ev["opening_cash"]
        - ev["initial_cash"]
        - (ev["account"][-1]["equity"] - ev["initial_cash"])
    )
    winners = sorted([flow[cid] for cid in closed if flow[cid] > 0], reverse=True)
    top_n = math.ceil(0.1 * len(winners))
    assert max(max_cash, max_wealth, max_fee, residual) < 1e-6
    return {
        "closed": len(closed),
        "positive_closed": len(winners),
        "top_count": top_n,
        "positive_cash_profit": sum(winners),
        "top_cash_profit": sum(winners[:top_n]),
        "concentration": sum(winners[:top_n]) / sum(winners),
        "open_cycles": len(flow) - len(closed),
        "open_pnl": open_pnl,
        "closed_pnl": closed_pnl,
        "equity_minus_initial": ev["account"][-1]["equity"] - ev["initial_cash"],
        "max_cash_error": max_cash,
        "max_equity_error": max_wealth,
        "max_fee_error": max_fee,
        "wealth_error": residual,
    }


def select(raw, scenario):
    ev = next(x for x in raw["assessment_evidence"] if x["scenario_id"] == scenario)
    obs = next(x["observation"] for x in raw["runs"] if x["scenario_id"] == scenario)
    stats = metric(ev)
    assert abs(stats["net_cagr"] - obs["net_cagr"]) < 1e-12
    assert abs(stats["drawdown_magnitude"] - abs(obs["max_drawdown"])) < 1e-12
    return ev, stats, reconcile(ev)


def rolling(ev, benchmark, prefix):
    own = np.r_[ev["initial_cash"], [x["equity"] for x in ev["account"]]]
    bh = np.r_[ev["initial_cash"], benchmark]
    assert len(own) == len(bh)
    dates = [x["session"] for x in ev["account"]]
    assert dates == sorted(set(dates))
    rows = []
    for start in range(0, len(own) - 126, 21):
        rows.append(
            {
                "start_index": start,
                "first_date": dates[start],
                "last_date": dates[start + 125],
                "strategy_return": own[start + 126] / own[start] - 1,
                "benchmark_return": bh[start + 126] / bh[start] - 1,
                "excess": own[start + 126] / own[start] - bh[start + 126] / bh[start],
            }
        )
    pd.DataFrame(rows).to_csv(OUT / f"final-{prefix}-rolling.csv", index=False, lineterminator="\n")
    return {
        "q10_linear": float(np.quantile([x["excess"] for x in rows], 0.1, method="linear")),
        "windows": len(rows),
        "daily_points": len(dates),
        "first_date": dates[0],
        "last_date": dates[-1],
    }


def neighbors(rows, refkey):
    results = []
    for row in rows:
        assert row["status"] == "SUCCEEDED"
        raw = fact(row[refkey])
        assert (
            raw["request_hash"] == row["request_hash"] and raw["result_hash"] == row["result_hash"]
        )
        ev, stats, accountcheck = select(raw, "baseline")
        expected = row.get("content_sha256", row.get("child_content_sha256"))
        assert ev["candidate"]["content_sha256"] == expected
        results.append(
            {
                "candidate_id": row["candidate_id"],
                "metrics": stats,
                "account_check": accountcheck,
                "reference": row[refkey],
            }
        )
    assert len(results) == 8 and len({x["candidate_id"] for x in results}) == 8
    return results


def summarize(center, rows):
    q10 = float(np.quantile([x["metrics"]["net_cagr"] for x in rows], 0.1, method="linear"))
    q90 = float(
        np.quantile([x["metrics"]["drawdown_magnitude"] for x in rows], 0.9, method="linear")
    )
    return {
        "q10_cagr": q10,
        "q90_drawdown": q90,
        "cagr_degradation": max(0.0, center["net_cagr"] - q10),
        "drawdown_worsening": max(0.0, q90 - center["drawdown_magnitude"]),
        "count": 8,
        "quantile": "LINEAR",
        "rows": rows,
    }


def cost_proof(base, stress):
    assert base["candidate"] == stress["candidate"]
    assert base["scenario_context"]["one_way_cost"] == 0.001
    assert stress["scenario_context"]["one_way_cost"] == 0.002
    a, b = base["fills"], stress["fills"]
    assert len(a) == len(b)
    changes = []
    for x, y in zip(a, b):
        assert x["session"] == y["session"] and x["side"] == y["side"]
        if x["quantity"] != y["quantity"]:
            changes.append(
                {
                    "session": x["session"],
                    "side": x["side"],
                    "base_quantity": x["quantity"],
                    "stress_quantity": y["quantity"],
                    "base_price": x["price"],
                    "stress_price": y["price"],
                    "base_fees": x["fees"],
                    "stress_fees": y["fees"],
                }
            )
    assert changes
    return {
        "fill_count": len(a),
        "changed_quantity_fills": len(changes),
        "examples": changes[:3],
        "account_rerun_evidence": "Both complete daily accounts independently reconcile all fees and quantities; quantity changes exclude fixed-quantity fee rededuction.",
    }


def main():
    s007folder = "research/S007/assets/runs/EX003_20261010/"
    center_raw = fact(js(s007folder + "center_reference.json"))
    center, cstat, crec = select(center_raw, "baseline")
    stress, sstat, srec = select(center_raw, "stress_20bp_per_side")
    old_center_checks = original_center_check(center_raw)
    assert len(center["account"]) == 1373
    assert (
        center["account"][0]["session"] == "2021-01-05"
        and center["account"][-1]["session"] == "2026-09-02"
    )
    n = js(s007folder + "neighborhood.json")
    plan = js("research/S007/experiments/EX003_20261010/protocols/adapted_plan.json")
    original_plan = js("research/S007/experiments/EX003_20261010/protocols/plan.json")
    assert len(n["rows"]) == len(plan["cases"]) == 8
    for row, case in zip(n["rows"], plan["cases"]):
        assert (
            row["candidate_id"] == case["candidate_id"] and row["parameters"] == case["parameters"]
        )
        original_case = next(
            x for x in original_plan["cases"] if x["candidate_id"] == case["candidate_id"]
        )
        assert (
            original_case["parameters"] == case["parameters"]
            and original_case["coordinates"] == case["coordinates"]
        )
    s007neighbors = neighbors(n["rows"], "evidence")
    legacy_relative = "experiments/S007/20260915_S007_EX32/artifacts/buyhold_account_daily.csv"
    legacy_path = ROOT / legacy_relative
    SOURCES[legacy_relative] = {
        "sha256": hashlib.sha256(legacy_path.read_bytes()).hexdigest(),
        "bytes": legacy_path.stat().st_size,
    }
    legacy = pd.read_csv(legacy_path, float_precision="round_trip")
    assert legacy["date"].tolist() == [x["session"] for x in center["account"]]
    oldrolling = rolling(center, legacy["equity"].to_numpy(float), "s007-legacy")
    newrolling = rolling(center, center["benchmark_equity"], "s007-executable")
    bh = next(
        x["buyhold"]["account_daily"]["data"]
        for x in center_raw["runs"]
        if x["scenario_id"] == "baseline"
    )
    assert [x["equity"] for x in bh] == center["benchmark_equity"]
    assert all(x["quantity"] == 68800 and abs(x["cash"] - 140.24) < 1e-9 for x in bh)
    fractional = legacy["equity"].to_numpy(float) / legacy["close"].to_numpy(float)
    assert np.max(np.abs(fractional - fractional[0])) < 1e-9
    assert abs(fractional[0] - 68896.62062075856) < 1e-9
    rawrows = js("research/S013/assets/runs/EX008_20261010/rows.json")["rows"]
    s013rows = [x for x in rawrows if x["parent"]["key"]["candidate_id"] == "C2132"]
    sn = neighbors([x for x in s013rows if x["kind"] == "PARAMETERS"], "reference")
    auth = js("research/S013/assets/runs/EX008_20261010/center_authentication.json")
    source_ref = next(
        x["formal_account"]
        for x in auth["centers"]
        if x["candidate"]["key"]["candidate_id"] == "C2132"
    )
    s013center_raw = fact(source_ref)
    s013center, s013stat, s013rec = select(s013center_raw, "baseline")
    s013stressrow = next(x for x in s013rows if x["kind"] == "STRESS")
    s013stress_raw = fact(s013stressrow["reference"])
    s013stress, s013stressstat, s013stressrec = select(s013stress_raw, "stress_20bp_per_side")
    assert len(s013center["account"]) == 1636
    s013roll = rolling(s013center, s013center["benchmark_equity"], "c2132")
    a = {
        "center": cstat,
        "stress": sstat,
        "cost_cagr_loss": cstat["net_cagr"] - sstat["net_cagr"],
        "cost_return_retention": sstat["net_cagr"] / cstat["net_cagr"],
        "baseline_account": crec,
        "stress_account": srec,
        "parameter_sensitivity": summarize(cstat, s007neighbors),
        "time_legacy": oldrolling,
        "time_executable": newrolling,
        "benchmark_main_table": "Awaiting user choice; both are preserved, no main value chosen.",
        "original_center_economic_checks": old_center_checks,
        "benchmark_difference": {
            "legacy_fractional_quantity": float(fractional[0]),
            "new_quantity": 68800,
            "new_cash": 140.24,
        },
        "full_rerun_cost_proof": cost_proof(center, stress),
    }
    b = {
        "center": s013stat,
        "stress": s013stressstat,
        "cost_cagr_loss": s013stat["net_cagr"] - s013stressstat["net_cagr"],
        "cost_return_retention": s013stressstat["net_cagr"] / s013stat["net_cagr"],
        "baseline_account": s013rec,
        "stress_account": s013stressrec,
        "parameter_sensitivity": summarize(s013stat, sn),
        "time_executable": s013roll,
        "full_rerun_cost_proof": cost_proof(s013center, s013stress),
    }
    panel = js("research/S013/assets/runs/EX008_20261010/assessment.json")
    row = next(x for x in panel["rows"] if x["candidate"]["candidate_id"] == "S013-C2132")
    diag = {x["metric"].upper(): x["value"] for x in row["diagnostics"]}
    values = {
        "NET_ANNUAL_RETURN": s013stat["net_cagr"],
        "DRAWDOWN_MAGNITUDE": s013stat["drawdown_magnitude"],
        "PARAMETER_RETURN_DEGRADATION": b["parameter_sensitivity"]["cagr_degradation"],
        "PARAMETER_DRAWDOWN_DEGRADATION": b["parameter_sensitivity"]["drawdown_worsening"],
        "STRESS_ANNUAL_LOSS": b["cost_cagr_loss"],
        "PROFIT_CONCENTRATION": s013rec["concentration"],
        "ROLLING_EXCESS_Q10": s013roll["q10_linear"],
    }
    errors = {k: abs(diag[k] - v) for k, v in values.items()}
    assert max(errors.values()) < 1e-12
    results = {
        "status": "PASS",
        "method": "252/n account CAGR; DD includes initial cash; all quantiles LINEAR; published complete account facts only.",
        "s007": a,
        "c2132": b,
        "c2132_seven_formal_metric_errors": errors,
        "sources": SOURCES,
    }
    (OUT / "final-audit.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "s007": {k: v for k, v in a.items() if k not in ["parameter_sensitivity"]},
                "s007_parameter": {
                    k: v for k, v in a["parameter_sensitivity"].items() if k != "rows"
                },
                "c2132": {k: v for k, v in b.items() if k not in ["parameter_sensitivity"]},
                "c2132_parameter": {
                    k: v for k, v in b["parameter_sensitivity"].items() if k != "rows"
                },
                "formal_errors": errors,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
