"""Fixed midpoint correction of the selected-route causal volatility-time predicate."""
import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from .reentry_confirmed_range import ReentryConfirmedRange
from .confirmed_range import PROFILES, confirmation_features
from .range_reversion import components


class MidpointVolatilityTimeRange(ReentryConfirmedRange):
    def __init__(self, parameters):
        p = parameters.values
        if p.get('mechanism') not in ('BEAR_MIDPOINT_VOLATILITY_TIME', 'ALL_MIDPOINT_VOLATILITY_TIME'):
            raise ValueError('explicit fixed route volatility-time mechanism required')
        if p.get('confirmation', {}).get('enabled') is not True:
            raise ValueError('original buy confirmation must remain enabled')
        super().__init__(ParameterSet({key: value for key, value in p.items() if key != 'mechanism'}))
        self._parameters = parameters
        # Current true range needs prevClose; its past20 baseline requires 22 prices.
        self._warmup = max(self._warmup, 22)

    def calculate_history(self, inputs, sessions):
        p = self._parameters.values
        c, settings = p['confirmation'], p['context']
        daily = inputs['daily']
        if not {'Date', 'High', 'Low', 'Close'}.issubset(daily.columns):
            raise ValueError('complete signal Date/High/Low/Close required')
        prices = daily.loc[:, ['High', 'Low', 'Close']].to_numpy(dtype=float)
        if not np.isfinite(prices).all() or (prices <= 0).any() or (prices[:, 0] < prices[:, 1]).any():
            raise ValueError('signal High/Low/Close must be finite positive with High >= Low')
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
        previous_close = close.shift(1)
        true_range = pd.concat((bars.High.astype(float) - bars.Low.astype(float),
                                (bars.High.astype(float) - previous_close).abs(),
                                (bars.Low.astype(float) - previous_close).abs()), axis=1).max(axis=1)
        all_volatility = true_range / previous_close
        finite_volatility = all_volatility.where(np.isfinite(all_volatility.to_numpy()))
        reference = finite_volatility.shift(1).rolling(20, min_periods=20).mean().reindex(sessions)
        volatility = all_volatility.reindex(sessions)
        if (not np.isfinite(volatility.to_numpy()).all() or not np.isfinite(reference.to_numpy()).all()
                or (reference <= 0.).any()):
            raise ValueError('complete causal volatility and positive strictly past20 mean required')
        increments = volatility / reference
        if not np.isfinite(increments.to_numpy()).all() or (increments < 0.).any():
            raise ValueError('volatility clock increments must be finite nonnegative')
        momentum = (close / close.shift(p['regime_window']) - 1).reindex(sessions)
        if not np.isfinite(momentum.to_numpy()).all():
            raise ValueError('required causal regime features missing')
        regimes = np.where(momentum.to_numpy() >= p['regime_threshold'], 'bull', 'bear')
        holding = False
        active_route = None
        last_exit_reason = None
        age = 0
        clock = 0.
        anchor = peak = 0.
        targets, reasons, positions, opportunities, passes, contexts = [], [], [], [], [], []
        clocks, ages, time_conditions, time_triggers = [], [], [], []
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
            time_condition = time_trigger = False
            if holding:
                age += 1
                clock += increments.iloc[i]
                peak = max(peak, row.close)
                loss = rp['stop_loss'] is not None and row.close / anchor - 1 <= -rp['stop_loss']
                trail = rp['trailing_stop'] is not None and row.close / peak - 1 <= -rp['trailing_stop']
                selected = p['mechanism'] == 'ALL_MIDPOINT_VOLATILITY_TIME' or active_route == 'bear'
                time_condition = clock + .5 >= rp['max_hold'] if selected else age >= rp['max_hold']
                time_trigger = time_condition and not loss and not trail and row.range_position < rp['exit']
                changed = p['exit_on_regime_change'] and regime != active_route
                if loss or trail or row.range_position >= rp['exit'] or time_condition or changed:
                    holding = False
                    reason = ('loss' if loss else 'trailing' if trail else
                              'range' if row.range_position >= rp['exit'] else
                              'time' if time_condition else 'regime')
                    last_exit_reason = reason
                    active_route = None
                else:
                    reason = 'hold'
            elif eligible:
                if passed:
                    holding = True
                    active_route = regime
                    age = 0
                    clock = 0.
                    anchor = peak = row.close
                    last_exit_reason = None
                    reason = 'entry'
                else:
                    reason = 'confirmation_rejected'
            clocks.append(clock)
            ages.append(age)
            time_conditions.append(time_condition)
            time_triggers.append(time_trigger)
            targets.append(float(holding))
            reasons.append(reason)
        return features['bull'].assign(range_position=positions, target_position=targets,
            signal_reason=reasons, regime=regimes, regime_momentum=momentum,
            volatility_range_pct=volatility, volatility_reference_mean20=reference,
            volatility_clock_increment=increments, holding_clock=clocks, holding_age=ages,
            time_exit_condition=time_conditions, time_exit_trigger=time_triggers,
            bull_range_position=features['bull'].range_position,
            bear_range_position=features['bear'].range_position,
            confirmation_score=score, confirmation_acf=normalized.acf,
            confirmation_turnover=normalized.turnover, confirmation_volume=normalized.volume,
            confirmation_opportunity=opportunities, confirmation_pass=passes,
            confirmation_exit_context=contexts)
