"""Independent scalar fixed-depth CART and yearly causal forecast audit."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
import math

import numpy as np
import pandas as pd

FEATURES = (
    "momentum20", "range_position60", "acf1", "volatility20", "intraday_return",
    "overnight_gap", "intraday_energy20", "intraday_rms20", "confirmation_score",
    "daily_close_location", "feature_intraday_down_energy20", "feature_overnight_down_energy20",
    "turnover20", "volume_ratio20",
)
QUANTILES = (.25, .5, .75)


def cdf(sorted_train, value):
    return (bisect_left(sorted_train, value) + bisect_right(sorted_train, value))/(2*len(sorted_train))-.5


def moments(target, positions):
    average = math.fsum(float(target[i]) for i in positions)/len(positions)
    sse = math.fsum((float(target[i])-average)**2 for i in positions)
    return average, sse


def parameters(max_depth, minimum_leaf):
    if type(max_depth) is not int or not 1 <= max_depth <= 4:
        raise ValueError("integer tree depth1..4 required")
    if type(minimum_leaf) is not int or not 20 <= minimum_leaf <= 120:
        raise ValueError("integer leaf count20..120 required")


def fit_scalar(ranked_train, target, *, max_depth=2, minimum_leaf=40):
    """Enumerate feature-order x quantile-order splits without primary imports.

    Greedy strict SSE improvement cannot discover a perfectly symmetric XOR
    whose root candidates give no improvement. No two-level lookahead is used.
    """
    parameters(max_depth, minimum_leaf)
    x = np.asarray(ranked_train, dtype=float)
    y = np.asarray(target, dtype=float)
    if x.ndim != 2 or x.shape[1] != 14 or y.shape != (len(x),) or len(x) < max(40, minimum_leaf):
        raise ValueError("N>=max(40,minimum_leaf) x14 training and paired target required")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("finite ranked features and target required")

    def node(positions, depth):
        mean, sse = moments(y, positions)
        result = {"depth": depth, "positions": positions, "n": len(positions),
                  "mean": mean, "sse": sse, "leaf": True,
                  "reason": "DEPTH_LIMIT" if depth == max_depth else "NO_STRICT_SSE_IMPROVEMENT",
                  "feature_index": None, "feature_name": None, "quantile": None,
                  "threshold": None, "split_sse": None, "gain": None,
                  "candidates": [], "left": None, "right": None}
        if depth == max_depth:
            return result
        best, best_sse = None, sse
        for feature in range(14):
            ordered = sorted(float(x[i, feature]) for i in positions)
            for quantile in QUANTILES:
                index = math.ceil(len(positions)*quantile)-1
                threshold = ordered[index]
                left = [i for i in positions if float(x[i, feature]) <= threshold]
                right = [i for i in positions if float(x[i, feature]) > threshold]
                valid = len(left) >= minimum_leaf and len(right) >= minimum_leaf
                split_sse = left_sse = right_sse = None
                if valid:
                    left_sse, right_sse = moments(y, left)[1], moments(y, right)[1]
                    split_sse = math.fsum([left_sse, right_sse])
                    if split_sse < best_sse:
                        best = (feature, quantile, threshold, left, right)
                        best_sse = split_sse
                result["candidates"].append({
                    "feature_index": feature, "feature_name": FEATURES[feature],
                    "quantile": quantile, "orderstat_position": index,
                    "threshold": threshold, "valid": valid,
                    "left_n": len(left), "right_n": len(right), "split_sse": split_sse,
                    "left_sse": left_sse, "right_sse": right_sse,
                })
        if best is None:
            return result
        feature, quantile, threshold, left, right = best
        result.update({
            "leaf": False, "reason": "STRICT_SSE_IMPROVEMENT", "feature_index": feature,
            "feature_name": FEATURES[feature], "quantile": quantile,
            "threshold": threshold, "split_sse": best_sse, "gain": sse-best_sse,
            "left": node(left, depth+1), "right": node(right, depth+1),
        })
        return result
    return node(list(range(len(x))), 0)


def prediction(tree, ranked_test):
    x = np.asarray(ranked_test, dtype=float)
    if x.ndim != 2 or x.shape[1] != 14 or not np.isfinite(x).all():
        raise ValueError("finite x14 test features required")
    values = []
    for row in x:
        node = tree
        while not node["leaf"]:
            node = node["left"] if float(row[node["feature_index"]]) <= node["threshold"] else node["right"]
        values.append(node["mean"])
    return np.asarray(values, dtype=float)


def compare_tree(expected, actual, path="root"):
    """Audit every node and candidate rather than just final fitted leaf means."""
    if not isinstance(actual, dict):
        raise ValueError("tree node must be a dict: " + path)
    if set(actual) != set(expected):
        raise ValueError("tree node schema mismatch: " + path)
    checked = 0
    for key, value in expected.items():
        other = actual[key]
        if key in ("left", "right") and value is not None:
            checked += compare_tree(value, other, path+"."+key)
        elif key == "candidates":
            if not isinstance(other, list) or len(other) != len(value):
                raise ValueError("all threshold candidates required: " + path)
            for i, (candidate, reported) in enumerate(zip(value, other)):
                checked += compare_tree(candidate, reported, path+f".candidate{i}")
        elif isinstance(value, float):
            if not isinstance(other, (int, float)) or not math.isfinite(other) or not math.isclose(value, other, rel_tol=0, abs_tol=1e-12):
                raise ValueError("tree floating mismatch: " + path+"."+key)
            checked += 1
        elif value != other:
            raise ValueError("tree exact mismatch: " + path+"."+key)
        else:
            checked += 1
    return checked


def _axis(index):
    if (
        not isinstance(index, pd.DatetimeIndex) or len(index) == 0 or index.tz is not None
        or index.hasnans or index.has_duplicates or not index.is_monotonic_increasing
        or not index.equals(index.normalize())
    ):
        raise ValueError("nonempty unique ordered naive midnight axis required")


def verify(features, labels, scores, traces, *, max_depth=2, minimum_leaf=40):
    """Rebuild past-year CDFs, all tree nodes, predictions and positive flags."""
    parameters(max_depth, minimum_leaf)
    if not isinstance(features, pd.DataFrame):
        raise ValueError("feature DataFrame required")
    axis = features.index
    _axis(axis)
    if not isinstance(labels, pd.DataFrame) or labels.columns.has_duplicates or not {"return_4", "label_end_return_4"}.issubset(labels.columns) or tuple(features.columns) != FEATURES or not labels.index.equals(axis):
        raise ValueError("exact14 features and paired labels required")
    if not isinstance(scores, pd.DataFrame) or not scores.index.equals(axis) or tuple(scores.columns) != ("training_mean", "cart_net"):
        raise ValueError("two exact forecast fields and shared axis required")
    x = features.to_numpy(float)
    y = labels.return_4.to_numpy(float)
    ends = pd.to_datetime(labels.label_end_return_4)
    if ends.dt.tz is not None or not ends.equals(ends.dt.normalize()):
        raise ValueError("naive midnight maturity dates required")
    if np.isinf(x).any() or np.isinf(y).any() or not np.array_equal(np.isfinite(y), ends.notna()):
        raise ValueError("finite/missing observations with paired maturity required")
    if any(v <= -1 or pd.Timestamp(e) <= t for t, e, v in zip(axis, ends, y) if math.isfinite(v)):
        raise ValueError("truth must mature strictly after its signal")
    complete = [bool(np.isfinite(row).all()) for row in x]
    expected_scores = np.full((len(axis), 2), np.nan)
    years = list(range(2021, 2027))
    if not isinstance(traces, list) or len(traces) != len(years) or any(not isinstance(t, dict) for t in traces):
        raise ValueError("one trace for each forecast year required")
    tree_fields = cdf_values = forecast_values = 0
    for year, trace in zip(years, traces):
        first = next((day for day in axis if day.year == year), None)
        train = [i for i, day in enumerate(axis) if first is not None and complete[i] and math.isfinite(y[i]) and 2020 <= day.year < year and pd.Timestamp(ends.iloc[i]) < first]
        test = [i for i, day in enumerate(axis) if complete[i] and day.year == year]
        expected_meta = {
            "year": year, "first_test": first.isoformat() if first is not None else None,
            "train_positions": train, "test_positions": test, "train_n": len(train),
            "future_test_count_gate": False,
            "max_maturity": max(pd.Timestamp(ends.iloc[i]) for i in train).isoformat() if train else None,
            "max_depth": max_depth, "minimum_leaf": minimum_leaf,
            "reason": "NO_YEAR" if first is None else "INSUFFICIENT_MATURE_TRAINING" if len(train) < max(40, minimum_leaf) else None,
        }
        if set(trace) != set(expected_meta) | {"train_cdfs", "tree"} or any(trace[key] != value for key, value in expected_meta.items()):
            raise ValueError("causal annual train/test support mismatch")
        available = first is not None and len(train) >= max(40, minimum_leaf)
        if available:
            ordered = [sorted(float(x[i, j]) for i in train) for j in range(14)]
            if trace["train_cdfs"] != ordered:
                raise ValueError("training-only CDF values differ")
            cdf_values += sum(len(values) for values in ordered)
            tx = np.asarray([[cdf(ordered[j], float(x[i, j])) for j in range(14)] for i in train])
            vx = np.asarray([[cdf(ordered[j], float(x[i, j])) for j in range(14)] for i in test]).reshape(len(test), 14)
            tree = fit_scalar(tx, y[train], max_depth=max_depth, minimum_leaf=minimum_leaf)
            tree_fields += compare_tree(tree, trace["tree"])
            mean = math.fsum(float(y[i]) for i in train)/len(train)
            pred = prediction(tree, vx)
            expected_scores[test, 0], expected_scores[test, 1] = mean, pred
            forecast_values += len(test)*2
        elif trace["tree"] is not None or trace["train_cdfs"] is not None:
            raise ValueError("unavailable model must not contain a fallback tree/CDF")
    actual = scores.to_numpy(float)
    if not np.array_equal(np.isnan(actual), np.isnan(expected_scores)) or not np.isfinite(actual[~np.isnan(actual)]).all():
        raise ValueError("forecast unavailable masks mismatch")
    if not np.allclose(actual, expected_scores, rtol=0, atol=1e-12, equal_nan=True):
        raise ValueError("scalar CART/prior forecasts differ")
    if not np.array_equal(actual > 0, expected_scores > 0):
        raise ValueError("strict positive-selection flags differ")
    return {"status": "PASS", "annual_traces": len(years), "tree_fields": tree_fields,
            "cdf_training_values": cdf_values, "forecast_values": forecast_values,
            "all_score_cells": actual.size, "positive_flags_exact": True,
            "scope": "independent scalar CDF, all candidate thresholds/SSE, greedy depth2 tree and causal predictions"}
