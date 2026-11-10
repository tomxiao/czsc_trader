"""Review all actual C0067 entries using only contemporaneously available inputs."""
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from dataflows import BarFrequency, EquityProduct

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research/S019/experiments/EX013_20261110/src"))
from runner import read_account, save  # noqa: E402
from data_window import load  # noqa: E402


def main():
    frames, _ = load()
    selected = {}
    for (instrument, frequency, product), frame in frames.items():
        if instrument.symbol == "MU" and product is EquityProduct.BARS:
            frame = frame.copy()
            frame["session"] = frame.Date.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
            selected[frequency] = frame
    daily = selected[BarFrequency.DAILY].set_index("session")
    first = selected[BarFrequency.M30].groupby("session", sort=True).first()
    volume_base = first.Volume.shift(1).rolling(20).median()
    atr = pd.concat([daily.High - daily.Low, (daily.High - daily.Close.shift()).abs(),
                    (daily.Low - daily.Close.shift()).abs()], axis=1).max(axis=1).rolling(14).mean()
    ref, payload = read_account(ROOT / "research/S019/experiments/EX024_20261110/others/trail2p5_account.json")
    run = payload["runs"]["candidate"]
    outcomes = {t["cycle_id"]: t for t in run["trades"] if t["status"] == "CLOSED"}
    entries, previous_cycle = [], None
    for decision, point in zip(run["decisions"], run["account_points"], strict=True):
        cycle = point["cycle_id"]
        if cycle is not None and cycle != previous_cycle:
            day = point["session"]
            i = daily.index.get_loc(day)
            bar, prior = first.loc[day], daily.iloc[i - 1]
            assert bar.AvailableDate <= pd.Timestamp(decision["decision_at"])
            assert prior.AvailableDate <= pd.Timestamp(decision["decision_at"])
            assert bar.High > bar.Low and volume_base.loc[day] > 0
            trade = outcomes.get(cycle)
            entries.append({"session": day, "cycle_id": cycle, "closed": trade is not None,
                "net_return": None if trade is None else trade["net_return"],
                "gap": float(bar.Open / prior.Close - 1), "day_return": float(bar.Close / prior.Close - 1),
                "close_location": float((bar.Close - bar.Low) / (bar.High - bar.Low)),
                "volume_ratio": float(bar.Volume / volume_base.loc[day]),
                "decline_atr": float((daily.Close.iloc[i - 2] - prior.Close) / atr.iloc[i - 1]),
                "return5": float(prior.Close / daily.Close.iloc[i - 6] - 1)})
        previous_cycle = cycle
    assert len(entries) == run["metrics"]["closed_cycles"] + 1
    table = pd.DataFrame([x for x in entries if x["closed"]])
    table["year"] = table.session.str[:4]
    masks = {"gap_negative": table.gap < 0, "prior_close_recovered": table.day_return >= 0,
             "upper_quarter_close": table.close_location >= .75, "volume_above_typical": table.volume_ratio >= 1,
             "decline_one_atr": table.decline_atr >= 1, "five_day_positive": table.return5 > 0}
    groups = {}
    for feature, mask in masks.items():
        groups[feature] = {}
        for label, part in (("true", table[mask]), ("false", table[~mask])):
            groups[feature][label] = {"n": len(part), "mean": float(part.net_return.mean()),
                "median": float(part.net_return.median()), "win_rate": float((part.net_return > 0).mean()),
                "loss5_rate": float((part.net_return <= -.05).mean()),
                "yearly": {y: {"n": len(g), "mean": float(g.net_return.mean())} for y, g in part.groupby("year")}}
    equity = np.array([100000., *(x["equity"] for x in run["account_daily"])])
    dd = 1 - equity / np.maximum.accumulate(equity)
    trough = int(dd.argmax())
    peak = int(equity[:trough + 1].argmax())
    result = {"account": ref.to_dict(), "entries": entries, "groups": groups, "closed_label_count": len(table),
        "unclosed_count": sum(not x["closed"] for x in entries), "candidate_accounts": 0, "benchmark_accounts": 0,
        "mdd": float(dd[trough]), "peak": run["account_daily"][peak - 1]["session"],
        "trough": run["account_daily"][trough - 1]["session"], "availability_check": "PASS"}
    save(WORK / "others/diagnosis.json", result)
    print(json.dumps(groups), flush=True)


if __name__ == "__main__":
    main()
