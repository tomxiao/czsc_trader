"""Single artificial-only independent interface proof. No real data IO."""

from pathlib import Path
from hashlib import sha256
import json
import sys
import importlib
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
MAIN = HERE.parent / "s013-base-net-opportunity"
sys.path.insert(0, str(MAIN))
main = importlib.import_module("net_statistics")

sys.path.insert(0, str(HERE))
audit = importlib.import_module("audit")


def run():
    rng = np.random.default_rng(39)
    grid = pd.DatetimeIndex(
        np.concatenate(
            [pd.bdate_range(f"{year}-01-02", periods=65).to_numpy() for year in range(2020, 2027)]
        )
    )
    price_axis = pd.DatetimeIndex([pd.Timestamp("2019-12-31"), *grid, grid[-1] + pd.offsets.BDay()])
    path = np.exp(np.cumsum(rng.normal(0.001, 0.014, len(price_axis))))
    prices = pd.DataFrame(
        {"Open": path, "Close": path * np.exp(rng.normal(0, 0.002, len(path)))}, index=price_axis
    )
    old = pd.DataFrame(
        rng.integers(-4, 5, size=(len(grid), 14)).astype(float), index=grid, columns=audit.FEATURES
    )
    old.iloc[[3, 68, 134], 0] = np.nan
    labels = audit.net_labels(prices, grid)
    target = rng.integers(0, 2, len(grid) + 1).astype(float)
    eligible = rng.integers(0, 2, len(grid) + 1).astype(bool)
    opportunities = eligible & np.r_[True, target[:-1] == 0]
    history = pd.DataFrame(
        {
            "target_position": target,
            "entry_eligible": eligible,
            "confirmation_opportunity": opportunities,
        },
        index=price_axis[:-1],
    )
    aux = pd.Series(opportunities[1:], index=grid, dtype=bool)
    input_check = audit.verify_inputs(old, prices, history, old.copy(), labels.copy(), aux)
    reconstructed, _, _ = audit.forecasts(old, labels)
    records = []
    for year in range(2021, 2027):
        first = grid[grid.year == year][0]
        train = (
            np.isfinite(old.to_numpy()).all(axis=1)
            & np.isfinite(labels.return_4)
            & (grid.year >= 2020)
            & (grid.year < year)
            & (labels.label_end_return_4 < first)
        )
        baseline = float(labels.return_4.to_numpy()[train].mean())
        for i, day in enumerate(grid):
            if (
                day.year == year
                and np.isfinite(reconstructed[i]).all()
                and np.isfinite(labels.return_4.iloc[i])
            ):
                records.append(
                    {
                        "signaldate": day.isoformat(),
                        "target": float(labels.return_4.iloc[i]),
                        "prediction": float(reconstructed[i, 2]),
                        "baseline": baseline,
                    }
                )
    result = main.analyze(old, labels, aux, records)
    statistics_check = audit.verify_statistics(old, labels, aux, result, records)
    assert all(
        row["scores"]["original14_joint"] is None
        for row in result["forecasts"]
        if pd.Timestamp(row["signal_date"]).year == 2020
    )
    assert all(
        row["scores"]["original14_joint"] is not None and row["truth_missing"]
        for row in result["forecasts"][-4:]
    )
    # Test-year future labels cannot change any available forecasts or score groups.
    mutated = labels.copy()
    mutated.loc[grid.year == 2026, "return_4"] *= 2
    altered, _, _ = audit.forecasts(old, mutated)
    np.testing.assert_allclose(altered, reconstructed, equal_nan=True, rtol=0, atol=0)
    # Hand tie ECDF and intercept/ridge, rather than expected production outputs.
    np.testing.assert_array_equal(
        audit.empirical_transform(np.array([1.0, 1.0, 3.0]), np.array([0.0, 1.0, 2.0, 3.0, 4.0])),
        [0, 1 / 3, 2 / 3, 5 / 6, 1],
    )
    np.testing.assert_allclose(
        audit.predict(np.array([[0.0], [1.0]]), np.array([1.0, 3.0]), np.array([[0.0], [1.0]])),
        [41 / 21, 43 / 21],
        rtol=0,
        atol=1e-14,
    )
    zeros = np.zeros(45)
    group = audit.group(np.r_[0.0, np.ones(44)], zeros, np.ones(45, bool), zeros <= 0)
    assert (
        group["zero_score_n"] == 45
        and group["strict_negative_score_n"] == 0
        and group["nonpositive_truth_n"] == 1
    )
    assert (
        audit.group(np.ones(19), np.ones(19), np.ones(19, bool), np.ones(19, bool))["true_net_mean"]
        is None
    )
    no_positive = audit.bootstrap(np.ones(45), np.zeros((45, 3)))
    assert all(
        row["reason"] == "INSUFFICIENT_ORIGINAL_GROUP" for row in no_positive["summary"].values()
    )
    assert len(no_positive["records"]) == 500 and all(
        value == "INSUFFICIENT_REQUIRED_GROUP"
        for row in no_positive["records"]
        for value in row["status"].values()
    )
    rejected = 0
    bad = aux.copy()
    bad.iloc[0] = not bad.iloc[0]
    try:
        audit.verify_inputs(old, prices, history, old, labels, bad)
    except AssertionError:
        rejected += 1
    broken = json.loads(json.dumps(result))
    broken["forecasts"][-1]["scores"]["confirmation_only"] = None
    try:
        audit.verify_statistics(old, labels, aux, broken, records)
    except AssertionError:
        rejected += 1
    assert rejected == 2
    proof = dict(
        status="PASS",
        artificial_only=True,
        input_audit=input_check,
        statistics_audit=statistics_check,
        focused_checks=8,
        refusals=rejected,
        real_inputs=0,
        real_statistics=0,
        new_accounts=0,
        publication=0,
        source_files={
            name: sha256((HERE / name).read_bytes()).hexdigest()
            for name in ["audit.py", "synthetic.py"]
        },
        production_sources={
            name: sha256((MAIN / name).read_bytes()).hexdigest()
            for name in ["net_statistics.py", "inputs.py"]
        },
    )
    (HERE / "synthetic.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(proof))


if __name__ == "__main__":
    run()
