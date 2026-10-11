"""Pure EX080 causal features, annual forecast and signal episode; no IO."""

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
NUMERIC_SOURCE = "research/S013/experiments/EX066_20261011/src/opportunity_statistics.py"
NUMERIC_SHA = "565db5bb8e50a49ce303e10c0e0f44eab4f707e8f8c6eed0ec19f528c7b94d9a"
CLOCKS = ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")


def parameters(confirmation_lookback=120, holding_sessions=4, ridge_alpha=10.0):
    if type(confirmation_lookback) is not int or not 40 <= confirmation_lookback <= 120:
        raise ValueError("confirmation lookback full domain40..120")
    if type(holding_sessions) is not int or not 1 <= holding_sessions <= 60:
        raise ValueError("holding horizon full domain1..60")
    if (
        type(ridge_alpha) is not float
        or not np.isfinite(ridge_alpha)
        or not 1 <= ridge_alpha <= 100
    ):
        raise ValueError("ridge alpha float full domain1..100")


def dates(values, daily=True):
    axis = pd.DatetimeIndex(pd.to_datetime(values, errors="raise"))
    original = axis
    axis = axis.as_unit("ns")
    pd.testing.assert_index_equal(axis.as_unit(original.unit), original, exact=True)
    if (
        axis.tz is not None
        or axis.hasnans
        or not axis.is_unique
        or not axis.is_monotonic_increasing
    ):
        raise ValueError("unique ordered naive dates required")
    if daily and not axis.equals(axis.normalize()):
        raise ValueError("actual daily timestamps required; no normalize repair")
    return axis


def frame(value, intraday=False):
    names = ("Date", "Open", "High", "Low", "Close", "Volume", "Amount")
    if not set(names).issubset(value.columns):
        raise ValueError("explicit original uppercase OHLCVA schema")
    out = pd.DataFrame(value, copy=False).loc[:, names].copy()
    out.index = dates(out.pop("Date"), daily=not intraday)
    out = out.astype(float)
    if not np.isfinite(out.to_numpy()).all() or (out.to_numpy() <= 0).any():
        raise ValueError("finite positive complete admitted prices/volume/amount required")
    return out


def acf(values):
    centered = values - values.mean()
    variance = np.mean(centered**2)
    return (
        np.nan
        if np.isclose(variance, 0)
        else float(np.dot(centered[1:], centered[:-1]) / 19 / variance)
    )


def causal_rank(values, window):
    def last(items):
        current = items[-1]
        return float(
            (np.count_nonzero(items < current) + 0.5 * np.count_nonzero(items == current))
            / len(items)
            - 0.5
        )

    return values.rolling(window, min_periods=window).apply(last, raw=True)


def rebuild(daily, native_daily, intraday, signals, confirmation_lookback=120):
    """ADJUSTED Volume exactly original C8880;2019 daily warms only daily features.

    Native/intraday requests may include final execution day; explicitly restrict
    all consumed price observations to latest signal. First intraday session is
    original first execution session, never2019, preserving first19missing.
    """
    parameters(confirmation_lookback)
    axis = dates(signals)
    d = frame(daily)
    n = frame(native_daily)
    bars = frame(intraday, True)
    d = d.loc[d.index <= axis[-1]]
    n = n.loc[(n.index >= axis[0]) & (n.index <= axis[-1])]
    bars = bars.loc[(bars.index.normalize() > axis[0]) & (bars.index.normalize() <= axis[-1])]
    if not n.index.equals(axis) or not axis.isin(d.index).all():
        raise ValueError("complete native decision-prefix prices required")
    c = d.Close
    change = c.pct_change(fill_method=None)
    f = pd.DataFrame(index=d.index)
    f["momentum20"] = c / c.shift(20) - 1
    f["range_position60"] = (c - d.Low.rolling(60).min()) / (
        d.High.rolling(60).max() - d.Low.rolling(60).min()
    )
    f["acf1"] = change.rolling(20).apply(acf, raw=True)
    f["volatility20"] = change.rolling(20).std(ddof=1)
    f["intraday_return"] = c / d.Open - 1
    raw = pd.DataFrame(
        {
            "acf": f.acf1,
            "turnover": d.Amount / d.Amount.rolling(20).mean(),
            "volume": np.log(d.Volume).diff().rolling(20).mean(),
        },
        index=d.index,
    )
    norm = raw.apply(lambda v: causal_rank(v, confirmation_lookback))
    f["confirmation_score"] = 0.5 * norm.acf + 0.25 * norm.turnover + 0.25 * norm.volume
    f["daily_close_location"] = (2 * c - d.High - d.Low) / (d.High - d.Low)
    f["turnover20"] = d.Amount / d.Amount.rolling(20).mean()
    f["volume_ratio20"] = d.Volume / d.Volume.rolling(20).mean()
    # Original EX060 native daily starts at anchor; no old2019 gap warmup.
    gaps = np.log(n.Open / n.Close.shift(1))
    intraday_change = np.log(n.Close / n.Open)
    f = f.reindex(axis)
    f["overnight_gap"] = gaps
    f["intraday_rms20"] = intraday_change.pow(2).rolling(20, min_periods=20).mean().pow(0.5)
    f["feature_overnight_down_energy20"] = (
        np.minimum(gaps, 0).pow(2).rolling(20, min_periods=20).mean().pow(0.5)
    )
    rows = []
    for day, b in bars.groupby(bars.index.normalize(), sort=True):
        if tuple(b.index.strftime("%H:%M")) != CLOCKS:
            raise ValueError("exact eight completed original30m clocks required")
        ref = np.concatenate(([b.Open.iloc[0]], b.Close.to_numpy()[:-1]))
        changes = np.log(b.Close.to_numpy() / ref)
        rows.append(
            (
                day,
                float(np.dot(np.minimum(changes, 0), np.minimum(changes, 0))),
                float(np.dot(changes, changes)),
            )
        )
    energies = pd.DataFrame(rows, columns=["Date", "down", "total"]).set_index("Date")
    if not energies.index.equals(axis[1:]):
        raise ValueError("original no2019 intraday session axis required")
    denominator = energies.total.rolling(20, min_periods=20).sum()
    if (denominator.dropna() <= 0).any():
        raise ValueError("zero twenty-session intraday denominator, no fallback")
    f["feature_intraday_down_energy20"] = (
        energies.down.rolling(20, min_periods=20).sum() / denominator
    )
    f["intraday_energy20"] = energies.total.rolling(20, min_periods=20).mean().pow(0.5)
    return f.loc[:, FEATURES]


def _cdf_apply(train: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Training empirical CDF midpoint ties; test extremes map exactly to 0/1."""
    ordered = np.sort(train)
    return (
        np.searchsorted(ordered, values, side="left")
        + np.searchsorted(ordered, values, side="right")
    ) / (2.0 * len(train))


def _ridge_predict(train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray) -> np.ndarray:
    mean_x, mean_y = train_x.mean(axis=0), float(train_y.mean())
    centered = train_x - mean_x
    slopes = np.linalg.solve(
        centered.T @ centered + 10.0 * np.eye(train_x.shape[1]), centered.T @ (train_y - mean_y)
    )
    return mean_y + (test_x - mean_x) @ slopes


def annual_forecasts(features, prices, signals, holding_sessions=4, ridge_alpha=10.0):
    """Predict by history alone, no future test-count/target gate.

    Annual intercept/ECDF trained once using only labels mature strictly before
    that year's first decision. Native fullprefix anchor excluded fromtrain.
    """
    parameters(holding_sessions=holding_sessions, ridge_alpha=ridge_alpha)
    axis = dates(signals)
    if not features.index.equals(axis) or not axis.isin(prices.index).all():
        raise ValueError("aligned features/prices/signals required")
    x = features.loc[:, FEATURES].to_numpy(float)
    if np.isinf(x).any():
        raise ValueError("infinite original feature")
    complete = np.isfinite(x).all(axis=1)
    scores = pd.Series(np.nan, index=axis, name="net_forecast")
    proof = {}
    for year in sorted(set(axis.year)):
        if year <= 2020:
            continue
        first = axis[axis.year == year][0]
        # Only actually observed pre-first OPEN prices enter annual labels.
        past = prices.loc[prices.index < first]
        ends = pd.Series(past.index, index=past.index).shift(-holding_sessions - 1)
        y = (
            past.Open.shift(-holding_sessions - 1) / past.Open.shift(-1) * (0.999 / 1.001) - 1
        ).reindex(axis)
        end = ends.reindex(axis)
        train = (
            complete
            & np.isfinite(y.to_numpy())
            & (axis.year >= 2020)
            & (axis.year < year)
            & (end < first).to_numpy()
        )
        test = complete & (axis.year == year)
        proof[str(year)] = {
            "first_signal": first.isoformat(),
            "train_n": int(train.sum()),
            "train_dates": [t.isoformat() for t in axis[train]],
            "max_maturity": end[train].max().isoformat() if train.any() else None,
            "available": bool(train.sum() >= 40),
            "future_test_count_gate": False,
        }
        if train.sum() < 40:
            continue
        raw_train = x[train, 8]
        raw_test = x[test, 8]
        rt = _cdf_apply(raw_train, raw_train)[:, None]
        rv = _cdf_apply(raw_train, raw_test)[:, None]
        if ridge_alpha == 10.0:
            prediction = _ridge_predict(rt, y.to_numpy()[train], rv)
        else:
            mx = rt.mean(axis=0)
            my = float(y.to_numpy()[train].mean())
            centered = rt - mx
            slope = np.linalg.solve(
                centered.T @ centered + ridge_alpha * np.eye(1),
                centered.T @ (y.to_numpy()[train] - my),
            )
            prediction = my + (rv - mx) @ slope
        scores.loc[test] = prediction
    return scores, proof


def episode_history(scores, signals, holding_sessions=4):
    parameters(holding_sessions=holding_sessions)
    axis = dates(signals)
    if not scores.index.equals(axis) or np.isinf(scores.to_numpy()).any():
        raise ValueError("aligned finite-or-unavailable forecasts required")
    entry = None
    rows = []
    for i, (day, score) in enumerate(scores.items()):
        age = i - entry if entry is not None else None
        reason = "flat"
        if entry is not None:
            if age >= holding_sessions:
                entry = None
                reason = "expiry"
            else:
                reason = "hold"
        elif day.year > 2020 and np.isfinite(score) and score > 0:
            entry = i
            age = 0
            reason = "entry"
        rows.append(
            (
                day,
                float(entry is not None),
                reason,
                age,
                entry,
                bool(np.isfinite(score) and score > 0),
            )
        )
    return (
        pd.DataFrame(
            rows,
            columns=[
                "signal_date",
                "target_position",
                "signal_reason",
                "policy_age",
                "episode_entry_position",
                "positive_forecast",
            ],
        )
        .set_index("signal_date")
        .set_axis(axis.rename("signal_date"))
        .assign(net_forecast=scores)
    )
