"""Independent raw-ACF signal-price-classified bear TIME-reentry oracle with bound dates.

Only signal predicates and the complete signal state are audited. Counts are
descriptive; this module never prepares/evaluates an account or predicts profit.
"""
import numpy as np
import pandas as pd
from dataflows import canonical_frame_sha256
from common import SOURCE_CALLS


MECHANISMS = frozenset(('RAW_BEAR_TIME_BELOW_BODY_ACF_RECOVERY',))


def _exit_category(close, anchor):
    """Strict price comparison at the final bear TIME signal; not trade PnL."""
    assert np.isfinite(close) and np.isfinite(anchor) and close > 0 and anchor > 0
    return 'BELOW' if close < anchor else 'ABOVE' if close > anchor else 'EQUAL'


def _reconstruct(bars, dates, p):
    """Recompute formulas and state without importing any strategy functions."""
    _validate_parameters(p)
    assert bars.index.is_unique and bars.index.is_monotonic_increasing
    assert dates.is_unique and dates.is_monotonic_increasing and dates.isin(bars.index).all()
    mechanism = p['mechanism']
    assert mechanism in MECHANISMS
    assert p['context'] == {'entry_gate': 'all', 'volume_basis': 'ADJUSTED',
                            'weighting': 'EQUAL_BLOCKS'}
    c = p['confirmation']
    assert c['enabled'] is True and c['profile'] == 'all'
    assert c['scope'] == 'both' and c['orientation'] == 1
    assert all(p[route]['cooldown'] == 0 for route in ('bull', 'bear'))
    assert type(c['lookback']) is int and 40 <= c['lookback'] <= 120
    assert np.isfinite(c['threshold'])
    close, opening, amount, volume = (bars[name].astype(float)
                                      for name in ('Close', 'Open', 'Amount', 'Volume'))
    for name in ('Close', 'Open', 'High', 'Low', 'Amount', 'Volume'):
        assert np.isfinite(bars[name]).all() and (bars[name] > 0).all(), name

    def covariance(items):
        centered = items - items.mean()
        variance = np.mean(centered ** 2)
        return np.nan if np.isclose(variance, 0) else float(
            np.dot(centered[1:], centered[:-1]) / 19 / variance)

    def rank(items):
        return float((np.count_nonzero(items < items[-1])
                      + .5 * np.count_nonzero(items == items[-1])) / len(items) - .5)

    full_acf = close.pct_change(fill_method=None).rolling(20).apply(covariance, raw=True)
    raw = pd.DataFrame({'acf': full_acf, 'turnover': amount / amount.rolling(20).mean(),
                        'volume': np.log(volume).diff().rolling(20).mean()}, index=bars.index)
    normalized = raw.apply(lambda series: series.rolling(c['lookback'],
        min_periods=c['lookback']).apply(rank, raw=True)).reindex(dates)
    assert np.isfinite(normalized.to_numpy()).all(), 'Incomplete causal score warmup'
    score = .5 * normalized.acf + .25 * normalized.turnover + .25 * normalized.volume
    raw_acf = full_acf.reindex(dates)
    positions = {route: ((close - bars.Low.rolling(p[route]['range_window']).min()) /
        (bars.High.rolling(p[route]['range_window']).max()
         - bars.Low.rolling(p[route]['range_window']).min())).reindex(dates)
        for route in ('bull', 'bear')}
    momentum20 = (close / close.shift(20) - 1).reindex(dates)
    full_momentum = close / close.shift(p['regime_window']) - 1
    momentum = full_momentum.reindex(dates)
    signal_close, signal_open, previous_close = close.reindex(dates), opening.reindex(dates), close.shift(1).reindex(dates)
    for series in (raw_acf, *positions.values(), momentum20, momentum,
                   signal_close, signal_open, previous_close):
        assert np.isfinite(series).all(), 'Incomplete causal input history'
    regimes = np.where(momentum >= p['regime_threshold'], 'bull', 'bear')
    direction = (signal_close > signal_open).to_numpy()
    expected = pd.DataFrame({'acf1': raw_acf, 'close': signal_close, 'momentum20': momentum20,
        'regime_momentum': momentum, 'regime': regimes,
        'bull_range_position': positions['bull'], 'bear_range_position': positions['bear'],
        'confirmation_score': score, 'confirmation_acf': normalized.acf,
        'confirmation_turnover': normalized.turnover, 'confirmation_volume': normalized.volume,
        'bear_acf_raw': raw_acf,
        'entry_signal_close': signal_close, 'entry_signal_open': signal_open,
        'previous_signal_close': previous_close, 'entry_direction_up': direction}, index=dates)
    return _state_path(expected, p)


def _state_path(features, p):
    """Independent state recurrence; features are causal and do not seed state."""
    expected = features.copy()
    assert np.isfinite(expected.acf1.to_numpy()).all(), 'Required original raw ACF must be finite even for recovery'
    c = p['confirmation']
    holding, active, age, anchor, peak, last, last_route, category = False, None, 0, 0., 0., None, None, None
    records = []
    for i in range(len(expected)):
        route = active if holding else str(expected.regime.iloc[i])
        rp, position = p[route], expected[f'{route}_range_position'].iloc[i]
        entry_acf = expected.acf1.iloc[i]
        acf_pass = rp['acf_min'] is None or entry_acf >= rp['acf_min']
        range_pass = bool(position <= rp['entry'])
        momentum_pass = bool(rp['momentum_min'] is None or expected.momentum20.iloc[i] >= rp['momentum_min'])
        recovery = bool(not holding and not acf_pass and range_pass and momentum_pass
                        and expected.regime.iloc[i] == 'bear' and last == 'time'
                        and last_route == 'bear' and category == 'BELOW'
                        and expected.entry_direction_up.iloc[i])
        eligible = bool(range_pass and momentum_pass and (acf_pass or recovery))
        opportunity = bool(not holding and eligible)
        passed = bool(expected.confirmation_score.iloc[i] >= c['threshold'])
        gate = False
        record = {'holding_before': holding, 'route_before': active,
            'age_before': age if holding else 0, 'active_route': route, 'eligible': eligible,
            'range_position': float(position), 'entry_acf_value': float(entry_acf),
            'entry_acf_pass': bool(acf_pass), 'entry_acf_recovery_applies': recovery,
            'entry_eligible': eligible, 'confirmation_opportunity': opportunity,
            'confirmation_pass': passed, 'confirmation_exit_context': last or 'initial',
            'entry_direction_gate_applies': gate, 'last_exit_reason': last, 'last_exit_route': last_route,
            'last_exit_category': category}
        reason = 'flat'
        if holding:
            age += 1
            peak = max(peak, expected.close.iloc[i])
            loss = rp['stop_loss'] is not None and expected.close.iloc[i] / anchor - 1 <= -rp['stop_loss']
            trail = rp['trailing_stop'] is not None and expected.close.iloc[i] / peak - 1 <= -rp['trailing_stop']
            reason = ('loss' if loss else 'trailing' if trail else 'range' if position >= rp['exit']
                else 'time' if age >= rp['max_hold'] else 'regime'
                if p['exit_on_regime_change'] and expected.regime.iloc[i] != active else 'hold')
            if reason != 'hold':
                category = (_exit_category(expected.close.iloc[i], anchor)
                            if reason == 'time' and active == 'bear' else None)
                holding, active, last, last_route = False, None, reason, active
        elif eligible:
            reason = 'entry' if passed else 'confirmation_rejected'
            if reason == 'entry':
                holding, active, age = True, str(expected.regime.iloc[i]), 0
                anchor = peak = expected.close.iloc[i]
                last = last_route = category = None
        record.update(signal_reason=reason, target_position=float(holding))
        records.append(record)
    states = pd.DataFrame(records, index=expected.index)
    for name in ('route_before', 'last_exit_reason', 'last_exit_route', 'last_exit_category'):
        states[name] = pd.Series([record[name] for record in records], index=expected.index, dtype=object)
    for name in states:
        expected[name] = states[name]
    return expected


def _validate_parameters(p):
    """Respect original units/domains without casting any numeric parameter."""
    assert set(p) == {'bull', 'bear', 'regime_window', 'regime_threshold',
                      'exit_on_regime_change', 'confirmation', 'context', 'mechanism'}
    assert p['mechanism'] in MECHANISMS
    assert type(p['regime_window']) is int and 5 <= p['regime_window'] <= 60
    assert type(p['regime_threshold']) is float and -.2 <= p['regime_threshold'] <= .2
    assert type(p['exit_on_regime_change']) is bool
    c = p['confirmation']
    assert set(c) == {'enabled', 'profile', 'scope', 'orientation', 'lookback', 'threshold'}
    assert type(c['lookback']) is int and 40 <= c['lookback'] <= 120
    assert type(c['threshold']) is float and -.5 <= c['threshold'] <= .5
    assert c['enabled'] is True and c['profile'] == 'all' and c['scope'] == 'both'
    assert type(c['orientation']) is int and c['orientation'] == 1
    assert p['context'] == {'entry_gate': 'all', 'volume_basis': 'ADJUSTED', 'weighting': 'EQUAL_BLOCKS'}
    for route in ('bull', 'bear'):
        r = p[route]
        assert set(r) == {'range_window', 'entry', 'exit', 'max_hold', 'acf_min',
                          'stop_loss', 'trailing_stop', 'cooldown', 'momentum_min', 'limit_premium'}
        assert type(r['range_window']) is int and 21 <= r['range_window'] <= 360
        assert 0 <= r['entry'] < r['exit'] <= 1
        assert type(r['max_hold']) is int and 1 <= r['max_hold'] <= 60
        assert type(r['cooldown']) is int and r['cooldown'] == 0
        for key in ('stop_loss', 'trailing_stop'):
            assert r[key] is None or 0 < r[key] < .5
        for key in ('acf_min', 'momentum_min'):
            assert r[key] is None or np.isfinite(r[key])
        assert 0 <= r['limit_premium'] < .09
    assert p['bull']['limit_premium'] == p['bear']['limit_premium']



def _audit_dates(ctx, bound, binding, frame, dates, bars):
    """Use the bound calendar/execute dates, never a T+1 signal price."""
    dates = dates.as_unit('ns')
    plan = binding.plan
    request = plan.requests[plan.calendar_name]
    calendar = ctx.data.fetch(request, prepared=binding.prepared)
    assert calendar.ready and not SOURCE_CALLS, 'Existing prepared calendar required; no fallback'
    assert calendar.identity.content_sha256 == plan.calendar_sha256, 'Bound calendar identity drift'
    assert canonical_frame_sha256(calendar.dataframe) == calendar.identity.content_sha256, 'Prepared calendar bytes drift'
    assert calendar.identity.dataset == str(request.dataset) and calendar.identity.symbol == request.symbol
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



def _assert_exit_metadata(actual, expected, name):
    """Compare only nullable signal metadata; all financial fields remain exact."""
    categories = {'last_exit_reason': {'time', 'regime', 'range', 'loss', 'trailing'},
                  'last_exit_route': {'bull', 'bear'},
                  'last_exit_category': {'BELOW', 'EQUAL', 'ABOVE'}}
    assert name in categories
    actual, expected = np.asarray(actual, dtype=object), np.asarray(expected, dtype=object)
    assert actual.shape == expected.shape
    missing = np.array([value is None for value in expected])
    for i, (value, wanted) in enumerate(zip(actual, expected, strict=True)):
        if missing[i]:
            assert value is None or isinstance(value, (float, np.floating)) and np.isnan(value), name
        else:
            assert isinstance(wanted, str) and wanted in categories[name], name
            assert isinstance(value, str) and value == wanted, (name, i, value, wanted)
    return int(missing.sum())


def audit_raw_recovery(ctx, bound, frame, p):
    """Authenticate all features/state and predecision exit category from own signal-entry anchor."""
    assert p == bound.strategy.payload['parameters'], 'Audit the actual bound parameters'
    assert len(bound.input_bindings) == 1
    binding = next(iter(bound.input_bindings.values()))
    assert binding.prepared is not None, 'Prepared S013 input required'
    request = binding.plan.requests['daily']
    fetched = ctx.data.fetch(request, prepared=binding.prepared)
    assert fetched.ready and not SOURCE_CALLS, 'Existing prepared data must be ready; no preparation or fallback'
    assert canonical_frame_sha256(fetched.dataframe) == fetched.identity.content_sha256, 'Prepared daily bytes drift'
    assert fetched.identity.dataset == str(request.dataset) and fetched.identity.symbol == request.symbol, 'Prepared daily identity/request drift'
    assert request.symbol == '510500.SH', 'Only authorized S013 instrument'
    bars = fetched.dataframe.copy()
    bars.index = pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize()
    assert bars.index.is_unique and bars.index.is_monotonic_increasing
    assert bars.index[0] >= pd.Timestamp(request.start) and bars.index[-1] <= pd.Timestamp(request.end)
    dates = pd.DatetimeIndex(pd.to_datetime(frame.signal_date)).normalize()
    assert len(dates) and dates.is_unique and dates.is_monotonic_increasing
    assert dates.isin(bars.index).all()
    expected = _reconstruct(bars, dates, p)
    # State before the decision is internal oracle state, not strategy output.
    internal = {'holding_before', 'route_before', 'age_before', 'active_route', 'eligible'}
    audited = [name for name in expected if name not in internal]
    assert set(audited).issubset(frame.columns), 'Missing native audit fields'
    nullable_counts = {}
    for name in audited:
        if name in ('last_exit_reason', 'last_exit_route', 'last_exit_category'):
            nullable_counts[name] = _assert_exit_metadata(frame[name].to_numpy(), expected[name].to_numpy(), name)
        else:
            np.testing.assert_array_equal(frame[name].to_numpy(), expected[name].to_numpy(), err_msg=name)
    date_audit = _audit_dates(ctx, bound, binding, frame, dates, bars)
    assert bars.index[-1] == dates[-1], 'Daily prepared request must stop at last T signal'
    years = sorted(set(dates.year))
    groups = []
    for year in ['ALL', *years]:
        year_mask = np.ones(len(dates), bool) if year == 'ALL' else dates.year == year
        for route in ('bull', 'bear'):
            mask = year_mask & expected.regime.eq(route).to_numpy()
            opportunity = mask & expected.confirmation_opportunity.to_numpy(bool)
            passed = expected.confirmation_pass.to_numpy(bool)
            gate = expected.entry_direction_gate_applies.to_numpy(bool)
            direction = expected.entry_direction_up.to_numpy(bool)
            entry = expected.signal_reason.eq('entry').to_numpy()
            refused = expected.signal_reason.eq('entry_direction_rejected').to_numpy()
            score_refused = expected.signal_reason.eq('confirmation_rejected').to_numpy()
            assert np.array_equal(entry, expected.confirmation_opportunity.to_numpy(bool) & (~gate | direction) & passed)
            assert np.array_equal(refused, gate & ~direction)
            assert np.array_equal(score_refused, expected.confirmation_opportunity.to_numpy(bool) & (~gate | direction) & ~passed)
            groups.append({'year': str(year), 'route': route, 'signal_days': int(mask.sum()),
                'original_eligible_flat_opportunities': int((opportunity & expected.entry_acf_pass.to_numpy(bool)).sum()),
                'enhanced_eligible_flat_opportunities': int(opportunity.sum()),
                'acf_recovery_opportunities': int((mask & expected.entry_acf_recovery_applies.to_numpy(bool)).sum()),
                'acf_recovery_entries': int((mask & expected.entry_acf_recovery_applies.to_numpy(bool) & entry).sum()),
                'acf_recovery_score_rejections': int((mask & expected.entry_acf_recovery_applies.to_numpy(bool) & ~passed).sum()),
                'score_pass_opportunities': int((opportunity & passed).sum()),
                'direction_gate_opportunities': int((mask & gate).sum()),
                'direction_rejected_opportunities': int((mask & refused).sum()),
                'score_rejected_after_direction': int((mask & score_refused).sum()),
                'both_direction_and_score_reject': int((opportunity & gate & ~direction & ~passed).sum()),
                'signal_entries': int((mask & entry).sum()),
                'signal_reasons': {str(k): int(v) for k, v in expected.loc[mask, 'signal_reason'].value_counts().items()}})
    for key in ('signal_days', 'original_eligible_flat_opportunities', 'enhanced_eligible_flat_opportunities',
                'acf_recovery_opportunities', 'acf_recovery_entries', 'acf_recovery_score_rejections', 'signal_entries'):
        assert sum(row[key] for row in groups if row['year'] == 'ALL') == sum(
            row[key] for row in groups if row['year'] != 'ALL')
    return {'status': 'PASS', 'mechanism': p['mechanism'], 'signal_days': len(dates),
        'confirmation_threshold': float(p['confirmation']['threshold']), 'date_audit': date_audit,
        'prepared_data_authentication': {'daily_content_sha256': fetched.identity.content_sha256,
            'prepared_manifest_sha256': binding.prepared.manifest_sha256,
            'prepared_space_id': str(binding.prepared.space_id),
            'preparation_id': str(binding.prepared.preparation_id),
            'request': {'dataset': str(request.dataset), 'symbol': request.symbol,
                        'start': str(request.start), 'end': str(request.end)},
            'existing_prepared_fetch_only': True, 'canonical_daily_bytes_checked': True},
        'nullable_exit_metadata_absences': nullable_counts,
        'exit_category_counts': {key: int(expected.last_exit_category.eq(key).sum())
            for key in ('BELOW', 'EQUAL', 'ABOVE')},
        'audited_fields': audited + ['signal_date', 'valid_session'], 'groups': groups,
        'limits': 'Complete native signal path, retained predecision exit memory and strictly classified bear TIME price state, and all signal years; counts only. No changed cash replay, profit attribution, forecast or independent validation.'}
