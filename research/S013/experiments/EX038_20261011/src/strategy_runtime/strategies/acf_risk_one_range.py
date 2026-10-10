"""Past-mean bear ACF backgrounds with fixed one-past-TR20 risk exit."""
import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from .acf_background_range import AcfRange as BackgroundAcfRange
from .confirmed_range import PROFILES, confirmation_features
from .range_reversion import components


class AcfRange(BackgroundAcfRange):
    def __init__(self, parameters):
        p = parameters.values
        if p.get('mechanism') not in ('BEAR_MEAN_ACF_ADVERSE_TR', 'BEAR_MEAN_ACF_BODY_ADVERSE_TR'):
            raise ValueError('explicit past-mean bear ACF and adverse-TR mechanism required')
        if p.get('confirmation', {}).get('enabled') is not True:
            raise ValueError('original buy confirmation must remain enabled')
        background = dict(p)
        background['mechanism'] = 'MEAN_ACF_NEW_BULL_BODY'
        super().__init__(ParameterSet(background))
        self._parameters = parameters
        # ACF20 needs 21 prices; L past estimates plus current need L+21.
        self._warmup = max(self._warmup, p['confirmation']['lookback'] + 21,
                           p['regime_window'] + 2, 22)

    def calculate_history(self, inputs, sessions):
        p = self._parameters.values
        c, settings = p['confirmation'], p['context']
        daily = inputs['daily']
        if not {'Date', 'Open', 'High', 'Low', 'Close'}.issubset(daily.columns):
            raise ValueError('complete signal Date/OHLC required')
        prices = daily.loc[:, ['Open', 'High', 'Low', 'Close']].to_numpy(dtype=float)
        if not np.isfinite(prices).all() or (prices <= 0).any():
            raise ValueError('signal OHLC must be finite and positive')
        if (daily.High.to_numpy(dtype=float) < daily.Low.to_numpy(dtype=float)).any():
            raise ValueError('signal High must be at least Low')
        if ((daily.High.to_numpy(dtype=float) < daily.loc[:, ['Open', 'Close']].max(axis=1).to_numpy()).any()
                or (daily.Low.to_numpy(dtype=float) > daily.loc[:, ['Open', 'Close']].min(axis=1).to_numpy()).any()):
            raise ValueError('signal Open/Close must lie within Low/High')
        all_features = {key: components(inputs['daily'], p[key]['range_window']) for key in ('bull', 'bear')}
        raw_bear_acf = all_features['bear'].acf1
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
        if not bars.index.is_unique or not bars.index.is_monotonic_increasing:
            raise ValueError('signal dates must be unique and ordered')
        close = bars.Close.astype(float)
        previous = close.shift(1)
        high, low = bars.High.astype(float), bars.Low.astype(float)
        true_range = pd.Series(np.maximum.reduce((
            (high - low).to_numpy(), (high - previous).abs().to_numpy(),
            (low - previous).abs().to_numpy())), index=bars.index)
        reference = true_range.shift(1).rolling(20, min_periods=20).mean().reindex(sessions)
        signal_true_range = true_range.reindex(sessions)
        if (not np.isfinite(reference.to_numpy()).all() or (reference <= 0).any()
                or not np.isfinite(signal_true_range.to_numpy()).all()
                or (signal_true_range < 0).any()):
            raise ValueError('complete finite TR and strictly positive past20 reference required')
        signal_close = close.reindex(sessions)
        signal_open = bars.Open.astype(float).reindex(sessions)
        previous_close = close.shift(1).reindex(sessions)
        if not np.isfinite(np.column_stack((signal_close, signal_open, previous_close))).all():
            raise ValueError('complete current and previous signal prices required')
        direction = (signal_close > signal_open).to_numpy()
        all_momentum = close / close.shift(p['regime_window']) - 1
        momentum = all_momentum.reindex(sessions)
        previous_momentum = all_momentum.shift(1).reindex(sessions)
        if not (np.isfinite(momentum.to_numpy()).all() and np.isfinite(previous_momentum.to_numpy()).all()):
            raise ValueError('required current and previous causal regime features missing')
        regimes = np.where(momentum.to_numpy() >= p['regime_threshold'], 'bull', 'bear')
        previous_regimes = np.where(previous_momentum.to_numpy() >= p['regime_threshold'], 'bull', 'bear')
        direction_gate_applies = ((regimes == 'bull') & (previous_regimes == 'bear')
                                  & (p['mechanism'] == 'BEAR_MEAN_ACF_BODY_ADVERSE_TR'))
        holding = False
        active_route = None
        last_exit_reason = None
        age = 0
        anchor = peak = 0.
        targets, reasons, positions, opportunities, passes, contexts = [], [], [], [], [], []
        entry_acf_values, entry_acf_passes = [], []
        anchors, ages, displacements, risk_hits, risk_triggers = [], [], [], [], []
        for i, regime in enumerate(regimes):
            route = active_route if holding else regime
            rp = p[route]
            row = features[route].iloc[i]
            positions.append(row.range_position)
            entry_acf = centered_bear_acf.iloc[i] if route == 'bear' else row.acf1
            acf_pass = rp['acf_min'] is None or entry_acf >= rp['acf_min']
            entry_acf_values.append(entry_acf)
            entry_acf_passes.append(acf_pass)
            eligible = (row.range_position <= rp['entry']
                        and acf_pass
                        and (rp['momentum_min'] is None or row.momentum20 >= rp['momentum_min']))
            applies = (c['scope'] in ('both', regime)
                       and (settings['entry_gate'] == 'all' or last_exit_reason == 'regime'))
            opportunity = not holding and eligible
            passed = not applies or score.iloc[i] >= c['threshold']
            opportunities.append(opportunity)
            passes.append(passed)
            contexts.append(last_exit_reason or 'initial')
            reason = 'flat'
            displacement, risk_hit, risk_trigger = 0., False, False
            if holding:
                age += 1
                peak = max(peak, row.close)
                loss = rp['stop_loss'] is not None and row.close / anchor - 1 <= -rp['stop_loss']
                trail = rp['trailing_stop'] is not None and row.close / peak - 1 <= -rp['trailing_stop']
                changed = p['exit_on_regime_change'] and regime != active_route
                if active_route == 'bear':
                    displacement = max(anchor - signal_close.iloc[i], 0.)
                    risk_hit = age >= 1 and displacement >= reference.iloc[i]
                    risk_trigger = risk_hit and not loss and not trail
                if loss or trail or risk_trigger or row.range_position >= rp['exit'] or age >= rp['max_hold'] or changed:
                    holding = False
                    reason = ('loss' if loss else 'trailing' if trail else
                              'bear_risk' if risk_trigger else 'range' if row.range_position >= rp['exit'] else
                              'time' if age >= rp['max_hold'] else 'regime')
                    last_exit_reason = reason
                    active_route = None
                else:
                    reason = 'hold'
            elif eligible:
                # The boundary direction refusal precedes the unchanged score refusal.
                if direction_gate_applies[i] and not direction[i]:
                    reason = 'entry_direction_rejected'
                elif passed:
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
            anchors.append(anchor)
            ages.append(age)
            displacements.append(displacement)
            risk_hits.append(bool(risk_hit))
            risk_triggers.append(bool(risk_trigger))
        return features['bull'].assign(range_position=positions, target_position=targets,
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
            bear_acf_raw=raw_bear_acf.reindex(sessions),
            bear_acf_baseline=baseline_bear_acf,
            bear_acf_centered=centered_bear_acf,
            entry_acf_value=entry_acf_values, entry_acf_pass=entry_acf_passes,
            risk_true_range_hfq=signal_true_range,
            risk_reference_mean20_hfq=reference,
            entry_anchor_signal_close=anchors, holding_age=ages,
            bear_adverse_displacement_hfq=displacements,
            bear_risk_hit=risk_hits, bear_risk_trigger=risk_triggers)
