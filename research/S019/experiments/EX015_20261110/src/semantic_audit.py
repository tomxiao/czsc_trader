"""Independent ledger check for opening-recovery prototypes with fixed holding."""
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from dataflows import BarFrequency, EquityProduct

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "research/S019/experiments/EX006_20261110/src"))
from runner import read_account  # noqa: E402
from data_window import load  # noqa: E402


def main(manifest, output):
    frames, _ = load()
    bars = {}
    for (instrument, frequency, product), frame in frames.items():
        if product is EquityProduct.BARS:
            frame = frame.copy()
            frame["session"] = frame.Date.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
            bars[instrument.symbol, frequency] = frame
    daily = bars["MU", BarFrequency.DAILY].set_index("session")
    sector_daily = bars["SOXX", BarFrequency.DAILY].set_index("session")
    assert daily.index.equals(sector_daily.index)
    fine = {symbol: {day: group.reset_index(drop=True) for day, group in bars[symbol, BarFrequency.M30].groupby("session")}
        for symbol in ("MU", "SOXX")}
    ordinals = {day: i for i, day in enumerate(daily.index)}
    results = []
    for item in json.loads(manifest.read_text(encoding="utf-8")):
        definition = json.loads((ROOT / item["definition"]).read_text(encoding="utf-8"))
        p = json.loads(definition["parameters_json"])
        assert p["exit_mode"] == "fixed" and not p["require_sector"]
        assert "stop_mode" not in p
        ref, payload = read_account(ROOT / item["account"])
        run = payload["runs"]["candidate"]
        orders = {x["order_id"]: x["decision_id"] for x in run["orders"]}
        fills = {}
        for fill in run["fills"]:
            fills.setdefault(orders[fill["order_id"]], []).append(fill)
        quantity, entry_day, allocation, entry_reference = 0, None, None, None
        entries = exits = 0
        for decision, point in zip(run["decisions"], run["account_points"], strict=True):
            stamp = pd.Timestamp(decision["execution_start"])
            day = stamp.tz_convert("America/New_York").strftime("%Y-%m-%d")
            grid = fine["MU"][day]
            slot = int((stamp - grid.iloc[0].BarStart).total_seconds() / 1800)
            i = ordinals[day]
            if quantity:
                age = i - ordinals[entry_day]
                lack_progress = "review_after" in p and slot == 0 and age >= p["review_after"] and daily.Close.iloc[i-1] <= entry_reference
                expected = 0.0 if age >= p["hold_days"] or lack_progress else allocation
            elif slot != 1:
                expected = 0.0
            else:
                history = daily.iloc[:i]
                first = grid.iloc[0]
                assert history.iloc[-1].AvailableDate <= pd.Timestamp(decision["decision_at"])
                assert first.AvailableDate <= pd.Timestamp(decision["decision_at"])
                n = p["down_days"]
                declines = bool(np.all(np.diff(history.Close.iloc[-n-1:].to_numpy()) < 0))
                anchor = float(history.Close.iloc[-n-1])
                recovery = first.Close > first.Open
                stage = p.get("repair_stage", "partial")
                stage_ok = first.Close < anchor if stage == "partial" else first.Close >= anchor if stage == "complete" else True
                eligible = (declines or not p.get("require_down", True)) and stage_ok and (not p["confirm"] or recovery)
                target = 1.0
                if p.get("risk_mode") == "trend":
                    target = p["down_alloc"] if history.Close.iloc[-1] <= history.Close.iloc[-64] else 1.0
                elif p.get("risk_mode") == "vol":
                    sigma = history.Close.pct_change().iloc[-20:].std(ddof=1) * np.sqrt(252)
                    target = min(1.0, p["vol_target"] / sigma)
                if "information" in p:
                    sector = fine["SOXX"][day].iloc[0]
                    assert sector.AvailableDate <= pd.Timestamp(decision["decision_at"])
                    sector_return = sector.Close / sector.Open - 1
                    mu_return = first.Close / first.Open - 1
                    strong = sector_return > 0 if p["information"] == "sector" else mu_return > sector_return
                    if p["treatment"] == "gate":
                        eligible = eligible and strong
                    else:
                        target = 1.0 if strong else .5
                if "risk_basis" in p:
                    relative_growth = (history.Close.iloc[-1] / history.Close.iloc[-64]) / (sector_daily.Close.iloc[i-1] / sector_daily.Close.iloc[i-64])
                    target = 1.0 if relative_growth > 1 else p["weak_fraction"]
                    if p["risk_basis"] == "joint":
                        target *= 1.0 if strong else .5
                expected = float(target) if eligible else 0.0
            assert np.isclose(decision["target"], expected, atol=1e-12, rtol=0), (day, slot, decision["target"], expected)
            before = quantity
            for fill in fills.get(decision["decision_id"], []):
                quantity += fill["quantity"] * (1 if fill["side"] == "BUY" else -1)
                assert pd.Timestamp(fill["interval_start"]) == stamp
            assert quantity == point["quantity"]
            if before == 0 and quantity > 0:
                entry_day, allocation, entry_reference = day, expected, float(grid.iloc[0].Close)
                entries += 1
            elif before > 0 and quantity == 0:
                assert expected == 0
                entry_day = allocation = None
                exits += 1
        assert exits == run["metrics"]["closed_cycles"]
        equity = np.array([100000.0, *(row["equity"] for row in run["account_daily"])])
        drawdowns = 1 - equity / np.maximum.accumulate(equity)
        trough = int(drawdowns.argmax())
        peak = int(equity[:trough + 1].argmax())
        results.append({**item, "account_sha256": ref.sha256, "decisions": len(run["decisions"]),
            "entries": entries, "exits": exits, "business_rules": "PASS", "signal_availability": "PASS",
            "holding_and_position_feedback": "PASS", "max_drawdown": float(drawdowns[trough]),
            "drawdown_peak": run["account_daily"][peak - 1]["session"] if peak else "INITIAL",
            "drawdown_trough": run["account_daily"][trough - 1]["session"]})
    output.write_bytes((json.dumps({"manifest_sha256": sha256(manifest.read_bytes()).hexdigest(),
        "audit_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(), "results": results}, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
