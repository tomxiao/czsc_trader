"""Independent recomputation of published rank/DF, maturity and prediction MSE."""

import numpy as np
import pandas as pd
from scipy.stats import rankdata, spearmanr
import opportunity_statistics as stats


def verify_statistics(features, labels, scopes, result):
    checks = 0
    for scope, panel in result["scopes"].items():
        mask = scopes[scope].to_numpy(bool)
        assert panel["eligible_n"] == int(mask.sum())
        for label, block in panel["labels"].items():
            ends = pd.to_datetime(labels["label_end_" + label])
            for component, reported in block["components"].items():
                good = mask & np.isfinite(features[component]) & np.isfinite(labels[label])
                x, y = features.loc[good, component].to_numpy(), labels.loc[good, label].to_numpy()
                assert reported["spearman"]["n"] == len(x)
                if len(x) >= 20 and np.ptp(x) > 0 and np.ptp(y) > 0:
                    np.testing.assert_allclose(
                        reported["spearman"]["value"], spearmanr(x, y).statistic, rtol=0, atol=1e-13
                    )
                checks += 1
                controls = features.loc[:, stats.CONTROLS]
                partial_good = good & np.isfinite(controls).all(axis=1)
                x, y = (
                    features.loc[partial_good, component].to_numpy(),
                    labels.loc[partial_good, label].to_numpy(),
                )
                assert reported["partial_rank_ic"]["n"] == len(x)
                partial = reported["partial_rank_ic"]
                design_check = np.column_stack(
                    [
                        np.ones(len(x)),
                        *(rankdata(v) for v in controls.loc[partial_good].to_numpy().T),
                    ]
                )
                rank = int(np.linalg.matrix_rank(design_check)) if len(x) else 0
                assert partial["design_rank"] == rank and partial["residual_df"] == len(x) - rank
                if len(x) - rank < 10:
                    assert (
                        partial["value"] is None and partial["reason"] == "INSUFFICIENT_RESIDUAL_DF"
                    )
                if len(x) >= 20 and np.ptp(x) > 0 and np.ptp(y) > 0:
                    xr, yr = rankdata(x), rankdata(y)
                    design = np.column_stack(
                        [
                            np.ones(len(x)),
                            *(rankdata(v) for v in controls.loc[partial_good].to_numpy().T),
                        ]
                    )
                    xr -= design @ np.linalg.lstsq(design, xr, rcond=None)[0]
                    yr -= design @ np.linalg.lstsq(design, yr, rcond=None)[0]
                    if reported["partial_rank_ic"]["value"] is not None:
                        np.testing.assert_allclose(
                            reported["partial_rank_ic"]["value"],
                            np.corrcoef(xr, yr)[0, 1],
                            rtol=0,
                            atol=1e-12,
                        )
                checks += 1
            finite = (
                np.isfinite(features).all(axis=1).to_numpy() & np.isfinite(labels[label]).to_numpy()
            )
            for year, row in block["walk_forward"]["yearly"].items():
                first = features.index[features.index.year == int(year)][0]
                train = (
                    mask
                    & finite
                    & (features.index.year >= 2020)
                    & (features.index.year < int(year))
                    & (ends < first).to_numpy()
                )
                test = mask & finite & (features.index.year == int(year))
                assert row["common_train_n"] == int(train.sum()) and row["common_test_n"] == int(
                    test.sum()
                )
                if row["latest_train_label_end"] is not None:
                    assert pd.Timestamp(row["latest_train_label_end"]) == ends[train].max() < first
                checks += 1
            for model, records in block["walk_forward"]["prediction_records"].items():
                dates = pd.DatetimeIndex(pd.to_datetime([v["signaldate"] for v in records]))
                truth = np.array([v["target"] for v in records])
                predicted = np.array([v["prediction"] for v in records])
                baseline = np.array([v["baseline"] for v in records])
                for year in np.unique(dates.year):
                    first = features.index[features.index.year == year][0]
                    train = (
                        mask
                        & finite
                        & (features.index.year >= 2020)
                        & (features.index.year < year)
                        & (ends < first).to_numpy()
                    )
                    np.testing.assert_allclose(
                        baseline[dates.year == year],
                        labels.loc[train, label].mean(),
                        rtol=0,
                        atol=1e-15,
                    )
                    checks += 1
                np.testing.assert_array_equal(truth, labels.loc[dates, label].to_numpy())
                aggregate = block["walk_forward"]["aggregate_models"][model]
                assert aggregate["n"] == len(records)
                if len(records) >= 20:
                    np.testing.assert_allclose(
                        aggregate["mse"], np.mean((truth - predicted) ** 2), rtol=0, atol=1e-15
                    )
                    np.testing.assert_allclose(
                        aggregate["baseline_mse"],
                        np.mean((truth - baseline) ** 2),
                        rtol=0,
                        atol=1e-15,
                    )
                    np.testing.assert_allclose(
                        aggregate["mse_improvement"],
                        aggregate["baseline_mse"] - aggregate["mse"],
                        rtol=0,
                        atol=1e-15,
                    )
                checks += 1
    # Independently verify DF metadata for every year and every nonoverlapping phase.
    for scope, panel in result["scopes"].items():
        scope_mask = scopes[scope].to_numpy(bool)
        for label, block in panel["labels"].items():
            for component, reported in block["components"].items():
                for category in ("yearly", "nonoverlap_phases"):
                    for key, row in reported[category].items():
                        submask = scope_mask & (
                            (features.index.year == int(key))
                            if category == "yearly"
                            else (
                                np.arange(len(features)) % (stats.HORIZONS[label] + 1) == int(key)
                            )
                        )
                        valid = (
                            submask
                            & np.isfinite(features[component])
                            & np.isfinite(labels[label])
                            & np.isfinite(features.loc[:, stats.CONTROLS]).all(axis=1)
                        )
                        values = features.loc[valid, stats.CONTROLS].to_numpy()
                        design = np.column_stack(
                            [np.ones(len(values)), *(rankdata(v) for v in values.T)]
                        )
                        rank = int(np.linalg.matrix_rank(design)) if len(values) else 0
                        observed = row["partial_rank_ic"]
                        assert (
                            observed["n"] == len(values)
                            and observed["design_rank"] == rank
                            and observed["residual_df"] == len(values) - rank
                        )
                        if len(values) - rank < 10:
                            assert (
                                observed["value"] is None
                                and observed["reason"] == "INSUFFICIENT_RESIDUAL_DF"
                            )
                        checks += 1
    return checks
