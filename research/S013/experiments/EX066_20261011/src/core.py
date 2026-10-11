"""Fee-aware open-to-open opportunity diagnostics, never account evaluation."""

from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = (1, 4, 8, 10)
COST = 0.001


def labels(prices: pd.DataFrame, signals: pd.DatetimeIndex) -> pd.DataFrame:
    if not prices.index.is_unique or not prices.index.is_monotonic_increasing:
        raise ValueError("Ordered unique daily prices required")
    if not signals.isin(prices.index).all() or signals.has_duplicates:
        raise ValueError("Signal grid must be unique subset")
    vals = prices[["open", "low"]].to_numpy(float)
    if not np.isfinite(vals).all() or not (vals > 0).all():
        raise ValueError("Strictly positive finite prices required")
    out = pd.DataFrame(index=signals)
    positions = prices.index.get_indexer(signals)
    for h in HORIZONS:
        gross, net, risk = [], [], []
        ends = []
        for t in positions:
            if t + h + 1 >= len(prices):
                gross.append(np.nan)
                net.append(np.nan)
                risk.append(np.nan)
                ends.append(pd.NaT)
                continue
            entry, exit_price = vals[t + 1, 0], vals[t + h + 1, 0]
            g = exit_price / entry - 1
            gross.append(g)
            net.append((1 + g) * (1 - COST) / (1 + COST) - 1)
            risk.append(max(0.0, 1 - vals[t + 1 : t + h + 1, 1].min() / entry))
            ends.append(prices.index[t + h + 1])
        out[f"gross_{h}"] = gross
        out[f"return_{h}"] = net
        out[f"downside_{h}"] = risk
        for prefix in ("return", "downside"):
            out[f"label_end_{prefix}_{h}"] = pd.to_datetime(ends)
    return out


def oracle(
    intervals: list[tuple[int, int, float]], length: int, minimum: int = 0, turnaround: int = 1
) -> dict:
    """Exact interval DP: one full-size fractional position and fixed turnaround.

    Foresight, perfect opening fills and no lots/limit restrictions are deliberate
    relaxations. This is not a strategy or an estimate of obtainable returns.
    """
    if length < 1 or minimum < 0 or turnaround not in (0, 1):
        raise ValueError("Positive length and nonnegative minimum required")
    by_end: dict[int, list[tuple[int, float]]] = {}
    for start, end, net in intervals:
        if not (0 <= start < end < length) or not np.isfinite(net) or net <= -1:
            raise ValueError("Legal finite interval required")
        by_end.setdefault(end, []).append((start, float(np.log1p(net))))
    dp = np.full((length, length), -np.inf)
    dp[:, 0] = 0.0
    positive_count = np.zeros(length, dtype=int)
    for end in range(1, length):
        dp[end] = dp[end - 1]
        positive_count[end] = positive_count[end - 1]
        for start, log_net in by_end.get(end, []):
            before = start - turnaround
            prior = dp[before] if before >= 0 else np.r_[0.0, np.full(length - 1, -np.inf)]
            dp[end, 1:] = np.maximum(dp[end, 1:], prior[:-1] + log_net)
            if log_net > 0:
                positive_count[end] = max(
                    positive_count[end], (positive_count[before] if before >= 0 else 0) + 1
                )
    final = dp[-1]
    best_k = int(np.argmax(final))
    restricted = final.copy()
    restricted[:minimum] = -np.inf
    constrained_k = int(np.argmax(restricted))
    feasible = bool(np.isfinite(restricted[constrained_k]))
    return {
        "turnaround_sessions": turnaround,
        "positive_nonoverlap_max_count": int(positive_count[-1]),
        "foresight_best_count": best_k,
        "foresight_best_log_growth": float(final[best_k]),
        "minimum_count": minimum,
        "minimum_count_feasible": feasible,
        "foresight_constrained_best_count": constrained_k if feasible else None,
        "foresight_constrained_best_log_growth": float(restricted[constrained_k])
        if feasible
        else None,
    }


def supply(
    prices: pd.DataFrame, target: pd.DataFrame, features: pd.DataFrame, opportunity: pd.Series
) -> dict:
    if not target.index.equals(features.index) or not target.index.equals(opportunity.index):
        raise ValueError("Exact diagnostic grid required")
    pos = prices.index.get_indexer(target.index)
    years = prices.index.year
    scopes = {
        "all": np.ones(len(target), bool),
        "past20_declining": (features.momentum20 < 0).to_numpy(),
        "old_entry_eligible": opportunity.to_numpy(bool),
        "declining_old_eligible": (opportunity & features.momentum20.lt(0)).to_numpy(bool),
    }
    result = {"label_means": {}, "foresight_capacity": {}, "four_horizon_mixture": {}}
    for year in sorted(y for y in set(years) if y >= 2020):
        for scope_name, scope in scopes.items():
            for h in HORIZONS:
                end = pd.to_datetime(target[f"label_end_return_{h}"])
                net = target[f"return_{h}"].to_numpy(float)
                # Entry and exit must be in the same year for capacity. This is
                # a posthoc annual diagnostic; never a predictive year filter.
                good = (
                    scope
                    & np.isfinite(net)
                    & (years[np.minimum(pos + 1, len(years) - 1)] == year)
                    & end.dt.year.eq(year).to_numpy()
                )
                raw = target.loc[good, f"gross_{h}"].to_numpy(float)
                rows = net[good]
                key = f"{year}/{scope_name}/h{h}"
                result["label_means"][key] = {
                    "n": len(rows),
                    "mean_gross": float(raw.mean()) if len(rows) else None,
                    "mean_net": float(rows.mean()) if len(rows) else None,
                    "net_positive_n": int((rows > 0).sum()),
                    "net_positive_rate": float((rows > 0).mean()) if len(rows) else None,
                }
        subset = np.flatnonzero(years == year)
        origin, length = int(subset[0]), len(subset)
        mix = []
        for h in HORIZONS:
            intervals = []
            for start in range(max(1, origin), origin + length - h):
                end = start + h
                net = float(
                    prices.open.iloc[end] / prices.open.iloc[start] * (1 - COST) / (1 + COST) - 1
                )
                intervals.append((start - origin, end - origin, net))
            result["foresight_capacity"][f"{year}/h{h}"] = oracle(intervals, length)
            mix.extend(intervals)
        result["four_horizon_mixture"][str(year)] = oracle(mix, length)
    intervals = []
    for start in range(1, len(prices)):
        for h in HORIZONS:
            if start + h < len(prices):
                net = float(
                    prices.open.iloc[start + h] / prices.open.iloc[start] * (1 - COST) / (1 + COST)
                    - 1
                )
                intervals.append((start, start + h, net))
    result["whole_pool_foresight_min110"] = oracle(intervals, len(prices), 110)
    result["limitations"] = [
        "All oracle choices use future returns; not tradable.",
        "Fractional all-capital positions; perfect opening fills; no buy-limit/tick/lot constraints.",
        "Zero cash yield, two-sided10bp modeled; HFQ no cash dividend overlay.",
        "Overlapping label means are not compounded portfolio returns.",
        "Annual rows only describe supply; no per-year trade count hard gate.",
        "Canonical capacity leaves one session between exit and next entry; this still does not reproduce limit fills or the native state machine.",
        "Capacity is conditional on the four declared horizons, not all possible strategies.",
    ]
    return result
