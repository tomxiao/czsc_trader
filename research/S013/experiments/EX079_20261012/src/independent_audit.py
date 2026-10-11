"""Independent in-memory net-opportunity audit. No production imports or IO."""

from hashlib import sha256
import json
from math import fsum
import numpy as np
import pandas as pd

FEATURES = (
    "momentum20",
    "range_position60",
    "acf1",
    "volatility20",
    "intraday_return",
    "overnight_gap",
    "intraday_energy20",
    "intraday_rms20",
    "confirmation_score",
    "daily_close_location",
    "feature_intraday_down_energy20",
    "feature_overnight_down_energy20",
    "turnover20",
    "volume_ratio20",
)
MODELS = ("training_mean", "confirmation_only", "original14_joint")
QUANTITIES = (
    "training_mean_positive_mean",
    "confirmation_only_positive_mean",
    "original14_joint_positive_mean",
    "training_mean_positive_minus_all",
    "confirmation_only_positive_minus_all",
    "original14_joint_positive_minus_all",
    "joint_minus_confirmation_positive",
    "joint_minus_training_mean_positive",
)


def ranks(values):
    """Average ties by explicit sorted equal runs; no scipy rankdata."""
    order = np.argsort(values, kind="stable")
    result = np.empty(len(values), dtype=float)
    a = 0
    while a < len(values):
        b = a + 1
        while b < len(values) and values[order[b]] == values[order[a]]:
            b += 1
        result[order[a:b]] = (a + 1 + b) / 2
        a = b
    return result


def full_axis_blocks(n):
    """Seed13 starts on the full T axis, explicit block assembly and truncation."""
    if n < 40:
        return None
    count = (n + 39) // 40
    starts = np.random.Generator(np.random.PCG64(13)).integers(0, n - 39, (500, count))
    output = np.empty((500, n), dtype=int)
    for rep in range(500):
        output[rep] = np.concatenate([np.arange(start, start + 40) for start in starts[rep]])[:n]
    return output


def linear_percentile(values, probabilities):
    ordered = sorted(values)
    result = []
    for probability in probabilities:
        position = (len(ordered) - 1) * probability
        lower, upper = int(np.floor(position)), int(np.ceil(position))
        fraction = position - lower
        result.append(float(ordered[lower] * (1 - fraction) + ordered[upper] * fraction))
    return result


def empirical_transform(train, values):
    # Unique counts and cumulative mass instead of searchsorted twice on raw train.
    unique, counts = np.unique(train, return_counts=True)
    cumulative = np.r_[0, np.cumsum(counts)]
    result = np.empty(len(values))
    for j, value in enumerate(values):
        p = int(np.searchsorted(unique, value))
        equal = counts[p] if p < len(unique) and unique[p] == value else 0
        result[j] = (cumulative[p] + equal / 2) / len(train)
    return result


def predict(train, y, test):
    # Intercept augmented normal equations; source uses centered features.
    design = np.column_stack([np.ones(len(train)), train])
    penalty = np.diag([0.0] + [10.0] * train.shape[1])
    coef = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    return np.column_stack([np.ones(len(test)), test]) @ coef


def dates(index):
    if (
        not isinstance(index, pd.DatetimeIndex)
        or index.tz is not None
        or index.hasnans
        or index.has_duplicates
        or not index.is_monotonic_increasing
        or not index.equals(index.normalize())
    ):
        raise ValueError("complete ordered normalized session axis required")
    return index.as_unit("ns")


def equivalent(actual, expected, path=""):
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            raise AssertionError(path + ": keys")
        for key, value in expected.items():
            equivalent(actual[key], value, path + "." + key)
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise AssertionError(path + ": length")
        for p, value in enumerate(expected):
            equivalent(actual[p], value, path + f"[{p}]")
    elif isinstance(expected, float):
        if (
            not isinstance(actual, (int, float))
            or not np.isfinite(actual)
            or not np.isclose(actual, expected, atol=2e-10, rtol=2e-9)
        ):
            raise AssertionError(path + ": numeric")
    elif actual != expected or type(actual) is not type(expected):
        raise AssertionError(path + ": exact/null/type")


def metrics(target, forecast, mean):
    n = len(target)
    if n < 20:
        return dict(
            n=n,
            mse=None,
            baseline_mse=None,
            mse_improvement=None,
            ic=None,
            reason="INSUFFICIENT_SAMPLE",
        )
    mse = float(fsum(float(value) ** 2 for value in target - forecast) / n)
    base = float(fsum(float(value) ** 2 for value in target - mean) / n)
    corr = ic(forecast, target)
    return dict(
        n=n,
        mse=mse,
        baseline_mse=base,
        mse_improvement=base - mse,
        ic=corr["value"],
        ic_reason=corr["reason"],
        reason=None,
    )


def ic(x, y):
    good = np.isfinite(x) & np.isfinite(y)
    n = int(good.sum())
    if n < 20:
        return dict(n=n, value=None, reason="INSUFFICIENT_SAMPLE")
    a, b = ranks(x[good]), ranks(y[good])
    a -= fsum(a) / n
    b -= fsum(b) / n
    if not np.any(a) or not np.any(b):
        return dict(n=n, value=None, reason="CONSTANT_COMPONENT_OR_LABEL")
    scale = float(np.linalg.norm(a) * np.linalg.norm(b))
    value = (
        None if scale <= np.finfo(float).eps * max(1, n) else float(np.clip(a @ b / scale, -1, 1))
    )
    return dict(
        n=n, value=value, reason=None if value is not None else "CONSTANT_OR_EXPLAINED_RESIDUAL"
    )


def net_labels(prices, signal_axis):
    axis, grid = dates(prices.index), dates(signal_axis)
    values = prices[["Open", "Close"]].to_numpy(float)
    if not np.isfinite(values).all() or (values <= 0).any() or not grid.isin(axis).all():
        raise ValueError("positive finite native OPEN/CLOSE and complete T axis required")
    positions = {day: i for i, day in enumerate(axis)}
    rows = []
    for day in grid:
        p = positions[day]
        rows.append(
            (float(values[p + 5, 0]) / float(values[p + 1, 0]) * (0.999 / 1.001) - 1, axis[p + 5])
            if p + 5 < len(axis)
            else (np.nan, pd.NaT)
        )
    return pd.DataFrame(rows, index=grid, columns=["return_4", "label_end_return_4"])


def verify_inputs(old, prices, original_history, features, labels, auxiliary):
    """Root authenticates exact public/native identities before supplying frames.

    original_history is complete native signal-prefix history, including anchor
    and target_position/entry_eligible/confirmation_opportunity metadata.
    """
    grid = dates(old.index)
    history_axis = dates(original_history.index)
    if (
        not history_axis[1:].equals(grid)
        or not dates(features.index).equals(grid)
        or not dates(labels.index).equals(grid)
        or not dates(auxiliary.index).equals(grid)
    ):
        raise ValueError("original anchor-prefix then full signal calendar required")
    if tuple(features.columns) != FEATURES or tuple(labels.columns) != (
        "return_4",
        "label_end_return_4",
    ):
        raise ValueError("exact original14 and fixedh4 labels required")
    np.testing.assert_array_equal(
        features.to_numpy(float), old.loc[:, list(FEATURES)].to_numpy(float)
    )
    expected = net_labels(prices, grid)
    np.testing.assert_allclose(
        labels.return_4, expected.return_4, atol=2e-14, rtol=2e-13, equal_nan=True
    )
    pd.testing.assert_series_equal(
        pd.to_datetime(labels.label_end_return_4), expected.label_end_return_4, check_names=False
    )
    targets = original_history.target_position.to_numpy(float)
    eligibility = original_history.entry_eligible.to_numpy()
    if not np.isin(targets, [0, 1]).all() or eligibility.dtype != bool or auxiliary.dtype != bool:
        raise ValueError("original binary targets/Boolean ex-ante eligibility required")
    previous = False
    opportunities = []
    for target, eligible, recorded in zip(
        targets, eligibility, original_history.confirmation_opportunity
    ):
        opportunity = (not previous) and bool(eligible)
        if type(recorded) not in (bool, np.bool_) or recorded != opportunity:
            raise AssertionError(
                "original opportunity must use previous policy target, never filled or future state"
            )
        opportunities.append(opportunity)
        previous = bool(target)
    np.testing.assert_array_equal(auxiliary.to_numpy(), opportunities[1:])
    return dict(
        status="PASS",
        signal_n=len(grid),
        original_policy_flat_opportunities=int(auxiliary.sum()),
        new_accounts=0,
    )


def forecasts(features, labels):
    axis = dates(features.index)
    if tuple(features.columns) != FEATURES or not axis.equals(labels.index):
        raise ValueError("exact original14 and aligned full calendar required")
    x, y = features.to_numpy(float), labels.return_4.to_numpy(float)
    ends = pd.to_datetime(labels.label_end_return_4)
    if (
        np.isinf(x).any()
        or np.isinf(y).any()
        or not np.array_equal(np.isfinite(y), ends.notna())
        or (ends[np.isfinite(y)] <= axis[np.isfinite(y)]).any()
    ):
        raise ValueError("finite-or-missing targets with future maturity required")
    complete = np.isfinite(x).all(axis=1)
    scores = np.full((len(axis), 3), np.nan)
    reasons = ["NO_PROSPECTIVE_2020_FORECAST"] * len(axis)
    yearly = {}
    for year in range(2021, 2027):
        rows = np.flatnonzero(axis.year == year)
        first = axis[rows[0]] if len(rows) else None
        train = [
            i
            for i, day in enumerate(axis)
            if complete[i]
            and np.isfinite(y[i])
            and 2020 <= day.year < year
            and first is not None
            and ends.iloc[i] < first
        ]
        test = [i for i in rows if complete[i]]
        reason = (
            "NO_TEST_YEAR"
            if first is None
            else "INSUFFICIENT_TRAIN_SAMPLE"
            if len(train) < 40
            else "INSUFFICIENT_FEATURE_TEST_SAMPLE"
            if len(test) < 20
            else None
        )
        yearly[str(year)] = dict(
            first_test_signal=first.isoformat() if first is not None else None,
            common_train_n=len(train),
            feature_test_n=len(test),
            latest_train_maturity=max(ends.iloc[train]).isoformat() if train else None,
            reason=reason,
            reuse={},
        )
        for i in rows:
            reasons[i] = reason if complete[i] else "INCOMPLETE_FEATURES"
        if reason:
            continue
        training = x[train]
        target = y[train]
        mean = float(fsum(float(v) for v in target) / len(train))
        scores[test, 0] = mean
        for model, columns in [(1, [FEATURES.index("confirmation_score")]), (2, list(range(14)))]:
            ranked_train = np.column_stack(
                [empirical_transform(training[:, c], training[:, c]) for c in columns]
            )
            ranked_test = np.column_stack(
                [empirical_transform(training[:, c], x[test, c]) for c in columns]
            )
            scores[test, model] = predict(ranked_train, target, ranked_test)
        known = sum(np.isfinite(y[test]))
        missing = len(test) - int(known)
        if missing and (year != 2026 or not known):
            raise ValueError("only unlabelled2026 tail extension declared")
        yearly[str(year)]["common_training_dates"] = [axis[i].isoformat() for i in train]
        yearly[str(year)]["reuse"] = dict(
            matured_mean_joint_reused_n=int(known),
            new_confirmation_predictions_n=len(test),
            mean_tail_from_existing_baseline_n=missing,
            joint_tail_coefficient_reconstruction_n=missing,
            new_mean_joint_models=0,
        )
    return scores, reasons, yearly


def group(y, prediction, eligible, selected):
    available = [i for i in range(len(y)) if eligible[i] and np.isfinite(prediction[i])]
    chosen = [i for i in available if selected[i]]
    valid = [i for i in chosen if np.isfinite(y[i])]
    n = len(valid)
    gains = sorted((float(y[i]) for i in valid if y[i] > 0), reverse=True)
    positives = sum(y[i] > 0 for i in valid)
    return dict(
        forecast_eligible_n=len(available),
        forecast_selected_n=len(chosen),
        forecast_coverage=len(chosen) / len(available) if available else None,
        evaluation_n=n,
        truth_missing_n=len(chosen) - n,
        true_net_mean=fsum(float(y[i]) for i in valid) / n if n >= 20 else None,
        positive_truth_n=int(positives),
        positive_truth_rate=float(positives / n) if n >= 20 else None,
        nonpositive_truth_n=n - int(positives),
        nonpositive_truth_rate=float((n - positives) / n) if n >= 20 else None,
        zero_score_n=int(sum(prediction[i] == 0 for i in chosen)),
        strict_negative_score_n=int(sum(prediction[i] < 0 for i in chosen)),
        positive_proxy_gain_concentration=fsum(gains[: (len(gains) + 9) // 10]) / fsum(gains)
        if gains
        else None,
        reason=None if n >= 20 else "INSUFFICIENT_EVALUATION_SAMPLE",
    )


def quantities(y, scores, rows):
    valid = [i for i in rows if np.isfinite(y[i]) and np.isfinite(scores[i]).all()]
    n = {"all": len(valid)}
    overall = fsum(float(y[i]) for i in valid) / len(valid) if len(valid) >= 20 else None
    means = {}
    for m, model in enumerate(MODELS):
        selected = [i for i in valid if scores[i, m] > 0]
        n[model] = len(selected)
        means[model] = (
            fsum(float(y[i]) for i in selected) / len(selected) if len(selected) >= 20 else None
        )
    values = {}
    for model in MODELS:
        values[model + "_positive_mean"] = means[model]
        values[model + "_positive_minus_all"] = (
            means[model] - overall if means[model] is not None and overall is not None else None
        )
    for model, key in [
        ("confirmation_only", "joint_minus_confirmation_positive"),
        ("training_mean", "joint_minus_training_mean_positive"),
    ]:
        values[key] = (
            means["original14_joint"] - means[model]
            if means["original14_joint"] is not None and means[model] is not None
            else None
        )
    return values, n


def bootstrap(y, scores):
    original, original_n = quantities(y, scores, range(len(y)))
    blocks = full_axis_blocks(len(y))
    records = []
    for rep in range(500):
        values, n = (
            quantities(y, scores, blocks[rep])
            if blocks is not None
            else ({key: None for key in original}, {})
        )
        records.append(
            dict(
                replicate=rep,
                n=n,
                values=values,
                status={
                    key: "VALID" if value is not None else "INSUFFICIENT_REQUIRED_GROUP"
                    for key, value in values.items()
                },
            )
        )
    summary = {}
    for key, value in original.items():
        valid = [row["values"][key] for row in records if row["values"][key] is not None]
        ok = value is not None and len(valid) >= 400
        summary[key] = dict(
            original=value,
            valid_replicates=len(valid),
            ci95=linear_percentile(valid, [0.025, 0.975]) if ok else None,
            reason=None
            if ok
            else "INSUFFICIENT_ORIGINAL_GROUP"
            if value is None
            else "INSUFFICIENT_VALID_REPLICATES",
        )
    return dict(
        original_n=original_n,
        summary=summary,
        records=records,
        requested_replicates=500,
        shared_full_axis_sampling=True,
        refitted_models=0,
    )


def verify_statistics(features, labels, auxiliary, reported, prior14_records):
    axis = dates(features.index)
    if (
        not axis.equals(auxiliary.index)
        or auxiliary.dtype != bool
        or set(reported)
        != {
            "method",
            "method_sha256",
            "signal_n",
            "forecasts",
            "fit_years",
            "quality",
            "panels",
            "paired_mean_bootstrap",
            "accounts",
            "scientific_judgment",
            "old_baseline_MSE_is_not_new_evidence",
        }
    ):
        raise ValueError("fixed aligned causal Boolean mask/result schema required")
    method = reported["method"]
    if (
        method["features"] != list(FEATURES)
        or method["models"] != list(MODELS)
        or method["quantities"] != list(QUANTITIES)
        or sha256(json.dumps(method, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        != reported["method_sha256"]
    ):
        raise AssertionError("fixed method coordinates/hash")
    if (
        reported["signal_n"] != len(axis)
        or reported["accounts"] != 0
        or reported["old_baseline_MSE_is_not_new_evidence"] is not True
    ):
        raise AssertionError("calendar and zero-account role")
    scores, reasons, years = forecasts(features, labels)
    equivalent(reported["fit_years"], years, "fit_years")
    y = labels.return_4.to_numpy(float)
    expected_records = []
    for i, day in enumerate(axis):
        expected_records.append(
            dict(
                signal_date=day.isoformat(),
                original_axis_phase5=i % 5,
                target=float(y[i]) if np.isfinite(y[i]) else None,
                label_end=labels.label_end_return_4.iloc[i].isoformat()
                if pd.notna(labels.label_end_return_4.iloc[i])
                else None,
                truth_missing=not bool(np.isfinite(y[i])),
                feature_complete=bool(np.isfinite(features.iloc[i].to_numpy()).all()),
                forecast_unavailable_reason=reasons[i],
                confirmation_opportunity=bool(auxiliary.iloc[i]),
                scores={
                    model: float(scores[i, m]) if np.isfinite(scores[i, m]) else None
                    for m, model in enumerate(MODELS)
                },
            )
        )
    equivalent(reported["forecasts"], expected_records, "forecasts")
    source = {pd.Timestamp(row["signaldate"]): row for row in prior14_records}
    if len(source) != len(prior14_records):
        raise AssertionError("duplicate old records")
    expected_old = {
        day for i, day in enumerate(axis) if np.isfinite(y[i]) and np.isfinite(scores[i]).all()
    }
    if set(source) != expected_old:
        raise AssertionError("old records must exactly cover mature common OOS rows")
    # Numeric model reconstruction is independent; bit-exact reuse is separately
    # checked against actual published old records, not independent roundoff.
    for row in reported["forecasts"]:
        day = pd.Timestamp(row["signal_date"])
        if day in source:
            old = source[day]
            if (
                row["target"] != old["target"]
                or row["scores"]["original14_joint"] != old["prediction"]
                or row["scores"]["training_mean"] != old["baseline"]
            ):
                raise AssertionError("mature mean/joint records not reused EXACT")
    common = np.isfinite(y) & np.isfinite(scores).all(axis=1)
    quality = {
        model: metrics(y[common], scores[common, m], scores[common, 0])
        for m, model in enumerate(MODELS)
    }
    equivalent(reported["quality"], quality, "quality")
    masks = {
        "all": np.ones(len(axis), bool),
        **{"year_" + str(year): axis.year == year for year in range(2020, 2027)},
        **{"phase_" + str(phase): np.arange(len(axis)) % 5 == phase for phase in range(5)},
        "original_policy_flat_confirmation_opportunity": auxiliary.to_numpy(bool),
    }
    panels = {}
    for name, mask in masks.items():
        panels[name] = {}
        for m, model in enumerate(MODELS):
            p = scores[:, m]
            panels[name][model] = {
                "all": group(y, p, mask, np.ones(len(axis), bool)),
                "positive": group(y, p, mask, p > 0),
                "nonpositive": group(y, p, mask, p <= 0),
            }
            positive = panels[name][model]["positive"]
            positive["false_positive_n"] = positive["nonpositive_truth_n"]
            positive["false_positive_rate_among_positive_predictions"] = positive[
                "nonpositive_truth_rate"
            ]
    equivalent(reported["panels"], panels, "panels")
    equivalent(reported["paired_mean_bootstrap"], bootstrap(y, scores), "paired_mean_bootstrap")
    return dict(
        status="PASS",
        signal_n=len(axis),
        reconstructed_models=3,
        old_reused_records=len(source),
        bootstrap_replicates=500,
        bootstrap_quantities=8,
        bootstrap_values_checked=4000,
        new_accounts=0,
        scientific_judgment="NOT_MADE",
    )
