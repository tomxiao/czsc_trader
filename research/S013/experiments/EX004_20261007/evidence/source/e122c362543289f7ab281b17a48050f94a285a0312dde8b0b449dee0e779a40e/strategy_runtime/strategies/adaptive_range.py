"""S013 causal dual-route range strategy; routing uses only known daily closes."""
from collections.abc import Mapping
from dataclasses import replace
from datetime import timedelta
import math

import numpy as np
import pandas as pd
from strategy_runtime import CalendarWindow, InputContract, ParameterSet

from .range_reversion import RangeReversion, components


class AdaptiveRange(RangeReversion):
    def __init__(self, parameters):
        p = parameters.values
        if set(p) != {'bull', 'bear', 'regime_window', 'regime_threshold',
                      'exit_on_regime_change'}:
            raise ValueError('exact adaptive parameter contract required')
        if type(p['regime_window']) is not int or not 5 <= p['regime_window'] <= 60:
            raise ValueError('regime_window must be 5..60 sessions')
        if (type(p['regime_threshold']) is not float
                or not math.isfinite(p['regime_threshold'])
                or not -.2 <= p['regime_threshold'] <= .2):
            raise ValueError('regime_threshold must be a finite float in [-.2,.2]')
        if type(p['exit_on_regime_change']) is not bool:
            raise ValueError('exit_on_regime_change must be bool')
        for key in ('bull', 'bear'):
            if not isinstance(p[key], Mapping):
                raise ValueError(key + ' must contain complete range parameters')
        self._routes = {
            key: RangeReversion(ParameterSet(p[key])) for key in ('bull', 'bear')
        }
        if p['bull']['limit_premium'] != p['bear']['limit_premium']:
            raise ValueError('route limit_premium must be identical')
        self._parameters = parameters
        self._warmup = max(p['bull']['range_window'], p['bear']['range_window'],
                           p['regime_window'] + 1, 21)

    @property
    def definition(self):
        base = self._routes['bull'].definition
        requirements = tuple(
            replace(item, lookback_sessions=self._warmup)
            if item.name == 'daily' else item for item in base.inputs.requirements
        )
        return replace(base, parameters=self._parameters,
                       inputs=InputContract(requirements))

    def calendar_window(self, window):
        return CalendarWindow(
            window.start - timedelta(days=max(45, self._warmup * 2)), window.end)

    def calculate_history(self, inputs, sessions):
        p = self._parameters.values
        route_features = {
            key: components(inputs['daily'], p[key]['range_window']).reindex(sessions)
            for key in ('bull', 'bear')
        }
        for feature in route_features.values():
            if not np.isfinite(feature.to_numpy()).all():
                raise ValueError('required causal route features missing')
        bars = inputs['daily'].copy()
        bars.index = pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize()
        close = bars.Close.astype(float)
        regime_momentum = (close / close.shift(p['regime_window']) - 1).reindex(sessions)
        if not np.isfinite(regime_momentum.to_numpy()).all():
            raise ValueError('required causal regime features missing')
        regimes = np.where(regime_momentum.to_numpy() >= p['regime_threshold'],
                           'bull', 'bear')
        holding = False
        active_route = None
        age = cooldown = 0
        anchor = peak = 0.0
        targets, reasons, positions = [], [], []
        for i, regime in enumerate(regimes):
            route = active_route if holding else regime
            rp = p[route]
            row = route_features[route].iloc[i]
            positions.append(row.range_position)
            reason = 'flat'
            if holding:
                age += 1
                peak = max(peak, row.close)
                loss = rp['stop_loss'] is not None and row.close / anchor - 1 <= -rp['stop_loss']
                trail = rp['trailing_stop'] is not None and row.close / peak - 1 <= -rp['trailing_stop']
                changed = p['exit_on_regime_change'] and regime != active_route
                if loss or trail or row.range_position >= rp['exit'] or age >= rp['max_hold'] or changed:
                    holding = False
                    cooldown = rp['cooldown']
                    reason = ('loss' if loss else 'trailing' if trail else
                              'range' if row.range_position >= rp['exit'] else
                              'time' if age >= rp['max_hold'] else 'regime')
                    active_route = None
                else:
                    reason = 'hold'
            elif cooldown:
                cooldown -= 1
                reason = 'cooldown'
            elif (row.range_position <= rp['entry']
                  and (rp['acf_min'] is None or row.acf1 >= rp['acf_min'])
                  and (rp['momentum_min'] is None or row.momentum20 >= rp['momentum_min'])):
                holding = True
                active_route = regime
                age = 0
                anchor = peak = row.close
                reason = 'entry'
            targets.append(float(holding))
            reasons.append(reason)
        return route_features['bull'].assign(
            range_position=positions, target_position=targets, signal_reason=reasons,
            regime=regimes, regime_momentum=regime_momentum,
            bull_range_position=route_features['bull'].range_position,
            bear_range_position=route_features['bear'].range_position)
