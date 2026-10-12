"""Market-only episode clock: no confirmation, ACF, accepted trade or labels."""
import numpy as np
import pandas as pd

COLUMNS = ('episode_live', 'episode_route', 'episode_age', 'episode_reason',
           'episode_expired', 'episode_anchor', 'episode_peak', 'episode_id')


def observe(parameters, features, regimes, sessions):
    if not isinstance(sessions, pd.DatetimeIndex) or not len(sessions) or sessions.tz is not None or sessions.hasnans:
        raise ValueError('Nonempty naive finite signal axis required')
    if not sessions.is_unique or not sessions.is_monotonic_increasing or not sessions.equals(sessions.normalize()):
        raise ValueError('Unique ordered midnight signals required')
    if len(regimes) != len(sessions) or any(route not in ('bull', 'bear') for route in regimes):
        raise ValueError('Complete known bull/bear raw routes required')
    if type(parameters['exit_on_regime_change']) is not bool or set(features) != {'bull', 'bear'}:
        raise ValueError('Explicit route-change flag and two route features required')
    for route in ('bull', 'bear'):
        frame, rp = features[route], parameters[route]
        if not frame.index.equals(sessions) or not {'range_position', 'momentum20', 'close'}.issubset(frame.columns):
            raise ValueError('Complete shared causal route feature axis required')
        values = frame[['range_position', 'momentum20', 'close']].to_numpy(float)
        if not np.isfinite(values).all() or (values[:, 2] <= 0).any():
            raise ValueError('Finite range/momentum and positive known close required')
        if type(rp['max_hold']) is not int or not 1 <= rp['max_hold'] <= 60:
            raise ValueError('Original max_hold must be1..60')
        if not (np.isfinite(rp['entry']) and np.isfinite(rp['exit']) and 0 <= rp['entry'] < rp['exit'] <= 1):
            raise ValueError('Original finite ordered range thresholds required')
        if rp['momentum_min'] is not None and not np.isfinite(rp['momentum_min']):
            raise ValueError('Finite or missing original momentum threshold required')
    active, age, anchor, peak, identity = None, 0, 0., 0., 0
    rows = []
    for i, rawroute in enumerate(regimes):
        expired, reason = False, 'flat'
        if active is not None:
            route, rp = active, parameters[active]
            row = features[active].iloc[i]
            age += 1
            peak = max(peak, float(row.close))
            reason = ('range' if row.range_position >= rp['exit'] else
                      'time' if age >= rp['max_hold'] else
                      'regime' if parameters['exit_on_regime_change'] and rawroute != active else 'hold')
            expired = reason == 'time'
            live = reason == 'hold'
            rows.append((live, route, age, reason, expired, anchor, peak, identity))
            if not live:
                active = None
        else:
            rp, row = parameters[rawroute], features[rawroute].iloc[i]
            eligible = row.range_position <= rp['entry'] and (
                rp['momentum_min'] is None or row.momentum20 >= rp['momentum_min'])
            if eligible:
                active, age, anchor, peak = rawroute, 0, float(row.close), float(row.close)
                identity += 1
                reason = 'start'
                rows.append((True, active, age, reason, False, anchor, peak, identity))
            else:
                rows.append((False, None, None, reason, False, None, None, None))
    frame = pd.DataFrame(rows, index=sessions, columns=COLUMNS)
    # Fixed storage dtypes keep prefix tables independent of a future flat row.
    for column in ('episode_age', 'episode_anchor', 'episode_peak', 'episode_id'):
        frame[column] = frame[column].astype(float)
    for column in ('episode_route', 'episode_reason'):
        frame[column] = pd.Series(frame[column].to_numpy(), index=sessions, dtype=object)
    return frame
