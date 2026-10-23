"""Describe retained EX054 actual cycle paths; no counterfactual reconstruction."""

import importlib.util
import json
from hashlib import sha256
from pathlib import Path

import numpy as np

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
SOURCE = ROOT / "research/S015/experiments/EX052_20261024/src/account_audit.py"
spec = importlib.util.spec_from_file_location("audit", SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
OUT = ROOT / "research/S015/experiments/EX054_20261024/others/exit_loss_diagnostic.json"


def load(ex, candidate):
    results = m.read(m.experiment_path(ex) / "others/results.json")
    row = next(x for x in results["rows"] if x["candidate_id"] == candidate)
    ref = m.EvidenceRef.from_dict(row["evidence"])
    ev = m.read(ref.resolve(ROOT))
    accounts = {}
    for run in ev["runs"]:
        window = run["window_id"]
        desc = m.describe(run, row["runs"][window])
        fills = m.frame(run["ledgers"]["fills"])
        daily = m.frame(run["ledgers"]["account_daily"])
        decisions = m.frame(run["ledgers"]["decisions"])
        for cycle in desc["cycles"]:
            group = fills[fills.cycle_id.eq(cycle["cycle_id"])]
            buys = group[group.side.eq("BUY")]
            sells = group[group.side.eq("SELL")]
            cycle["first_buy_price"] = float(buys.price.iloc[0])
            cycle["total_buy_quantity"] = int(buys.quantity.sum())
            cycle["last_sell_price"] = None if sells.empty else float(sells.price.iloc[-1])
            cost = float((buys.quantity * buys.price + buys.fees).sum())
            cycle["net_return_on_actual_buy_cost"] = cycle["net_yuan"] / cost
            if not sells.empty:
                decision = decisions[decisions.decision_id.eq(sells.decision_id.iloc[-1])].iloc[0]
                cycle["exit_decision"] = {
                    k: str(decision[k])
                    if k in ("signal_date", "valid_session")
                    else float(decision[k])
                    for k in (
                        "signal_date",
                        "valid_session",
                        "target_position",
                        "intent_age",
                        "exit_signal",
                        "m",
                        "p",
                        "center_gain",
                        "dcenter",
                    )
                }
        equity = np.r_[100000.0, daily.equity.to_numpy(float)]
        dd = 1 - equity / np.maximum.accumulate(equity)
        trough = int(np.argmax(dd))
        peak = int(np.argmax(equity[: trough + 1]))
        dates = ["OPENING_100000"] + list(daily.date.map(m.day))
        desc["maximum_drawdown_path"] = {
            "peak_date": dates[peak],
            "trough_date": dates[trough],
            "peak_equity": float(equity[peak]),
            "trough_equity": float(equity[trough]),
            "drawdown": float(dd[trough]),
        }
        accounts[window] = desc
    return {
        "candidate": candidate,
        "experiment": ex,
        "evidence": ref.to_dict(),
        "accounts": accounts,
    }


def main():
    assert not OUT.exists()
    sources = [
        load("EX053_20261024", "C5303"),
        load("EX054_20261024", "C5404"),
        load("EX054_20261024", "C5405"),
    ]
    comparisons = []
    for alt in sources[1:]:
        for window in m.WINDOWS:
            left = sources[0]["accounts"][window]
            right = alt["accounts"][window]
            a = {x["entry_day"]: x for x in left["cycles"]}
            b = {x["entry_day"]: x for x in right["cycles"]}
            assert len(a) == len(left["cycles"]) and len(b) == len(right["cycles"])
            matched = []
            for entry in sorted(set(a) & set(b)):
                x, y = a[entry], b[entry]
                matched.append(
                    {
                        "entry_day": entry,
                        "baseline": x,
                        "alternative": y,
                        "actual_net_difference_yuan": y["net_yuan"] - x["net_yuan"],
                        "actual_trade_return_difference": y["net_return_on_actual_buy_cost"]
                        - x["net_return_on_actual_buy_cost"],
                        "earlier_exit": bool(
                            x["exit_day"] and y["exit_day"] and y["exit_day"] < x["exit_day"]
                        ),
                        "later_exit": bool(
                            x["exit_day"] and y["exit_day"] and y["exit_day"] > x["exit_day"]
                        ),
                    }
                )
            comparisons.append(
                {
                    "baseline": "C5303",
                    "alternative": alt["candidate"],
                    "window": window,
                    "common_entry_dates": len(matched),
                    "earlier_exit_count": sum(x["earlier_exit"] for x in matched),
                    "later_exit_count": sum(x["later_exit"] for x in matched),
                    "matched_entry_actual_paths": matched,
                    "baseline_only_actual_cycles": [a[k] for k in sorted(set(a) - set(b))],
                    "alternative_only_actual_cycles": [b[k] for k in sorted(set(b) - set(a))],
                    "september_2026_actual_cycles": {
                        "baseline": [
                            x for x in left["cycles"] if x["entry_day"].startswith("2026-09")
                        ],
                        "alternative": [
                            x for x in right["cycles"] if x["entry_day"].startswith("2026-09")
                        ],
                    },
                }
            )
    out = {
        "scope": "actual retained account cycle descriptions only",
        "limitations": [
            "Different exits change subsequent entry queues, cash and quantities. Common entry date is a descriptive join, not a same-population causal comparison.",
            "Yuan differences include actual account capital differences. Trade returns use each actual inclusive-fee buy cost, and are not a replay of a shared budget.",
            "Baseline-only cycles do not imply the alternative was in cash throughout that interval.",
            "No losing-cycle deletion, invented exit, counterfactual replay or official attribution claim.",
        ],
        "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "audit_source_sha256": sha256(SOURCE.read_bytes()).hexdigest(),
        "sources": sources,
        "comparisons": comparisons,
    }
    OUT.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    for c in comparisons:
        if c["window"] == "full":
            print(
                c["alternative"],
                "common",
                c["common_entry_dates"],
                "early",
                c["earlier_exit_count"],
                "late",
                c["later_exit_count"],
            )
            print("SEPTEMBER", json.dumps(c["september_2026_actual_cycles"]))
            print(
                "LARGEST_NEGATIVE_DIFFERENCES",
                json.dumps(
                    sorted(
                        c["matched_entry_actual_paths"],
                        key=lambda x: x["actual_net_difference_yuan"],
                    )[:5]
                ),
            )


if __name__ == "__main__":
    main()
