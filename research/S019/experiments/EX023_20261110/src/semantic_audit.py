"""Reconstruct fixed-horizon, ATR-trailing and time-allocation decisions independently."""
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from dataflows import BarFrequency, EquityProduct
from strategy_runtime import equity_source_hash

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "research/S019/experiments/EX013_20261110/src"))
from runner import read_account  # noqa: E402
from data_window import load  # noqa: E402


def main(manifest, output):
    frames, _ = load()
    data = {}
    for (instrument, frequency, product), frame in frames.items():
        if product is EquityProduct.BARS:
            frame = frame.copy()
            frame["session"] = frame.Date.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
            data[instrument.symbol, frequency] = frame
    daily = data["MU", BarFrequency.DAILY].set_index("session")
    sector = data["SOXX", BarFrequency.DAILY].set_index("session")
    assert daily.index.equals(sector.index)
    ordinals = {day: i for i, day in enumerate(daily.index)}
    fine = {day: group.reset_index(drop=True) for day, group in data["MU", BarFrequency.M30].groupby("session")}
    true_range = pd.concat([daily.High - daily.Low, (daily.High - daily.Close.shift()).abs(),
                            (daily.Low - daily.Close.shift()).abs()], axis=1).max(axis=1)
    results = []
    for item in json.loads(manifest.read_bytes()):
        definition_path = ROOT / item["definition"]
        definition = json.loads(definition_path.read_bytes())
        assert definition["source_sha256"] == equity_source_hash(definition_path.parent.parent / "src", tuple(definition["source_files"]))
        p = json.loads(definition["parameters_json"])
        assert p["exit_mode"] == "fixed" and not p["require_sector"] and p["down_days"] == 1 and p["confirm"]
        assert p["risk_basis"] == "daily" and p["treatment"] == "tilt"
        assert not set(p) & {"review_after", "risk_days", "relative_days", "entry_slot", "starter_fraction"}
        ref, payload = read_account(ROOT / item["account"])
        run = payload["runs"]["candidate"]
        orders = {row["order_id"]: row["decision_id"] for row in run["orders"]}
        fills = {}
        for fill in run["fills"]:
            fills.setdefault(orders[fill["order_id"]], []).append(fill)
        quantity, entry_day, base, peak, atr, exiting = 0, None, None, None, None, False
        entries = exits = 0
        for decision, point in zip(run["decisions"], run["account_points"], strict=True):
            stamp = pd.Timestamp(decision["execution_start"])
            day = stamp.tz_convert("America/New_York").strftime("%Y-%m-%d")
            grid, i = fine[day], ordinals[day]
            slot = int((stamp - grid.BarStart.iloc[0]).total_seconds() / 1800)
            price = float(daily.Close.iloc[i - 1] if slot == 0 else grid.Close.iloc[slot - 1])
            observed = daily.AvailableDate.iloc[i - 1] if slot == 0 else grid.AvailableDate.iloc[slot - 1]
            assert observed <= pd.Timestamp(decision["decision_at"]) <= stamp
            factor = 1.0 if slot == len(grid) - 1 else p.get("day_fraction", 1.0)
            if quantity:
                age = i - ordinals[entry_day]
                peak = max(peak, price)
                stopped = "trail_atr" in p and price <= peak - p["trail_atr"] * atr
                exiting = bool(exiting or age >= p["hold_days"] or stopped)
                expected = 0.0 if exiting else base * factor
            elif slot == 1:
                prior, anchor = float(daily.Close.iloc[i - 1]), float(daily.Close.iloc[i - 2])
                eligible = prior < anchor and price < anchor and price > grid.Open.iloc[0]
                relative = (prior / daily.Close.iloc[i - 64]) / (sector.Close.iloc[i - 1] / sector.Close.iloc[i - 64])
                base_at_entry = 1.0 if relative > 1 else p["weak_fraction"]
                expected = base_at_entry * factor if eligible else 0.0
            else:
                expected = 0.0
            assert np.isclose(expected, decision["target"], atol=1e-12, rtol=0), (day, slot, expected, decision["target"])
            before = quantity
            for fill in fills.get(decision["decision_id"], []):
                assert pd.Timestamp(fill["interval_start"]) == stamp
                quantity += fill["quantity"] * (1 if fill["side"] == "BUY" else -1)
            assert quantity == point["quantity"]
            if before == 0 and quantity > 0:
                entry_day, base, peak = day, base_at_entry, price
                atr = float(true_range.iloc[i - 14:i].mean())
                exiting = False
                entries += 1
            elif before > 0 and quantity == 0:
                assert expected == 0
                entry_day = base = peak = atr = None
                exiting = False
                exits += 1
        assert exits == run["metrics"]["closed_cycles"]
        values = np.array([100000., *(x["equity"] for x in run["account_daily"])])
        mdd = 1 - values / np.maximum.accumulate(values)
        trough = int(mdd.argmax())
        high = int(values[:trough + 1].argmax())
        results.append({**item, "account_sha256": ref.sha256, "decisions": len(run["decisions"]),
            "entries": entries, "exits": exits, "business_rules": "PASS", "signal_availability": "PASS",
            "holding_and_position_feedback": "PASS", "mdd": float(mdd[trough]),
            "drawdown_peak": run["account_daily"][high - 1]["session"] if high else "INITIAL",
            "drawdown_trough": run["account_daily"][trough - 1]["session"]})
    output.write_bytes((json.dumps({"manifest_sha256": sha256(manifest.read_bytes()).hexdigest(),
        "audit_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(), "results": results}, ensure_ascii=False, indent=2) + "\n").encode())
    print("BUSINESS_AUDIT_PASS", sum(r["decisions"] for r in results), flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
