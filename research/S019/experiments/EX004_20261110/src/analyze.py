"""Predeclared event diagnostics on the approved unified historical window."""
from hashlib import sha256
import inspect
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from dataflows import BarFrequency, EquityProduct

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
EXPERIMENTS = WORK.parent
sys.path.insert(0, str(EXPERIMENTS / "EX003_20261110/src"))
from data_window import FIRST, load  # noqa: E402
sys.path.insert(0, str(EXPERIMENTS / "EX002_20261110/src"))
from analyze import buy, describe, resolve_fill  # noqa: E402


def main():
    frames, _ = load()
    bars = {}
    for (instrument, frequency, product), frame in frames.items():
        if product is EquityProduct.BARS:
            frame = frame.copy()
            frame["session"] = frame.Date.dt.tz_convert(instrument.timezone).dt.date
            bars[instrument.symbol, frequency] = frame
    daily = bars["MU", BarFrequency.DAILY].set_index("session")
    sector = bars["SOXX", BarFrequency.DAILY].set_index("session")
    fine = {day: group.reset_index(drop=True) for day, group in bars["MU", BarFrequency.M30].groupby("session")}
    mu_return, sector_return = daily.Close.pct_change(), sector.Close.pct_change()
    beta = mu_return.rolling(63).cov(sector_return).shift(1) / sector_return.rolling(63).var().shift(1)
    common = beta * sector_return
    trend = daily.Close.pct_change(63)
    rows = []
    for index, day in enumerate(daily.index):
        if day < FIRST:
            continue
        previous, current = daily.iloc[index - 1], daily.iloc[index]
        signal_day = daily.index[index - 1]
        intraday = fine[day]
        assert len(intraday) >= 3
        assert previous.AvailableDate <= intraday.iloc[0].BarStart
        assert sector.loc[signal_day].AvailableDate <= intraday.iloc[0].BarStart
        assert pd.notna(common.loc[signal_day]) and pd.notna(trend.loc[signal_day])
        for clock, before, quote in (("wait30", intraday.iloc[0], intraday.iloc[1]),
                                    ("last30", intraday.iloc[-2], intraday.iloc[-1])):
            assert before.AvailableDate <= quote.BarStart
            fill = buy(quote, before.Close)
            row = {"session": str(day), "year": day.year, "clock": clock,
                "signal_session": str(signal_day), "signal_available": str(before.AvailableDate),
                "interval_start": str(quote.BarStart), "interval_end": str(quote.Date),
                "filled": fill.filled, "entry": fill.price, "fill_trigger": fill.trigger,
                "common": float(common.loc[signal_day]), "trend63": float(trend.loc[signal_day]),
                "common_group": "nonpositive" if common.loc[signal_day] <= 0 else "positive",
                "trend_group": "nonpositive" if trend.loc[signal_day] <= 0 else "positive",
                "net_same": None, "net_next": None, "log_intraday": None,
                "log_overnight": None, "log_total": None, "next_exit": None}
            if fill.filled:
                if clock == "wait30":
                    assert quote.Date <= intraday.iloc[-1].BarStart
                    row["net_same"] = float(intraday.iloc[-1].Open * .999 / (fill.price * 1.001) - 1)
                if index + 1 < len(daily):
                    next_day = daily.iloc[index + 1]
                    row.update(net_next=float(next_day.Open * .999 / (fill.price * 1.001) - 1),
                        next_exit=str(daily.index[index + 1]),
                        log_intraday=float(np.log(current.Close / fill.price)),
                        log_overnight=float(np.log(next_day.Open / current.Close)),
                        log_total=float(np.log(next_day.Open / fill.price)))
            rows.append(row)
    events = pd.DataFrame(rows)
    valid = events.dropna(subset=["net_next"])
    assert len(events) == 2424
    assert np.allclose(valid.log_intraday + valid.log_overnight, valid.log_total, atol=1e-12, rtol=0)
    assert np.allclose(np.expm1(valid.log_total + np.log(.999 / 1.001)), valid.net_next, atol=1e-12, rtol=0)
    groups = []
    for clock, subset in events.groupby("clock"):
        for period, period_rows in [("ALL", subset), *list(subset.groupby("year"))]:
            selections = [("ALL", "ALL", period_rows)]
            for axis in ("common_group", "trend_group", ["common_group", "trend_group"]):
                for label, selected in period_rows.groupby(axis):
                    selections.append((axis, label, selected))
            for axis, label, selected in selections:
                groups.append({"clock": clock, "period": str(period), "axis": axis, "label": label,
                    "opportunities": len(selected), "filled": int(selected.filled.sum()),
                    "zero_common": int(selected.common.eq(0).sum()),
                    "metrics": {metric: describe(selected[metric]) for metric in
                        ("net_same", "net_next", "log_intraday", "log_overnight", "log_total")}})
    paired = []
    for label, subset in [("ALL", events), *list(events.groupby("common_group"))]:
        pivot = subset.pivot(index="session", columns="clock", values="net_next")
        delta = pivot.last30 - pivot.wait30
        paired.append({"common_group": label, "last_minus_wait": describe(delta),
            "annual": {str(year): describe(values) for year, values in delta.groupby(delta.index.str[:4])}})
    sources = [Path(__file__), WORK / "protocols/diagnostics.md",
        EXPERIMENTS / "EX003_20261110/others/preparation.json",
        EXPERIMENTS / "EX003_20261110/src/data_window.py",
        EXPERIMENTS / "EX002_20261110/src/analyze.py", Path(inspect.getsourcefile(resolve_fill))]
    result = {"source_identity": {path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()).hexdigest() for path in sources},
        "groups": groups, "paired": paired, "checks": {"event_rows": len(events), "sessions": 1212,
            "chronology": "PASS", "return_identity": "PASS", "account_replays": 0}}
    (WORK / "others/results.json").write_bytes((json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())
    events.to_csv(WORK / "others/events.csv", index=False)
    print(json.dumps({"checks": result["checks"], "paired": paired}, ensure_ascii=False))


if __name__ == "__main__":
    main()
