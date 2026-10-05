"""Fixed conditional confirmation definitions; no future execution inputs."""

import numpy as np
import pandas as pd

BASES = ("o01", "mid_momentum_positive")
GATES = (
    "afternoon_positive",
    "last_hour_positive",
    "close_upper_half",
    "recovered_after_shock",
    "peer_positive",
    "volume_participation",
)


def make_gates(f, peer):
    peer_return = peer.Close / peer.Open - 1
    values = {
        "afternoon_positive": f.afternoon,
        "last_hour_positive": f.last_hour,
        "close_upper_half": f.location - 0.5,
        "recovered_after_shock": f.recovery,
        "peer_positive": peer_return,
        "volume_participation": f.volume_ratio - 1,
    }
    gates, valid = {}, {}
    for name, series in values.items():
        valid[name] = np.isfinite(series)
        gates[name] = (series.ge(0) if name == "close_upper_half" else series.gt(0)) & valid[name]
    # Equal-to-average turnover belongs to participation, with equality fixed in protocol.
    gates["volume_participation"] = (
        values["volume_participation"].ge(0) & valid["volume_participation"]
    )
    return pd.DataFrame(gates), pd.DataFrame(valid)


def risk_states(d, f):
    values = pd.DataFrame(
        {
            "volatility20": f.volatility20,
            "momentum20": f.momentum20,
            "kurtosis60": d.Close.pct_change(fill_method=None).rolling(60).kurt(),
        },
        index=d.index,
    )
    limits = pd.DataFrame(np.nan, index=d.index, columns=values.columns)
    for year in sorted(set(d.index.year)):
        for name in values:
            past = values.loc[d.index.year < year, name].dropna()
            if len(past) >= 252:
                limits.loc[d.index.year == year, name] = past.median()
    valid = np.isfinite(values) & limits.notna()
    return values, limits, (values.gt(limits) & valid), valid


def nonoverlap(mask, spacing):
    result = []
    next_index = 0
    for index in np.flatnonzero(np.asarray(mask)):
        if index >= next_index:
            result.append(int(index))
            next_index = int(index) + spacing
    return np.asarray(result, dtype=int)
