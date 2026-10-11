"""Focused synthetic checks before seeing new statistics."""

from itertools import combinations
from pathlib import Path
import json
import numpy as np
import pandas as pd
from core import labels, oracle


def main():
    checks = 0
    intervals = [(0, 1, 0.1), (1, 2, -0.02), (0, 2, 0.2), (2, 4, 0.08), (1, 3, 0.15), (3, 4, 0.03)]
    for minimum in range(6):
        scores = []
        positive_counts = []
        for n in range(len(intervals) + 1):
            for combo in combinations(intervals, n):
                ordered = sorted(combo)
                if any(a[1] + 1 > b[0] for a, b in zip(ordered, ordered[1:])):
                    continue
                if n >= minimum:
                    scores.append(sum(np.log1p(r) for _, _, r in combo))
                if all(r > 0 for _, _, r in combo):
                    positive_counts.append(n)
        actual = oracle(intervals, 5, minimum)
        assert actual["positive_nonoverlap_max_count"] == max(positive_counts)
        assert actual["minimum_count_feasible"] == bool(scores)
        if scores:
            np.testing.assert_allclose(
                actual["foresight_constrained_best_log_growth"], max(scores), rtol=0, atol=1e-15
            )
        checks += 3
    index = pd.bdate_range("2020-01-01", periods=25)
    p = pd.DataFrame(
        {"open": 100 * np.exp(np.arange(25) * 0.01), "low": 99 * np.exp(np.arange(25) * 0.01)},
        index=index,
    )
    result = labels(p, index[:-1])
    for h in (1, 4, 8, 10):
        np.testing.assert_allclose(
            result[f"gross_{h}"].iloc[: 24 - h], np.expm1(0.01 * h), atol=1e-15
        )
        np.testing.assert_allclose(
            result[f"return_{h}"].iloc[: 24 - h], np.exp(0.01 * h) * 0.999 / 1.001 - 1, atol=1e-15
        )
        assert result[f"return_{h}"].iloc[24 - h :].isna().all()
        assert result[f"label_end_return_{h}"].iloc[0] == index[h + 1]
        changed = p.copy()
        changed.iloc[15:] *= 5
        pd.testing.assert_series_equal(
            labels(changed, index[:-1])[f"return_{h}"].iloc[: 15 - h - 1],
            result[f"return_{h}"].iloc[: 15 - h - 1],
        )
        checks += 5
    for bad in ([(0, 0, 0.1)], [(0, 5, 0.1)], [(0, 1, -1.0)]):
        try:
            oracle(bad, 5)
        except ValueError:
            checks += 1
        else:
            raise AssertionError("illegal interval accepted")
    Path(__file__).with_name("checks.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "checks": checks,
                "scope": "fee-label formula/maturity/future-mutation and exhaustive interval-DP comparisons",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print({"status": "PASS", "checks": checks})


if __name__ == "__main__":
    main()
