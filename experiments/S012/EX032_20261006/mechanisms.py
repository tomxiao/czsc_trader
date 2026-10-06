"""Frozen volatility-source and price-state competition; no threshold search."""

import numpy as np
import pandas as pd

HYPOTHESES = (
    ("D01", 5, "C_SAFE", "机会", "低VIX/GVZ可能表示黄金风险已被定价，避险上涨继续"),
    ("D02", 5, "C_M05", "确认", "低比值可能改善黄金随风险上涨且相关为正的机会"),
    ("D03", 5, "C_SAFE", "来源竞争", "低VIX低GVZ：相对平静环境中的避险需求延续"),
    ("D04", 5, "C_SAFE", "来源竞争", "低VIX高GVZ：黄金自身重定价主导收益"),
    ("D05", 5, "C_SAFE", "来源竞争", "高VIX低GVZ：股票压力尚未传至黄金的补涨"),
    ("D06", 5, "C_SAFE", "来源竞争", "高VIX高GVZ：共同风险重定价延续"),
    ("D07", 10, "C_GOLD", "机会", "黄金中期上涨、GVZ上升且短期继续上涨的需求延续"),
    ("D08", 10, "C_GOLD", "机会", "黄金中期上涨、GVZ上升但短期回调的修复机会"),
    ("D09", 5, "C_CATCHUP", "机会", "国际金价上涨、GVZ上升但本地ETF未涨的补涨机会"),
    ("D10", 5, "C_CATCHUP", "竞争反证", "国际金价上涨、GVZ上升且本地ETF已涨的延续竞争"),
    ("D11", 5, "C_SAFE", "机会", "低比值避险状态下本地ETF三日回调后的补涨"),
    ("D12", 5, "C_SAFE", "竞争反证", "低比值避险状态下本地ETF三日已涨的延续竞争"),
    ("D13", 10, "C_USDTREND", "确认", "有限美元走弱黄金趋势叠加GVZ上升的重定价确认"),
    ("D14", 10, "C_USDTREND", "竞争反证", "有限美元走弱黄金趋势叠加GVZ下降的风险缓和竞争"),
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
    if not native.AvailableDate.is_monotonic_increasing:
        raise ValueError(
            "non-monotonic feature availability requires publication-window reconstruction"
        )
    x = native.reset_index(names="SourceDate").sort_values(
        ["AvailableDate", "SourceDate"], kind="stable"
    )
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
    g, u, v = indexed(gvz), indexed(usdollar), indexed(vix)
    pair = (
        v.Close.rename("pair_vix")
        .to_frame()
        .join(g[["Close", "AvailableDate"]].rename(columns={"Close": "pair_gvz"}), how="inner")
    )
    available = pd.concat(
        [
            pd.to_datetime(pair.AvailableDate),
            pd.Series(pair.index + pd.Timedelta(days=1, hours=8, minutes=30), index=pair.index),
        ],
        axis=1,
    ).max(axis=1)
    ratio = pair.pair_vix / pair.pair_gvz
    native = pd.DataFrame(
        {
            "pair_vix": pair.pair_vix,
            "pair_gvz": pair.pair_gvz,
            "vix_median": pair.pair_vix.rolling(126, min_periods=63).median().shift(1),
            "gvz_median": pair.pair_gvz.rolling(126, min_periods=63).median().shift(1),
            "risk_ratio": ratio,
            "ratio_median": ratio.rolling(126, min_periods=63).median().shift(1),
            "pair_gvz5": pair.pair_gvz.diff(5),
            "vix_log5": np.log(pair.pair_vix / pair.pair_vix.shift(5)),
            "gvz_log5": np.log(pair.pair_gvz / pair.pair_gvz.shift(5)),
            "ratio_log5": np.log(ratio / ratio.shift(5)),
            "AvailableDate": available,
        }
    )
    hit, audit = align(native, d.index, "paired_risk")
    for c in hit:
        f[c] = hit[c]
    usd, ua = align(
        pd.DataFrame(
            {
                "usd5": u.BidClose.pct_change(5, fill_method=None),
                "AvailableDate": pd.to_datetime(u.AvailableDate),
            }
        ),
        d.index,
        "usdollar",
        decision_end=u.index.max(),
    )
    f["usd5"] = usd.usd5
    # Separate VIX level retains the preceding experiment's control timing.
    vx, va = align(
        pd.DataFrame(
            {
                "vix_level": v.Close,
                "AvailableDate": v.index + pd.Timedelta(days=1, hours=8, minutes=30),
            }
        ),
        d.index,
        "vix_level",
    )
    f["vix_level"] = vx.vix_level
    safe = (f.vix5 > 0) & (f.xau5 > 0)
    m05 = safe & (f.gold_vix_corr60 > 0)
    low = f.risk_ratio <= f.ratio_median
    vl = f.pair_vix <= f.vix_median
    gl = f.pair_gvz <= f.gvz_median
    rise = f.pair_gvz5 >= 0
    gold = f.xau20 > 0
    usdtrend = (f.usd5 < 0) & gold
    sr = ["vix5", "xau5"]
    rr = ["risk_ratio", "ratio_median"]
    qr = ["pair_vix", "pair_gvz", "vix_median", "gvz_median"]
    expressions = {
        "C_SAFE": (safe, sr),
        "C_M05": (m05, sr + ["gold_vix_corr60"]),
        "C_GOLD": (gold, ["xau20"]),
        "C_CATCHUP": (f.xau5 > 0, ["xau5"]),
        "C_USDTREND": (usdtrend, ["usd5", "xau20"]),
        "D01": (low & safe, sr + rr),
        "D02": (low & m05, sr + rr + ["gold_vix_corr60"]),
        "D03": (vl & gl & safe, sr + qr),
        "D04": (vl & ~gl & safe, sr + qr),
        "D05": (~vl & gl & safe, sr + qr),
        "D06": (~vl & ~gl & safe, sr + qr),
        "D07": (rise & gold & (f.xau5 > 0), ["pair_gvz5", "xau20", "xau5"]),
        "D08": (rise & gold & (f.xau5 <= 0), ["pair_gvz5", "xau20", "xau5"]),
        "D09": (rise & (f.xau5 > 0) & (f.etf5 <= 0), ["pair_gvz5", "xau5", "etf5"]),
        "D10": (rise & (f.xau5 > 0) & (f.etf5 > 0), ["pair_gvz5", "xau5", "etf5"]),
        "D11": (low & safe & (f.etf3 <= 0), sr + rr + ["etf3"]),
        "D12": (low & safe & (f.etf3 > 0), sr + rr + ["etf3"]),
        "D13": (usdtrend & rise, ["usd5", "xau20", "pair_gvz5"]),
        "D14": (usdtrend & ~rise, ["usd5", "xau20", "pair_gvz5"]),
    }
    signals, valids = pd.DataFrame(index=d.index), pd.DataFrame(index=d.index)
    for key, (condition, required) in expressions.items():
        valids[key] = f[required].notna().all(axis=1)
        signals[key] = condition & valids[key]
    return f, signals, valids, pd.concat([audit, ua, va], axis=1)


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
    for h in (3, 5, 20):
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
    # A delayed batch is released together: the newest observation must win.
    gvz.loc[120:122, "InitialReleaseDate"] = index[122]
    gvz.loc[120:122, "AvailableDate"] = index[122] + pd.Timedelta(days=1, hours=16)
    usd = pd.DataFrame(
        {
            "Date": index,
            "BidClose": 10000 * np.exp(0.005 * np.sin(t / 19)),
            "AvailableDate": index + pd.Timedelta(days=2, hours=8),
        }
    )
    vix = pd.DataFrame({"Date": index, "Close": 22 + 7 * np.sin(t / 9)})
    return d, f, gvz, usd, vix
