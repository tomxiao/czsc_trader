"""Pure S013 short-horizon risk components; no data or account I/O."""

from __future__ import annotations

import numpy as np
import pandas as pd


WINDOW = 20
HORIZONS = (3, 5)
SEED = 13


def _frame(frame: pd.DataFrame, columns: tuple[str, ...], *, daily: bool) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or "Date" not in frame:
        raise ValueError("explicit Date-indexed DataFrame required")
    if not set(columns).issubset(frame.columns):
        raise ValueError("required price columns missing")
    result = frame.loc[:, ["Date", *columns]].copy()
    dates = pd.DatetimeIndex(pd.to_datetime(result.pop("Date"), errors="raise"))
    if dates.hasnans or not dates.is_unique or not dates.is_monotonic_increasing:
        raise ValueError("Date must be unique, finite and increasing")
    if daily and not dates.equals(dates.normalize()):
        raise ValueError("daily Date must identify sessions without intraday time")
    result.index = dates
    prices = result.astype(float)
    if not np.isfinite(prices.to_numpy()).all() or (prices.to_numpy() <= 0).any():
        raise ValueError("prices must be positive and finite; missing input is not filled")
    return prices


def intraday_downside_energy(bars: pd.DataFrame) -> pd.DataFrame:
    """Eight completed 30m bars per date; first close/open then close/close.

    Sum negative and total daily energies over twenty complete sessions, then
    divide. A zero twenty-session denominator is rejected; a flat day can have
    zero energy. No high, low, volume or amount is consumed. Multiplying a
    day's prices by any positive scale leaves all within-day returns unchanged.
    """
    prices = _frame(bars, ("Open", "Close"), daily=False)
    rows = []
    for session, day in prices.groupby(prices.index.normalize(), sort=True):
        if len(day) != 8:
            raise ValueError("every completed session requires exactly eight 30m bars")
        close = day.Close.to_numpy()
        reference = np.concatenate(([day.Open.iloc[0]], close[:-1]))
        changes = np.log(close / reference)
        energy = float(np.dot(changes, changes))
        if not np.isfinite(energy):
            raise ValueError("invalid intraday energy")
        negative = np.minimum(changes, 0.0)
        downside = float(np.dot(negative, negative))
        rows.append((session, downside, energy, float(np.log(close[-1] / reference[0]))))
    daily = pd.DataFrame(
        rows, columns=["Date", "intraday_negative_energy", "intraday_total_energy", "intraday_net_logreturn"]
    ).set_index("Date")
    denominator = daily.intraday_total_energy.rolling(WINDOW, min_periods=WINDOW).sum()
    if (denominator.dropna() <= 0).any():
        raise ValueError("zero twenty-session intraday-energy denominator")
    numerator = daily.intraday_negative_energy.rolling(WINDOW, min_periods=WINDOW).sum()
    daily["feature_intraday_down_energy20"] = numerator / denominator
    daily["intraday_energy20"] = daily.intraday_total_energy.rolling(WINDOW, min_periods=WINDOW).mean().pow(0.5)
    return daily


def overnight_downside_risk(daily: pd.DataFrame) -> pd.DataFrame:
    """RMS of negative HFQ overnight log-gaps over twenty complete sessions.

    Warmup remains NaN, and no parameterized lookback or weight is searched.
    A common positive price rescaling leaves outputs unchanged.
    """
    prices = _frame(daily, ("Open", "Close"), daily=True)
    gaps = np.log(prices.Open / prices.Close.shift(1))
    intraday = np.log(prices.Close / prices.Open)
    close_return = np.log(prices.Close / prices.Close.shift(1))
    downside = np.minimum(gaps, 0.0)
    return pd.DataFrame({
        "feature_overnight_down_energy20": downside.pow(2).rolling(WINDOW, min_periods=WINDOW).mean().pow(0.5),
        "overnight_gap": gaps,
        "intraday_rms20": intraday.pow(2).rolling(WINDOW, min_periods=WINDOW).mean().pow(0.5),
        "close_return_rms20": close_return.pow(2).rolling(WINDOW, min_periods=WINDOW).mean().pow(0.5),
    }, index=prices.index)


def short_horizon_labels(daily: pd.DataFrame) -> pd.DataFrame:
    """h denotes h full execution sessions from entry open to exit open.

    Signal T -> entry Open at first subsequent session -> exit Open at (h+1)-th
    subsequent session (h=3/5). MAE uses Low of entry through session before
    exit. Incomplete tail labels, entry dates and exit dates remain missing.
    These are price labels; they are not fee-inclusive account returns.
    """
    prices = _frame(daily, ("Open", "Low"), daily=True)
    if (prices.Low > prices.Open).any():
        raise ValueError("daily Low cannot exceed Open")
    labels = pd.DataFrame(index=prices.index)
    for horizon in HORIZONS:
        returns = np.full(len(prices), np.nan)
        downside = np.full(len(prices), np.nan)
        entries = np.full(len(prices), np.datetime64("NaT"), dtype="datetime64[ns]")
        exits = entries.copy()
        for offset in range(len(prices) - horizon - 1):
            entry_open = prices.Open.iloc[offset + 1]
            exit_open = prices.Open.iloc[offset + horizon + 1]
            returns[offset] = exit_open / entry_open - 1.0
            low = prices.Low.iloc[offset + 1:offset + horizon + 1].min()
            downside[offset] = max(0.0, 1.0 - float(low / entry_open))
            entries[offset] = prices.index[offset + 1].to_datetime64()
            exits[offset] = prices.index[offset + horizon + 1].to_datetime64()
        labels[f"return_h{horizon}"] = returns
        labels[f"risk_h{horizon}"] = downside
        labels[f"label_entry_h{horizon}"] = entries
        labels[f"label_exit_h{horizon}"] = exits
    return labels


def mature_training_mask(labels: pd.DataFrame, horizon: int, test_first_signal: pd.Timestamp) -> pd.Series:
    """Training labels must have exited strictly before first test signal."""
    if type(horizon) is not int or horizon not in HORIZONS:
        raise ValueError("horizon must be exactly 3 or 5")
    first = pd.Timestamp(test_first_signal)
    if pd.isna(first) or first != first.normalize():
        raise ValueError("test_first_signal must be an explicit normalized session")
    required = (f"return_h{horizon}", f"risk_h{horizon}", f"label_exit_h{horizon}")
    if not set(required).issubset(labels.columns):
        raise ValueError("required typed label columns missing")
    return (labels.index < first) & (labels[required[2]] < first) & labels[list(required)].notna().all(axis=1)
