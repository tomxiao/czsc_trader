"""Independent original/winsor same-cutoff consensus bear ACF20 oracle; no strategy import."""
from dataclasses import dataclass
from common import SOURCE_CALLS

import numpy as np
import pandas as pd

MECHANISM = 'BEAR_CONSENSUS_ACF20'


def validate(p):
    assert set(p) == {'bull', 'bear', 'regime_window', 'regime_threshold', 'exit_on_regime_change',
                      'context', 'confirmation', 'mechanism'}
    assert p['mechanism'] == MECHANISM
    assert type(p['regime_window']) is int and 5 <= p['regime_window'] <= 60
    assert type(p['regime_threshold']) is float and np.isfinite(p['regime_threshold']) and -.2 <= p['regime_threshold'] <= .2
    assert type(p['exit_on_regime_change']) is bool
    assert p['context'] == {'entry_gate': 'all', 'volume_basis': 'ADJUSTED', 'weighting': 'EQUAL_BLOCKS'}
    c = p['confirmation']
    assert c == {'enabled': True, 'profile': 'all', 'scope': 'both', 'orientation': 1,
                 'lookback': c['lookback'], 'threshold': c['threshold']}
    assert type(c['lookback']) is int and 40 <= c['lookback'] <= 120
    assert type(c['threshold']) is float and np.isfinite(c['threshold']) and -.5 <= c['threshold'] <= .5
    for route in ('bull', 'bear'):
        q = p[route]
        assert type(q['range_window']) is int and 21 <= q['range_window'] <= 360
        assert type(q['max_hold']) is int and 1 <= q['max_hold'] <= 60
        assert np.isfinite(q['entry']) and np.isfinite(q['exit']) and 0 <= q['entry'] < q['exit'] <= 1
        assert q['cooldown'] == 0
        for name in ('acf_min', 'momentum_min'):
            assert q[name] is None or np.isfinite(q[name])
        for name in ('stop_loss', 'trailing_stop'):
            assert q[name] is None or np.isfinite(q[name]) and 0 < q[name] < .5


@dataclass(frozen=True)
class Position:
    route: str | None = None
    age: int = 0
    anchor: float | None = None
    peak: float | None = None
    last_exit_reason: str | None = None


def state_path(features, p):
    """Independent event-priority derivation using an explicit immutable position."""
    validate(p)
    state, output = Position(), []
    for f in features.itertuples():
        assert f.regime in ('bull', 'bear')
        held = state.route is not None
        route = state.route if held else f.regime
        rule = p[route]
        position = float(getattr(f, route + '_range_position'))
        qualifies = all((position <= rule['entry'], rule['acf_min'] is None or (f.bear_acf_value if route == 'bear' else f.acf1) >= rule['acf_min'],
                        rule['momentum_min'] is None or f.momentum20 >= rule['momentum_min']))
        score_pass = bool(f.confirmation_score >= p['confirmation']['threshold'])
        row = {'range_position': position, 'confirmation_opportunity': bool(not held and qualifies),
               'confirmation_pass': score_pass, 'confirmation_exit_context': state.last_exit_reason or 'initial',
               '_route_before': state.route, '_age_before': state.age, '_anchor_before': state.anchor}
        if held:
            assert state.anchor is not None and state.peak is not None
            age, peak = state.age + 1, max(state.peak, f.close)
            predicates = (
                ('loss', rule['stop_loss'] is not None and f.close / state.anchor - 1 <= -rule['stop_loss']),
                ('trailing', rule['trailing_stop'] is not None and f.close / peak - 1 <= -rule['trailing_stop']),
                ('range', position >= rule['exit']), ('time', age >= rule['max_hold']),
                ('regime', p['exit_on_regime_change'] and f.regime != state.route),
            )
            triggered = [(priority, reason) for priority, (reason, yes) in enumerate(predicates) if yes]
            reason = min(triggered)[1] if triggered else 'hold'
            state = (Position(last_exit_reason=reason) if triggered else
                     Position(state.route, age, state.anchor, peak, state.last_exit_reason))
        elif qualifies and score_pass:
            reason, state = 'entry', Position(f.regime, 0, f.close, f.close)
        else:
            reason = 'confirmation_rejected' if qualifies else 'flat'
        row.update(signal_reason=reason, target_position=float(state.route is not None))
        output.append(row)
    frame = pd.DataFrame(output, index=features.index)
    for name in ('_route_before', '_anchor_before'):
        frame[name] = pd.Series([row[name] for row in output], index=features.index, dtype=object)
    return frame


def winsor_acf(values):
    """Python order statistics and time-preserving list clamp; original ACF formula."""
    values = np.asarray(values, dtype=float)
    assert values.shape == (20,) and np.isfinite(values).all(), 'Exactly20 finite original simple returns required'
    ordered = sorted(float(value) for value in values)
    lower, upper = ordered[1], ordered[18]
    transformed = [max(lower, min(float(value), upper)) for value in values]
    sample = np.asarray(transformed, dtype=float)
    centered = sample - sample.mean()
    variance = float(np.mean(centered ** 2))
    assert not np.isclose(variance, 0), 'Undefined original near-zero variance after winsorization; no fallback/filter'
    value = float(np.dot(centered[1:], centered[:-1]) / 19 / variance)
    assert np.isfinite(value), 'Nonfinite winsorized correlation'
    return value



def consensus_acf(values):
    """Two independently defined scalar statistics, Python min; no short circuit."""
    sample = np.asarray(values, dtype=float)
    assert sample.shape == (20,) and np.isfinite(sample).all(), 'Exactly20 finite original simple returns required'
    centered = sample - sample.mean()
    variance = float(np.mean(centered ** 2))
    assert not np.isclose(variance, 0), 'Undefined original near-zero raw variance; no fallback/filter'
    raw = float(np.dot(centered[1:], centered[:-1]) / 19 / variance)
    assert np.isfinite(raw), 'Nonfinite original raw correlation'
    winsor = winsor_acf(sample)
    return min(raw, winsor)


def reconstruct(bars, dates, p):
    validate(p)
    assert bars.index.is_unique and bars.index.is_monotonic_increasing
    assert dates.is_unique and dates.is_monotonic_increasing and dates.isin(bars.index).all()
    for name in ('Open', 'High', 'Low', 'Close', 'Volume', 'Amount'):
        assert np.isfinite(bars[name]).all() and bars[name].gt(0).all(), name
    close = bars.Close.astype(float)
    returns = close.pct_change(fill_method=None)
    def acf20(values):
        values = values - values.mean()
        variance = np.mean(values * values)
        return np.nan if np.isclose(variance, 0) else float(np.dot(values[1:], values[:-1]) / 19 / variance)
    def midrank(values):
        return float((np.count_nonzero(values < values[-1]) + .5 * np.count_nonzero(values == values[-1])) / len(values) - .5)
    acf = returns.rolling(20).apply(acf20, raw=True)
    raw = pd.DataFrame({'acf': acf, 'turnover': bars.Amount.astype(float) / bars.Amount.astype(float).rolling(20).mean(),
                         'volume': np.log(bars.Volume.astype(float)).diff().rolling(20).mean()}, index=bars.index)
    ranks = raw.apply(lambda col: col.rolling(p['confirmation']['lookback']).apply(midrank, raw=True)).reindex(dates)
    positions = {}
    for route in ('bull', 'bear'):
        low, high = bars.Low.rolling(p[route]['range_window']).min(), bars.High.rolling(p[route]['range_window']).max()
        positions[route] = ((close - low) / (high - low)).reindex(dates)
    momentum = (close / close.shift(p['regime_window']) - 1).reindex(dates)
    locations = bars.index.get_indexer(dates)
    assert np.all(locations >= 20), '21 Close prices required for20 returns'
    bear_consensus = [consensus_acf(returns.iloc[i-19:i+1].to_numpy()) for i in locations]
    feature = pd.DataFrame({'acf1': acf.reindex(dates), 'close': close.reindex(dates),
        'momentum20': (close / close.shift(20) - 1).reindex(dates), 'regime_momentum': momentum,
        'regime': np.where(momentum >= p['regime_threshold'], 'bull', 'bear'),
        'bull_range_position': positions['bull'], 'bear_range_position': positions['bear'],
        'confirmation_acf': ranks.acf, 'confirmation_turnover': ranks.turnover, 'confirmation_volume': ranks.volume,
        'confirmation_score': .5 * ranks.acf + .25 * ranks.turnover + .25 * ranks.volume,
        'bear_acf_value': bear_consensus}, index=dates)
    assert np.isfinite(feature.select_dtypes(include='number').to_numpy()).all(), 'Complete causal parent warmup/features required'
    state = state_path(feature, p)
    for name in state:
        feature[name] = state[name]
    return feature


def audit_consensus(ctx, bound, frame, p):
    assert p == bound.strategy.payload['parameters']
    assert len(bound.input_bindings) == 1
    binding = next(iter(bound.input_bindings.values()))
    assert binding.prepared is not None
    result = ctx.data.fetch(binding.plan.requests['daily'], prepared=binding.prepared)
    assert result.ready and not SOURCE_CALLS
    bars = result.dataframe.copy()
    bars.index = pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize().as_unit('ns')
    dates = pd.DatetimeIndex(pd.to_datetime(frame.signal_date)).normalize().as_unit('ns')
    expected = reconstruct(bars, dates, p)
    fields = [column for column in expected if not column.startswith('_')]
    assert set(fields).issubset(frame.columns)
    for column in fields:
        np.testing.assert_array_equal(frame[column].to_numpy(), expected[column].to_numpy(), err_msg=column)
    calendar = _audit_dates(ctx, bound, binding, frame, dates, bars)
    assert np.array_equal(expected.signal_reason.eq('entry'), expected.confirmation_opportunity & expected.confirmation_pass)
    groups = []
    for year in ('ALL', *sorted(set(dates.year))):
        yearly = np.ones(len(dates), dtype=bool) if year == 'ALL' else dates.year == year
        for route in ('bull', 'bear'):
            mask = yearly & expected.regime.eq(route).to_numpy()
            groups.append({'year': str(year), 'regime': route, 'signal_days': int(mask.sum()),
                'negative_bear_consensus_days': int((mask & expected.bear_acf_value.lt(0)).sum()),
                'reasons': {str(k): int(v) for k, v in expected.loc[mask, 'signal_reason'].value_counts().items()}})
    return {'status': 'PASS', 'signal_days': len(dates), 'fields': fields, 'calendar': calendar, 'groups': groups,
        'limits': 'Independent causal signals/date only; original13 numeric geometry retained, changed same-cutoff raw/winsor consensus semantics; no cash replay or economic improvement claim.'}



def _audit_dates(ctx, bound, binding, frame, dates, bars):
    """Use the bound calendar/execute dates, never a T+1 signal price."""
    dates = dates.as_unit('ns')
    plan = binding.plan
    request = plan.requests[plan.calendar_name]
    calendar = ctx.data.fetch(request, prepared=binding.prepared)
    assert calendar.ready and not SOURCE_CALLS, 'Existing prepared calendar required; no fallback'
    assert calendar.identity.content_sha256 == plan.calendar_sha256, 'Bound calendar identity drift'
    data = calendar.dataframe
    calendar_dates = pd.DatetimeIndex(pd.to_datetime(data.Date)).normalize().as_unit('ns')
    assert calendar_dates.is_unique and calendar_dates.is_monotonic_increasing
    pd.testing.assert_index_equal(calendar_dates, pd.date_range(request.start, request.end).as_unit('ns'), check_names=False)
    assert data.IsOpen.isin((0, 1)).all(), 'Invalid public calendar open flag'
    opened = calendar_dates[data.IsOpen.to_numpy() == 1]
    pd.testing.assert_index_equal(opened, pd.DatetimeIndex(plan.calendar_dates).as_unit('ns'), check_names=False)
    previous = pd.DatetimeIndex(pd.to_datetime(data.loc[data.IsOpen.eq(1), 'PreviousTradingDate'])).normalize().as_unit('ns')
    pd.testing.assert_index_equal(previous[1:], opened[:-1], check_names=False)
    assert np.all(previous < opened), 'Public previous-session relation must be strict'
    window = plan.tradable_window
    expected_valid = opened[(opened >= pd.Timestamp(window.start)) & (opened <= pd.Timestamp(window.end))]
    locations = opened.get_indexer(expected_valid)
    assert len(expected_valid) and np.all(locations > 0), 'Complete pre-window signal calendar required'
    expected_signals = opened[locations - 1]
    pd.testing.assert_index_equal(dates, expected_signals, check_names=False)
    actual_valid = pd.DatetimeIndex(pd.to_datetime(frame.valid_session)).normalize().as_unit('ns')
    pd.testing.assert_index_equal(actual_valid, expected_valid, check_names=False)
    assert dict(plan.signal_dates) == {valid.date(): signal.date()
        for valid, signal in zip(expected_valid, expected_signals, strict=True)}, 'Entire public signal mapping drift'
    # Execution preparation covers first T through final T+1, while the signal
    # OHLC request correctly stops at final T. Only dates below are inspected.
    execution_dates = pd.DatetimeIndex(pd.to_datetime(bound.execution_data.execution_daily.dt)).normalize().as_unit('ns')
    assert execution_dates.is_unique and execution_dates.is_monotonic_increasing
    execution_expected = expected_signals.union(expected_valid).sort_values()
    pd.testing.assert_index_equal(execution_dates, execution_expected, check_names=False)
    pd.testing.assert_index_equal(pd.DatetimeIndex(bound.execution_data.evaluation_sessions).normalize().as_unit('ns'),
                                  expected_valid, check_names=False)
    pd.testing.assert_index_equal(bars.index.as_unit('ns').intersection(execution_dates), expected_signals, check_names=False)
    signal_locations = execution_dates.get_indexer(dates)
    assert np.all(signal_locations >= 0) and np.all(signal_locations + 1 < len(execution_dates))
    pd.testing.assert_index_equal(execution_dates[signal_locations + 1], actual_valid, check_names=False)
    return {'source': 'Existing prepared bound calendar and execution_daily date sequence',
            'calendar_sha256': plan.calendar_sha256, 'exact_signal_execute_pairs': len(dates),
            'first_signal': dates[0].date().isoformat(), 'last_signal': dates[-1].date().isoformat(),
            'first_valid_session': actual_valid[0].date().isoformat(),
            'last_valid_session': actual_valid[-1].date().isoformat(),
            'final_signal_ohlc_date': bars.index[-1].date().isoformat(),
            'future_signal_prices_used': False, 'final_pair_retained': True}
