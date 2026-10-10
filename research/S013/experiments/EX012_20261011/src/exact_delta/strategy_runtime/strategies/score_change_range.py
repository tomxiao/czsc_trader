"""Approved causal score-change gate; original trade exits retained."""
from collections.abc import Mapping
from dataclasses import replace

import numpy as np
import pandas as pd
from strategy_runtime import InputContract, ParameterSet
from .reentry_confirmed_range import ReentryConfirmedRange
from .confirmed_range import ConfirmedRange, PROFILES, confirmation_features
from .range_reversion import components


class ScoreChangeRange(ReentryConfirmedRange):
    def __init__(self, parameters):
        p = parameters.values
        c = p['confirmation']
        if not isinstance(c, Mapping) or set(c) != {'profile', 'orientation', 'scope', 'lookback', 'direction'}:
            raise ValueError('exact score-change confirmation contract required')
        if type(c['direction']) is not int or c['direction'] not in (-1, 1):
            raise ValueError('direction must be integer +1 or -1')
        if p['context']['entry_gate'] != 'all':
            raise ValueError('change confirmation applies to all basic opportunities')
        parent = {key: value for key, value in p.items()}
        parent['confirmation'] = {key: value for key, value in c.items() if key != 'direction'}
        parent['confirmation'].update(enabled=True, threshold=0.0)
        super().__init__(ParameterSet(parent))
        self._parameters = parameters

    @property
    def definition(self):
        base = super().definition
        requirements = tuple(replace(item, lookback_sessions=60)
                             if item.name == 'execution' and self._parameters.values['context']['volume_basis'] == 'RAW'
                             else item for item in base.inputs.requirements)
        return replace(base, parameters=self._parameters, inputs=InputContract(requirements))

    def calculate_history(self, inputs, sessions):
        p = self._parameters.values
        c, settings = p['confirmation'], p['context']
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
        raw, normalized = confirmation_features(score_bars, all_features['bull'].acf1, c['lookback'])
        score = (.5 * normalized.acf + .25 * normalized.turnover + .25 * normalized.volume
                 if settings['weighting'] == 'EQUAL_BLOCKS' else
                 normalized.loc[:, list(PROFILES[c['profile']])].mean(axis=1)) * c['orientation']
        if c['profile'] != 'all' or settings['weighting'] != 'EQUAL_BLOCKS':
            raise ValueError('exact change gate requires the approved all/equal-blocks score')
        # Midrank has denominator 2*N; .5/.25/.25 weights give exact units 1/(8*N).
        # Rounding only removes arithmetic tails, never a business threshold.
        scale = 8 * c['lookback']
        exact_score_units = np.rint(score * scale)
        score_delta = (exact_score_units.diff() / scale).reindex(sessions)
        score = score.reindex(sessions)
        raw = raw.reindex(sessions)
        normalized = normalized.reindex(sessions)
        if not np.isfinite(score_delta.to_numpy()).all() or not np.isfinite(normalized.to_numpy()).all():
            raise ValueError('complete causal current and prior score history missing')
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
        for i, regime in enumerate(regimes):
            route = active_route if holding else regime
            rp = p[route]
            row = features[route].iloc[i]
            positions.append(row.range_position)
            eligible = (row.range_position <= rp['entry']
                        and (rp['acf_min'] is None or row.acf1 >= rp['acf_min'])
                        and (rp['momentum_min'] is None or row.momentum20 >= rp['momentum_min']))
            applies = (c['scope'] in ('both', regime)
                       and (settings['entry_gate'] == 'all' or last_exit_reason == 'regime'))
            opportunity = not holding and eligible
            passed = not applies or c['direction'] * score_delta.iloc[i] >= 0.0
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
            confirmation_score=score, confirmation_delta=score_delta,
            raw_confirmation_acf=raw.acf, raw_confirmation_turnover=raw.turnover,
            raw_confirmation_volume=raw.volume, confirmation_acf=normalized.acf,
            confirmation_turnover=normalized.turnover, confirmation_volume=normalized.volume,
            confirmation_opportunity=opportunities, confirmation_pass=passes,
            confirmation_exit_context=contexts)
