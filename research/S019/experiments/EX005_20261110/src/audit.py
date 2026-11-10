"""Check actual initial entries and liquidation clocks against event diagnostics."""
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.equity_replay import materialize_equity
from dataflows import BarFrequency, EquityProduct

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORK.parent / "EX003_20261110/src"))
from data_window import load  # noqa: E402


def read_account(reference_file):
    ref = EvidenceRef.from_dict(json.loads(reference_file.read_text(encoding="utf-8")))
    path = ref.resolve(ROOT)
    assert sha256(path.read_bytes()).hexdigest() == ref.sha256

    def resolve(item):
        data = path.with_name(item["sha256"] + ".json").read_bytes()
        assert sha256(data).hexdigest() == item["sha256"]
        return data

    return ref, materialize_equity(path.read_bytes(), resolve).payload


def window_metrics(daily, start):
    base = 100000.0 if start == 0 else daily[start - 1]["equity"]
    path = np.array([base, *(row["equity"] for row in daily[start:start + 252])])
    nar = float(path[-1] / base - 1)
    dd = float(np.max(1 - path / np.maximum.accumulate(path)))
    return {"nar": nar, "drawdown": dd, "calmar": nar / dd if dd > 1e-12 else None}


def main():
    events = pd.read_csv(WORK.parent / "EX004_20261110/others/events.csv")
    events = events.loc[events.clock.eq("wait30")].set_index("session")
    frames, _ = load()
    fine = next(value.copy() for (instrument, frequency, product), value in frames.items()
        if instrument.symbol == "MU" and frequency is BarFrequency.M30 and product is EquityProduct.BARS)
    fine["session"] = fine.Date.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    day_bars = {day: group for day, group in fine.groupby("session")}
    sessions = list(events.index)
    report = {}
    _, reference = read_account(WORK.parent / "EX003_20261110/others/reference_account.json")
    rolling = {}
    for mode in ("all", "common", "trend_filter", "adaptive_exit"):
        ref, payload = read_account(WORK / f"others/{mode}_account.json")
        run = payload["runs"]["candidate"]
        expected = events if mode == "all" else events.loc[events.common.le(0)]
        if mode == "trend_filter":
            expected = expected.loc[expected.trend63.gt(0)]
        decisions = {row["decision_id"]: row for row in run["decisions"]}
        orders = {row["order_id"]: row for row in run["orders"]}
        cycles = {}
        for fill in run["fills"]:
            cycles.setdefault(fill["cycle_id"], []).append(fill)
        days, closed, early = [], 0, 0
        examples = []
        for fills in cycles.values():
            entry = fills[0]
            when = pd.Timestamp(entry["interval_start"]).tz_convert("America/New_York")
            day = when.strftime("%Y-%m-%d")
            days.append(day)
            observation = events.loc[day]
            assert entry["side"] == "BUY" and day in expected.index
            assert when == pd.Timestamp(observation.interval_start)
            assert np.isclose(entry["price"], observation.entry, atol=1e-10, rtol=0)
            first_decision = decisions[orders[entry["order_id"]]["decision_id"]]
            facts = {item["key"]: item["text"] for item in first_decision["explanation"]["basis"]}
            assert np.isclose(float(facts["common"]), observation.common, atol=1e-12, rtol=0)
            assert np.isclose(float(facts["trend63"]), observation.trend63, atol=1e-12, rtol=0)
            assert first_decision["target"] == 1.0
            exits = [fill for fill in fills if fill["side"] == "SELL"
                     and decisions[orders[fill["order_id"]]["decision_id"]]["target"] == 0]
            same_day = mode == "adaptive_exit" and observation.trend63 <= 0
            if same_day:
                expected_exit = day_bars[day].iloc[-1].BarStart
                early += 1
            elif day != sessions[-1]:
                expected_exit = day_bars[sessions[sessions.index(day) + 1]].iloc[0].BarStart
            else:
                expected_exit = None
            if expected_exit is None:
                assert not exits
            else:
                assert len(exits) == 1 and pd.Timestamp(exits[0]["interval_start"]) == expected_exit
                closed += 1
            if len(examples) < 2 or (same_day and not any(x["same_day_exit"] for x in examples)):
                examples.append({"day": day, "same_day_exit": bool(same_day), "entry_decision": first_decision,
                    "exit_fill": exits[0] if exits else None})
        assert sorted(days) == sorted(expected.index)
        assert closed == run["metrics"]["closed_cycles"]
        assert all(pd.Timestamp(row["observed_through"]) <= pd.Timestamp(row["decision_at"]) <= pd.Timestamp(row["execution_start"]) for row in run["decisions"])
        report[mode] = {"account_sha256": ref.sha256, "cycles": len(cycles), "closed_cycles": closed,
            "same_day_exits": early, "entry_signal_price_clock": "PASS", "liquidation_clock": "PASS",
            "chronology": "PASS", "bar_max_drawdown": run["metrics"]["bar_max_drawdown"], "examples": examples}
        metrics = run["metrics"]
        counts = metrics["rolling_60_closed_cycle_counts"]
        dd, nar = metrics["daily_max_drawdown"], metrics["annualized_return"]
        report[mode]["target_checks"] = {"nar_ge_55pct": nar >= .55,
            "calmar_ge_5": nar / dd >= 5 if dd > 1e-12 else None,
            "drawdown_le_25pct": dd <= .25,
            "drawdown_le_80pct_buyhold": dd <= .8 * payload["runs"]["buy_hold"]["metrics"]["daily_max_drawdown"],
            "rolling60_median_ge_6": metrics["rolling_60_closed_cycle_median"] >= 6,
            "rolling60_coverage_ge_90pct": sum(value >= 3 for value in counts) / len(counts) >= .9}
        report[mode]["paid_fees"] = float(sum(fill["fees"] for fill in run["fills"]))
        windows, streaks, longest = [], {}, {}
        accounts = {"candidate": run, "buy_hold": payload["runs"]["buy_hold"], "S018_v1": reference["runs"]["candidate"]}
        for start in range(0, len(sessions) - 251, 21):
            values = {name: window_metrics(account["account_daily"], start) for name, account in accounts.items()}
            differences = {}
            for baseline in ("buy_hold", "S018_v1"):
                for metric in ("nar", "calmar"):
                    key = baseline + "_" + metric
                    a, b = values["candidate"][metric], values[baseline][metric]
                    delta = a - b if a is not None and b is not None else None
                    differences[key] = delta
                    streaks[key] = streaks.get(key, 0) + 1 if delta is not None and delta < 0 else 0
                    longest[key] = max(longest.get(key, 0), streaks[key])
            windows.append({"start": sessions[start], "end": sessions[start + 251], "metrics": values,
                "differences": differences, "consecutive_underperforming_windows": dict(streaks)})
        assert len(windows) == 46
        rolling[mode] = {"windows": windows, "longest_underperforming_sequences": longest,
            "basis": "252 sessions, 21-session step; inherited account paths and pre-window equity; overlapping seen-history diagnostics."}
    (WORK / "others/audit.json").write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
    (WORK / "others/rolling252.json").write_bytes((json.dumps(rolling, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps({name: {key: value for key, value in row.items() if key != "examples"} for name, row in report.items()}))


if __name__ == "__main__":
    main()
