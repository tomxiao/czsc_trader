"""Frozen financial calculations copied without algorithm changes for native V4."""
from datetime import date
import numpy as np
import pandas as pd
FIRST=date(2025,1,2)
TIMES=("10:00","10:30","11:00","11:30","13:30","14:00","14:30","15:00")
def validate_parameters(parameters):
    p = dict(parameters)
    if set(p) != {"center_kind", "lookback", "allocation", "minimum_repair_space"}:
        raise ValueError("exact active parameters required")
    if p["center_kind"] not in ("mean", "median"):
        raise ValueError("unknown center definition")
    if type(p["lookback"]) is not int or not 1 <= p["lookback"] <= 30:
        raise ValueError("lookback must be 1..30 completed sessions")
    if isinstance(p["allocation"], bool) or not isinstance(p["allocation"], (int, float)) or not 0 < p["allocation"] <= 1:
        raise ValueError("allocation outside (0,1]")
    if isinstance(p["minimum_repair_space"], bool) or not isinstance(p["minimum_repair_space"], (int,float)) or not 0 <= p["minimum_repair_space"] <= 0.05:
        raise ValueError("minimum repair price-ratio space outside [0,.05]")
    return p

def causal_features(market, intraday, lookback=3, center_kind="median"):
    frames = []
    for name, frame in (("market", market), ("intraday", intraday)):
        f = frame[["Date", "Open", "High", "Low", "Close"]].copy()
        f.attrs = {}
        f["Date"] = pd.to_datetime(f.Date)
        if f.Date.duplicated().any() or not f.Date.is_monotonic_increasing:
            raise ValueError(name + ": ordered unique dates required")
        z = f[["Open", "High", "Low", "Close"]].to_numpy(float)
        if not np.isfinite(z).all() or (z <= 0).any():
            raise ValueError("positive finite prices required")
        frames.append(f)
    adj, bars = frames
    if (
        len(adj) < 75
        or adj.Date.iloc[0] != pd.Timestamp("2024-09-09")
        or adj.Date.iloc[74] != pd.Timestamp("2024-12-31")
    ):
        raise ValueError("canonical daily preheat mismatch")
    dev = adj.iloc[75:]
    groups = list(bars.groupby(bars.Date.dt.normalize(), sort=False))
    if [d for d, _ in groups] != list(dev.Date) or len(bars) != 8 * len(dev):
        raise ValueError("exact eight bars for each development session required")
    centers = []
    for pos, (day, b) in enumerate(groups):
        if tuple(b.Date.dt.strftime("%H:%M")) != TIMES:
            raise ValueError("invalid bar clock")
        if center_kind == "median":
            center = float(np.median(np.log(b.Close.to_numpy(float))))
        elif center_kind == "mean":
            center = float(np.mean(np.log(b.Close.to_numpy(float))))
        else:
            raise ValueError("unknown center definition")
        centers.append(center)
    logc = np.log(adj.Close.to_numpy(float))
    idx = pd.DatetimeIndex(dev.Date)
    m = pd.Series(centers, index=idx, dtype=float)
    out = pd.DataFrame({"m": m, "p": logc[75:], "center_gain": m - m.shift(lookback)}, index=idx)
    out["repair_space"] = np.expm1(out.m - out.p)
    out["feature_ready"] = out.notna().all(axis=1)
    out = out.fillna(0.0)
    seed = pd.DataFrame([{**{k: 0.0 for k in out.columns}, "feature_ready": False}], index=pd.DatetimeIndex(["2024-12-31"]))
    out = pd.concat([seed, out])
    out.index.name = "date"
    return out

def intentions(features, parameters):
    p = validate_parameters(parameters)
    active = False
    repair_target = invalidation_origin = 0.0
    rows = []
    for day, row in features.iterrows():
        enter = exit_ = False
        permit = bool(row.feature_ready and day.date() >= FIRST and row.center_gain > 0 and row.p < row.m and row.repair_space >= p["minimum_repair_space"])
        if active:
            if row.p >= repair_target or row.m <= invalidation_origin:
                active = False
                exit_ = True
        elif permit:
            active = True
            enter = True
            repair_target = row.m
            invalidation_origin = row.m - row.center_gain
        rows.append({"target_position": float(active), "entry_allocation_fraction": p["allocation"] if active else None,
                     "permission": float(permit), "entry_signal": float(enter), "exit_signal": float(exit_),
                     "repair_target": repair_target, "invalidation_origin": invalidation_origin})
    decisions = pd.DataFrame(rows, index=features.index)
    decisions["entry_allocation_fraction"] = decisions.entry_allocation_fraction.astype(float)
    return features.join(decisions)
