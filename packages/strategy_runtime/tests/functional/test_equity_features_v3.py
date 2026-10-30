"""Visibility-versioned finite features, including nonmonotonic publication."""
from dataclasses import FrozenInstanceError
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import pickle
import warnings
from statistics import median

import numpy as np
import pandas as pd
import pytest

from strategy_runtime.equity_features import (BarField, FeatureGraph, HistoryView, Lag,
    Mean, NotReady, RawField, ReadyValue, SameLocalSlotMedian, TrueRange)
from strategy_runtime.equity_replay import PreparedReplay, _FeatureEvaluator, _Visibility


def observations(starts, closes=None):
    starts = pd.DatetimeIndex(starts)
    closes = [10.] * len(starts) if closes is None else closes
    return pd.DataFrame({'BarStart': starts, 'Date': starts + pd.Timedelta(minutes=30),
        'AvailableDate': starts + pd.Timedelta(minutes=30), 'Open': closes, 'High': [x + 1 for x in closes],
        'Low': [x - 1 for x in closes], 'Close': closes, 'Volume': 100., 'Amount': 1000.})


def prepare(frame, graph):
    constraints = pd.DataFrame({'Date': frame.BarStart, 'AvailableDate': frame.BarStart,
                                'QuantityStep': 1, 'PriceTick': .01, 'Tradable': True})
    return PreparedReplay.from_frames(frame, constraints, graph)


@pytest.mark.parametrize('zone,expected_identity', [
    ('UTC', 'ad4a9a1db5cc9a1ad4ce29ced77fbafc3a3de086fa32d44c65d88096cd477340'),
    ('America/New_York', 'e4b974f9cbad01b09549a088b0847e4b27bca0812146e6cc6bf17704ccaaee5f'),
])
@pytest.mark.parametrize('text_constraints', [False, True])
def test_bulk_datetime_preparation_preserves_established_identity(zone, expected_identity, text_constraints):
    stamps = pd.date_range('2024-11-01 09:30:00.000000123', periods=3, freq='30min', tz=zone)
    bars = observations(stamps)
    bars['BarStatus'], bars['ExecutionBlocked'] = 'OBSERVED', False
    bars.index = [7, 7, 9]
    constraints = pd.DataFrame({'Date': stamps, 'AvailableDate': stamps, 'QuantityStep': 1,
        'PriceTick': .01, 'Tradable': True, 'SettlementAt': stamps + pd.Timedelta(days=3)},
        index=bars.index)
    if text_constraints:
        for name in ('Date', 'AvailableDate', 'SettlementAt'):
            constraints[name] = constraints[name].map(lambda value: value.isoformat())
    original_bars, original_constraints = bars.copy(deep=True), constraints.copy(deep=True)
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='Discarding nonzero nanoseconds.*', category=UserWarning)
        value = PreparedReplay.from_frames(bars, constraints, FeatureGraph())
    assert value.identity == expected_identity
    assert type(value._data.rows[0]['Date']) is datetime
    assert type(value._data.constraints[0]['SettlementAt']) is datetime
    pd.testing.assert_frame_equal(bars, original_bars)
    pd.testing.assert_frame_equal(constraints, original_constraints)


@pytest.mark.parametrize('column', ['Date', 'AvailableDate', 'SettlementAt'])
def test_bulk_constraint_conversion_rejects_nat(column):
    bars = observations(pd.date_range('2024-11-01 14:30', periods=3, freq='30min', tz='UTC'))
    constraints = pd.DataFrame({'Date': bars.BarStart, 'AvailableDate': bars.BarStart,
        'QuantityStep': 1, 'PriceTick': .01, 'Tradable': True,
        'SettlementAt': bars.BarStart + pd.Timedelta(days=3)}).copy(deep=True)
    constraints.loc[1, column] = pd.NaT
    with pytest.raises(ValueError, match='constraint times must be aware and finite'):
        PreparedReplay.from_frames(bars, constraints, FeatureGraph())


def test_graph_types_cycles_roundtrip_and_numeric_order():
    graph = FeatureGraph((RawField('close', BarField.CLOSE), Lag('previous', 'close', 1),
                          Mean('mean', 'close', 3)), ('previous', 'mean'))
    assert FeatureGraph.from_dict(json.loads(json.dumps(graph.to_dict()))) == graph
    with pytest.raises(ValueError, match='cycle'):
        FeatureGraph((Lag('first', 'second', 1), Lag('second', 'first', 1)), ('first',))
    with pytest.raises(ValueError, match='undeclared'):
        FeatureGraph((Mean('mean', 'absent', 3),), ('mean',))
    with pytest.raises(TypeError):
        RawField('close', 'Close')
    with pytest.raises(ValueError):
        Lag('previous', 'close', True)
    with pytest.raises(ValueError, match='raw Volume'):
        FeatureGraph((RawField('close', BarField.CLOSE), SameLocalSlotMedian('median', 'close')), ('median',))
    stamps = pd.date_range('2024-03-01 14:30', periods=4, freq='30min', tz='UTC')
    frame = observations(stamps, [1e16, 2., 2., 4.])
    prepared = prepare(frame, graph)
    visibility = _Visibility(prepared._data)
    visibility.advance(frame.Date.iloc[2].to_pydatetime())
    result = _FeatureEvaluator(prepared._data, graph, visibility).at(frame.Date.iloc[2])
    assert result.get('mean').value == sum([1e16, 2., 2.]) / 3


def test_late_bar_insertion_changes_current_asof_not_old_view():
    starts = pd.date_range('2024-03-01 14:30', periods=5, freq='30min', tz='UTC')
    frame = observations(starts, [10., 20., 30., 40., 50.])
    frame.loc[1, 'AvailableDate'] = frame.Date.iloc[3]
    graph = FeatureGraph((RawField('close', BarField.CLOSE), Lag('previous', 'close', 1),
                         Mean('mean', 'close', 3)), ('previous', 'mean'))
    prepared = prepare(frame, graph)
    visibility = _Visibility(prepared._data)
    evaluator = _FeatureEvaluator(prepared._data, graph, visibility)
    earlier = frame.Date.iloc[2].to_pydatetime()
    visibility.advance(earlier)
    first = evaluator.at(earlier)
    history = visibility.history_view(earlier)
    assert first.get('previous') == ReadyValue(10.)
    assert type(first.get('mean')) is NotReady
    visibility.advance(frame.Date.iloc[3].to_pydatetime())
    later = evaluator.at(frame.Date.iloc[3].to_pydatetime())
    assert later.get('previous') == ReadyValue(30.)
    assert later.get('mean') == ReadyValue(30.)
    assert first.get('previous') == ReadyValue(10.)
    assert history.to_frame().Close.tolist() == [10., 30.]
    assert history.last(0)['Close'] == 30. and history.last(1)['Close'] == 10.
    with pytest.raises(TypeError):
        history.last(0).items().mapping['Close'] = -1
    assert not hasattr(history, '_data')  # No all-history/future storage capability reaches strategy.
    with pytest.raises(ValueError, match='unavailable'):
        HistoryView(earlier, visibility.history_root, visibility.count)
    copied = history.to_frame()
    copied.loc[0, 'Close'] = -1
    assert history.to_frame().Close.tolist() == [10., 30.]
    with pytest.raises(TypeError):
        prepared._data.rows[0]['Close'] = -1
    with pytest.raises((FrozenInstanceError, AttributeError)):
        first.as_of = later.as_of
    restored = pickle.loads(pickle.dumps(prepared))
    assert restored._data.rows[0]['Close'] == 10.
    saved_history = pickle.loads(pickle.dumps(history))
    assert saved_history.to_frame().Close.tolist() == [10., 30.]
    assert pickle.loads(pickle.dumps(first)).get('previous') == ReadyValue(10.)


def test_true_range_lagged_atr_and_unseen_future_values():
    frame = observations(pd.date_range('2024-03-01 14:30', periods=18, freq='30min', tz='UTC'))
    frame.loc[16, ['Open', 'High', 'Low', 'Close']] = [10., 20., 9., 19.]
    graph = FeatureGraph((RawField('close', BarField.CLOSE), RawField('high', BarField.HIGH),
        RawField('low', BarField.LOW), TrueRange('range', 'high', 'low', 'close'),
        Mean('atr', 'range', 13), Lag('before_prior', 'atr', 2)), ('atr', 'before_prior'))
    prepared = prepare(frame, graph)
    visibility = _Visibility(prepared._data)
    when = frame.Date.iloc[16].to_pydatetime()
    visibility.advance(when)
    value = _FeatureEvaluator(prepared._data, graph, visibility).at(when)
    assert value.get('before_prior') == ReadyValue(2.)
    assert value.get('atr') == ReadyValue((12 * 2. + 11.) / 13)
    altered = frame.copy()
    altered.loc[17, ['Open', 'High', 'Low', 'Close', 'Volume']] *= 3
    second = prepare(altered, graph)
    index = _Visibility(second._data)
    index.advance(when)
    assert _FeatureEvaluator(second._data, graph, index).at(when).get('atr') == value.get('atr')


def test_same_slot_twenty_distinct_days_DST_missing_slot_and_today_exclusion():
    stamps = []
    for index, day in enumerate(pd.bdate_range('2024-02-01', periods=35)):
        for minute in (570, 600, 930):
            if index == 20 and minute == 930:
                continue
            stamps.append((day + pd.Timedelta(minutes=minute)).tz_localize('America/New_York').tz_convert('UTC'))
    frame = observations(stamps)
    frame['Volume'] = range(1, len(frame) + 1)
    graph = FeatureGraph((RawField('volume', BarField.VOLUME),
        SameLocalSlotMedian('median', 'volume', 20, 0)), ('median',))
    prepared = prepare(frame, graph)
    visibility = _Visibility(prepared._data)
    when = frame.Date.iloc[-1].to_pydatetime()
    visibility.advance(when)
    result = _FeatureEvaluator(prepared._data, graph, visibility).at(when)
    local = frame.BarStart.dt.tz_convert('America/New_York')
    previous = frame.loc[(local.dt.date < local.iloc[-1].date()) & (local.dt.hour == 15)]
    assert previous.BarStart.dt.hour.nunique() == 2
    assert result.get('median') == ReadyValue(float(previous.Volume.iloc[-20:].median()))
    changed = frame.copy()
    changed.loc[local.dt.date == local.iloc[-1].date(), 'Volume'] = 1e12
    second = prepare(changed, graph)
    index = _Visibility(second._data)
    index.advance(when)
    assert _FeatureEvaluator(second._data, graph, index).at(when).get('median') == result.get('median')


def test_availability_latency_and_invalid_input_rejected():
    frame = observations([datetime(2024, 3, 1, 14, 30, tzinfo=timezone.utc)])
    graph = FeatureGraph((RawField('close', BarField.CLOSE),), ('close',))
    prepared = prepare(frame, graph)
    from dataclasses import replace
    data = replace(prepared._data, ready_at=(prepared._data.ready_at[0] + timedelta(seconds=1),))
    index = _Visibility(data)
    index.advance(frame.Date.iloc[0].to_pydatetime())
    assert index.count == 0
    invalid = frame.copy()
    invalid.loc[0, 'AvailableDate'] = frame.BarStart.iloc[0]
    with pytest.raises(ValueError, match='availability'):
        prepare(invalid, graph)


def test_visible_rank_and_persistent_tree_match_full_asof_oracle():
    starts = pd.date_range('2024-03-01 14:30', periods=45, freq='30min', tz='UTC')
    frame = observations(starts, [float(i + 10) for i in range(len(starts))])
    for index in range(len(frame)):
        frame.loc[index, 'AvailableDate'] += pd.Timedelta(minutes=30 * ((index * 17) % 9))
    prepared = prepare(frame, FeatureGraph())
    visibility = _Visibility(prepared._data)
    retained = []
    for when in sorted(set(prepared._data.ready_at)):
        visibility.advance(when)
        expected = [i for i, stamp in enumerate(prepared._data.ready_at) if stamp <= when]
        assert [visibility.row(offset) for offset in range(visibility.count)] == list(reversed(expected))
        view = visibility.history_view(when)
        assert view.to_frame().Close.tolist() == [float(i + 10) for i in expected]
        assert view.to_frame(tail=2).Close.tolist() == [float(i + 10) for i in expected[-2:]]
        retained.append((view, [float(i + 10) for i in expected]))
    for view, expected in retained:
        assert view.to_frame().Close.tolist() == expected


def test_prefix_mean_preserves_python_float_sum_compensation():
    frame = observations(pd.date_range('2024-03-01 14:30', periods=4, freq='30min', tz='UTC'),
                         [1e16, 1., 1., 5.])
    frame['Low'] = [max(.5, float(value) - 1.) for value in frame.Close]
    graph = FeatureGraph((RawField('close', BarField.CLOSE), Mean('mean', 'close', 3)), ('mean',))
    prepared = prepare(frame, graph)
    index = _Visibility(prepared._data)
    evaluator = _FeatureEvaluator(prepared._data, graph, index)
    assert evaluator._prefix_outputs is not None
    when = frame.Date.iloc[2].to_pydatetime()
    index.advance(when)
    assert evaluator.at(when).get('mean') == ReadyValue(sum([1e16, 1., 1.]) / 3)


@pytest.mark.parametrize('late', [False, True])
def test_bulk_prefix_and_general_asof_equal_independent_random_scalar(late):
    random = np.random.default_rng(930271)
    stamps = []
    for day_index, day in enumerate(pd.bdate_range('2024-02-01', periods=35)):
        for minute in (570, 600, 930):
            if day_index == 18 and minute >= 780:  # Actual half-day missing afternoon slots.
                continue
            stamps.append((day + pd.Timedelta(minutes=minute)).tz_localize('America/New_York').tz_convert('UTC'))
    closes = (100. + random.random(len(stamps)) * 10).tolist()
    frame = observations(stamps, closes)
    frame['Volume'] = random.uniform(1., 100000., len(frame))
    frame['BarStatus'] = 'OBSERVED'
    frame.loc[::37, 'BarStatus'] = 'ZERO_VOLUME'
    frame.loc[::37, 'Volume'] = 0.
    if late:
        frame.loc[11::17, 'AvailableDate'] += pd.Timedelta(days=2)
    graph = FeatureGraph((RawField('close', BarField.CLOSE), RawField('high', BarField.HIGH),
        RawField('low', BarField.LOW), RawField('volume', BarField.VOLUME),
        TrueRange('tr', 'high', 'low', 'close'), Mean('atr', 'tr', 13),
        Lag('before_prior', 'atr', 2), SameLocalSlotMedian('median', 'volume', 20, 1),
        Lag('median_lag', 'median', 3), Mean('median_mean', 'median', 3)),
        ('close', 'tr', 'atr', 'before_prior', 'median', 'median_lag', 'median_mean'))
    prepared = prepare(frame, graph)
    index = _Visibility(prepared._data)
    evaluator = _FeatureEvaluator(prepared._data, graph, index)
    assert (evaluator._prefix_outputs is None) is late
    records = frame.to_dict('records')
    for when in frame.Date:
        index.advance(when.to_pydatetime())
        view = evaluator.at(when.to_pydatetime())
        visible = [row for row in records if row['Date'] <= when and row['AvailableDate'] <= when
                   and row['BarStatus'] == 'OBSERVED']

        def true_range(position):
            if position < 1:
                return None
            current, previous = visible[position], visible[position - 1]
            return max(float(current['High'] - current['Low']),
                       abs(float(current['High'] - previous['Close'])),
                       abs(float(current['Low'] - previous['Close'])))

        def mean_range(position):
            if position < 13:
                return None
            return sum(true_range(j) for j in range(position - 12, position + 1)) / 13

        def slot_median(position):
            anchor_position = position - 1
            if anchor_position < 0:
                return None
            anchor = visible[anchor_position]['BarStart'].tz_convert('America/New_York')
            values = []
            seen_days = set()
            for row in reversed(visible[:anchor_position]):
                local = row['BarStart'].tz_convert('America/New_York')
                if (local.date() < anchor.date() and local.date() not in seen_days
                        and (local.hour, local.minute) == (anchor.hour, anchor.minute)):
                    values.append(float(row['Volume']))
                    seen_days.add(local.date())
                    if len(values) == 20:
                        return float(median(values))
            return None

        position = len(visible) - 1
        medians = [slot_median(j) for j in range(position - 2, position + 1)]
        expected = {'close': float(visible[-1]['Close']) if visible else None,
                    'tr': true_range(position), 'atr': mean_range(position),
                    'before_prior': mean_range(position - 2), 'median': slot_median(position),
                    'median_lag': slot_median(position - 3),
                    'median_mean': sum(medians) / 3 if all(value is not None for value in medians) else None}
        for key, value in expected.items():
            actual = view.get(key)
            if value is None:
                assert type(actual) is NotReady, (late, when, key)
            else:
                assert actual == ReadyValue(value), (late, when, key, actual, value)


def test_same_slot_rejects_unsupported_timezone():
    with pytest.raises(ValueError, match='America/New_York'):
        SameLocalSlotMedian('median', 'volume', timezone='Asia/Shanghai')


def test_chronological_history_appends_without_ordered_tree_updates(monkeypatch):
    from strategy_runtime import equity_replay

    frame = observations(pd.date_range('2024-03-01 14:30', periods=256, freq='30min', tz='UTC'),
                         [float(index + 10) for index in range(256)])
    frame['BarStatus'], frame['ExecutionBlocked'] = 'OBSERVED', False
    frame.loc[13::17, 'BarStatus'] = 'ZERO_VOLUME'
    frame.loc[13::17, ['Volume', 'Amount']] = 0.
    value = prepare(frame, FeatureGraph())

    def unexpected_tree_update(*args, **kwargs):
        raise AssertionError('chronological visibility must not insert into an ordered tree')

    class UnusedFenwick:
        def __len__(self):
            raise AssertionError('chronological visibility must not maintain a Fenwick tree')

    monkeypatch.setattr(equity_replay, '_history_insert', unexpected_tree_update)
    visibility = _Visibility(value._data)
    visibility.tree = UnusedFenwick()
    retained, expected = [], []
    for index, when in enumerate(frame.Date):
        visibility.advance(when.to_pydatetime())
        if frame.BarStatus.iloc[index] == 'OBSERVED':
            expected.append(float(index + 10))
        view = visibility.history_view(when.to_pydatetime())
        assert view.last()['Close'] == expected[-1]
        assert view.to_frame(tail=2).Close.tolist() == expected[-2:]
        if index in (0, 63, 127, 255):
            retained.append((view, expected.copy()))
    for view, rows in retained:
        assert view.to_frame().Close.tolist() == rows
        assert pickle.loads(pickle.dumps(view)).to_frame().Close.tolist() == rows


def test_long_chronological_snapshots_serialize_and_compare_without_recursion():
    frame = observations(pd.date_range('2024-03-01 14:30', periods=4096, freq='30min', tz='UTC'),
                         [float(index + 10) for index in range(4096)])
    value = prepare(frame, FeatureGraph())
    visibility = _Visibility(value._data)
    visibility.advance(frame.Date.iloc[-1].to_pydatetime())
    history = visibility.history_view(frame.Date.iloc[-1].to_pydatetime())
    saved = pickle.loads(pickle.dumps(history))
    copied = deepcopy(history)
    assert saved == copied == history
    assert not (saved._root != history._root)
    assert saved.to_frame(tail=2).Close.tolist() == [4104., 4105.]
    assert len(saved) == len(copied) == 4096
    with pytest.raises(TypeError):
        saved.last()['Close'] = -1
