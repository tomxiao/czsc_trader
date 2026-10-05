"""VWAP successor, fixed selected-path audit and causal annual selection."""

import numpy as np
import pandas as pd
from factor_signal_catalog.calculations import calculate_daily_close_vwap_deviation
from .statistics import number

SELECTED = (
    "pre_long_closure",
    "dry_pullback",
    "late_volume_low",
    "thin_impact_low",
    "peer_lag_absorbed",
    "o01",
)


def extend(d, f, old, valids):
    source = d.reset_index().rename(
        columns={"Date": "trade_date", "Close": "close", "Amount": "amount", "Volume": "volume"}
    )
    source["ts_code"] = "518850.SH"
    actual = calculate_daily_close_vwap_deviation(source)["daily_close_vwap_deviation"].to_numpy()
    np.testing.assert_allclose(actual, f.vwap_gap, rtol=1e-12, atol=1e-12)
    f = f.copy()
    f["actual_vwap_gap"] = actual
    lo, hi = pd.Series(np.nan, index=d.index), pd.Series(np.nan, index=d.index)
    for year in sorted(set(d.index.year)):
        history = f.loc[f.index.year < year, "actual_vwap_gap"].dropna()
        if len(history) >= 252:
            lo.loc[d.index.year == year] = history.quantile(0.25)
            hi.loc[d.index.year == year] = history.quantile(0.75)
    s = old[list(SELECTED)].copy()
    v = valids[list(SELECTED)].copy()
    defined = {
        "actual_vwap_low": f.actual_vwap_gap.lt(lo),
        "actual_vwap_high": f.actual_vwap_gap.gt(hi),
        "vwap_negative": f.actual_vwap_gap.lt(0),
        "vwap_below_cost": f.actual_vwap_gap.lt(-0.002),
        "vwap_low_late_heavy": f.actual_vwap_gap.lt(lo) & old.late_volume_high,
        "vwap_low_late_thin": f.actual_vwap_gap.lt(lo) & old.late_volume_low,
        "vwap_low_recovered": f.actual_vwap_gap.lt(lo) & old.recovery_high,
        "vwap_low_down_day": f.actual_vwap_gap.lt(lo) & f.day_return.lt(0),
    }
    for name, mask in defined.items():
        s[name] = mask
        v[name] = f.actual_vwap_gap.notna()
        if name not in ("vwap_negative", "vwap_below_cost"):
            v[name] &= lo.notna()
        if "late_heavy" in name:
            v[name] &= valids.late_volume_high
        if "late_thin" in name:
            v[name] &= valids.late_volume_low
        if "recovered" in name:
            v[name] &= valids.recovery_high
    return (
        f,
        s,
        v,
        pd.DataFrame({"vwap_low_threshold": lo, "vwap_high_threshold": hi}, index=d.index),
    )


def audit(d, s, v, labels, features, bad, workers):
    output = {"pairwise": [], "unions": [], "walkforward": [], "bootstrap": [], "minute_touch": []}
    primary = labels["h5_delay0"]
    y = primary.net
    eligible = (d.index.year >= 2022) & y.notna()
    for name in s:
        mask = eligible & v[name] & s[name]
        other = eligible & v.o01 & s.o01
        output["pairwise"].append(
            {
                "signal": name,
                "events": int(mask.sum()),
                "o01_overlap": int((mask & other).sum()),
                "overlap_fraction": int((mask & other).sum()) / max(int(mask.sum()), 1),
                "minute_proxy_correlation": number(
                    features.actual_vwap_gap.corr(features.vwap_close_proxy_gap, method="spearman")
                ),
            }
        )
        ids = np.flatnonzero(mask.to_numpy())
        chosen = []
        nxt = 0
        for i in ids:
            if i >= nxt:
                chosen.append(int(i))
                nxt = int(i) + 6
        z = pd.Series(False, index=d.index)
        z.iloc[chosen] = True
        values = y[z].to_numpy()
        rng = np.random.default_rng(12016)
        if len(values):
            # Circular chronological blocks of five nonoverlapping events; selection-biased diagnostic.
            samples = []
            for _ in range(999):
                starts = rng.integers(0, len(values), size=int(np.ceil(len(values) / 5)))
                sample = np.concatenate([values[(a + np.arange(5)) % len(values)] for a in starts])[
                    : len(values)
                ]
                samples.append(float(sample.mean()))
            output["bootstrap"].append(
                {
                    "signal": name,
                    "nonoverlap_events": len(values),
                    "net_mean": float(values.mean()),
                    "ci_low": float(np.quantile(samples, 0.025)),
                    "ci_high": float(np.quantile(samples, 0.975)),
                    "selection_adjusted": False,
                }
            )
    for group in (
        ("o01", "pre_long_closure"),
        ("o01", "late_volume_low"),
        ("o01", "dry_pullback"),
        ("o01", "actual_vwap_low"),
        ("o01", "pre_long_closure", "late_volume_low"),
        ("o01", "pre_long_closure", "actual_vwap_low"),
    ):
        mask = pd.Series(False, index=d.index)
        for name in group:
            mask |= s[name] & v[name]
        mask &= eligible
        chosen = []
        nxt = 0
        for i in np.flatnonzero(mask.to_numpy()):
            if i >= nxt:
                chosen.append(int(i))
                nxt = int(i) + 6
        output["unions"].append(
            {
                "signals": list(group),
                "events": int(mask.sum()),
                "nonoverlap_events": len(chosen),
                "open_net": number(y.iloc[chosen].mean()),
                "limit_fills": int(primary.limit_net.iloc[chosen].notna().sum()),
                "limit_per60": int(primary.limit_net.iloc[chosen].notna().sum()) * 60 / len(d),
                "limit_net": number(primary.limit_net.iloc[chosen].mean()),
                "denominator": len(d),
            }
        )
    # Annual selection uses only past labels that have fully matured before January 1.
    # No strategy account or per-day hindsight selection is created.
    candidates = [c for c in s if c != "o01"]
    for year in (2023, 2024, 2025, 2026):
        cutoff = pd.Timestamp(f"{year}-01-01")
        exits = pd.Series(d.index, index=d.index).shift(-6)
        prior = eligible & exits.lt(cutoff)
        scoring = {}
        for name in candidates:
            a = prior & s[name] & v[name]
            scoring[name] = number(y[a].mean() - y[prior & v[name]].mean()) if a.any() else None
        finite = {k: x for k, x in scoring.items() if x is not None}
        selected = max(finite, key=finite.get) if finite else None
        mask = eligible & (d.index.year == year)
        events = mask & s[selected] & v[selected] if selected else mask & False
        output["walkforward"].append(
            {
                "year": year,
                "selected": selected,
                "training_score": finite.get(selected),
                "training_scores": scoring,
                "events": int(events.sum()),
                "net_mean": number(y[events].mean()),
                "unconditional_increment": number(y[events].mean() - y[mask].mean()),
                "selection_history": "候选集合来自已见EX015；年度排序使用历史成熟标签，不是独立样本外证明。",
            }
        )
    return output
