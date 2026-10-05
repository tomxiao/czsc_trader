"""Causal pricing-state contrasts; fixed after the EX016 development results."""

import numpy as np
import pandas as pd
from .statistics import number

NEW = (
    "actual_vwap_mid",
    "mid_nonnegative",
    "mid_negative",
    "vwap_near_zero",
    "mid_late_thin",
    "mid_momentum_positive",
    "o01_mid",
)
CONTROLS = ("actual_vwap_low", "actual_vwap_high", "o01", "unconditional")


def annual_thresholds(gap):
    """Prior-year prefix only, at least 252 nonmissing historical observations."""
    result = pd.DataFrame(
        np.nan, index=gap.index, columns=["vwap_low_threshold", "vwap_high_threshold"]
    )
    for year in sorted(set(gap.index.year)):
        history = gap.loc[gap.index.year < year].dropna()
        if len(history) >= 252:
            result.loc[gap.index.year == year] = history.quantile([0.25, 0.75]).to_numpy()
    return result


def make_states(features, old, valids, thresholds):
    if not features.index.equals(thresholds.index):
        raise ValueError("threshold dates disagree with inherited features")
    gap = features.actual_vwap_gap
    lo, hi = thresholds.vwap_low_threshold, thresholds.vwap_high_threshold
    if (lo.isna() != hi.isna()).any() or (lo.gt(hi)).any():
        raise ValueError("invalid inherited quartile pair")
    bounded = np.isfinite(gap) & np.isfinite(lo) & np.isfinite(hi)
    mid = gap.ge(lo) & gap.le(hi)
    signals = old[["actual_vwap_low", "actual_vwap_high", "o01"]].copy()
    valid = valids[["actual_vwap_low", "actual_vwap_high", "o01"]].copy()
    states = {
        "actual_vwap_mid": mid,
        "mid_nonnegative": mid & gap.ge(0),
        "mid_negative": mid & gap.lt(0),
        "vwap_near_zero": gap.abs().le(0.002),
        "mid_late_thin": mid & old.late_volume_low,
        "mid_momentum_positive": mid & features.return3.gt(0),
        "o01_mid": mid & old.o01,
    }
    for name, mask in states.items():
        defined = np.isfinite(gap) if name == "vwap_near_zero" else bounded.copy()
        if name == "mid_late_thin":
            defined &= valids.late_volume_low
        if name == "mid_momentum_positive":
            defined &= np.isfinite(features.return3)
        if name == "o01_mid":
            defined &= valids.o01
        valid[name] = defined
        signals[name] = mask & defined
    signals["unconditional"], valid["unconditional"] = True, True
    return signals, valid


def audit(d, signals, valids, labels):
    """Fixed unions and selection-biased dependence intervals, main horizon only."""
    output = {"pairwise": [], "bootstrap": [], "unions": []}
    primary = labels["h5_delay0"]
    eligible = primary.valid & primary.net.notna()

    def deoverlap(mask):
        chosen, nxt = [], 0
        for position in np.flatnonzero(mask.to_numpy()):
            if position >= nxt:
                chosen.append(int(position))
                nxt = int(position) + 6
        return chosen

    for name in signals:
        mask = eligible & signals[name] & valids[name]
        other = eligible & signals.o01 & valids.o01
        output["pairwise"].append(
            {
                "signal": name,
                "events": int(mask.sum()),
                "o01_overlap": int((mask & other).sum()),
                "o01_overlap_fraction": int((mask & other).sum()) / max(int(mask.sum()), 1),
            }
        )
        values = primary.net.iloc[deoverlap(mask)].to_numpy()
        interval = {"ci_low": None, "ci_high": None}
        reason = "少于6个非重叠事件，5事件循环块区间不具可辨识性。"
        if len(values) >= 6:
            rng = np.random.default_rng(12017)
            samples = []
            for _ in range(999):
                starts = rng.integers(0, len(values), size=int(np.ceil(len(values) / 5)))
                sample = np.concatenate([values[(a + np.arange(5)) % len(values)] for a in starts])[
                    : len(values)
                ]
                samples.append(float(sample.mean()))
            interval = {
                "ci_low": float(np.quantile(samples, 0.025)),
                "ci_high": float(np.quantile(samples, 0.975)),
            }
            reason = "999次循环5事件块；候选已见开发池，选择偏差未校正。"
        output["bootstrap"].append(
            {
                "signal": name,
                "nonoverlap_events": len(values),
                "net_mean": number(values.mean()) if len(values) else None,
                **interval,
                "reason": reason,
                "selection_adjusted": False,
            }
        )
    for group in (
        ("o01", "actual_vwap_mid"),
        ("o01", "mid_late_thin"),
        ("o01", "mid_momentum_positive"),
        ("o01", "mid_nonnegative"),
        ("o01", "vwap_near_zero"),
    ):
        mask = pd.Series(False, index=d.index)
        for name in group:
            mask |= signals[name] & valids[name]
        mask &= eligible
        chosen = deoverlap(mask)
        fills = primary.limit_net.iloc[chosen].dropna()
        output["unions"].append(
            {
                "signals": list(group),
                "events": int(mask.sum()),
                "nonoverlap_events": len(chosen),
                "open_net": number(primary.net.iloc[chosen].mean()),
                "limit_fills": len(fills),
                "limit_per60": len(fills) * 60 / len(d),
                "limit_net": number(fills.mean()),
                "denominator": len(d),
            }
        )
    output["selection_history"] = (
        "EX016两端弱后提出中段竞争解释；信号全集已见开发池，不开展本轮年度候选选型，不宣称独立验证。"
    )
    return output
