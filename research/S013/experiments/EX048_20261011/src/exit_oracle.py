"""Independent BEAR_EXIT_BULL2 formulas/state; prepared bindings only, no account replay."""
import numpy as np
import pandas as pd

from common import SOURCE_CALLS
MECHANISM = 'BEAR_EXIT_BULL2'


def _validate(p):
    assert p['mechanism'] == MECHANISM
    assert type(p['exit_on_regime_change']) is bool
    assert p['context'] == {'entry_gate': 'all', 'volume_basis': 'ADJUSTED', 'weighting': 'EQUAL_BLOCKS'}
    c = p['confirmation']
    assert c['enabled'] is True and c['profile'] == 'all' and c['scope'] == 'both' and c['orientation'] == 1
    assert type(c['lookback']) is int and 40 <= c['lookback'] <= 120
    assert type(c['threshold']) is float and np.isfinite(c['threshold']) and -.5 <= c['threshold'] <= .5
    assert type(p['regime_window']) is int and 5 <= p['regime_window'] <= 60
    assert np.isfinite(p['regime_threshold']) and -.2 <= p['regime_threshold'] <= .2
    for route in ('bull', 'bear'):
        q = p[route]
        assert q['cooldown'] == 0
        assert type(q['range_window']) is int and 21 <= q['range_window'] <= 360
        assert 0 <= q['entry'] < q['exit'] <= 1
        assert type(q['max_hold']) is int and 1 <= q['max_hold'] <= 60
        for key in ('acf_min', 'momentum_min'):
            assert q[key] is None or np.isfinite(q[key])
        for key in ('stop_loss', 'trailing_stop'):
            assert q[key] is None or 0 < q[key] < .5


def _states(features, p):
    """One complete signal state path; no fills/cash or use of runtime functions."""
    _validate(p)
    holding, active, age, anchor, peak, last = False, None, 0, 0., 0., None
    records = []
    for feature in features.itertuples():
        raw = str(feature.regime)
        previous = str(feature.previous_regime)
        assert raw in ('bull', 'bear') and previous in ('bull', 'bear')
        route = active if holding else raw
        q = p[route]
        position = getattr(feature, route + '_range_position')
        eligible = bool(position <= q['entry'] and (q['acf_min'] is None or feature.acf1 >= q['acf_min'])
            and (q['momentum_min'] is None or feature.momentum20 >= q['momentum_min']))
        opportunity = bool(not holding and eligible)
        passed = bool(feature.confirmation_score >= p['confirmation']['threshold'])
        confirmed = bool(holding and (raw == 'bear' if active == 'bull' else raw == previous == 'bull'))
        condition = confirmed and p['exit_on_regime_change']
        record = {'holding_before': holding, 'route_before': active, 'age_before': age if holding else 0,
            'active_route': route, 'eligible': eligible, 'range_position': float(position),
            'confirmation_opportunity': opportunity, 'confirmation_pass': passed,
            'confirmation_exit_context': last or 'initial', 'entry_regime_confirmed': True,
            'exit_regime_confirmed': confirmed, 'regime_exit_condition': bool(condition)}
        reason, trigger = 'flat', False
        if holding:
            age += 1
            peak = max(peak, feature.close)
            loss = q['stop_loss'] is not None and feature.close / anchor - 1 <= -q['stop_loss']
            trail = q['trailing_stop'] is not None and feature.close / peak - 1 <= -q['trailing_stop']
            reason = ('loss' if loss else 'trailing' if trail else 'range' if position >= q['exit']
                else 'time' if age >= q['max_hold'] else 'regime' if condition else 'hold')
            trigger = reason == 'regime'
            if reason != 'hold':
                holding, active, last = False, None, reason
        elif eligible:
            reason = 'entry' if passed else 'confirmation_rejected'
            if passed:
                holding, active, age = True, raw, 0
                anchor = peak = feature.close
                last = None
        record.update(regime_exit_trigger=bool(trigger), target_position=float(holding), signal_reason=reason)
        records.append(record)
    state = pd.DataFrame(records, index=features.index)
    state['route_before'] = pd.Series([row['route_before'] for row in records], index=features.index, dtype=object)
    return state


def _reconstruct(bars, dates, p):
    _validate(p)
    assert bars.index.is_unique and bars.index.is_monotonic_increasing
    assert dates.is_unique and dates.is_monotonic_increasing and dates.isin(bars.index).all()
    for name in ('Open', 'High', 'Low', 'Close', 'Amount', 'Volume'):
        assert np.isfinite(bars[name]).all() and (bars[name] > 0).all(), name
    close = bars.Close.astype(float)
    def covariance(items):
        centered = items - items.mean()
        variance = np.mean(centered ** 2)
        return np.nan if np.isclose(variance, 0) else float(np.dot(centered[1:], centered[:-1]) / 19 / variance)
    def rank(items):
        return float((np.count_nonzero(items < items[-1]) + .5 * np.count_nonzero(items == items[-1])) / len(items) - .5)
    acf = close.pct_change(fill_method=None).rolling(20).apply(covariance, raw=True)
    raw = pd.DataFrame({'acf': acf, 'turnover': bars.Amount.astype(float) / bars.Amount.astype(float).rolling(20).mean(),
        'volume': np.log(bars.Volume.astype(float)).diff().rolling(20).mean()}, index=bars.index)
    c = p['confirmation']
    normalized = raw.apply(lambda col: col.rolling(c['lookback'], min_periods=c['lookback']).apply(rank, raw=True)).reindex(dates)
    positions = {route: ((close - bars.Low.rolling(p[route]['range_window']).min()) /
        (bars.High.rolling(p[route]['range_window']).max() - bars.Low.rolling(p[route]['range_window']).min())).reindex(dates)
        for route in ('bull', 'bear')}
    momentum = close / close.shift(p['regime_window']) - 1
    current, previous = momentum.reindex(dates), momentum.shift(1).reindex(dates)
    expected = pd.DataFrame({'acf1': acf.reindex(dates), 'close': close.reindex(dates),
        'momentum20': (close / close.shift(20) - 1).reindex(dates), 'regime_momentum': current,
        'previous_regime_momentum': previous, 'regime': np.where(current >= p['regime_threshold'], 'bull', 'bear'),
        'previous_regime': np.where(previous >= p['regime_threshold'], 'bull', 'bear'),
        'bull_range_position': positions['bull'], 'bear_range_position': positions['bear'],
        'confirmation_acf': normalized.acf, 'confirmation_turnover': normalized.turnover,
        'confirmation_volume': normalized.volume, 'confirmation_score': .5 * normalized.acf + .25 * normalized.turnover + .25 * normalized.volume}, index=dates)
    numeric = expected.select_dtypes(include='number')
    assert np.isfinite(numeric.to_numpy()).all(), 'Incomplete causal features/score/previous rawregime warmup'
    states = _states(expected, p)
    for name in states:
        expected[name] = states[name]
    return expected


def audit_exit(ctx, bound, frame, p):
    """Exact all-date prepared signal/date audit; no financial-account replay."""
    assert p == bound.strategy.payload['parameters']
    assert len(bound.input_bindings) == 1
    binding = next(iter(bound.input_bindings.values()))
    assert binding.prepared is not None
    fetched = ctx.data.fetch(binding.plan.requests['daily'], prepared=binding.prepared)
    assert fetched.ready and not SOURCE_CALLS
    bars = fetched.dataframe.copy()
    bars.index = pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize().as_unit('ns')
    dates = pd.DatetimeIndex(pd.to_datetime(frame.signal_date)).normalize().as_unit('ns')
    expected = _reconstruct(bars, dates, p)
    internal = {'holding_before', 'route_before', 'age_before', 'active_route', 'eligible'}
    audited = [name for name in expected if name not in internal]
    assert set(audited).issubset(frame.columns)
    for name in audited:
        np.testing.assert_array_equal(frame[name].to_numpy(), expected[name].to_numpy(), err_msg=name)
    calendar = _audit_dates(ctx, bound, binding, frame, dates, bars)
    assert np.array_equal(expected.signal_reason.eq('entry'), expected.confirmation_opportunity & expected.confirmation_pass)
    assert np.array_equal(expected.signal_reason.eq('regime'), expected.regime_exit_trigger)
    groups = []
    for year in ('ALL', *sorted(set(dates.year))):
        yy = np.ones(len(dates), dtype=bool) if year == 'ALL' else dates.year == year
        for route in ('bull', 'bear'):
            mask = yy & expected.regime.eq(route).to_numpy()
            groups.append({'year': str(year), 'raw_route': route, 'signal_days': int(mask.sum()),
                'confirmed_exit_days': int((mask & expected.exit_regime_confirmed).sum()),
                'regime_condition_days': int((mask & expected.regime_exit_condition).sum()),
                'regime_trigger_days': int((mask & expected.regime_exit_trigger).sum()),
                'signal_entries': int((mask & expected.signal_reason.eq('entry')).sum()),
                'signal_reasons': {str(k): int(v) for k, v in expected.loc[mask, 'signal_reason'].value_counts().items()}})
    return {'status': 'PASS', 'mechanism': MECHANISM, 'signal_days': len(dates), 'audited_fields': audited,
        'calendar': calendar, 'groups': groups,
        'limits': 'Independent full13 causal formulas/state/date certification only; no account evaluation, profit forecast or cash replay.'}


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
