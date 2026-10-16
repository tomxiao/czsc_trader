"""Paired calendar-session block diagnostics; absent events stay absent."""
import numpy as np


def compare(task):
    groups, mode, sign, seed = task
    rng = np.random.default_rng(seed)
    usable, years = [], []
    for year, session, values, selected, control in groups:
        n, ns, nc = len(values), int(selected.sum()), int(control.sum())
        years.append({"year": int(year), "n": n, "selected": ns, "control": nc,
            "selected_mean": float(values[selected].mean()) if ns else None,
            "control_mean": float(values[control].mean()) if nc else None})
        if mode == "allocation" or (ns and nc):
            usable.append((year, session, values, selected, control))
    if not usable:
        return {"status": "NO_BOTH_GROUPS", "years": years, "difference": None,
                "interval95": None, "interval_history440": None, "valid_fraction": 0.}
    total = sum(len(v) if mode == "allocation" else int((s | c).sum()) for _, _, v, s, c in usable)
    distribution = np.zeros(5000)
    valid = np.ones(5000, dtype=bool)
    point = 0.
    without26, without26_weight = 0., 0
    drop3_point = 0.
    for year, session, values, selected, control in usable:
        if mode == "allocation":
            delta = sign * values * (selected.astype(float) - control.astype(float))
            estimate, weight = float(delta.mean()), len(values)
            drop = float(np.sort(delta)[::-1][3:].mean())
        else:
            estimate = sign * float(values[selected].mean() - values[control].mean())
            weight = int((selected | control).sum())
            ordered = np.sort(sign * values[selected])[::-1]
            drop = float(ordered[3:].mean() - sign * values[control].mean()) if len(ordered) > 3 else np.nan
        point += estimate * weight / total
        drop3_point += drop * weight / total
        if year != 2026:
            without26 += estimate * weight
            without26_weight += weight
        first, last = int(session.min()), int(session.max())
        grid = np.zeros((last - first + 1, 5))
        grid[session - first] = np.column_stack((values * selected, values * control, selected, control, np.ones(len(values))))
        n = len(grid)
        for start in range(0, 5000, 100):
            origins = rng.integers(0, n, (100, int(np.ceil(n / 20))))
            indices = ((origins[:, :, None] + np.arange(20)) % n).reshape(100, -1)[:, :n]
            sums = grid[indices].sum(axis=1)
            if mode == "allocation":
                contribution = sign * (sums[:, 0] - sums[:, 1]) / sums[:, 4]
            else:
                good = (sums[:, 2] > 0) & (sums[:, 3] > 0)
                valid[start:start + 100] &= good
                contribution = sign * (np.divide(sums[:, 0], sums[:, 2], out=np.full(100, np.nan), where=sums[:, 2] > 0) -
                    np.divide(sums[:, 1], sums[:, 3], out=np.full(100, np.nan), where=sums[:, 3] > 0))
            distribution[start:start + 100] += contribution * weight / total
    draws = distribution[valid & np.isfinite(distribution)]
    return {"status": "COMPUTED", "years": years, "covered_years": [int(x[0]) for x in usable],
        "difference": point, "without2026": without26 / without26_weight if without26_weight else None,
        "drop3_per_year": drop3_point if np.isfinite(drop3_point) else None,
        "interval95": np.quantile(draws, [.025, .975]).tolist() if len(draws) else None,
        "interval_history440": np.quantile(draws, [.05 / 880, 1 - .05 / 880]).tolist() if len(draws) else None,
        "valid_fraction": len(draws) / 5000}
