"""Independent scalar confirmation-policy arithmetic; in-memory, no IO."""

from math import fsum, sqrt
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


def original14(daily, native_prices, intraday, signals, confirmation_lookback=120):
    """Independent loops reproduce original feature definitions and missingness.

    daily: full original warm ADJUSTED OHLCV/Amount, DatetimeIndex.
    native_prices: native anchor+execution prices with Open/Close, DatetimeIndex.
    intraday: original execution30m only, Open/Close with intraday DatetimeIndex.
    signals: full native signalprefix (anchor included), not future execution grid.
    """
    signals, dayaxis = dates(signals), dates(daily.index)
    if type(confirmation_lookback) is not int or not 40 <= confirmation_lookback <= 120:
        raise ValueError("original confirmation domain40..120 required")
    needed = ["Open", "High", "Low", "Close", "Volume", "Amount"]
    a = daily[needed].to_numpy(float)
    if not np.isfinite(a).all() or (a <= 0).any() or (a[:, 1] <= a[:, 2]).any():
        raise ValueError("complete positive original adjusted OHLCVA required")
    close, volume, amount = a[:, 3], a[:, 4], a[:, 5]
    raw = np.full((len(dayaxis), 3), np.nan)
    daily_fields = pd.DataFrame(np.nan, index=dayaxis, columns=FEATURES)
    changes = np.r_[np.nan, close[1:] / close[:-1] - 1]
    logchanges = np.r_[np.nan, np.diff(np.log(volume))]
    for i in range(len(dayaxis)):
        daily_fields.iloc[i, daily_fields.columns.get_loc("intraday_return")] = (
            close[i] / a[i, 0] - 1
        )
        daily_fields.iloc[i, daily_fields.columns.get_loc("daily_close_location")] = (
            2 * close[i] - a[i, 1] - a[i, 2]
        ) / (a[i, 1] - a[i, 2])
        if i >= 19:
            mean_amount = fsum(float(v) for v in amount[i - 19 : i + 1]) / 20
            daily_fields.iloc[i, daily_fields.columns.get_loc("turnover20")] = (
                amount[i] / mean_amount
            )
            daily_fields.iloc[i, daily_fields.columns.get_loc("volume_ratio20")] = volume[i] / (
                fsum(float(v) for v in volume[i - 19 : i + 1]) / 20
            )
            raw[i, 1] = amount[i] / mean_amount
        if i >= 20:
            daily_fields.iloc[i, daily_fields.columns.get_loc("momentum20")] = (
                close[i] / close[i - 20] - 1
            )
            r = changes[i - 19 : i + 1]
            mean = fsum(float(v) for v in r) / 20
            centered = [float(v) - mean for v in r]
            variance = fsum(v * v for v in centered) / 20
            acf = (
                np.nan
                if np.isclose(variance, 0)
                else fsum(centered[j] * centered[j - 1] for j in range(1, 20)) / 19 / variance
            )
            raw[i, 0] = acf
            raw[i, 2] = fsum(float(v) for v in logchanges[i - 19 : i + 1]) / 20
            daily_fields.iloc[i, daily_fields.columns.get_loc("acf1")] = acf
            daily_fields.iloc[i, daily_fields.columns.get_loc("volatility20")] = sqrt(
                fsum(v * v for v in centered) / 19
            )
        if i >= 59:
            low = float(min(a[i - 59 : i + 1, 2]))
            high = float(max(a[i - 59 : i + 1, 1]))
            daily_fields.iloc[i, daily_fields.columns.get_loc("range_position60")] = (
                (close[i] - low) / (high - low) if high > low else np.nan
            )
        if i >= confirmation_lookback - 1:
            window = raw[i - confirmation_lookback + 1 : i + 1]
            if np.isfinite(window).all():
                rank = []
                for col in range(3):
                    current = float(raw[i, col])
                    values = window[:, col]
                    rank.append(
                        (sum(v < current for v in values) + 0.5 * sum(v == current for v in values))
                        / confirmation_lookback
                        - 0.5
                    )
                daily_fields.iloc[i, daily_fields.columns.get_loc("confirmation_score")] = (
                    0.5 * rank[0] + 0.25 * rank[1] + 0.25 * rank[2]
                )
    prices = native_prices[["Open", "Close"]].to_numpy(float)
    priceaxis = dates(native_prices.index)
    gaps = np.r_[np.nan, np.log(prices[1:, 0] / prices[:-1, 1])]
    body = np.log(prices[:, 1] / prices[:, 0])
    overnight = pd.DataFrame(
        np.nan,
        index=priceaxis,
        columns=["overnight_gap", "intraday_rms20", "feature_overnight_down_energy20"],
    )
    overnight["overnight_gap"] = gaps
    for i in range(19, len(priceaxis)):
        overnight.iloc[i, 1] = sqrt(fsum(float(v) ** 2 for v in body[i - 19 : i + 1]) / 20)
        if i >= 20:
            overnight.iloc[i, 2] = sqrt(
                fsum(min(float(v), 0) ** 2 for v in gaps[i - 19 : i + 1]) / 20
            )
    if (
        not isinstance(intraday.index, pd.DatetimeIndex)
        or intraday.index.tz is not None
        or intraday.index.has_duplicates
        or not intraday.index.is_monotonic_increasing
    ):
        raise ValueError("ordered original intraday axis required")
    energies = []
    for day, group in intraday.groupby(intraday.index.normalize(), sort=True):
        if len(group) != 8 or list(group.index.strftime("%H:%M")) != [
            "10:00",
            "10:30",
            "11:00",
            "11:30",
            "13:30",
            "14:00",
            "14:30",
            "15:00",
        ]:
            raise ValueError("original complete8 observed bars required")
        ref = float(group.Open.iloc[0])
        total = []
        down = []
        for c in group.Close:
            r = float(np.log(float(c) / ref))
            total.append(r * r)
            down.append(min(r, 0) ** 2)
            ref = float(c)
        energies.append((day, fsum(total), fsum(down)))
    energy = pd.DataFrame(energies, columns=["day", "total", "down"]).set_index("day")
    ef = pd.DataFrame(
        np.nan, index=energy.index, columns=["intraday_energy20", "feature_intraday_down_energy20"]
    )
    for i in range(19, len(energy)):
        total = fsum(float(v) for v in energy.total.iloc[i - 19 : i + 1])
        if total <= 0:
            raise ValueError("zero energy denominator prohibited by original definition")
        ef.iloc[i, 0] = sqrt(total / 20)
        ef.iloc[i, 1] = fsum(float(v) for v in energy.down.iloc[i - 19 : i + 1]) / total
    result = daily_fields.reindex(signals)
    for name in overnight:
        result[name] = overnight[name].reindex(signals)
    for name in ef:
        result[name] = ef[name].reindex(signals)
    return result.loc[:, list(FEATURES)]


def scalar_forecasts(features, native_prices, signals, horizon=4, alpha=10.0):
    """Annual one-variable ridge via centered scalar covariance, no main kernel."""
    signals = dates(signals)
    if (
        type(horizon) is not int
        or not 1 <= horizon <= 60
        or type(alpha) is not float
        or not 1 <= alpha <= 100
    ):
        raise ValueError("fixed declared horizon/ridge domain required")
    # Derive historical maturity with the horizon, not precomputed forecasts.
    prices = native_prices.Open.to_numpy(float)
    positions = {day: i for i, day in enumerate(native_prices.index)}
    y = np.full(len(signals), np.nan)
    ends = [pd.NaT] * len(signals)
    for i, day in enumerate(signals):
        p = positions[day]
        if p + horizon + 1 < len(prices):
            y[i] = float(prices[p + horizon + 1]) / float(prices[p + 1]) * (0.999 / 1.001) - 1
            ends[i] = native_prices.index[p + horizon + 1]
    x = features.confirmation_score.to_numpy(float)
    complete = np.isfinite(features.loc[:, list(FEATURES)].to_numpy(float)).all(axis=1)
    scores = np.full(len(signals), np.nan)
    years = {}
    for year in range(2021, 2027):
        yearrows = [i for i, day in enumerate(signals) if day.year == year]
        if not yearrows:
            continue
        first = signals[yearrows[0]]
        train = [
            i
            for i, day in enumerate(signals)
            if 2020 <= day.year < year and complete[i] and np.isfinite(y[i]) and ends[i] < first
        ]
        years[str(year)] = dict(
            first_signal=first.isoformat(),
            train_dates=[signals[i].isoformat() for i in train],
            train_n=len(train),
            max_maturity=max(ends[i] for i in train).isoformat() if train else None,
            available=len(train) >= 40,
            future_test_count_gate=False,
        )
        if len(train) < 40:
            continue
        z = empirical_transform(x[train], x[train])
        meanx = fsum(float(v) for v in z) / len(train)
        meany = fsum(float(y[i]) for i in train) / len(train)
        numerator = fsum((float(z[j]) - meanx) * (float(y[i]) - meany) for j, i in enumerate(train))
        denominator = fsum((float(v) - meanx) ** 2 for v in z) + alpha
        for i in yearrows:
            if complete[i]:
                rank = float(empirical_transform(x[train], np.array([x[i]]))[0])
                scores[i] = meany + (rank - meanx) * numerator / denominator
    return pd.Series(scores, index=signals, name="net_forecast"), years


def episodes(scores, horizon=4):
    """Fixed signal clock, no fill state or expiry extension."""
    axis = dates(scores.index)
    if type(horizon) is not int or not 1 <= horizon <= 60 or np.isinf(scores.to_numpy(float)).any():
        raise ValueError("finite-or-unavailable scores and legal clock required")
    entry = None
    rows = []
    for i, day in enumerate(axis):
        if entry is not None:
            age = i - entry
            target = 0 if age >= horizon else 1
            reason = "expiry" if target == 0 else "hold"
            if not target:
                entry = None
        elif day.year < 2021:
            age = np.nan
            target = 0
            reason = "flat"
        elif np.isfinite(scores.iloc[i]) and scores.iloc[i] > 0:
            entry = i
            age = 0
            target = 1
            reason = "entry"
        else:
            age = np.nan
            target = 0
            reason = "flat"
        rows.append(
            (
                float(target),
                reason,
                age,
                entry,
                bool(np.isfinite(scores.iloc[i]) and scores.iloc[i] > 0),
                scores.iloc[i],
            )
        )
    return pd.DataFrame(
        rows,
        index=axis,
        columns=[
            "target_position",
            "signal_reason",
            "policy_age",
            "episode_entry_position",
            "positive_forecast",
            "net_forecast",
        ],
    )


def verify(
    daily,
    native_prices,
    intraday,
    signals,
    reported_features,
    reported_scores,
    reported_fit,
    reported_history,
    confirmation_lookback=120,
    holding_sessions=4,
    ridge_alpha=10.0,
):
    features = original14(daily, native_prices, intraday, signals, confirmation_lookback)
    if (
        not features.index.equals(reported_features.index)
        or tuple(reported_features.columns) != FEATURES
    ):
        raise AssertionError("full signalprefix and original14 fields required")
    np.testing.assert_allclose(
        reported_features.to_numpy(float),
        features.to_numpy(float),
        atol=2e-11,
        rtol=2e-10,
        equal_nan=True,
    )
    np.testing.assert_array_equal(
        np.isfinite(reported_features.to_numpy(float)), np.isfinite(features.to_numpy(float))
    )
    scores, fit = scalar_forecasts(features, native_prices, signals, holding_sessions, ridge_alpha)
    np.testing.assert_allclose(reported_scores, scores, atol=2e-12, rtol=2e-10, equal_nan=True)
    np.testing.assert_array_equal(reported_scores.to_numpy() > 0, scores.to_numpy() > 0)
    equivalent(reported_fit, fit, "year_fit")
    expected = episodes(scores, holding_sessions)
    if not expected.index.equals(reported_history.index):
        raise AssertionError("native decision-prefix changed")
    for name in expected:
        if name == "net_forecast":
            np.testing.assert_allclose(
                reported_history[name], expected[name], atol=2e-12, rtol=2e-10, equal_nan=True
            )
        else:
            pd.testing.assert_series_equal(
                reported_history[name], expected[name], check_names=False, check_dtype=False
            )
    return dict(
        status="PASS",
        signals=len(signals),
        feature_numeric_checks=len(signals) * 14,
        strict_masks_and_positive_flags="EXACT",
        annual_fits=len(fit),
        policy_all_fields="EXACT",
        new_accounts=0,
    )
