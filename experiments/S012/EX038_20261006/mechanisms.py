"""Exact historical opportunity signals, fixed-parent and complement revalidation."""

import numpy as np
import pandas as pd

HYPOTHESES = (
    ("L01", 5, "C_ALL", "机会复验", "继承O01强汇率变化与ETF三日回调的原固定信号"),
    ("L02", 5, "C_MOMPOS", "机会复验", "继承N09实际VWAP正常中段且三日动量正的原固定信号"),
    ("L03", 5, "C_O01", "确认复验", "继承Q07目标当日阳线，仅在原O01父内"),
    ("L04", 5, "C_O01", "竞争反证", "原O01当日非阳线竞争组"),
    ("L05", 5, "C_M05", "互补机会", "原M05在O01与N09机会集合之外的增量"),
    ("L06", 5, "C_M05", "重叠竞争", "原M05与O01或N09重叠的竞争组"),
)


def build(d, base, inherited, valids):
    f = base.copy()
    f.attrs = {}
    f["own_day"] = d.Close / d.Open - 1
    if not inherited.index.equals(d.index) or not valids.index.equals(d.index):
        raise ValueError("legacy dates differ")
    s = pd.DataFrame(index=d.index)
    v = pd.DataFrame(index=d.index)
    v["C_ALL"] = valids.o01 & valids.mid_momentum_positive
    s["C_ALL"] = v.C_ALL
    for new, old, parent in (
        ("L01", "o01", "C_ALL"),
        ("L02", "mid_momentum_positive", "C_MOMPOS"),
        ("L03", "o01_own_positive", "C_O01"),
        ("L04", "o01_own_nonpositive", "C_O01"),
    ):
        s[new] = inherited[old]
        v[new] = valids[old]
    v["C_MOMPOS"] = valids.mid_momentum_positive & f.etf3.notna()
    s["C_MOMPOS"] = (f.etf3 > 0) & v.C_MOMPOS
    v["C_O01"] = valids.o01
    s["C_O01"] = inherited.o01
    req = ["vix5", "xau5", "gold_vix_corr60"]
    v["C_M05"] = f[req].notna().all(axis=1) & v.C_ALL
    s["C_M05"] = (f.vix5 > 0) & (f.xau5 > 0) & (f.gold_vix_corr60 > 0) & v.C_M05
    old = s.L01 | s.L02
    for k, c in (("L05", ~old), ("L06", old)):
        v[k] = v.C_M05
        s[k] = s.C_M05 & c
    # Inherited signals retain their original invalid bits, never recalibrate thresholds.
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
    for k, values in {
        "vix5": np.sin(t / 9),
        "xau5": np.sin(t / 13),
        "gold_vix_corr60": np.sin(t / 23),
        "pair_vix": 20 + np.sin(t / 9),
        "pair_gvz": 17 + np.sin(t / 11),
    }.items():
        f[k] = values
    s = pd.DataFrame(index=dates)
    s["o01"] = t % 7 == 0
    s["mid_momentum_positive"] = (f.etf3 > 0) & (t % 3 == 0)
    s["o01_own_positive"] = s.o01 & (d.Close > d.Open)
    s["o01_own_nonpositive"] = s.o01 & (d.Close <= d.Open)
    v = pd.DataFrame(True, index=dates, columns=s.columns)
    return d, f, s, v
