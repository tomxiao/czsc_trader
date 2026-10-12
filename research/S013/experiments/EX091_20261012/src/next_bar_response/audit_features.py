"""Independent scalar next-bar response reconstruction; no data or account I/O."""
from math import fsum, log
import numpy as np
import pandas as pd

CLOCKS = ('10:00', '10:30', '11:00', '11:30', '13:30', '14:00', '14:30', '15:00')
COLUMNS = ('X', 'S', 'U', 'sources_count', 'sources_negative_mean',
           'negative_body_mean', 'samebar_cov', 'past_clock_samebar',
           'past_clock_next_response_minus_U')


def average(values):
    return fsum(values) / len(values)


def ordered_dates(axis, normalized):
    if not isinstance(axis, pd.DatetimeIndex) or not len(axis):
        raise ValueError('Nonempty explicit datetime axis required')
    if axis.tz is not None or axis.hasnans or not axis.is_unique or not axis.is_monotonic_increasing:
        raise ValueError('Naive unique increasing finite axis required')
    if normalized and not axis.equals(axis.normalize()):
        raise ValueError('Midnight sessions required')


def reconstruct(bars, axis):
    ordered_dates(axis, True)
    if not isinstance(bars, pd.DataFrame) or bars.empty or bars.columns.has_duplicates:
        raise ValueError('Nonempty frame with unique columns required')
    if not {'Date', 'Open', 'Close', 'Volume'}.issubset(bars.columns):
        raise ValueError('Complete Date/Open/Close/Volume required')
    if not pd.api.types.is_datetime64_any_dtype(bars.Date.dtype):
        raise ValueError('Explicit datetime Date required')
    stamps = pd.DatetimeIndex(bars.Date)
    ordered_dates(stamps, False)
    days, sessions = [], {}
    for stamp, open_price, close_price, volume in bars[['Date', 'Open', 'Close', 'Volume']].itertuples(index=False, name=None):
        if not all(np.isfinite(v) for v in (open_price, close_price, volume)):
            raise ValueError('Finite prices and volumes required')
        if open_price <= 0 or close_price <= 0 or volume < 0:
            raise ValueError('Positive prices and nonnegative volume required')
        day = stamp.normalize()
        if day not in sessions:
            days.append(day)
            sessions[day] = []
        sessions[day].append((stamp, float(open_price), float(close_price), float(volume)))
    bodies, volumes, profiles = [], [], []
    for day in days:
        records = sessions[day]
        if len(records) != 8:
            raise ValueError('Exactly eight complete bars per day required')
        for j, (stamp, _, _, _) in enumerate(records):
            if stamp != day + pd.Timedelta(CLOCKS[j] + ':00'):
                raise ValueError('Exact fixed bar-end clocks required')
        body = [log(close_price) - log(open_price) for _, open_price, close_price, _ in records]
        volume = [value for _, _, _, value in records]
        vmax = max(volume)
        relative = [v / vmax for v in volume] if vmax else [0.] * 8
        total = fsum(relative)
        profile = [v / total for v in relative] if total else None
        bodies.append(body)
        volumes.append(relative)
        profiles.append(profile)
    positions = {day: i for i, day in enumerate(days)}
    if any(day not in positions for day in axis):
        raise ValueError('Output session missing from bars')
    rows, traces = [], []
    for day in axis:
        i = positions[day]
        body, volume = bodies[i], volumes[i]
        negative = [max(-value, 0.) for value in body]
        source = [j for j in range(7) if body[j] < 0]
        successors = [j + 1 for j in source]
        count = len(source)
        u = average([body[j] for j in successors]) if count else np.nan
        source_mean = average([negative[j] for j in source]) if count else np.nan
        total, source_weight = fsum(volume), fsum(volume[j] for j in source)
        current_reason = ('ZERO_SESSION_VOLUME' if total == 0 else
                          'NO_NEGATIVE_SOURCE_PAIR' if not count else
                          'ZERO_SOURCE_VOLUME' if source_weight == 0 else None)
        s = fsum(volume[j] / source_weight * body[j + 1] for j in source) if current_reason is None else np.nan
        past_days = days[max(0, i - 20):i]
        past = profiles[max(0, i - 20):i]
        clock_reason = ('INSUFFICIENT_PAST20_FULL_SESSIONS' if len(past) < 20 else
                        'ZERO_VOLUME_IN_PAST20_PROFILE' if any(profile is None for profile in past) else None)
        clock = [average([profile[j] for profile in past]) for j in range(8)] if clock_reason is None else None
        next_reason = clock_reason
        projection = np.nan
        if next_reason is None:
            clock_sum = fsum(clock[j] for j in source)
            next_reason = ('NO_NEGATIVE_SOURCE_PAIR' if not count else
                           'ZERO_PAST_CLOCK_SOURCE_WEIGHT' if clock_sum == 0 else None)
            if next_reason is None:
                projection = fsum(clock[j] / clock_sum * body[j + 1] for j in source) - u
        negative_mean = average(negative)
        same = fsum(profiles[i][j] * negative[j] for j in range(8)) - negative_mean if profiles[i] is not None else np.nan
        past_same = fsum(clock[j] * negative[j] for j in range(8)) - negative_mean if clock is not None else np.nan
        row = (s - u, s, u, count, source_mean, negative_mean, same, past_same, projection)
        if np.isinf(np.asarray(row, float)).any():
            raise ValueError('Nonfinite arithmetic result')
        rows.append(row)
        traces.append({'source_indices': source, 'successor_indices': successors,
                       'last_bar_source_excluded': True, 'X_available': current_reason is None,
                       'X_reason': current_reason, 'S_reason': current_reason,
                       'U_reason': None if count else 'NO_NEGATIVE_SOURCE_PAIR',
                       'sources_negative_mean_reason': None if count else 'NO_NEGATIVE_SOURCE_PAIR',
                       'samebar_cov_reason': None if total > 0 else 'ZERO_SESSION_VOLUME',
                       'past_clock_samebar_reason': clock_reason,
                       'past_clock_next_response_reason': next_reason,
                       'past_clock_available': clock is not None,
                       'past_window_sessions': len(past_days),
                       'past_window_dates': [d.isoformat() for d in past_days],
                       'past_clock_weights': clock,
                       'joint_nine_available': all(np.isfinite(v) for v in row),
                       'available_after': day.isoformat()[:10] + 'T15:00:00'})
    index = axis.rename('Date')
    return pd.DataFrame(rows, index=index, columns=COLUMNS), pd.DataFrame(traces, index=index)


def verify(bars, axis, reported_features, reported_trace):
    expected, trace = reconstruct(bars, axis)
    pd.testing.assert_frame_equal(reported_features, expected, check_exact=False, atol=3e-13, rtol=2e-10)
    assert reported_trace.index.equals(trace.index) and tuple(reported_trace.columns) == tuple(trace.columns)
    clock_values = 'past_clock_weights'
    for key in trace.columns:
        if key != clock_values:
            pd.testing.assert_series_equal(reported_trace[key], trace[key], check_exact=True)
    for a, b in zip(reported_trace[clock_values], trace[clock_values], strict=True):
        if b is None:
            assert a is None
        else:
            np.testing.assert_allclose(a, b, atol=3e-15, rtol=2e-12)
    np.testing.assert_array_equal(np.isfinite(reported_features), np.isfinite(expected))
    return {'status': 'PASS', 'sessions': len(axis), 'feature_cells': len(axis) * 9,
            'trace_fields_per_session': len(trace.columns),
            'causal_prefix_windows': len(axis), 'source_pairs': int(expected.sources_count.sum()),
            'independent_scalar_profiles': 'ALL', 'real_data_loading': False,
            'accounts': 0, 'experiments_allocated': 0}
