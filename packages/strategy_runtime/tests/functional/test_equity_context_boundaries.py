"""Public context boundaries retained when avoiding redundant scalar work."""
from dataclasses import replace
from datetime import timedelta

import pandas as pd
import pytest
from dataflows import BarFrequency, TimeInterval, TradingSession
from strategy_runtime import DecisionPoint

from test_equity_context import build, fixture, make_candidate


@pytest.mark.parametrize('representation', ['utc', 'new_york', 'strings', 'nullable'])
def test_context_timestamp_and_numeric_representations(tmp_path, representation):
    value, data = make_candidate(tmp_path), fixture()
    auxiliary = data[1].copy(deep=True)
    if representation == 'new_york':
        for field in ('Date', 'AvailableDate'):
            auxiliary[field] = auxiliary[field].dt.tz_convert('America/New_York')
    elif representation == 'strings':
        for field in ('Date', 'AvailableDate'):
            auxiliary[field] = auxiliary[field].map(lambda item: item.isoformat())
    elif representation == 'nullable':
        auxiliary['Volume'] = auxiliary.Volume.astype('Float64')
    original = auxiliary.copy(deep=True)
    context = build(value, data, auxiliary_histories={'market': auxiliary})
    assert context.auxiliary_histories['market'].Close.tolist() == [10., 11.]
    assert value.decide(context).target == 1
    pd.testing.assert_frame_equal(auxiliary, original)


@pytest.mark.parametrize(('field', 'bad'), [('Close', float('nan')), ('Close', float('inf')),
    ('Close', float('-inf')), ('Amount', float('nan')), ('Amount', float('inf')),
    ('Amount', -1.), ('Volume', 0.), ('Close', 1 + 2j)])
def test_context_rejects_invalid_observed_numeric_values(tmp_path, field, bad):
    value, data = make_candidate(tmp_path), fixture()
    auxiliary = data[1].copy(deep=True)
    if field == 'Amount':
        auxiliary[field] = 1000.
    if isinstance(bad, complex):
        auxiliary[field] = auxiliary[field].astype(complex)
    auxiliary.loc[1, field] = bad
    with pytest.raises((TypeError, ValueError)):
        build(value, data, auxiliary_histories={'market': auxiliary})


@pytest.mark.parametrize('bad_time', ['naive', 'nat'])
def test_context_rejects_invalid_timestamp_even_outside_visible_prefix(tmp_path, bad_time):
    value, data = make_candidate(tmp_path), fixture()
    auxiliary = data[1].copy(deep=True)
    if bad_time == 'naive':
        auxiliary['Date'] = auxiliary.Date.dt.tz_localize(None)
    else:
        auxiliary.loc[2, 'Date'] = pd.NaT
    with pytest.raises(ValueError, match='aware finite timestamps'):
        build(value, data, auxiliary_histories={'market': auxiliary})


def test_context_checks_incomplete_noncurrent_session_and_daily_interval(tmp_path):
    value, data = make_candidate(tmp_path), fixture()
    current = data[4][0]
    previous_start = current.segments[0].start - timedelta(days=1)
    previous = TradingSession(current.session_date - timedelta(days=1), current.timezone,
        (TimeInterval(previous_start, previous_start + timedelta(minutes=31)),))
    table = pd.concat([pd.DataFrame({'Date': [previous_start], 'AvailableDate': [previous_start],
        'SessionDate': [previous.session_date.isoformat()]}), data[3]], ignore_index=True)
    with pytest.raises(ValueError, match='incomplete 30-minute interval'):
        build(value, data, sessions=table, trading_sessions=(previous, current))
    # DAILY bars span the session boundaries; odd-length historical segments
    # are legal for this frequency and must not acquire an M30 restriction.
    daily = replace(value, definition=replace(value.definition, execution_spec=replace(
        value.definition.execution_spec, decision_clock=BarFrequency.DAILY)))
    interval = TimeInterval(current.segments[0].start, current.segments[-1].end)
    point = DecisionPoint(interval.start, interval.start, interval)
    shifted = data[0].copy(deep=True)
    shifted['Date'] -= timedelta(days=1)
    shifted['AvailableDate'] -= timedelta(days=1)
    daily = replace(daily, definition=replace(daily.definition, auxiliary_inputs=()))
    context = build(daily, (shifted, data[1], point, table, (previous, current)))
    assert context.session == current
    assert daily.decide(context).target == 0


def test_context_keeps_unique_session_matching_and_split_session_gap(tmp_path):
    value, data = make_candidate(tmp_path), fixture()
    current = data[4][0]
    overlap = TradingSession(current.session_date + timedelta(days=1), 'Pacific/Kiritimati',
                              current.segments)
    table = pd.concat([data[3], pd.DataFrame({'Date': [overlap.segments[0].start],
        'AvailableDate': [overlap.segments[0].start],
        'SessionDate': [overlap.session_date.isoformat()]})], ignore_index=True)
    with pytest.raises(ValueError, match='no unique session'):
        build(value, data, sessions=table, trading_sessions=(current, overlap))
    interval = data[2].execution_interval
    split = TradingSession(current.session_date, current.timezone, (
        TimeInterval(current.segments[0].start, interval.start),
        TimeInterval(interval.end, current.segments[-1].end)))
    with pytest.raises(ValueError, match='no unique session'):
        build(value, data, trading_sessions=(split,))
