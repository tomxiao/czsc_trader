"""Pure supplied-frame authentication. No market/provider/cache/publication IO."""

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


def dates(index):
    if (
        not isinstance(index, pd.DatetimeIndex)
        or index.tz is not None
        or index.hasnans
        or index.has_duplicates
        or not index.is_monotonic_increasing
        or not index.equals(index.normalize())
    ):
        raise ValueError("ordered unique timezone-naive midnight dates required")
    unit = np.datetime_data(index.dtype)[0]
    canonical = index.as_unit("ns")
    pd.testing.assert_index_equal(canonical.as_unit(unit), index, exact=True)
    return canonical


def validate(features, labels, auxiliary):
    axis = dates(features.index)
    if (
        features.columns.has_duplicates
        or labels.columns.has_duplicates
        or not dates(labels.index).equals(axis)
    ):
        raise ValueError("aligned unique feature/label columns required")
    if set(FEATURES) - set(features.columns) or not {"return_4", "label_end_return_4"} <= set(
        labels.columns
    ):
        raise ValueError("original14 and fixedh4 net label/maturity required")
    if any(str(n).startswith("label_end_") or n == "return_4" for n in features.columns):
        raise ValueError("future labels forbidden from features")
    x = features.loc[:, list(FEATURES)].astype(float).set_axis(axis)
    if np.isinf(x.to_numpy()).any():
        raise ValueError("infinite features prohibited")
    y = labels.loc[:, ["return_4", "label_end_return_4"]].copy().set_axis(axis)
    y["return_4"] = pd.to_numeric(y.return_4, errors="raise")
    ends = pd.to_datetime(y.label_end_return_4, errors="raise")
    if getattr(ends.dt, "tz", None) is not None:
        raise ValueError("timezone-naive maturity required")
    unit = np.datetime_data(ends.dtype)[0]
    canonical = ends.dt.as_unit("ns")
    pd.testing.assert_series_equal(canonical.dt.as_unit(unit), ends, check_exact=True)
    y["label_end_return_4"] = canonical
    finite = np.isfinite(y.return_4.to_numpy(float))
    if (
        np.isinf(y.return_4.to_numpy(float)).any()
        or not np.array_equal(finite, canonical.notna().to_numpy())
        or (canonical[finite] <= axis[finite]).any()
    ):
        raise ValueError("paired finite target/future maturity or NaN/NaT tail required")
    if (
        not isinstance(auxiliary, pd.Series)
        or not dates(auxiliary.index).equals(axis)
        or not pd.api.types.is_bool_dtype(auxiliary.dtype)
        or auxiliary.isna().any()
    ):
        raise ValueError("aligned causal nonnull confirmation_opportunity mask required")
    return x, y, auxiliary.set_axis(axis).astype(bool)


def construct(old_features, old_labels, confirmation_opportunity):
    x, y, aux = validate(old_features, old_labels, confirmation_opportunity)
    if (
        len(x) != 1635
        or x.index[0] != pd.Timestamp("2020-01-02")
        or x.index[-1] != pd.Timestamp("2026-09-29")
    ):
        raise ValueError("exact original1635T axis required; full calendar认证由root输入证据绑定")
    return (
        x,
        y,
        aux,
        {
            "signal_n": 1635,
            "features": list(FEATURES),
            "feature_complete_n": int(x.notna().all(axis=1).sum()),
            "label_valid_n": int(y.return_4.notna().sum()),
            "forecast_does_not_use_future_label": True,
            "auxiliary_never_selects_training": True,
        },
    )
