"""First-round opportunity diagnostics; no account simulation or selection."""
from decimal import Decimal, ROUND_FLOOR
from hashlib import sha256
import json
import inspect
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from execution_channels.historical.fills import DailyQuote, OrderSpec, resolve_fill

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SHARED = ROOT / "research/S019/experiments/EX001_20261110/src"
sys.path.insert(0, str(SHARED))
from load_data import load  # noqa: E402 -- shared experiment module path declared above


def limit(reference):
    ticks = (Decimal(str(reference)) * Decimal("1.01") / Decimal("0.01")).to_integral_value(rounding=ROUND_FLOOR)
    return float(ticks * Decimal("0.01"))


def buy(row, reference):
    return resolve_fill(OrderSpec("BUY", "LIMIT", 1.0, limit(reference)),
        session_open=float(row.Open), session_time=row.BarStart.to_pydatetime(),
        intraday_touches=(), inclusive_touch=False,
        daily_quote=DailyQuote(float(row.Low), float(row.High)))


def describe(values):
    values = values.dropna()
    if values.empty:
        return {"n": 0}
    return {"n": len(values), "mean": float(values.mean()), "median": float(values.median()),
        "q05": float(values.quantile(0.05)), "win_rate": float((values > 0).mean())}


def main():
    frames = load()
    daily = frames["daily", "MU"].set_index("session")
    sector = frames["daily", "SOXX"].set_index("session")
    fine = {day: group.reset_index(drop=True) for day, group in frames["m30", "MU"].groupby("session")}
    mu_returns, sector_returns = daily.Close.pct_change(), sector.Close.pct_change()
    beta = mu_returns.rolling(63).cov(sector_returns).shift(1) / sector_returns.rolling(63).var().shift(1)
    common = beta * sector_returns
    residual = mu_returns - common
    rows, components = [], []
    for index, day in enumerate(daily.index):
        if day.isoformat() < "2023-01-03":
            continue
        previous = daily.iloc[index - 1]
        current = daily.iloc[index]
        first, second = fine[day].iloc[0], fine[day].iloc[1]
        assert previous.AvailableDate <= first.BarStart and first.AvailableDate <= second.BarStart
        signal_day = daily.index[index - 1]
        assert pd.notna(common.loc[signal_day]) and pd.notna(residual.loc[signal_day])
        components.append({"session": str(day), "year": day.year,
            "overnight": float(np.log(current.Open / previous.Close)),
            "first30": float(np.log(first.Close / current.Open)),
            "remaining": float(np.log(current.Close / first.Close)),
            "total": float(np.log(current.Close / previous.Close))})
        for clock, quote, reference in (("daily", current, previous.Close), ("open30", first, previous.Close), ("wait30", second, first.Close)):
            fill = buy(quote, reference)
            row = {"session": str(day), "signal_session": str(signal_day), "year": day.year,
                "clock": clock, "filled": fill.filled, "entry": fill.price,
                "fill_trigger": fill.trigger, "signal_available": str(previous.AvailableDate),
                "execution_interval_start": str(quote.BarStart), "execution_interval_end": str(quote.Date),
                "common": float(common.loc[signal_day]), "residual": float(residual.loc[signal_day]),
                "common_sign": "+" if common.loc[signal_day] > 0 else "-",
                "residual_sign": "+" if residual.loc[signal_day] > 0 else "-",
                "first30_return": float(first.Close / current.Open - 1),
                "first30_sign": "+" if first.Close > current.Open else "-" if first.Close < current.Open else "0"}
            if clock == "wait30":
                row["signal_available"] = str(first.AvailableDate)
            for horizon in (1, 5, 20):
                available = index + horizon < len(daily)
                row[f"net_{horizon}"] = float(daily.iloc[index + horizon].Open * 0.999 / (fill.price * 1.001) - 1) if fill.filled and available else None
                row[f"exit_{horizon}"] = str(daily.index[index + horizon]) if available else None
            rows.append(row)
    events = pd.DataFrame(rows)
    parts = pd.DataFrame(components)
    assert len(parts) == 961 and len(events) == 2883
    assert np.allclose(parts.overnight + parts.first30 + parts.remaining, parts.total, atol=1e-12, rtol=0)
    decomposition = []
    for name, subset in [("ALL", parts), *list(parts.groupby("year"))]:
        sums = subset[["overnight", "first30", "remaining", "total"]].sum()
        decomposition.append({"period": str(name), "n": len(subset), "log_return": sums.to_dict(),
            "growth_factor": np.exp(sums).to_dict()})
    summary = []
    for clock, group in events.groupby("clock"):
        for horizon in (1, 5, 20):
            summary.append({"clock": clock, "horizon": horizon, "opportunities": len(group),
                "filled": int(group.filled.sum()), "fill_rate": float(group.filled.mean()),
                **describe(group[f"net_{horizon}"])})
    groups = []
    for clock, subset in events.groupby("clock"):
        axes = ["common_sign", "residual_sign", ["common_sign", "residual_sign"]]
        if clock == "wait30":
            axes.append("first30_sign")
        for axis in axes:
            for label, selected in subset.groupby(axis):
                for horizon in (1, 5, 20):
                    metric = f"net_{horizon}"
                    groups.append({"clock": clock, "axis": axis, "label": label, "horizon": horizon,
                        "opportunities": len(selected), "filled": int(selected.filled.sum()),
                        **describe(selected[metric]),
                        "annual_means": {str(year): describe(year_rows[metric]) for year, year_rows in selected.groupby("year")}})
    paired = []
    for horizon in (1, 5, 20):
        pivot = events.pivot(index="session", columns="clock", values=f"net_{horizon}")
        paired.append({"horizon": horizon, "wait_minus_open30": describe(pivot.wait30 - pivot.open30),
            "wait_minus_daily": describe(pivot.wait30 - pivot.daily),
            "annual_wait_minus_open30": (pivot.wait30 - pivot.open30).groupby(pivot.index.str[:4]).mean().to_dict()})
    identity = {}
    for path in (SHARED / "load_data.py", SHARED / "prepare_data.py", Path(__file__), WORK / "protocols/first_round.md",
            SHARED.parent / "others/daily_preparation.json", SHARED.parent / "others/m30_preparation.json",
            Path(inspect.getsourcefile(resolve_fill))):
        identity[path.relative_to(ROOT).as_posix()] = sha256(path.read_bytes()).hexdigest()
    output = {"source_identity": identity, "decomposition": decomposition, "entry_summary": summary,
        "groups": groups, "paired": paired, "checks": {"events": len(events), "decomposition_days": len(parts),
        "chronological_information": "PASS", "log_return_identity": "PASS", "account_replays": 0}}
    (WORK / "others/results.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    events.to_csv(WORK / "others/events.csv", index=False)
    parts.to_csv(WORK / "others/return_components.csv", index=False)
    print(json.dumps({"decomposition": decomposition, "entry_summary": summary, "paired": paired}, ensure_ascii=False))


if __name__ == "__main__":
    main()
