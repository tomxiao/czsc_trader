"""Refresh the original raw bear eligibility after a bear TIME signal exit.

This signal-model latch uses the existing route/range/ACF/momentum gates. It does
not delay execution or alter the original time exit. Pending is released on a
flat signal bar before the original entry evaluation. Rejection has precedence
over the original score rejection; both original gate diagnostics are retained.
"""
import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet

from .confirmed_range import PROFILES, confirmation_features
from .range_reversion import components
from .reentry_confirmed_range import ReentryConfirmedRange


class EligibilityRefreshRange(ReentryConfirmedRange):
    def __init__(self, parameters):
        p = parameters.values
        if p.get('mechanism') != 'BEAR_TIME_ELIGIBILITY_REFRESH':
            raise ValueError('explicit BEAR_TIME_ELIGIBILITY_REFRESH mechanism required')
        if p.get('confirmation', {}).get('enabled') is not True:
            raise ValueError('original enabled buy confirmation required')
        super().__init__(ParameterSet({key: value for key, value in p.items() if key != 'mechanism'}))
        self._parameters = parameters

    def calculate_history(self, inputs, sessions):
        p = self._parameters.values
        c, settings = p['confirmation'], p['context']
        if not c['enabled']:
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
        bars = inputs['daily'].copy()
        bars.index = pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize()
        close = bars.Close.astype(float)
        momentum = (close / close.shift(p['regime_window']) - 1).reindex(sessions)
        if not np.isfinite(momentum.to_numpy()).all():
            raise ValueError('required causal regime features missing')
        regimes = np.where(momentum.to_numpy() >= p['regime_threshold'], 'bull', 'bear')
        pending = False
        holding = False
        active_route = None
        last_exit_reason = None
        age = 0
        anchor = peak = 0.
        targets, reasons, positions, opportunities, passes, contexts = [], [], [], [], [], []
        pending_before, pending_after, blocked_flags, release_flags = [], [], [], []
        refresh_opportunities, armed_flags, ages = [], [], []
        for i, regime in enumerate(regimes):
            pending_before.append(pending)
            released = (pending and not holding and
                        (regime != 'bear' or features['bear'].range_position.iloc[i] > p['bear']['entry']
                         or (p['bear']['acf_min'] is not None and
                             features['bear'].acf1.iloc[i] < p['bear']['acf_min'])
                         or (p['bear']['momentum_min'] is not None and
                             features['bear'].momentum20.iloc[i] < p['bear']['momentum_min'])))
            if released:
                pending = False
            armed = False
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
            refresh_opportunity = opportunity and regime == 'bear'
            blocked = refresh_opportunity and pending
            passed = not applies or score.iloc[i] >= c['threshold']
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
                    armed = (active_route == 'bear' and reason == 'time' and
                             regime == 'bear' and row.range_position <= rp['entry'])
                    if armed:
                        pending = True
                    last_exit_reason = reason
                    active_route = None
                else:
                    reason = 'hold'
            elif eligible:
                if blocked:
                    reason = 'entry_refresh_rejected'
                elif passed:
                    holding = True
                    active_route = regime
                    age = 0
                    anchor = peak = row.close
                    last_exit_reason = None
                    reason = 'entry'
                else:
                    reason = 'confirmation_rejected'
            pending_after.append(pending)
            blocked_flags.append(blocked)
            release_flags.append(released)
            refresh_opportunities.append(refresh_opportunity)
            armed_flags.append(armed)
            ages.append(age)
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
            refresh_pending_before=pending_before, refresh_pending_after=pending_after,
            refresh_opportunity=refresh_opportunities, refresh_blocked=blocked_flags,
            refresh_released=release_flags, refresh_armed=armed_flags, holding_age=ages)
