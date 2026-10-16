"""Separate market amplitude, execution feasibility and directional return roles."""
import numpy as np
import pandas as pd
from methods import fitted_scores


def true_range(adjusted):
    previous = adjusted.Close.shift(1)
    return pd.concat([adjusted.High - adjusted.Low, (adjusted.High - previous).abs(),
                      (adjusted.Low - previous).abs()], axis=1).max(axis=1) / previous


def amplitude_target(ranges, horizon):
    # Every term occurs strictly after the feature date.
    return pd.concat([ranges.shift(-offset) for offset in range(1, horizon + 1)], axis=1).mean(axis=1, skipna=False)


def fit_amplitude(task):
    training, whole, values = task
    train_scores, scores = fitted_scores(("amplitude-ridge", training, whole, values))
    return np.maximum(0, train_scores), np.maximum(0, scores)


def error_interval(task):
    groups, seed = task
    generator = np.random.default_rng(seed)
    n_total = sum(len(x) for x in groups)
    distribution = np.zeros(5000)
    for group in groups:
        n = len(group)
        starts = generator.integers(0, n, (5000, int(np.ceil(n / 20))))
        indices = ((starts[:, :, None] + np.arange(20)) % n).reshape(5000, -1)[:, :n]
        distribution += np.asarray(group)[indices].sum(axis=1) / n_total
    return {"difference": float(sum(np.sum(x) for x in groups) / n_total),
            "interval95": np.quantile(distribution, [.025, .975]).tolist(),
            "interval_family24": np.quantile(distribution, [.05 / 48, 1 - .05 / 48]).tolist(),
            "positive_years": sum(float(np.mean(x)) > 0 for x in groups),
            "leave_one_year_out": [float(sum(np.sum(x) for j, x in enumerate(groups) if j != i) / (n_total - len(group))) for i, group in enumerate(groups)]}
