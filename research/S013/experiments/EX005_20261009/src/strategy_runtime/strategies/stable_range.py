"""S013 causal state hysteresis and consecutive regime-exit confirmation."""
from dataclasses import replace
import math

import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet

from .adaptive_range import AdaptiveRange
from .range_reversion import components


class StableRange(AdaptiveRange):
    def __init__(self, parameters):
        p = parameters.values
        extra = {'regime_band', 'regime_confirmation', 'exit_confirmation',
                 'exit_direction', 'regime_cooldown'}
        if not extra <= set(p):
            raise ValueError('complete stable-state parameters required')
        if (type(p['regime_band']) is not float or not math.isfinite(p['regime_band'])
                or not 0 <= p['regime_band'] <= .10):
            raise ValueError('regime_band must be a finite float in [0,.10]')
        for key in ('regime_confirmation', 'exit_confirmation'):
            if type(p[key]) is not int or not 1 <= p[key] <= 10:
                raise ValueError(key + ' must be 1..10 sessions')
        if type(p['regime_cooldown']) is not int or not 0 <= p['regime_cooldown'] <= 10:
            raise ValueError('regime_cooldown must be 0..10 sessions')
        if p['exit_direction'] not in ('both', 'bull_to_bear', 'bear_to_bull'):
            raise ValueError('exit_direction must identify the transition to exit')
        super().__init__(ParameterSet({k: v for k, v in p.items() if k not in extra}))
        self._parameters = parameters

    @property
    def definition(self):
        return replace(super().definition, parameters=self._parameters)

    @staticmethod
    def states(momentum, threshold, band, confirmation):
        """Use only the current and preceding observations; reset pending at neutral."""
        state = None
        pending = None
        count = 0
        output = []
        for value in momentum:
            if state is None:
                state = 'bull' if value >= threshold else 'bear'
            proposed = ('bull' if value >= threshold + band else
                        'bear' if value < threshold - band else state)
            if proposed == state:
                pending, count = None, 0
            else:
                count = count + 1 if proposed == pending else 1
                pending = proposed
                if count >= confirmation:
                    state, pending, count = proposed, None, 0
            output.append(state)
        return np.asarray(output)

    def calculate_history(self, inputs, sessions):
        p = self._parameters.values
        features = {
            key: components(inputs['daily'], p[key]['range_window']).reindex(sessions)
            for key in ('bull', 'bear')
        }
        if not all(np.isfinite(frame.to_numpy()).all() for frame in features.values()):
            raise ValueError('required causal route features missing')
        bars = inputs['daily'].copy()
        bars.index = pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize()
        close = bars.Close.astype(float)
        momentum = (close / close.shift(p['regime_window']) - 1).reindex(sessions)
        if not np.isfinite(momentum.to_numpy()).all():
            raise ValueError('required causal regime features missing')
        regimes = self.states(momentum.to_numpy(), p['regime_threshold'],
                              p['regime_band'], p['regime_confirmation'])
        holding = False
        active_route = None
        age = cooldown = contrary = 0
        anchor = peak = 0.
        targets, reasons, positions = [], [], []
        for i, regime in enumerate(regimes):
            route = active_route if holding else regime
            rp = p[route]
            row = features[route].iloc[i]
            positions.append(row.range_position)
            reason = 'flat'
            if holding:
                age += 1
                peak = max(peak, row.close)
                contrary = contrary + 1 if regime != active_route else 0
                loss = rp['stop_loss'] is not None and row.close / anchor - 1 <= -rp['stop_loss']
                trail = rp['trailing_stop'] is not None and row.close / peak - 1 <= -rp['trailing_stop']
                direction = (p['exit_direction'] == 'both'
                             or p['exit_direction'] == active_route + '_to_' + regime)
                changed = (p['exit_on_regime_change'] and direction
                           and contrary >= p['exit_confirmation'])
                if loss or trail or row.range_position >= rp['exit'] or age >= rp['max_hold'] or changed:
                    holding = False
                    cooldown = rp['cooldown']
                    reason = ('loss' if loss else 'trailing' if trail else
                              'range' if row.range_position >= rp['exit'] else
                              'time' if age >= rp['max_hold'] else 'regime')
                    if reason == 'regime':
                        cooldown = max(cooldown, p['regime_cooldown'])
                    active_route, contrary = None, 0
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
                age = contrary = 0
                anchor = peak = row.close
                reason = 'entry'
            targets.append(float(holding))
            reasons.append(reason)
        return features['bull'].assign(
            range_position=positions, target_position=targets, signal_reason=reasons,
            regime=regimes, regime_momentum=momentum,
            bull_range_position=features['bull'].range_position,
            bear_range_position=features['bear'].range_position)
