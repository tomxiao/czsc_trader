"""Actual-path rearm/exit factorial descriptions; no new strategy accounts."""

import importlib.util
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parents[1]
ROOT = next(p for p in HERE.parents if (p / "pyproject.toml").is_file())
spec = importlib.util.spec_from_file_location("account_audit", HERE / "src/account_audit.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
CANDIDATES = ("C6101", "C6102", "C6104", "C6105", "C6117")


def longest(mask, dates):
    ranges = []
    beginning = None
    for i, flag in enumerate(mask):
        if flag and beginning is None:
            beginning = i
        if beginning is not None and (not flag or i == len(mask) - 1):
            end = i if flag else i - 1
            ranges.append(
                {"count": end - beginning + 1, "start": dates[beginning], "end": dates[end]}
            )
            beginning = None
    return (
        max(ranges, key=lambda r: r["count"])
        if ranges
        else {"count": 0, "start": None, "end": None}
    )


def entry_summary(cycles):
    losses = [c for c in cycles if c["first_entry_day_net_yuan"] < 0]
    recoveries = [c for c in losses if c["net_yuan"] > 0]
    return {
        "entry_loss_count": len(losses),
        "entry_loss_yuan": -sum(c["first_entry_day_net_yuan"] for c in losses),
        "entry_loss_later_profitable_count": len(recoveries),
        "later_profitable_cycles_final_net_yuan": sum(c["net_yuan"] for c in recoveries),
        "later_profitable_cycles_entry_net_yuan": sum(
            c["first_entry_day_net_yuan"] for c in recoveries
        ),
        "later_profitable_cycles": recoveries,
    }


def main():
    destination = HERE / "others/mechanism_report.json"
    assert not destination.exists()
    audit = m.read(HERE / "others/audit.json")
    assert audit["status"] == "ARITHMETIC_CHECKS_PASS"
    results = m.read(HERE / "others/results.json")
    data, summary = {}, []
    for cid in CANDIDATES:
        row = next(r for r in results["rows"] if r["candidate_id"] == cid)
        ref = m.EvidenceRef.from_dict(row["evidence"])
        evidence = m.read(ref.resolve(ROOT))
        data[cid] = {r["window_id"]: r for r in evidence["runs"]}
        for window, run in data[cid].items():
            description = next(
                a["accounting_description"]
                for a in audit["accounts"]
                if a["candidate"] == cid and a["window"] == window
            )
            daily = m.frame(run["ledgers"]["account_daily"])
            dates = daily.date.str[:10].tolist()
            equity = np.r_[100000.0, daily.equity.to_numpy(float)]
            benchmark = np.r_[
                100000.0, m.frame(run["buyhold"]["account_daily"]).equity.to_numpy(float)
            ]
            rolling = []
            for start in range(0, len(daily) - 252 + 1, 21):
                end = start + 252
                rolling.append(
                    {
                        "start": dates[start],
                        "end": dates[end - 1],
                        "return": float(equity[end] / equity[start] - 1),
                        "buyhold_return": float(benchmark[end] / benchmark[start] - 1),
                    }
                )
            dd = 1 - equity / np.maximum.accumulate(equity)
            trough = int(np.argmax(dd))
            peak = int(np.argmax(equity[: trough + 1]))
            summary.append(
                {
                    "candidate": cid,
                    "window": window,
                    "parameters": row["parameters"],
                    "evidence": ref.to_dict(),
                    "net_return": description["net_return"],
                    "drawdown": description["drawdown"],
                    "years": description["years"],
                    "frequency": description["frequency"],
                    "exposure": description["exposure"],
                    "fees_yuan": description["fees_yuan"],
                    "cycle_sums": description["cycle_sums"],
                    "cycle_distribution": description["cycle_distribution"],
                    "entry_loss_recoveries": entry_summary(description["cycles"]),
                    "largest_losing_cycles": sorted(
                        description["cycles"], key=lambda x: x["net_yuan"]
                    )[:5],
                    "maximum_drawdown_dates": {
                        "peak": "OPENING_100000" if peak == 0 else dates[peak - 1],
                        "trough": dates[trough - 1],
                    },
                    "rolling252_step21_inherited_account": rolling,
                    "rolling_under_buyhold": {
                        "count": sum(r["return"] < r["buyhold_return"] for r in rolling),
                        "longest_consecutive_windows": longest(
                            [r["return"] < r["buyhold_return"] for r in rolling],
                            [r["end"] for r in rolling],
                        ),
                    },
                    "longest_cumulative_wealth_below_buyhold_sessions": longest(
                        equity[1:] < benchmark[1:] - 1e-7, dates
                    ),
                }
            )
    comparisons = []
    for base, alt in (("C6102", "C6105"), ("C6101", "C6104"), ("C6105", "C6117")):
        for window in m.WINDOWS:
            left, right = [
                next(
                    a["accounting_description"]
                    for a in audit["accounts"]
                    if a["candidate"] == cid and a["window"] == window
                )
                for cid in (base, alt)
            ]
            aa, bb = [{c["entry_day"]: c for c in d["cycles"]} for d in (left, right)]
            common = sorted(set(aa) & set(bb))
            dl, dr = [m.frame(data[cid][window]["ledgers"]["account_daily"]) for cid in (base, alt)]
            dates = dl.date.str[:10].tolist()
            assert dates == dr.date.str[:10].tolist()
            el, er = [np.r_[100000.0, d.equity.to_numpy(float)] for d in (dl, dr)]
            rolling = []
            for start in range(0, len(dl) - 252 + 1, 21):
                end = start + 252
                rolling.append(
                    {
                        "start": dates[start],
                        "end": dates[end - 1],
                        "control_return": float(el[end] / el[start] - 1),
                        "alternative_return": float(er[end] / er[start] - 1),
                    }
                )
            decisions = [m.frame(data[cid][window]["ledgers"]["decisions"]) for cid in (base, alt)]
            feature_columns = ["m", "p", "dcenter", "center_gain", "permission"]
            pd.testing.assert_frame_equal(
                decisions[0][feature_columns],
                decisions[1][feature_columns],
                check_exact=True,
                check_dtype=False,
            )
            comparisons.append(
                {
                    "control": base,
                    "alternative": alt,
                    "window": window,
                    "market_features_and_permission_equal_exactly": True,
                    "net_yuan_difference": right["net_yuan"] - left["net_yuan"],
                    "drawdown_difference": right["drawdown"] - left["drawdown"],
                    "common_actual_entry_count": len(common),
                    "common_entry_same_exit_count": sum(
                        aa[k]["exit_day"] == bb[k]["exit_day"] for k in common
                    ),
                    "control_only_actual_cycles": [aa[k] for k in sorted(set(aa) - set(bb))],
                    "alternative_only_actual_cycles": [bb[k] for k in sorted(set(bb) - set(aa))],
                    "common_actual_cycles": [
                        {"entry_day": k, "control": aa[k], "alternative": bb[k]} for k in common
                    ],
                    "rolling252_step21_inherited_returns": rolling,
                    "rolling_under_control": {
                        "count": sum(
                            r["alternative_return"] < r["control_return"] for r in rolling
                        ),
                        "longest_consecutive_windows": longest(
                            [r["alternative_return"] < r["control_return"] for r in rolling],
                            [r["end"] for r in rolling],
                        ),
                    },
                    "longest_cumulative_wealth_below_control_sessions": longest(
                        er[1:] < el[1:] - 1e-7, dates
                    ),
                }
            )
    result = {
        "status": "PASS",
        "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "new_account_simulations": 0,
        "accounts": summary,
        "factorial_comparisons": comparisons,
        "rolling_definition": "Inherited path: (equity[start+252]/equity[start])-1; start advances 21 sessions from the retained account opening; no account resets or appended off-grid final window.",
        "limitations": [
            "Rearm changes the subsequent entry queue, actual cash and quantities. Net differences are whole actual account contrasts, not subtraction of old cycle PNL.",
            "Control-only positive cycles describe dates absent from the alternative queue; their sum is not profits that would be recovered by modifying that alternative.",
            "Annual and rolling returns inherit past equity. Overlapping rolling windows and 434/415 windows are dependent observations, not independent tests.",
            "Longest relative-wealth-underperformance measures cumulative equity below comparator, distinct from longest negative incremental-return sequence.",
            "Only descriptive accounting is provided; public dynamic-capital causal attribution remains unsupported.",
        ],
    }
    destination.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"status": "PASS", "accounts": len(summary), "factorial_pairs": len(comparisons)}
        )
    )


if __name__ == "__main__":
    main()
