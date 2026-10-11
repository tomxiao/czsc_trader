"""Mean-centered ACF with direction gates in fixed bear TIME exit-price contexts."""
import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from .reentry_confirmed_range import ReentryConfirmedRange
from .confirmed_range import PROFILES, confirmation_features
from .range_reversion import components


class MechanismRange(ReentryConfirmedRange):
    def __init__(self, parameters):
        p = parameters.values
        if p.get('mechanism') not in (
                'MEAN_BEAR_TIME_BELOW_CLOSE', 'MEAN_BEAR_TIME_BELOW_BODY',
                'MEAN_BEAR_TIME_ABOVE_CLOSE', 'MEAN_BEAR_TIME_ABOVE_BODY',
                'MEAN_BEAR_TIME_BELOW_SEGMENT_CLOSE'):
            raise ValueError('explicit mean bear TIME exit-category direction mechanism required')
        if p.get('confirmation', {}).get('enabled') is not True:
            raise ValueError('original buy confirmation must remain enabled')
        super().__init__(ParameterSet({key: value for key, value in p.items() if key != 'mechanism'}))
        self._parameters = parameters
        # ACF20 needs 21 prices; L past estimates plus current need L+21.
        self._warmup = max(self._warmup, p['confirmation']['lookback'] + 21 if p['mechanism'].startswith('MEAN_') else 0,
                           p['regime_window'] + 2)

    def calculate_history(self, inputs, sessions):
        p = self._parameters.values
        c, settings = p['confirmation'], p['context']
        daily = inputs['daily']
        if not {'Date', 'Open', 'Close'}.issubset(daily.columns):
            raise ValueError('complete signal Date/Open/Close required')
        prices = daily.loc[:, ['Open', 'Close']].to_numpy(dtype=float)
        if not np.isfinite(prices).all() or (prices <= 0).any():
            raise ValueError('signal Open/Close must be finite and positive')
        all_features = {key: components(inputs['daily'], p[key]['range_window']) for key in ('bull', 'bear')}
        raw_bear_acf = all_features['bear'].acf1
        is_mean = p['mechanism'].startswith('MEAN_')
        if is_mean:
            finite_bear_acf = raw_bear_acf.where(np.isfinite(raw_bear_acf.to_numpy()))
            baseline_length = c['lookback']
            rolling = finite_bear_acf.shift(1).rolling(baseline_length, min_periods=baseline_length)
            baseline_bear_acf = rolling.mean().reindex(sessions)
            centered_bear_acf = raw_bear_acf.reindex(sessions) - baseline_bear_acf
            if not np.isfinite(baseline_bear_acf.to_numpy()).all() or not np.isfinite(centered_bear_acf.to_numpy()).all():
                raise ValueError('complete finite strictly past bear ACF baseline and current estimate required')
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
        signal_close = close.reindex(sessions)
        signal_open = bars.Open.astype(float).reindex(sessions)
        previous_close = close.shift(1).reindex(sessions)
        if not np.isfinite(np.column_stack((signal_close, signal_open, previous_close))).all():
            raise ValueError('complete current and previous signal prices required')
        direction = (signal_close > previous_close if p['mechanism'].endswith('_CLOSE')
                     else signal_close > signal_open).to_numpy()
        all_momentum = close / close.shift(p['regime_window']) - 1
        momentum = all_momentum.reindex(sessions)
        previous_momentum = all_momentum.shift(1).reindex(sessions)
        if not (np.isfinite(momentum.to_numpy()).all() and np.isfinite(previous_momentum.to_numpy()).all()):
            raise ValueError('required current and previous causal regime features missing')
        regimes = np.where(momentum.to_numpy() >= p['regime_threshold'], 'bull', 'bear')
        previous_regimes = np.where(previous_momentum.to_numpy() >= p['regime_threshold'], 'bull', 'bear')
        holding = False
        active_route = None
        last_exit_reason = None
        last_exit_route = None
        last_exit_category = None
        selected_category = 'BELOW' if '_BELOW_' in p['mechanism'] else 'ABOVE'
        age = 0
        anchor = peak = 0.
        targets, reasons, positions, opportunities, passes, contexts = [], [], [], [], [], []
        entry_acf_values, entry_acf_passes, direction_gate_applies = [], [], []
        previous_exit_reasons, previous_exit_routes, previous_exit_categories = [], [], []
        for i, regime in enumerate(regimes):
            if p['mechanism'] == 'MEAN_BEAR_TIME_BELOW_SEGMENT_CLOSE' and not holding and regime == 'bull':
                last_exit_category = None
            previous_exit_reasons.append(last_exit_reason)
            previous_exit_routes.append(last_exit_route)
            previous_exit_categories.append(last_exit_category)
            route = active_route if holding else regime
            rp = p[route]
            row = features[route].iloc[i]
            positions.append(row.range_position)
            entry_acf = centered_bear_acf.iloc[i] if is_mean and route == 'bear' else row.acf1
            acf_pass = rp['acf_min'] is None or entry_acf >= rp['acf_min']
            entry_acf_values.append(entry_acf)
            entry_acf_passes.append(acf_pass)
            eligible = (row.range_position <= rp['entry']
                        and acf_pass
                        and (rp['momentum_min'] is None or row.momentum20 >= rp['momentum_min']))
            applies = (c['scope'] in ('both', regime)
                       and (settings['entry_gate'] == 'all' or last_exit_reason == 'regime'))
            opportunity = not holding and eligible
            direction_applies = (opportunity and regime == 'bear'
                                 and last_exit_reason == 'time' and last_exit_route == 'bear'
                                 and last_exit_category == selected_category)
            direction_gate_applies.append(bool(direction_applies))
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
                    last_exit_reason = reason
                    last_exit_route = active_route
                    # Classify only the final bear TIME exit against this signal episode's anchor.
                    last_exit_category = (
                        'BELOW' if row.close < anchor else 'ABOVE' if row.close > anchor else 'EQUAL'
                    ) if reason == 'time' and active_route == 'bear' else None
                    if (p['mechanism'] == 'MEAN_BEAR_TIME_BELOW_SEGMENT_CLOSE'
                            and reason == 'time' and active_route == 'bear' and regime == 'bull'):
                        last_exit_category = None
                    active_route = None
                else:
                    reason = 'hold'
            elif eligible:
                # Only the selected past bear TIME price category gains direction refusal.
                if direction_applies and not direction[i]:
                    reason = 'entry_direction_rejected'
                elif passed:
                    holding = True
                    active_route = regime
                    age = 0
                    anchor = peak = row.close
                    last_exit_reason = None
                    last_exit_route = None
                    last_exit_category = None
                    reason = 'entry'
                else:
                    reason = 'confirmation_rejected'
            targets.append(float(holding))
            reasons.append(reason)
        history = features['bull'].assign(range_position=positions, target_position=targets,
            signal_reason=reasons, regime=regimes, regime_momentum=momentum,
            previous_regime=previous_regimes, previous_regime_momentum=previous_momentum,
            entry_direction_gate_applies=direction_gate_applies,
            entry_direction_up=direction, previous_signal_close=previous_close,
            entry_signal_close=signal_close, entry_signal_open=signal_open,
            bull_range_position=features['bull'].range_position,
            bear_range_position=features['bear'].range_position,
            confirmation_score=score, confirmation_acf=normalized.acf,
            confirmation_turnover=normalized.turnover, confirmation_volume=normalized.volume,
            confirmation_opportunity=opportunities, confirmation_pass=passes,
            confirmation_exit_context=contexts,
            last_exit_reason=pd.Series(previous_exit_reasons, index=sessions, dtype=object),
            last_exit_route=pd.Series(previous_exit_routes, index=sessions, dtype=object),
            last_exit_category=pd.Series(previous_exit_categories, index=sessions, dtype=object),
            bear_acf_raw=raw_bear_acf.reindex(sessions),
            entry_acf_value=entry_acf_values, entry_acf_pass=entry_acf_passes)
        if is_mean:
            history = history.assign(bear_acf_baseline=baseline_bear_acf,
                                     bear_acf_centered=centered_bear_acf)
        return history
