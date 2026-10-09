"""Complement ordinary entry information while retaining the state-reentry gate."""
from collections.abc import Mapping
import math
import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from .reentry_confirmed_range import ReentryConfirmedRange
from .confirmed_range import PROFILES, confirmation_features
from .range_reversion import components


class ComplementConfirmedRange(ReentryConfirmedRange):
    def __init__(self, parameters):
        p = parameters.values
        if set(p) != {'bull', 'bear', 'regime_window', 'regime_threshold',
                      'exit_on_regime_change', 'confirmation', 'context', 'opportunity_confirmation'}:
            raise ValueError('complete complement-confirmation parameter contract required')
        extra = p['opportunity_confirmation']
        if not isinstance(extra, Mapping) or set(extra) != {
            'enabled', 'profile', 'threshold', 'weighting', 'application', 'route_scope'}:
            raise ValueError('exact opportunity confirmation settings required')
        if type(extra['enabled']) is not bool or extra['profile'] not in PROFILES:
            raise ValueError('invalid opportunity confirmation mode or profile')
        if type(extra['threshold']) is not float or not math.isfinite(extra['threshold']) or not -.5 <= extra['threshold'] <= .5:
            raise ValueError('opportunity threshold must be a finite float in [-.5,.5]')
        if extra['weighting'] not in ('EQUAL_FEATURES', 'EQUAL_BLOCKS'):
            raise ValueError('invalid opportunity weighting')
        if extra['weighting'] == 'EQUAL_BLOCKS' and extra['profile'] != 'all':
            raise ValueError('equal state/participation blocks require all features')
        if extra['application'] not in ('all_entries', 'ordinary_entries') or extra['route_scope'] not in ('both', 'bull', 'bear'):
            raise ValueError('invalid opportunity application or route scope')
        super().__init__(ParameterSet({key: value for key, value in p.items() if key != 'opportunity_confirmation'}))
        self._parameters = parameters

    def calculate_history(self, inputs, sessions):
        p = self._parameters.values
        c, settings = p['confirmation'], p['context']
        extra = p['opportunity_confirmation']
        if not extra['enabled']:
            return super().calculate_history(inputs, sessions)
        all_features = {key: components(inputs['daily'], p[key]['range_window']) for key in ('bull', 'bear')}
        features = {key: frame.reindex(sessions) for key, frame in all_features.items()}
        if not all(np.isfinite(frame.to_numpy()).all() for frame in features.values()):
            raise ValueError('required causal route features missing')
        score_bars = inputs['daily'].copy()
        if settings['volume_basis'] == 'RAW':
            raw = inputs['execution'].copy()
            raw.index = pd.DatetimeIndex(pd.to_datetime(raw.Date)).normalize()
            score_bars.index = pd.DatetimeIndex(pd.to_datetime(score_bars.Date)).normalize()
            if not raw.index.is_unique or not raw.index.is_monotonic_increasing or not raw.index.isin(score_bars.index).all():
                raise ValueError('raw volume dates must be unique, ordered and share the adjusted calendar')
            adjusted = score_bars.loc[raw.index]
            reconstructed = adjusted.Volume * adjusted.Close / raw.Close
            if not np.allclose(reconstructed.to_numpy(), raw.Volume.to_numpy(), rtol=1e-12, atol=1e-6):
                raise ValueError('per-date raw/HFQ volume conversion differs')
            if not np.allclose(adjusted.Amount.to_numpy(), raw.Amount.to_numpy(), rtol=1e-12, atol=1e-6):
                raise ValueError('amount must be invariant across price-unit conversion')
            score_bars = adjusted.assign(Volume=raw.Volume)
        _, normalized = confirmation_features(score_bars, all_features['bull'].acf1, c['lookback'])
        normalized = normalized.reindex(sessions)
        if not np.isfinite(normalized.to_numpy()).all():
            raise ValueError('complete causal confirmation history missing')
        score = (.5 * normalized.acf + .25 * normalized.turnover + .25 * normalized.volume
                 if settings['weighting'] == 'EQUAL_BLOCKS' else
                 normalized.loc[:, list(PROFILES[c['profile']])].mean(axis=1)) * c['orientation']
        extra_score = (.5 * normalized.acf + .25 * normalized.turnover + .25 * normalized.volume
                       if extra['weighting'] == 'EQUAL_BLOCKS' else
                       normalized.loc[:, list(PROFILES[extra['profile']])].mean(axis=1))
        bars = inputs['daily'].copy()
        bars.index = pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize()
        close = bars.Close.astype(float)
        momentum = (close / close.shift(p['regime_window']) - 1).reindex(sessions)
        if not np.isfinite(momentum.to_numpy()).all():
            raise ValueError('required causal regime features missing')
        regimes = np.where(momentum.to_numpy() >= p['regime_threshold'], 'bull', 'bear')
        holding = False
        active_route = None
        last_exit_reason = None
        age = 0
        anchor = peak = 0.
        targets, reasons, positions, opportunities, passes, contexts = [], [], [], [], [], []
        extra_applies, extra_passes = [], []
        for i, regime in enumerate(regimes):
            route = active_route if holding else regime
            rp = p[route]
            row = features[route].iloc[i]
            positions.append(row.range_position)
            eligible = (row.range_position <= rp['entry']
                        and (rp['acf_min'] is None or row.acf1 >= rp['acf_min'])
                        and (rp['momentum_min'] is None or row.momentum20 >= rp['momentum_min']))
            applies = (c['enabled'] and c['scope'] in ('both', regime)
                       and (settings['entry_gate'] == 'all' or last_exit_reason == 'regime'))
            opportunity = not holding and eligible
            extra_applies_today = (extra['route_scope'] in ('both', regime)
                                   and (extra['application'] == 'all_entries' or last_exit_reason != 'regime'))
            extra_passed = not extra_applies_today or extra_score.iloc[i] >= extra['threshold']
            passed = (not applies or score.iloc[i] >= c['threshold']) and extra_passed
            extra_applies.append(extra_applies_today)
            extra_passes.append(extra_passed)
            opportunities.append(opportunity)
            passes.append(passed)
            contexts.append(last_exit_reason or 'initial')
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
                    last_exit_reason = reason
                    active_route = None
                else:
                    reason = 'hold'
            elif eligible:
                if passed:
                    holding = True
                    active_route = regime
                    age = 0
                    anchor = peak = row.close
                    last_exit_reason = None
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
            confirmation_opportunity=opportunities, confirmation_pass=passes,
            confirmation_exit_context=contexts,
            opportunity_confirmation_score=extra_score,
            opportunity_confirmation_applies=extra_applies,
            opportunity_confirmation_pass=extra_passes)
