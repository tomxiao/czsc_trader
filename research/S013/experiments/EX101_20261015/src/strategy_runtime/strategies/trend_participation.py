"""Prospectively fixed price breakout and single-position signal arbitration."""
from collections.abc import Mapping
from dataclasses import replace
import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from .reentry_confirmed_range import ReentryConfirmedRange


def arbitrate(base, entry, exit_, mode):
    """Signal responsibilities only; authoritative executions belong to TXE."""
    if mode not in ('TREND_ONLY', 'COMBINED'):
        raise ValueError('arbitration requires an active declared mode')
    if not base.index.equals(entry.index) or not base.index.equals(exit_.index):
        raise ValueError('signal dates must match exactly')
    if not base.target_position.isin((0.0, 1.0)).all():
        raise ValueError('BASE must declare binary targets')
    state = 'EMPTY'
    targets, reasons, owners, previous, blocked = [], [], [], [], []
    for i in range(len(base)):
        before = state
        base_entry = base.signal_reason.iloc[i] == 'entry'
        if base_entry and base.target_position.iloc[i] != 1.0:
            raise ValueError('BASE entry must have target one')
        reason = 'flat'
        if state == 'BASE':
            if base.target_position.iloc[i] == 0.0:
                state, reason = 'EMPTY', 'base_exit'
            else:
                reason = 'base_hold'
        elif state == 'TREND':
            if bool(exit_.iloc[i]):
                state, reason = 'EMPTY', 'trend_exit'
            else:
                reason = 'trend_hold'
        elif mode == 'COMBINED' and base_entry:
            state, reason = 'BASE', 'base_entry'
        elif bool(entry.iloc[i]):
            state, reason = 'TREND', 'trend_entry'
        targets.append(float(state != 'EMPTY'))
        reasons.append(reason)
        owners.append(state)
        previous.append(before)
        blocked.append(bool(mode == 'COMBINED' and base_entry and before != 'EMPTY'))
    return pd.DataFrame(dict(target_position=targets, signal_reason=reasons,
        signal_owner=owners, prior_owner=previous, blocked_base_entry=blocked), index=base.index)


class TrendParticipation(ReentryConfirmedRange):
    def __init__(self, parameters):
        p = parameters.values
        if set(p) != {'base', 'trend'} or not isinstance(p['trend'], Mapping):
            raise ValueError('exact base/trend contract required')
        t = p['trend']
        if set(t) != {'mode', 'entry_sessions', 'exit_sessions'}:
            raise ValueError('exact trend parameter contract required')
        if t['mode'] not in ('OFF', 'TREND_ONLY', 'COMBINED'):
            raise ValueError('unknown trend mode')
        if type(t['entry_sessions']) is not int or not 10 <= t['entry_sessions'] <= 60:
            raise ValueError('entry_sessions must be integer 10..60')
        if type(t['exit_sessions']) is not int or not 5 <= t['exit_sessions'] <= 30:
            raise ValueError('exit_sessions must be integer 5..30')
        if t['exit_sessions'] >= t['entry_sessions']:
            raise ValueError('exit_sessions must be below entry_sessions')
        super().__init__(ParameterSet(p['base']))
        self._configuration = parameters
        self._warmup = max(self._warmup, t['entry_sessions'] + 1)

    @property
    def definition(self):
        return replace(super().definition, parameters=self._configuration)

    def calculate_history(self, inputs, sessions):
        t = self._configuration.values['trend']
        if t['mode'] == 'OFF':
            return super().calculate_history(inputs, sessions)
        bars = inputs['daily'].copy()
        bars.index = pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize()
        if not bars.index.is_unique or not bars.index.is_monotonic_increasing:
            raise ValueError('daily dates must be unique and ordered')
        close = bars.Close.astype(float)
        if not np.isfinite(close.to_numpy()).all() or (close <= 0).any():
            raise ValueError('finite positive close history required')
        high = close.shift(1).rolling(t['entry_sessions'], min_periods=t['entry_sessions']).max()
        low = close.shift(1).rolling(t['exit_sessions'], min_periods=t['exit_sessions']).min()
        threshold = pd.DataFrame(dict(close=close, trend_high=high, trend_low=low)).reindex(sessions)
        if not np.isfinite(threshold.to_numpy()).all():
            raise ValueError('complete prior trading-session windows required')
        enter = threshold.close > threshold.trend_high
        exit_ = threshold.close < threshold.trend_low
        if t['mode'] == 'COMBINED':
            base = super().calculate_history(inputs, sessions)
        else:
            base = threshold.assign(target_position=0.0, signal_reason='flat')
        selected = arbitrate(base, enter, exit_, t['mode'])
        result = base.rename(columns=dict(target_position='base_target_position', signal_reason='base_signal_reason'))
        result = result.assign(trend_high=threshold.trend_high, trend_low=threshold.trend_low,
            trend_entry_condition=enter, trend_exit_condition=exit_)
        return result.join(selected)
