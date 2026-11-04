"""Describe matched-entry exit changes from exact published V4 account evidence.

This is path attribution, not a causal estimate or a synthetic recombined account.
"""
from hashlib import sha256
import json
import math
from pathlib import Path

from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.equity_replay import materialize_equity


ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
PAIRS = (("EX045_20261104", "C7502", "C7703"),
         ("EX046_20261104", "C7612", "C7706"))


def load(experiment, candidate):
    results = ROOT / "research/S018/experiments" / experiment / "others/results.json"
    record = json.loads(results.read_text(encoding="utf-8"))["accounts"][candidate]
    reference = EvidenceRef.from_dict(record["account_ref"])
    path = reference.resolve(ROOT)
    content = path.read_bytes()
    assert sha256(content).hexdigest() == reference.sha256

    def dependency(ref):
        data = (path.parent / (ref["sha256"] + ".json")).read_bytes()
        assert sha256(data).hexdigest() == ref["sha256"]
        return data

    payload = materialize_equity(content, dependency).payload
    run = payload["runs"]["candidate"]
    fills = {}
    for fill in run["fills"]:
        fills.setdefault(fill["cycle_id"], []).append(fill)
    closed = {}
    for trade in run["trades"]:
        if trade["status"] != "CLOSED":
            continue
        cycle = fills[trade["cycle_id"]]
        buys = [row for row in cycle if row["side"] == "BUY"]
        sells = [row for row in cycle if row["side"] == "SELL"]
        assert len(buys) == len(sells) == 1
        buy, sell = buys[0], sells[0]
        key = (buy["interval_start"], buy["executed_at"], buy["price"], buy["time_precision"])
        assert key not in closed
        closed[key] = {**trade, "entry_price": buy["price"], "entry_quantity": buy["quantity"],
            "entry_execution": buy["executed_at"], "entry_precision": buy["time_precision"],
            "exit_interval_start": sell["interval_start"], "exit_execution": sell["executed_at"],
            "exit_price": sell["price"]}
    return record, run, closed


def describe(trades):
    trades = list(trades)
    returns = [row["net_return"] for row in trades]
    return {"closed_trades": len(trades), "positive_trades": sum(value > 0 for value in returns),
        "mean_net_return": sum(returns) / len(returns) if returns else None,
        "sum_log_net_returns": sum(math.log1p(value) for value in returns),
        "actual_dollar_net_pnl": sum(row["net_pnl"] for row in trades)}


def compare(experiment, baseline, changed):
    a_record, a_run, a = load(experiment, baseline)
    b_record, b_run, b = load("EX047_20261104", changed)
    common = sorted(set(a) & set(b))
    rows = []
    for key in common:
        left, right = a[key], b[key]
        rows.append({"entry_date": key[0][:10], "entry_price": left["entry_price"],
            "baseline_exit_date": left["exit_interval_start"][:10],
            "changed_exit_date": right["exit_interval_start"][:10],
            "earlier_exit": right["exit_interval_start"] < left["exit_interval_start"],
            "same_exit": right["exit_interval_start"] == left["exit_interval_start"],
            "baseline_net_return": left["net_return"], "changed_net_return": right["net_return"],
            "net_return_difference": right["net_return"] - left["net_return"],
            "log_return_difference": math.log1p(right["net_return"]) - math.log1p(left["net_return"]),
            "baseline_actual_pnl": left["net_pnl"], "changed_actual_pnl": right["net_pnl"],
            "actual_pnl_difference": right["net_pnl"] - left["net_pnl"],
            "baseline_cost_scaled_return_difference": left["cost"] * (right["net_return"] - left["net_return"]),
            "baseline_entry_quantity": left["entry_quantity"], "changed_entry_quantity": right["entry_quantity"]})

    def summary(items):
        return {"count": len(items),
            "mean_return_difference": sum(row["net_return_difference"] for row in items) / len(items) if items else None,
            "sum_log_return_difference": sum(row["log_return_difference"] for row in items),
            "actual_pnl_difference": sum(row["actual_pnl_difference"] for row in items),
            "baseline_cost_scaled_return_difference": sum(row["baseline_cost_scaled_return_difference"] for row in items),
            "baseline_positive": sum(row["baseline_net_return"] > 0 for row in items),
            "changed_positive": sum(row["changed_net_return"] > 0 for row in items),
            "improved_return": sum(row["net_return_difference"] > 1e-10 for row in items),
            "worse_return": sum(row["net_return_difference"] < -1e-10 for row in items)}

    early = [row for row in rows if row["earlier_exit"]]
    profitable = [row for row in early if row["baseline_net_return"] > 0]
    unmatched_a = [a[key] for key in sorted(set(a) - set(b))]
    unmatched_b = [b[key] for key in sorted(set(b) - set(a))]
    unmatched_difference = describe(unmatched_b)["sum_log_net_returns"] - describe(unmatched_a)["sum_log_net_returns"]
    total_difference = describe(b.values())["sum_log_net_returns"] - describe(a.values())["sum_log_net_returns"]
    assert math.isclose(total_difference, summary(rows)["sum_log_return_difference"] + unmatched_difference, abs_tol=1e-12)
    return {"baseline": baseline, "changed": changed,
        "baseline_ref": a_record["account_ref"], "changed_ref": b_record["account_ref"],
        "baseline_metrics": a_record["candidate"], "changed_metrics": b_record["candidate"],
        "all_baseline_closed": describe(a.values()), "all_changed_closed": describe(b.values()),
        "baseline_open_trades": sum(t["status"] != "CLOSED" for t in a_run["trades"]),
        "changed_open_trades": sum(t["status"] != "CLOSED" for t in b_run["trades"]),
        "matched": summary(rows), "earlier_exits": summary(early),
        "earlier_exits_with_later_profitable_baseline": {**summary(profitable),
            "changed_nonpositive": sum(row["changed_net_return"] <= 0 for row in profitable)},
        "same_exit_count": sum(row["same_exit"] for row in rows),
        "later_exit_count": sum(not row["earlier_exit"] and not row["same_exit"] for row in rows),
        "unmatched_baseline": {**describe(unmatched_a), "entries": [row["entry_at"][:10] for row in unmatched_a]},
        "unmatched_changed": {**describe(unmatched_b), "entries": [row["entry_at"][:10] for row in unmatched_b]},
        "closed_log_return_difference": total_difference,
        "unmatched_log_return_difference": unmatched_difference,
        "largest_matched_return_losses": sorted(rows, key=lambda row: row["net_return_difference"])[:5],
        "largest_matched_return_improvements": sorted(rows, key=lambda row: row["net_return_difference"], reverse=True)[:5]}


def main():
    output = {"purpose": "Describe early-exit trade path differences; no new accounts or experiments.",
        "matching": "Same buy interval, modeled execution timestamp, price and precision; quantity may differ.",
        "limits": ["Posthoc development-pool diagnosis, not a causal estimate.",
            "Different exits change capital and later entry opportunities; actual dollar pnl mixes exit and position-size effects.",
            "Cost-scaled differences use each baseline trade cost only as a descriptive normalization, not an executable counterfactual account.",
            "Sums of closed-trade log returns are arithmetic attribution, not exact full-account returns; cash, integer shares and open positions remain in original accounts."],
        "pairs": [compare(*pair) for pair in PAIRS]}
    target = WORK / "others/analysis_exit_comparison.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for pair in output["pairs"]:
        print(json.dumps({key: value for key, value in pair.items() if key not in
            ("largest_matched_return_losses", "largest_matched_return_improvements",
             "baseline_ref", "changed_ref", "baseline_metrics", "changed_metrics")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
