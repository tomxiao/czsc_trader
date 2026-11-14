"""Frozen financial calculations copied without algorithm changes for native V4."""
import numpy as np
import pandas as pd
from strategy_runtime import InputAlignment, AlignmentRule, align_input_history
ALIGNMENT=InputAlignment(AlignmentRule.STRICT_PRIOR,"Date","US","SSE",10,False)
def indexed(frame):
    frame = frame.copy()
    frame['Date'] = pd.to_datetime(frame.Date)
    if frame.Date.duplicated().any() or not frame.Date.is_monotonic_increasing:
        raise ValueError('unordered or duplicate dates')
    return frame.set_index('Date')

def features(inputs):
    daily = indexed(inputs['daily']).loc['2024-12-26':]
    market = indexed(inputs['market'])
    bars = inputs['bars'].copy()
    bars['Date'] = pd.to_datetime(bars.Date)
    bars = bars.loc[bars.Date >= '2024-12-26'].copy()
    bars['day'] = bars.Date.dt.normalize()
    bars['clock'] = bars.Date.dt.strftime('%H:%M')
    close = bars.pivot(index='day', columns='clock', values='Close')
    if set(close.columns) != {'10:00', '10:30', '11:00', '11:30', '13:30', '14:00', '14:30', '15:00'} or close.isna().any().any():
        raise ValueError('incomplete intraday bars')
    aligned = align_input_history(inputs['spx'], daily.index, ALIGNMENT, value_columns=('PercentChange',)).dataframe
    aligned.index = daily.index
    output = pd.DataFrame({'tail': close['15:00'].div(close['13:30']).sub(1).reindex(daily.index), 'market': market.Close.pct_change(fill_method=None).reindex(daily.index), 'spx': aligned.PercentChange, 'risk5': daily.High.sub(daily.Low).div(daily.Close).rolling(5).mean()}, index=daily.index)
    for col in ('decision_time', 'source_time', 'staleness_days'):
        output['spx_' + col] = aligned[col]
    return output

def rank(values, lookback):

    def last(x):
        if not np.isfinite(x[-1]):
            return np.nan
        valid = x[np.isfinite(x)]
        return ((valid < x[-1]).sum() + 0.5 * (valid == x[-1]).sum()) / len(valid) - 0.5
    return values.rolling(lookback, min_periods=20).apply(last, raw=True)

def policy(panel, params, sessions):
    """Signal-cycle expiry is counted from intent, never from an assumed fill."""
    lb = params['lookback']
    tail, market, spx = (-rank(panel['tail'], lb), -rank(panel.market, lb), rank(panel.spx, lb))
    weight = params['tail_weight']
    score = (weight * tail + (1 - weight) * market + params['spx_weight'] * spx) / (1 + params['spx_weight'])
    frame = panel.reindex(sessions).copy()
    frame['score'] = score.reindex(sessions)
    if frame[['tail', 'market', 'spx', 'risk5', 'score']].isna().any().any():
        raise ValueError('missing input or insufficient causal warmup')
    current, age = (0, 0)
    targets, reasons, ages = ([], [], [])
    for value in frame.score:
        reason = 'HOLD' if current else 'CASH'
        if current:
            age += 1
            if value <= params['exit'] or age >= params['max_days']:
                current, reason = (0, 'PRESSURE_RELEASED' if value <= params['exit'] else 'SIGNAL_EXPIRED')
        elif value >= params['entry']:
            current, age, reason = (1, 0, 'PRESSURE_ENTRY')
        targets.append(current)
        reasons.append(reason)
        ages.append(age)
    frame['target_position'] = targets
    frame['reason'] = reasons
    frame['intent_age'] = ages
    return frame
