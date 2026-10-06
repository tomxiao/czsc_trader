"""Frozen end-of-day 30-minute repair and pullback mechanism competition."""

import numpy as np
import pandas as pd

HYPOTHESES = (
    ("I01", 5, "C_MDOWN", "机会", "上午下跌后午后修复可能积累次日后收益"),
    ("I02", 5, "C_MDOWN", "竞争反证", "上午下跌后午后继续下跌的低价机会竞争"),
    ("I03", 5, "C_MUP", "机会", "上午上涨后午后回调可能提供限价兼容机会"),
    ("I04", 5, "C_MUP", "竞争反证", "上午上涨且午后持续上涨的趋势竞争"),
    ("I05", 5, "C_DOWN", "机会", "全天未涨但尾盘反弹的修复机会"),
    ("I06", 5, "C_DOWN", "竞争反证", "全天未涨且尾盘继续回调的低价机会竞争"),
    ("I07", 5, "C_PULL", "机会", "已知人民币金价上涨、本地三日回调且尾盘回落"),
    ("I08", 5, "C_PULL", "竞争反证", "相同黄金支撑本地回调父环境下尾盘不跌竞争"),
    ("I09", 5, "C_M05", "确认", "M05正向共振环境下尾盘回调是否改善限价收益"),
    ("I10", 5, "C_M05", "竞争反证", "M05环境下尾盘未跌的延续竞争"),
    ("I11", 5, "C_M05", "确认", "M05环境上午后上涨是否确认机会"),
    ("I12", 5, "C_M05", "竞争反证", "M05环境上午后未涨的低价竞争"),
)
TIMES = ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")


def build(d, base, minute):
    f = base.copy()
    f.attrs = {}
    m = minute.copy()
    m.attrs = {}
    m.Date = pd.to_datetime(m.Date)
    m.AvailableDate = pd.to_datetime(m.AvailableDate)
    if m.Date.duplicated().any():
        raise ValueError("duplicate bar timestamp")
    m["day"] = m.Date.dt.normalize()
    m["time"] = m.Date.dt.strftime("%H:%M")
    if not m.time.isin(TIMES).all():
        raise ValueError("unexpected 30-minute grid")
    closes = m.pivot(index="day", columns="time", values="Close").reindex(
        index=d.index, columns=TIMES
    )
    availability = m.groupby("day").AvailableDate.max().reindex(d.index)
    counts = m.groupby("day").size().reindex(d.index)
    structural = (
        (counts == 8)
        & closes.notna().all(axis=1)
        & closes.gt(0).all(axis=1)
        & availability.le(d.index + pd.Timedelta(hours=17))
    )
    f["morning"] = closes["11:30"] / d.Open - 1
    f["afternoon"] = closes["15:00"] / closes["11:30"] - 1
    f["tail"] = closes["15:00"] / closes["14:00"] - 1
    f["own_day"] = d.Close / d.Open - 1
    f.loc[~structural, ["morning", "afternoon", "tail"]] = np.nan
    # The listed structural rules do not remove vendor quality-anomaly days.
    safe = (f.vix5 > 0) & (f.xau5 > 0) & (f.gold_vix_corr60 > 0)
    down = f.own_day <= 0
    pull = (f.known_rmb5 > 0) & (f.etf3 < 0)
    mr = ["morning", "afternoon"]
    sr = ["vix5", "xau5", "gold_vix_corr60"]
    expressions = {
        "C_MDOWN": (f.morning < 0, mr),
        "C_MUP": (f.morning >= 0, mr),
        "C_DOWN": (down, ["own_day", "tail"]),
        "C_PULL": (pull, ["known_rmb5", "etf3", "tail"]),
        "C_M05": (safe, sr),
        "I01": ((f.morning < 0) & (f.afternoon > 0), mr),
        "I02": ((f.morning < 0) & (f.afternoon <= 0), mr),
        "I03": ((f.morning >= 0) & (f.afternoon < 0), mr),
        "I04": ((f.morning >= 0) & (f.afternoon >= 0), mr),
        "I05": (down & (f["tail"] > 0), ["own_day", "tail"]),
        "I06": (down & (f["tail"] <= 0), ["own_day", "tail"]),
        "I07": (pull & (f["tail"] < 0), ["known_rmb5", "etf3", "tail"]),
        "I08": (pull & (f["tail"] >= 0), ["known_rmb5", "etf3", "tail"]),
        "I09": (safe & (f["tail"] < 0), sr + ["tail"]),
        "I10": (safe & (f["tail"] >= 0), sr + ["tail"]),
        "I11": (safe & (f.afternoon > 0), sr + ["afternoon"]),
        "I12": (safe & (f.afternoon <= 0), sr + ["afternoon"]),
    }
    s, v = pd.DataFrame(index=d.index), pd.DataFrame(index=d.index)
    for key, (condition, required) in expressions.items():
        v[key] = f[required].notna().all(axis=1)
        s[key] = condition & v[key]
    audit = pd.DataFrame(
        {
            "bar_count": counts,
            "last_available": availability,
            "decision_time": d.index + pd.Timedelta(hours=17),
            "structural_valid": structural,
        },
        index=d.index,
    )
    return f, s, v, audit


def synthetic_frames():
    dates = pd.bdate_range("2020-06-05", periods=320)
    t = np.arange(len(dates))
    close = 5 * np.exp(0.0004 * t + 0.03 * np.sin(t / 11))
    d = pd.DataFrame(
        {
            "Open": close * 0.999,
            "Close": close,
            "High": close * 1.02,
            "Low": close * 0.98,
            "Volume": 10000.0,
            "Amount": close * 10000,
        },
        index=dates,
    )
    f = pd.DataFrame(index=dates)
    for h in (3, 5, 20):
        f[f"etf{h}"] = d.Close.pct_change(h, fill_method=None)
    f["vol20"] = d.Close.pct_change(fill_method=None).rolling(20).std()
    f["xau5"] = np.sin(t / 13) * 0.02
    f["vix5"] = np.sin(t / 9) * 3
    f["gold_vix_corr60"] = np.sin(t / 23)
    f["known_rmb5"] = np.sin(t / 17) * 0.03
    f["pair_vix"] = 20 + np.sin(t / 9)
    f["pair_gvz"] = 17 + np.sin(t / 11)
    bars = []
    for i, day in enumerate(dates):
        for j, hh in enumerate(TIMES):
            time = day + pd.Timedelta(hours=int(hh[:2]), minutes=int(hh[3:]))
            price = d.Open.iloc[i] * (1 + 0.002 * np.sin(i / 7 + j)) if j < 7 else d.Close.iloc[i]
            bars.append({"Date": time, "AvailableDate": time, "Close": price})
    return d, f, pd.DataFrame(bars)
