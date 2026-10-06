"""Frozen normal-pricing necessity and macro confirmation competition."""

import numpy as np
import pandas as pd

HYPOTHESES = (
    ("U01", 5, "C_MOM", "机会必要性", "原N09正常定价正动量对纯正动量父组"),
    ("U02", 5, "C_N09", "确认", "原N09中原M05共振确认"),
    ("U03", 5, "C_N09", "竞争反证", "原N09中不满足M05的竞争组"),
    ("U04", 5, "C_MOM", "竞争反证", "同有效域正动量但不满足正常定价N09"),
)


def build(d, base, inherited, valids):
    f = base.copy()
    f.attrs = {}
    s = pd.DataFrame(index=d.index)
    v = pd.DataFrame(index=d.index)
    v["C_MOM"] = valids.C_MOMPOS & valids.C_M05
    s["C_MOM"] = inherited.C_MOMPOS & v.C_MOM
    v["C_N09"] = valids.L02 & valids.C_M05
    s["C_N09"] = inherited.L02 & v.C_N09
    for k, c, parent in [
        ("U01", inherited.L02, "C_MOM"),
        ("U02", inherited.L02 & inherited.C_M05, "C_N09"),
        ("U03", inherited.L02 & ~inherited.C_M05, "C_N09"),
        ("U04", inherited.C_MOMPOS & ~inherited.L02, "C_MOM"),
    ]:
        v[k] = v[parent]
        s[k] = c & v[k]
    return f, s, v


def synthetic_frames():
    dates = pd.bdate_range("2020-06-05", periods=320)
    t = np.arange(len(dates))
    p = 5 * np.exp(0.0004 * t + 0.03 * np.sin(t / 11))
    d = pd.DataFrame(
        {
            "Open": p * 0.999,
            "Close": p,
            "High": p * 1.02,
            "Low": p * 0.98,
            "Volume": 10000.0,
            "Amount": p * 10000,
        },
        index=dates,
    )
    f = pd.DataFrame(index=dates)
    for h in (3, 5, 20):
        f[f"etf{h}"] = d.Close.pct_change(h, fill_method=None)
    f["vol20"] = d.Close.pct_change(fill_method=None).rolling(20).std()
    f["own_day"] = d.Close / d.Open - 1
    for k, values in {
        "vix5": np.sin(t / 9),
        "xau5": np.sin(t / 13),
        "gold_vix_corr60": np.sin(t / 23),
        "pair_vix": 20 + np.sin(t / 9),
        "pair_gvz": 17 + np.sin(t / 11),
    }.items():
        f[k] = values
    s = pd.DataFrame(index=dates)
    s["C_MOMPOS"] = f.etf3 > 0
    s["L02"] = s.C_MOMPOS & (t % 3 == 0)
    s["L01"] = t % 7 == 0
    s["C_M05"] = (f.vix5 > 0) & (f.xau5 > 0) & (f.gold_vix_corr60 > 0)
    s["C_ALL"] = True
    v = pd.DataFrame(True, index=dates, columns=s.columns)
    return d, f, s, v
