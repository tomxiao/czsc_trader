"""Frozen volatility-source and price-state competition; no threshold search."""

import numpy as np
import pandas as pd

HYPOTHESES = (
    ("A01", 5, "C_ALL", "机会", "国际黄金与人民币汇率双向上涨的共同推动"),
    ("A02", 5, "C_ALL", "竞争反证", "黄金上涨但人民币汇率下降的单黄金推动"),
    ("A03", 5, "C_ALL", "竞争反证", "黄金未涨但人民币汇率上涨的单汇率推动"),
    ("A04", 5, "C_ALL", "竞争反证", "黄金与人民币汇率均未涨的相反状态"),
    ("A05", 5, "C_FXUP", "确认", "汇率上涨时人民币黄金上涨是否提供必要增量"),
    ("A06", 5, "C_FXUP", "竞争反证", "汇率上涨但人民币黄金未涨的机会竞争"),
    ("A07", 5, "C_DUAL", "确认", "双推动时本地同期落后是否提高收益贡献"),
    ("A08", 5, "C_DUAL", "竞争反证", "双推动时本地未落后的延续竞争"),
    ("A09", 5, "C_DUAL", "确认", "双推动后本地当日阳线是否提高成交贡献"),
    ("A10", 5, "C_DUAL", "竞争反证", "双推动后本地非阳线的低价机会竞争"),
    ("A11", 5, "C_P01", "确认", "低VIX高GVZ避险机会叠加汇率上涨"),
    ("A12", 5, "C_P01", "竞争反证", "低VIX高GVZ避险机会叠加汇率未涨"),
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


def build(d, baseline, gvz, usdollar, vix, xau, fx):
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
    x, c = indexed(xau), indexed(fx)
    price = x[["BidClose", "AvailableDate"]].join(
        c[["BidClose", "AvailableDate"]], how="inner", lsuffix="_xau", rsuffix="_fx"
    )
    price["AvailableDate"] = (
        price[["AvailableDate_xau", "AvailableDate_fx"]].apply(pd.to_datetime).max(axis=1)
    )
    # Compare ETF at the SAME two native observation endpoints, never T's close.
    q = pd.merge_asof(
        pd.DataFrame({"Date": price.index}),
        d[["Close"]].reset_index(names="ETFDate"),
        left_on="Date",
        right_on="ETFDate",
        direction="backward",
        tolerance=pd.Timedelta(days=7),
    ).set_index("Date")
    local = q.Close
    rmb = price.BidClose_xau * price.BidClose_fx
    pn = pd.DataFrame(
        {
            "known_rmb5": rmb / rmb.shift(5) - 1,
            "known_etf5": local / local.shift(5) - 1,
            "known_fx5": price.BidClose_fx / price.BidClose_fx.shift(5) - 1,
            "known_xau5": price.BidClose_xau / price.BidClose_xau.shift(5) - 1,
            "known_price_start": pd.Series(price.index, index=price.index).shift(5),
            "known_etf_start": q.ETFDate.shift(5),
            "known_etf_end": q.ETFDate,
            "AvailableDate": price.AvailableDate,
        }
    )
    price_features, pa = align(pn, d.index, "known_price")
    for col in price_features:
        f[col] = price_features[col]
    safe = (f.vix5 > 0) & (f.xau5 > 0)
    p01 = safe & (f.pair_vix <= f.vix_median) & (f.pair_gvz > f.gvz_median)
    xu = f.known_xau5 > 0
    fu = f.known_fx5 > 0
    ru = f.known_rmb5 > 0
    lag = f.known_rmb5 > f.known_etf5
    bullish = d.Close > d.Open
    dual = xu & fu
    pr = ["known_rmb5", "known_xau5", "known_fx5", "known_etf5"]
    vr = ["vix5", "xau5", "pair_vix", "pair_gvz", "vix_median", "gvz_median"]
    expressions = {
        "C_ALL": (pd.Series(True, index=d.index), pr),
        "C_FXUP": (fu, pr),
        "C_DUAL": (dual, pr),
        "C_P01": (p01, pr + vr),
        "A01": (xu & fu, pr),
        "A02": (xu & ~fu, pr),
        "A03": (~xu & fu, pr),
        "A04": (~xu & ~fu, pr),
        "A05": (fu & ru, pr),
        "A06": (fu & ~ru, pr),
        "A07": (dual & lag, pr),
        "A08": (dual & ~lag, pr),
        "A09": (dual & bullish, pr),
        "A10": (dual & ~bullish, pr),
        "A11": (p01 & fu, pr + vr),
        "A12": (p01 & ~fu, pr + vr),
    }
    signals, valids = pd.DataFrame(index=d.index), pd.DataFrame(index=d.index)
    for key, (condition, required) in expressions.items():
        valids[key] = f[required].notna().all(axis=1)
        signals[key] = condition & valids[key]
    return f, signals, valids, pd.concat([audit, ua, va, pa], axis=1)


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
    fx = pd.DataFrame(
        {
            "Date": index,
            "BidClose": 6.8 * np.exp(0.003 * np.sin(t / 17)),
            "AvailableDate": index + pd.Timedelta(days=2, hours=8),
        }
    )
    xau = pd.DataFrame(
        {
            "Date": index,
            "BidClose": 1500 * np.exp(0.0005 * t + 0.03 * np.sin(t / 12)),
            "AvailableDate": index + pd.Timedelta(days=2, hours=8),
        }
    )
    return d, f, gvz, usd, vix, xau, fx
