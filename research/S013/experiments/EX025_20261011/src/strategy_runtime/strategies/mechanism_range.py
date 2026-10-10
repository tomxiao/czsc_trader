"""Signal-anchor protection for bull holdings, with optional boundary BODY entry."""
import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from .reentry_confirmed_range import ReentryConfirmedRange
from .confirmed_range import PROFILES, confirmation_features
from .range_reversion import components


class MechanismRange(ReentryConfirmedRange):
    def __init__(self, parameters):
        p = parameters.values
        if p.get('mechanism') not in ('BULL_ANCHOR_LOSS', 'NEW_BULL_BODY_ANCHOR_LOSS'):
            raise ValueError('explicit bull signal-anchor protection mechanism required')
        if p['confirmation']['enabled'] is not True:
            raise ValueError('original buy confirmation must remain enabled')
        super().__init__(ParameterSet({key: value for key, value in p.items() if key != 'mechanism'}))
        self._parameters = parameters
        self._warmup = max(self._warmup, p['regime_window'] + 2)

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
        direction = (signal_close > signal_open).to_numpy()
        all_momentum = close / close.shift(p['regime_window']) - 1
        momentum = all_momentum.reindex(sessions)
        previous_momentum = all_momentum.shift(1).reindex(sessions)
        if not (np.isfinite(momentum.to_numpy()).all() and np.isfinite(previous_momentum.to_numpy()).all()):
            raise ValueError('required current and previous causal regime features missing')
        regimes = np.where(momentum.to_numpy() >= p['regime_threshold'], 'bull', 'bear')
        previous_regimes = np.where(previous_momentum.to_numpy() >= p['regime_threshold'], 'bull', 'bear')
        body_gate = p['mechanism'] == 'NEW_BULL_BODY_ANCHOR_LOSS'
        direction_gate_applies = body_gate & (regimes == 'bull') & (previous_regimes == 'bear')
        holding = False
        active_route = None
        last_exit_reason = None
        age = 0
        anchor = peak = 0.
        targets, reasons, positions, opportunities, passes, contexts = [], [], [], [], [], []
        anchor_conditions, anchor_triggers, entry_anchors = [], [], []
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
            passed = not applies or score.iloc[i] >= c['threshold']
            opportunities.append(opportunity)
            passes.append(passed)
            contexts.append(last_exit_reason or 'initial')
            reason = 'flat'
            anchor_condition = anchor_trigger = False
            entry_anchor = anchor
            if holding:
                age += 1
                peak = max(peak, row.close)
                loss = rp['stop_loss'] is not None and row.close / anchor - 1 <= -rp['stop_loss']
                trail = rp['trailing_stop'] is not None and row.close / peak - 1 <= -rp['trailing_stop']
                changed = p['exit_on_regime_change'] and regime != active_route
                anchor_condition = active_route == 'bull' and age >= 1 and signal_close.iloc[i] < anchor
                if loss or trail or anchor_condition or row.range_position >= rp['exit'] or age >= rp['max_hold'] or changed:
                    holding = False
                    reason = ('loss' if loss else 'trailing' if trail else
                              'bull_anchor_loss' if anchor_condition else
                              'range' if row.range_position >= rp['exit'] else
                              'time' if age >= rp['max_hold'] else 'regime')
                    anchor_trigger = reason == 'bull_anchor_loss'
                    last_exit_reason = reason
                    active_route = None
                else:
                    reason = 'hold'
            elif eligible:
                # Direction refusal precedes score refusal; score pass retains its original meaning.
                if direction_gate_applies[i] and not direction[i]:
                    reason = 'entry_direction_rejected'
                elif passed:
                    holding = True
                    active_route = regime
                    age = 0
                    anchor = peak = row.close
                    entry_anchor = anchor
                    last_exit_reason = None
                    reason = 'entry'
                else:
                    reason = 'confirmation_rejected'
            targets.append(float(holding))
            reasons.append(reason)
            anchor_conditions.append(bool(anchor_condition))
            anchor_triggers.append(bool(anchor_trigger))
            entry_anchors.append(entry_anchor)
        return features['bull'].assign(range_position=positions, target_position=targets,
            signal_reason=reasons, regime=regimes, regime_momentum=momentum,
            previous_regime=previous_regimes, previous_regime_momentum=previous_momentum,
            entry_direction_gate_applies=direction_gate_applies,
            bull_range_position=features['bull'].range_position,
            bear_range_position=features['bear'].range_position,
            confirmation_score=score, confirmation_acf=normalized.acf,
            confirmation_turnover=normalized.turnover, confirmation_volume=normalized.volume,
            confirmation_opportunity=opportunities, confirmation_pass=passes,
            confirmation_exit_context=contexts, entry_direction_up=direction,
            previous_signal_close=previous_close, entry_signal_open=signal_open,
            entry_signal_close=signal_close, entry_anchor_signal_close=entry_anchors,
            bull_anchor_loss_condition=anchor_conditions, bull_anchor_loss_trigger=anchor_triggers)
