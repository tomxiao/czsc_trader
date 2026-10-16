"""Paired event comparisons; missing selections and overlapping origins explicit."""
import numpy as np


def compare(task):
    groups, seed = task
    random = np.random.default_rng(seed)
    distribution, valid = np.zeros(5000), np.ones(5000, dtype=bool)
    total = sum(len(values) for _, values, _, _ in groups)
    yearly = []
    for year, values, selected, control in groups:
        if not selected.any() or not control.any():
            return {"status": "INSUFFICIENT_DATA", "reason": "YEAR_WITHOUT_BOTH_GROUPS", "year": int(year),
                    "difference": None, "interval95": None, "interval_history78": None, "valid_fraction": 0.}
        n = len(values)
        starts = random.integers(0, n, (5000, int(np.ceil(n / 20))))
        indices = ((starts[:, :, None] + np.arange(20)) % n).reshape(5000, -1)[:, :n]
        a, b = selected[indices], control[indices]
        a_count, b_count = a.sum(axis=1), b.sum(axis=1)
        valid &= (a_count > 0) & (b_count > 0)
        a_mean = np.divide((values[indices] * a).sum(axis=1), a_count, out=np.full(5000, np.nan), where=a_count > 0)
        b_mean = np.divide((values[indices] * b).sum(axis=1), b_count, out=np.full(5000, np.nan), where=b_count > 0)
        distribution += (a_mean - b_mean) * n / total
        difference = float(values[selected].mean() - values[control].mean())
        yearly.append({"year": int(year), "dates": n, "difference": difference,
                       "selected": int(selected.sum()), "control": int(control.sum()),
                       "selected_mean": float(values[selected].mean()), "control_mean": float(values[control].mean())})
    good = distribution[valid]
    point = sum(x["difference"] * x["dates"] for x in yearly) / total
    return {"status": "COMPUTED", "difference": point,
        "interval95": np.quantile(good, [.025, .975]).tolist() if len(good) else None,
        "interval_history78": np.quantile(good, [.05 / 156, 1 - .05 / 156]).tolist() if len(good) else None,
        "valid_fraction": float(valid.mean()), "positive_years": sum(x["difference"] > 0 for x in yearly), "years": yearly,
        "leave_one_year_out": {str(x["year"]): float(sum(z["difference"] * z["dates"] for z in yearly if z is not x) / (total - x["dates"])) for x in yearly}}
