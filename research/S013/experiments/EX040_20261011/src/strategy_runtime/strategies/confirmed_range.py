"""S013 range opportunity with a causal information-only buy confirmation gate."""
from collections.abc import Mapping
from dataclasses import replace
import math

import numpy as np
import pandas as pd
from strategy_runtime import InputContract, ParameterSet

from .adaptive_range import AdaptiveRange
from .range_reversion import components


PROFILES = {
    'acf': ('acf',), 'turnover': ('turnover',), 'volume': ('volume',),
    'acf_turnover': ('acf', 'turnover'), 'acf_volume': ('acf', 'volume'),
    'turnover_volume': ('turnover', 'volume'), 'all': ('acf', 'turnover', 'volume'),
}


def causal_rank(values, window):
    """S007-v1 midrank formula; complete trailing window, centered on zero."""
    def last(items):
        current = items[-1]
        return float((np.count_nonzero(items < current)
                      + .5 * np.count_nonzero(items == current)) / len(items) - .5)
    return values.rolling(window, min_periods=window).apply(last, raw=True)


def confirmation_features(bars, acf, window):
    frame = bars.copy()
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.Date)).normalize()
    volume, amount = frame.Volume.astype(float), frame.Amount.astype(float)
    if not np.isfinite(volume).all() or not np.isfinite(amount).all() or (volume <= 0).any() or (amount <= 0).any():
        raise ValueError('confirmation requires finite positive volume and amount')
    raw = pd.DataFrame({'acf': acf, 'turnover': amount / amount.rolling(20).mean(),
                        'volume': np.log(volume).diff().rolling(20).mean()}, index=frame.index)
    return raw, raw.apply(lambda values: causal_rank(values, window))


class ConfirmedRange(AdaptiveRange):
    def __init__(self, parameters):
        p = parameters.values
        if set(p) != {'bull', 'bear', 'regime_window', 'regime_threshold',
                      'exit_on_regime_change', 'confirmation'}:
            raise ValueError('exact confirmed-range parameter contract required')
        c = p['confirmation']
        if not isinstance(c, Mapping) or set(c) != {'enabled', 'profile', 'threshold', 'orientation', 'scope', 'lookback'}:
            raise ValueError('complete confirmation contract required')
        if type(c['enabled']) is not bool or c['profile'] not in PROFILES or c['scope'] not in ('both', 'bull', 'bear'):
            raise ValueError('invalid confirmation mode, profile or route scope')
        if type(c['lookback']) is not int or not 40 <= c['lookback'] <= 120:
            raise ValueError('normalization lookback must be 40..120 sessions')
        if type(c['orientation']) is not int or c['orientation'] not in (-1, 1):
            raise ValueError('confirmation orientation must be +1 or -1')
        if type(c['threshold']) is not float or not math.isfinite(c['threshold']) or not -.5 <= c['threshold'] <= .5:
            raise ValueError('confirmation threshold must be a finite float in [-.5,.5]')
        if any(p[key]['cooldown'] != 0 for key in ('bull', 'bear')):
            raise ValueError('fixed cooldown is excluded from this research')
        super().__init__(ParameterSet({k: v for k, v in p.items() if k != 'confirmation'}))
        self._parameters = parameters
        self._warmup = max(self._warmup, c['lookback'] + 20)

    @property
    def definition(self):
        base = self._routes['bull'].definition
        requirements = tuple(replace(item, lookback_sessions=self._warmup)
                             if item.name == 'daily' else item for item in base.inputs.requirements)
        return replace(base, parameters=self._parameters, inputs=InputContract(requirements))

    def calculate_history(self, inputs, sessions):
        p = self._parameters.values
        c = p['confirmation']
        if not c['enabled']:
            return super().calculate_history(inputs, sessions)
        all_features = {key: components(inputs['daily'], p[key]['range_window']) for key in ('bull', 'bear')}
        features = {key: frame.reindex(sessions) for key, frame in all_features.items()}
        if not all(np.isfinite(frame.to_numpy()).all() for frame in features.values()):
            raise ValueError('required causal route features missing')
        _, normalized = confirmation_features(inputs['daily'], all_features['bull'].acf1, c['lookback'])
        normalized = normalized.reindex(sessions)
        if not np.isfinite(normalized.to_numpy()).all():
            raise ValueError('complete causal confirmation history missing')
        score = normalized.loc[:, list(PROFILES[c['profile']])].mean(axis=1) * c['orientation']
        bars = inputs['daily'].copy()
        bars.index = pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize()
        close = bars.Close.astype(float)
        momentum = (close / close.shift(p['regime_window']) - 1).reindex(sessions)
        if not np.isfinite(momentum.to_numpy()).all():
            raise ValueError('required causal regime features missing')
        regimes = np.where(momentum.to_numpy() >= p['regime_threshold'], 'bull', 'bear')
        holding = False
        active_route = None
        age = 0
        anchor = peak = 0.
        targets, reasons, positions, opportunities, passes = [], [], [], [], []
        for i, regime in enumerate(regimes):
            route = active_route if holding else regime
            rp = p[route]
            row = features[route].iloc[i]
            positions.append(row.range_position)
            eligible = (row.range_position <= rp['entry']
                        and (rp['acf_min'] is None or row.acf1 >= rp['acf_min'])
                        and (rp['momentum_min'] is None or row.momentum20 >= rp['momentum_min']))
            opportunity = not holding and eligible
            passed = c['scope'] not in ('both', regime) or score.iloc[i] >= c['threshold']
            opportunities.append(opportunity)
            passes.append(passed)
            reason = 'flat'
            if holding:
                age += 1
                peak = max(peak, row.close)
                loss = rp['stop_loss'] is not None and row.close / anchor - 1 <= -rp['stop_loss']
                trail = rp['trailing_stop'] is not None and row.close / peak - 1 <= -rp['trailing_stop']
                changed = p['exit_on_regime_change'] and regime != active_route
                if loss or trail or row.range_position >= rp['exit'] or age >= rp['max_hold'] or changed:
                    holding = False
                    reason = ('loss' if loss else 'trailing' if trail else
                              'range' if row.range_position >= rp['exit'] else
                              'time' if age >= rp['max_hold'] else 'regime')
                    active_route = None
                else:
                    reason = 'hold'
            elif eligible:
                if passed:
                    holding = True
                    active_route = regime
                    age = 0
                    anchor = peak = row.close
                    reason = 'entry'
                else:
                    reason = 'confirmation_rejected'
            targets.append(float(holding))
            reasons.append(reason)
        return features['bull'].assign(range_position=positions, target_position=targets,
            signal_reason=reasons, regime=regimes, regime_momentum=momentum,
            bull_range_position=features['bull'].range_position,
            bear_range_position=features['bear'].range_position,
            confirmation_score=score, confirmation_acf=normalized.acf,
            confirmation_turnover=normalized.turnover, confirmation_volume=normalized.volume,
            confirmation_opportunity=opportunities, confirmation_pass=passes)
