"""Paired dependence-aware checks for fixed forecasts and execution awareness."""
import numpy as np


def error_interval62(task):
    groups, seed = task
    generator = np.random.default_rng(seed)
    count = sum(len(x) for x in groups)
    distribution = np.zeros(5000)
    for group in groups:
        n = len(group)
        starts = generator.integers(0, n, (5000, int(np.ceil(n / 20))))
        indices = ((starts[:, :, None] + np.arange(20)) % n).reshape(5000, -1)[:, :n]
        distribution += np.asarray(group)[indices].sum(axis=1) / count
    yearly = [float(x.mean()) for x in groups]
    return {"difference": float(sum(np.sum(x) for x in groups) / count),
            "interval95": np.quantile(distribution, [.025, .975]).tolist(),
            "interval_family62": np.quantile(distribution, [.05 / 124, 1 - .05 / 124]).tolist(),
            "positive_years": sum(x > 0 for x in yearly), "yearly_differences": yearly,
            "leave_one_year_out": [float(sum(np.sum(x) for j, x in enumerate(groups) if j != i) / (count - len(group))) for i, group in enumerate(groups)]}


def execution_interval(groups):
    random = np.random.default_rng(13)
    hits = np.zeros((5000, 2))
    counts = np.zeros((5000, 2))
    for flags, bad in groups:
        n = len(flags)
        starts = random.integers(0, n, (5000, int(np.ceil(n / 20))))
        idx = ((starts[:, :, None] + np.arange(20)) % n).reshape(5000, -1)[:, :n]
        for col, selected in enumerate((flags, ~flags)):
            mask = selected[idx]
            counts[:, col] += mask.sum(axis=1)
            hits[:, col] += (mask * bad[idx]).sum(axis=1)
    valid = (counts > 0).all(axis=1)
    probabilities = hits[valid] / counts[valid]
    values = probabilities[:, 0] - probabilities[:, 1]
    return {"interval95": np.quantile(values, [.025, .975]).tolist(),
            "interval_family62": np.quantile(values, [.05 / 124, 1 - .05 / 124]).tolist(),
            "valid_draw_fraction": float(valid.mean())}
