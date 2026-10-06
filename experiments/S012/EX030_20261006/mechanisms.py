"""Fixed GVZ and finite-history USDOLLAR hypotheses, with explicit causal dates."""

import numpy as np
import pandas as pd

# id, fixed primary horizon, parent, role, falsifiable mechanism
HYPOTHESES = (
    ("U01", 10, "C_GOLD", "机会环境", "美元篮子五观察期走弱，黄金上升需求可能延续"),
    ("U02", 5, "C_SAFE", "机会", "美元走弱可能增强已有风险上升且黄金上涨的避险传导"),
    ("U03", 5, "C_SAFE", "竞争反证", "美元走强可能削弱避险传导；与走弱状态直接竞争"),
    ("U04", 5, "C_SAFE", "确认", "美元走弱且股票相对黄金预期波动偏高可能确认避险传导"),
    ("V01", 5, "C_SAFE", "确认", "VIX/GVZ高于自身历史中位数可能增强避险传导"),
    ("V02", 5, "C_SAFE", "竞争反证", "VIX/GVZ较低时黄金风险可能已提前反映，避险增量较弱"),
    ("V03", 10, "C_GOLD", "机会环境", "黄金上升而GVZ五观察期下降可能表明趋势风险缓和"),
    ("V04", 10, "C_GOLD", "竞争反证", "黄金上升且GVZ五观察期上升可能反映趋势末期风险"),
    ("V05", 5, "C_M05", "确认", "相对波动状态可能改善前轮黄金随风险上涨的M05确认线索"),
)


def indexed(frame):
    x = frame.copy()
    x.attrs = {}
    x["Date"] = pd.to_datetime(x["Date"])
    x = x.set_index("Date").sort_index()
    if not x.index.is_unique:
        raise ValueError("duplicate native dates")
    return x


def align(native, index, name, *, decision_end=None):
    x = native.reset_index(names="SourceDate").sort_values("AvailableDate")
    target = pd.DataFrame({"Date": index, "DecisionTime": index + pd.Timedelta(hours=17)})
    out = pd.merge_asof(
        target,
        x,
        left_on="DecisionTime",
        right_on="AvailableDate",
        direction="backward",
        tolerance=pd.Timedelta(days=7),
    ).set_index("Date")
    found = out.AvailableDate.notna()
    assert (out.loc[found, "AvailableDate"] <= out.loc[found, "DecisionTime"]).all()
    assert (out.loc[found, "SourceDate"] < out.index[found]).all()
    if decision_end is not None:
        out.loc[out.index > decision_end, x.columns] = np.nan
    audit = out[["SourceDate", "AvailableDate", "DecisionTime"]].add_prefix(name + "_")
    return out.drop(columns=["SourceDate", "AvailableDate", "DecisionTime"]), audit


def build(d, baseline, gvz, usdollar, vix):
    f = baseline.copy()
    f.attrs = {}
    index = d.index
    audit = []
    g = indexed(gvz)
    u = indexed(usdollar)
    v = indexed(vix)
    gn = pd.DataFrame(
        {
            "gvz5": g.Close.diff(5),
            "gvz_level": g.Close,
            "AvailableDate": pd.to_datetime(g.AvailableDate),
        }
    )
    a, e = align(gn, index, "gvz")
    audit.append(e)
    for c in a:
        f[c] = a[c]
    un = pd.DataFrame(
        {
            "usd5": u.BidClose.pct_change(5, fill_method=None),
            "AvailableDate": pd.to_datetime(u.AvailableDate),
        }
    )
    a, e = align(un, index, "usdollar", decision_end=u.index.max())
    audit.append(e)
    f["usd5"] = a.usd5
    vn = pd.DataFrame(
        {"vix_level": v.Close, "AvailableDate": v.index + pd.Timedelta(days=1, hours=8, minutes=30)}
    )
    a, e = align(vn, index, "vix_level")
    audit.append(e)
    f["vix_level"] = a.vix_level
    # Pair both implied-volatility closes on the same observation date.
    pair = v[["Close"]].join(
        g[["Close", "AvailableDate"]], how="inner", lsuffix="_vix", rsuffix="_gvz"
    )
    ratio = pair.Close_vix / pair.Close_gvz
    available = pd.concat(
        [
            pd.to_datetime(pair.AvailableDate),
            pd.Series(pair.index + pd.Timedelta(days=1, hours=8, minutes=30), index=pair.index),
        ],
        axis=1,
    ).max(axis=1)
    rn = pd.DataFrame(
        {
            "risk_ratio": ratio,
            "ratio_median": ratio.rolling(126, min_periods=63).median().shift(1),
            "AvailableDate": available,
        }
    )
    a, e = align(rn, index, "relative_risk")
    audit.append(e)
    f["risk_ratio"] = a.risk_ratio
    f["ratio_median"] = a.ratio_median
    safe = (f.vix5 > 0) & (f.xau5 > 0)
    m05 = safe & (f.gold_vix_corr60 > 0)
    high = f.risk_ratio > f.ratio_median
    expressions = {
        "C_GOLD": (f.xau20 > 0, ["xau20"]),
        "C_SAFE": (safe, ["vix5", "xau5"]),
        "C_M05": (m05, ["vix5", "xau5", "gold_vix_corr60"]),
        "C_USD": (f.usd5 < 0, ["usd5"]),
        "U01": ((f.usd5 < 0) & (f.xau20 > 0), ["usd5", "xau20"]),
        "U02": ((f.usd5 < 0) & safe, ["usd5", "vix5", "xau5"]),
        "U03": ((f.usd5 >= 0) & safe, ["usd5", "vix5", "xau5"]),
        "U04": ((f.usd5 < 0) & high & safe, ["usd5", "risk_ratio", "ratio_median", "vix5", "xau5"]),
        "V01": (high & safe, ["risk_ratio", "ratio_median", "vix5", "xau5"]),
        "V02": ((~high) & safe, ["risk_ratio", "ratio_median", "vix5", "xau5"]),
        "V03": ((f.gvz5 < 0) & (f.xau20 > 0), ["gvz5", "xau20"]),
        "V04": ((f.gvz5 >= 0) & (f.xau20 > 0), ["gvz5", "xau20"]),
        "V05": (high & m05, ["risk_ratio", "ratio_median", "vix5", "xau5", "gold_vix_corr60"]),
    }
    signals = pd.DataFrame(index=index)
    valids = pd.DataFrame(index=index)
    for key, (condition, required) in expressions.items():
        valid = f[required].notna().all(axis=1)
        valids[key] = valid
        signals[key] = condition & valid
    return f, signals, valids, pd.concat(audit, axis=1)


def synthetic_frames():
    index = pd.bdate_range("2020-06-05", periods=380)
    t = np.arange(len(index))
    close = 5 * np.exp(0.0006 * t + 0.035 * np.sin(t / 12))
    d = pd.DataFrame(
        {
            "Open": close * 0.999,
            "Close": close,
            "High": close * 1.02,
            "Low": close * 0.98,
            "Volume": 10000.0,
            "Amount": close * 10000,
        },
        index=index,
    )
    f = pd.DataFrame(index=index)
    for h in (5, 20):
        f[f"etf{h}"] = d.Close.pct_change(h, fill_method=None)
    f["vol20"] = d.Close.pct_change(fill_method=None).rolling(20).std()
    f["xau5"] = np.sin(t / 11) * 0.02
    f["xau20"] = np.sin(t / 29) * 0.05
    f["fx5"] = np.sin(t / 17) * 0.004
    f["vix5"] = np.sin(t / 9) * 3
    f["gold_vix_corr60"] = np.sin(t / 23)
    gvz = pd.DataFrame(
        {
            "Date": index,
            "Close": 20 + 4 * np.sin(t / 7),
            "InitialReleaseDate": index,
            "AvailableDate": index + pd.Timedelta(days=1, hours=16),
        }
    )
    usd = pd.DataFrame(
        {
            "Date": index,
            "BidClose": 10000 * np.exp(0.005 * np.sin(t / 19)),
            "AvailableDate": index + pd.Timedelta(days=2, hours=8),
        }
    )
    vix = pd.DataFrame({"Date": index, "Close": 22 + 7 * np.sin(t / 9)})
    return d, f, gvz, usd, vix
