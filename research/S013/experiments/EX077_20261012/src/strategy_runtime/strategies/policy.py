"""Pure long-only close-price event policy. No IO, execution or account state."""

import numpy as np
import pandas as pd


def decisions(close, signal_sessions, *, lookback=20, distance=1.0):
    """Arm2k*sigma, buy/exit k*sigma; freeze sigma at arm for the whole cycle.

    Warmup supplies past returns only. Policy starts FLAT at first signal Close.
    target_position is intent at T17, never proof of actual quantity/fill at T+1.
    No timeout, epsilon, rolling exit scale, resizing, regime or vote.
    """
    if type(lookback) is not int or not 2 <= lookback <= 120:
        raise ValueError("integer lookback in full domain[2,120] required")
    if type(distance) is not float or not np.isfinite(distance) or not 0.25 <= distance <= 4.0:
        raise ValueError("float distance in full domain[.25,4] required")
    if not isinstance(close, pd.Series) or not pd.api.types.is_numeric_dtype(close.dtype):
        raise ValueError("numeric Close Series required")
    for index in (close.index, signal_sessions):
        if (
            not isinstance(index, pd.DatetimeIndex)
            or index.hasnans
            or index.has_duplicates
            or index.tz is not None
            or not index.is_monotonic_increasing
            or not index.equals(index.normalize())
        ):
            raise ValueError("unique complete ordered timezone-naive session axis required")
    if not len(signal_sessions) or not signal_sessions.isin(close.index).all():
        raise ValueError("nonempty known signal sessions required")
    first, last = close.index.get_loc(signal_sessions[0]), close.index.get_loc(signal_sessions[-1])
    if not signal_sessions.equals(close.index[first : last + 1]):
        raise ValueError("signal state must traverse every session without gaps")
    prices = close.to_numpy(float)
    if not np.isfinite(prices).all() or not (prices > 0).all():
        raise ValueError("strictly positive finite Close prices required")
    log_prices = np.log(prices)
    returns = np.diff(log_prices)
    state, peak, trough, locked = "FLAT", float(prices[first]), None, None
    rows = []
    for p in range(first, last + 1):
        day, price = close.index[p], float(prices[p])
        sigma = float(np.std(returns[p - lookback : p], ddof=0)) if p >= lookback else np.nan
        available = bool(np.isfinite(sigma) and sigma > 0)
        before, reason = state, None
        if state == "FLAT":
            peak = max(peak, price)
            if not available:
                reason = "FLAT_VOL_UNAVAILABLE"
            elif np.log(peak) - np.log(price) >= 2 * distance * sigma:
                state, trough, locked = "ARMED", price, sigma
                reason = "ARM_PRICE_EXCURSION"
            else:
                reason = "TRACK_FLAT_PEAK"
        elif state == "ARMED":
            trough = min(trough, price)
            if np.log(price) - np.log(trough) >= distance * locked:
                state, peak, trough = "HELD", price, None
                reason = "BUY_PRICE_REVERSAL"
            else:
                reason = "WAIT_PRICE_REVERSAL"
        else:
            peak = max(peak, price)
            if np.log(peak) - np.log(price) >= distance * locked:
                state, peak, trough, locked = "FLAT", price, None, None
                reason = "SELL_PRICE_RETRACE"
            else:
                reason = "CONTINUE_PRICE_CYCLE"
        rows.append(
            dict(
                signal_time=day + pd.Timedelta(hours=17),
                close=price,
                state_before=before,
                state_after=state,
                reason=reason,
                target_position=1 if state == "HELD" else 0,
                sigma_current=sigma,
                sigma_available=available,
                sigma_unavailable_reason=None
                if available
                else "INSUFFICIENT_PAST_L_RETURNS"
                if p < lookback
                else "ZERO_VOLATILITY",
                sigma_locked=locked if locked is not None else np.nan,
                known_peak=peak,
                known_trough=trough if trough is not None else np.nan,
            )
        )
    result = pd.DataFrame(rows, index=signal_sessions)
    for name in ("state_before", "state_after", "reason", "sigma_unavailable_reason"):
        result[name] = result[name].astype("string")
    return result
