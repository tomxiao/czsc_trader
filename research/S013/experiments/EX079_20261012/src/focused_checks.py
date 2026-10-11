"""Artificial fixed-model/reuse/pairing checks. No actual input/statistics IO."""

from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

import inputs
import net_statistics as stats


def run():
    rng = np.random.default_rng(13)
    checks = []
    # Two-calendar-month artificial numerical fixture:40train/22test rows.
    two_months = pd.date_range("2020-12-01", periods=62)
    x = rng.normal(size=(62, 14))
    x[:, 8] = np.round(x[:, 8], 1)
    y = 0.004 * x[:, 8] + rng.normal(scale=0.002, size=62)
    before = stats.score_model("confirmation_only", x[:40], y[:40], x[40:])
    reordered_truth = y[40:][::-1]
    after = stats.score_model("confirmation_only", x[:40], y[:40], x[40:])
    assert len(two_months) == 62 and not np.array_equal(y[40:], reordered_truth)
    np.testing.assert_array_equal(before, after)
    assert np.all(stats.score_model("training_mean", x[:40], np.zeros(40), x[40:]) == 0)
    checks.append(
        "two_month40/22 numerical fixture; future testtruth not an argument; zero trainingmean exact"
    )
    axis = pd.bdate_range("2020-10-01", "2021-02-26").append(
        pd.bdate_range("2026-01-02", "2026-02-27")
    )
    features = pd.DataFrame(rng.normal(size=(len(axis), 14)), index=axis, columns=inputs.FEATURES)
    target = pd.Series(0.003 + 0.002 * features.confirmation_score, index=axis)
    ends = pd.Series(pd.NaT, index=axis, dtype="datetime64[ns]")
    ends.iloc[:-5] = axis[5:]
    target.iloc[-5:] = np.nan
    labels = pd.DataFrame({"return_4": target, "label_end_return_4": ends}, index=axis)
    aux = pd.Series(np.arange(len(axis)) % 3 == 0, index=axis)
    inputs.validate(features, labels, aux)
    prior = []
    for year in (2021, 2026):
        first = axis[axis.year == year][0]
        train = (
            (axis.year >= 2020)
            & (axis.year < year)
            & (ends < first).to_numpy()
            & np.isfinite(target)
        )
        test = (axis.year == year) & np.isfinite(target)
        joint = stats.score_model(
            "original14_joint",
            features.to_numpy()[train],
            target.to_numpy()[train],
            features.to_numpy()[test],
        )
        baseline = float(target.to_numpy()[train].mean())
        prior.extend(
            {
                "signaldate": day.isoformat(),
                "target": float(truth),
                "prediction": float(prediction),
                "baseline": baseline,
            }
            for day, truth, prediction in zip(axis[test], target.to_numpy()[test], joint)
        )
    original_score = stats.score_model
    calls = []

    def traced(model, train_x, train_y, test_x):
        calls.append((model, len(test_x)))
        return original_score(model, train_x, train_y, test_x)

    with patch.object(stats, "score_model", side_effect=traced):
        scores, reasons, years = stats.forecasts(features, labels, prior)
    assert [call for call in calls if call[0] == "original14_joint"] == [("original14_joint", 5)]
    assert not any(call[0] == "training_mean" for call in calls)
    assert len([call for call in calls if call[0] == "confirmation_only"]) == 2
    assert scores.loc[axis.year == 2020].isna().all().all()
    assert scores.iloc[-5:].notna().all().all() and labels.return_4.iloc[-5:].isna().all()
    for record in prior:
        day = pd.Timestamp(record["signaldate"])
        assert scores.loc[day, "original14_joint"] == record["prediction"]
        assert scores.loc[day, "training_mean"] == record["baseline"]
    checks.append(
        "oldmean/joint record reuse exact; only2026tail joint reconstruction; tail scores feature-only;2020NaN"
    )
    mutated_labels = labels.copy()
    mutated_labels.loc[axis.year == 2026, "return_4"] *= -10
    mutated_prior = [dict(record) for record in prior]
    for record in mutated_prior:
        day = pd.Timestamp(record["signaldate"])
        if day.year == 2026:
            record["target"] = float(mutated_labels.loc[day, "return_4"])
    mutation, _, _ = stats.forecasts(features, mutated_labels, mutated_prior)
    pd.testing.assert_frame_equal(scores, mutation, check_exact=True)
    for row in years.values():
        if row["latest_train_maturity"] is not None:
            assert pd.Timestamp(row["latest_train_maturity"]) < pd.Timestamp(
                row["first_test_signal"]
            )
    broken = [dict(record) for record in prior]
    broken[0]["baseline"] += 0.0001
    try:
        stats.forecasts(features, labels, broken)
    except ValueError:
        pass
    else:
        raise AssertionError("incorrect prior training contract accepted")
    checks.append(
        "future testtruth mutation no scores change; strict trainmaturity; wrong prior baseline rejected"
    )
    truth = np.r_[np.ones(20) * 0.01, np.zeros(20), np.ones(20) * -0.01]
    p = np.r_[np.ones(20), np.zeros(20), -np.ones(20)]
    positive = stats.group(truth, p, np.ones(60, bool), p > 0)
    nonpositive = stats.group(truth, p, np.ones(60, bool), p <= 0)
    assert (
        positive["evaluation_n"] == 20
        and nonpositive["zero_score_n"] == 20
        and nonpositive["strict_negative_score_n"] == 20
    )
    zero_truth = stats.group(np.zeros(20), np.ones(20), np.ones(20, bool), np.ones(20, bool))
    assert zero_truth["nonpositive_truth_n"] == 20
    assert (
        stats.group(truth[:10], p[:10], np.ones(10, bool), np.ones(10, bool))["true_net_mean"]
        is None
    )
    checks.append("score0 nonpositive; target0 falsepositive; thinmean null")
    # Paired temporal selection uses the same full axis, not separately resampled groups.
    time_truth = np.linspace(-0.03, 0.04, 80)
    prediction = np.column_stack([np.ones(80), np.arange(80) % 2 - 0.5, np.arange(80) % 3 - 1.0])
    bootstrap = stats.paired_bootstrap(time_truth, prediction)
    assert len(bootstrap["records"]) == 500 and len(bootstrap["summary"]) == 8
    samples = stats.legacy()._bootstrap_indices(80)
    expected, ns = stats.quantities(time_truth, prediction, samples[0])
    assert expected == bootstrap["records"][0]["values"] and ns == bootstrap["records"][0]["n"]
    assert all(
        row["values"]["training_mean_positive_minus_all"] == 0.0 for row in bootstrap["records"]
    )
    empty = stats.paired_bootstrap(time_truth, -np.ones((80, 3)))
    assert all(row["ci95"] is None for row in empty["summary"].values())
    assert np.array_equal(np.arange(len(axis)) % 5, np.arange(len(axis)) % 5)
    checks.append(
        "singlefullaxis500x40 shared8quantities/500statuses; allpositivebaseline subtractpool0; emptygroupsnull; phasebeforefilter"
    )
    # One artificial end-to-end result/schema, never actual study.
    result = stats.analyze(features, labels, aux, prior)
    assert result["signal_n"] == len(axis) and len(result["forecasts"]) == len(axis)
    assert all(result["forecasts"][i]["original_axis_phase5"] == i % 5 for i in range(len(axis)))
    assert all(
        result["forecasts"][i]["truth_missing"]
        and all(v is not None for v in result["forecasts"][i]["scores"].values())
        for i in range(len(axis) - 5, len(axis))
    )
    json.dumps(result, allow_nan=False)
    checks.append(
        "fullaxis3score records/year5phase/auxonlyreport schema/JSONfinite; immature truth flagged"
    )
    here = Path(__file__).resolve().parent
    return {
        "status": "PASS",
        "checks": checks,
        "source_sha256": {
            name: sha256((here / name).read_bytes()).hexdigest()
            for name in ("inputs.py", "net_statistics.py", "focused_checks.py")
        },
        "numeric_dependency": {stats.SOURCE_REL: stats.SOURCE_SHA},
        "actualdata_reads": 0,
        "actual_statistics": 0,
        "actual_account": 0,
        "actual_experiment": 0,
        "actualpublication": 0,
        "synthetic_only": True,
    }


if __name__ == "__main__":
    result = run()
    Path(__file__).with_name("focused_checks.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
