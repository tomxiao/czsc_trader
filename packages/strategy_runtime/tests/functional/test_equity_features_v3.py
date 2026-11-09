"""Visibility-versioned finite features, including nonmonotonic publication."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import pickle
from statistics import median

import numpy as np
import pandas as pd
import pytest

from strategy_runtime.equity_features import (
    BarField,
    FeatureGraph,
    HistoryView,
    Lag,
    Mean,
    NotReady,
    RawField,
    ReadyValue,
    SameLocalSlotMedian,
    TrueRange,
)
from strategy_runtime.equity_replay import PreparedObservations, _FeatureEvaluator, _Visibility


def observations(starts, closes=None):
    starts = pd.DatetimeIndex(starts)
    closes = [10.0] * len(starts) if closes is None else closes
    return pd.DataFrame(
        {
            "BarStart": starts,
            "Date": starts + pd.Timedelta(minutes=30),
            "AvailableDate": starts + pd.Timedelta(minutes=30),
            "Open": closes,
            "High": [x + 1 for x in closes],
            "Low": [x - 1 for x in closes],
            "Close": closes,
            "Volume": 100.0,
            "Amount": 1000.0,
        }
    )


def prepare(frame, graph):
    return PreparedObservations.from_frames(frame, graph)


def test_SRT_14_C03_late_bar_insertion_changes_current_asof_not_old_view():
    starts = pd.date_range("2024-03-01 14:30", periods=5, freq="30min", tz="UTC")
    frame = observations(starts, [10.0, 20.0, 30.0, 40.0, 50.0])
    frame.loc[1, "AvailableDate"] = frame.Date.iloc[3]
    graph = FeatureGraph(
        (RawField("close", BarField.CLOSE), Lag("previous", "close", 1), Mean("mean", "close", 3)),
        ("previous", "mean"),
    )
    prepared = prepare(frame, graph)
    visibility = _Visibility(prepared._data)
    evaluator = _FeatureEvaluator(prepared._data, graph, visibility)
    earlier = frame.Date.iloc[2].to_pydatetime()
    visibility.advance(earlier)
    first = evaluator.at(earlier)
    history = visibility.history_view(earlier)
    assert first.get("previous") == ReadyValue(10.0)
    assert type(first.get("mean")) is NotReady
    visibility.advance(frame.Date.iloc[3].to_pydatetime())
    later = evaluator.at(frame.Date.iloc[3].to_pydatetime())
    assert later.get("previous") == ReadyValue(30.0)
    assert later.get("mean") == ReadyValue(30.0)
    assert first.get("previous") == ReadyValue(10.0)
    assert history.to_frame().Close.tolist() == [10.0, 30.0]
    assert history.last(0)["Close"] == 30.0 and history.last(1)["Close"] == 10.0
    with pytest.raises(TypeError):
        history.last(0).items().mapping["Close"] = -1
    assert not hasattr(
        history, "_data"
    )  # No all-history/future storage capability reaches strategy.
    with pytest.raises(ValueError, match="unavailable"):
        HistoryView(earlier, visibility.history_root, visibility.count)
    copied = history.to_frame()
    copied.loc[0, "Close"] = -1
    assert history.to_frame().Close.tolist() == [10.0, 30.0]
    with pytest.raises(TypeError):
        prepared._data.rows[0]["Close"] = -1
    with pytest.raises((FrozenInstanceError, AttributeError)):
        first.as_of = later.as_of
    restored = pickle.loads(pickle.dumps(prepared))
    assert restored._data.rows[0]["Close"] == 10.0
    saved_history = pickle.loads(pickle.dumps(history))
    assert saved_history.to_frame().Close.tolist() == [10.0, 30.0]
    assert pickle.loads(pickle.dumps(first)).get("previous") == ReadyValue(10.0)


def test_SRT_20_C03_true_range_lagged_atr_and_unseen_future_values():
    frame = observations(pd.date_range("2024-03-01 14:30", periods=18, freq="30min", tz="UTC"))
    frame.loc[16, ["Open", "High", "Low", "Close"]] = [10.0, 20.0, 9.0, 19.0]
    graph = FeatureGraph(
        (
            RawField("close", BarField.CLOSE),
            RawField("high", BarField.HIGH),
            RawField("low", BarField.LOW),
            TrueRange("range", "high", "low", "close"),
            Mean("atr", "range", 13),
            Lag("before_prior", "atr", 2),
        ),
        ("atr", "before_prior"),
    )
    prepared = prepare(frame, graph)
    visibility = _Visibility(prepared._data)
    when = frame.Date.iloc[16].to_pydatetime()
    visibility.advance(when)
    value = _FeatureEvaluator(prepared._data, graph, visibility).at(when)
    assert value.get("before_prior") == ReadyValue(2.0)
    assert value.get("atr") == ReadyValue((12 * 2.0 + 11.0) / 13)
    altered = frame.copy()
    altered.loc[17, ["Open", "High", "Low", "Close", "Volume"]] *= 3
    second = prepare(altered, graph)
    index = _Visibility(second._data)
    index.advance(when)
    assert _FeatureEvaluator(second._data, graph, index).at(when).get("atr") == value.get("atr")


def test_SRT_20_C05_prefix_mean_preserves_python_float_sum_compensation():
    frame = observations(
        pd.date_range("2024-03-01 14:30", periods=4, freq="30min", tz="UTC"), [1e16, 1.0, 1.0, 5.0]
    )
    frame["Low"] = [max(0.5, float(value) - 1.0) for value in frame.Close]
    graph = FeatureGraph((RawField("close", BarField.CLOSE), Mean("mean", "close", 3)), ("mean",))
    prepared = prepare(frame, graph)
    index = _Visibility(prepared._data)
    evaluator = _FeatureEvaluator(prepared._data, graph, index)
    assert evaluator._prefix_outputs is not None
    when = frame.Date.iloc[2].to_pydatetime()
    index.advance(when)
    assert evaluator.at(when).get("mean") == ReadyValue(sum([1e16, 1.0, 1.0]) / 3)


@pytest.mark.parametrize(
    "late",
    [
        True,
    ],
    ids=["SRT-21-C04"],
)
def test_bulk_prefix_and_general_asof_equal_independent_random_scalar(late):
    random = np.random.default_rng(930271)
    stamps = []
    for day_index, day in enumerate(pd.bdate_range("2024-02-01", periods=35)):
        for minute in (570, 600, 930):
            if day_index == 18 and minute >= 780:  # Actual half-day missing afternoon slots.
                continue
            stamps.append(
                (day + pd.Timedelta(minutes=minute))
                .tz_localize("America/New_York")
                .tz_convert("UTC")
            )
    closes = (100.0 + random.random(len(stamps)) * 10).tolist()
    frame = observations(stamps, closes)
    frame["Volume"] = random.uniform(1.0, 100000.0, len(frame))
    frame["BarStatus"] = "OBSERVED"
    frame.loc[::37, "BarStatus"] = "ZERO_VOLUME"
    frame.loc[::37, "Volume"] = 0.0
    if late:
        frame.loc[11::17, "AvailableDate"] += pd.Timedelta(days=2)
    graph = FeatureGraph(
        (
            RawField("close", BarField.CLOSE),
            RawField("high", BarField.HIGH),
            RawField("low", BarField.LOW),
            RawField("volume", BarField.VOLUME),
            TrueRange("tr", "high", "low", "close"),
            Mean("atr", "tr", 13),
            Lag("before_prior", "atr", 2),
            SameLocalSlotMedian("median", "volume", 20, 1),
            Lag("median_lag", "median", 3),
            Mean("median_mean", "median", 3),
        ),
        ("close", "tr", "atr", "before_prior", "median", "median_lag", "median_mean"),
    )
    prepared = prepare(frame, graph)
    index = _Visibility(prepared._data)
    evaluator = _FeatureEvaluator(prepared._data, graph, index)
    assert (evaluator._prefix_outputs is None) is late
    records = frame.to_dict("records")
    retained = []
    for observation_index, when in enumerate(frame.Date):
        index.advance(when.to_pydatetime())
        view = evaluator.at(when.to_pydatetime())
        visible = [
            row
            for row in records
            if row["Date"] <= when
            and row["AvailableDate"] <= when
            and row["BarStatus"] == "OBSERVED"
        ]
        history = index.history_view(when.to_pydatetime())
        assert len(history) == len(visible)
        if visible:
            assert history.last()["Close"] == visible[-1]["Close"]
        if len(visible) > 1:
            assert history.last(1)["Close"] == visible[-2]["Close"]
        if observation_index in (13, 50, len(frame) - 1):
            expected_closes = [float(row["Close"]) for row in visible]
            assert history.to_frame().Close.tolist() == expected_closes
            assert history.to_frame(tail=2).Close.tolist() == expected_closes[-2:]
            retained.append((history, expected_closes))

        def true_range(position):
            if position < 1:
                return None
            current, previous = visible[position], visible[position - 1]
            return max(
                float(current["High"] - current["Low"]),
                abs(float(current["High"] - previous["Close"])),
                abs(float(current["Low"] - previous["Close"])),
            )

        def mean_range(position):
            if position < 13:
                return None
            return sum(true_range(j) for j in range(position - 12, position + 1)) / 13

        def slot_median(position):
            anchor_position = position - 1
            if anchor_position < 0:
                return None
            anchor = visible[anchor_position]["BarStart"].tz_convert("America/New_York")
            values = []
            seen_days = set()
            for row in reversed(visible[:anchor_position]):
                local = row["BarStart"].tz_convert("America/New_York")
                if (
                    local.date() < anchor.date()
                    and local.date() not in seen_days
                    and (local.hour, local.minute) == (anchor.hour, anchor.minute)
                ):
                    values.append(float(row["Volume"]))
                    seen_days.add(local.date())
                    if len(values) == 20:
                        return float(median(values))
            return None

        position = len(visible) - 1
        medians = [slot_median(j) for j in range(position - 2, position + 1)]
        expected = {
            "close": float(visible[-1]["Close"]) if visible else None,
            "tr": true_range(position),
            "atr": mean_range(position),
            "before_prior": mean_range(position - 2),
            "median": slot_median(position),
            "median_lag": slot_median(position - 3),
            "median_mean": sum(medians) / 3
            if all(value is not None for value in medians)
            else None,
        }
        for key, value in expected.items():
            actual = view.get(key)
            if value is None:
                assert type(actual) is NotReady, (late, when, key)
            else:
                assert actual == ReadyValue(value), (late, when, key, actual, value)
    # Both arrival paths retain the exact old snapshot after all future events.
    for history, expected_closes in retained:
        assert history.to_frame().Close.tolist() == expected_closes
        assert pickle.loads(pickle.dumps(history)).to_frame().Close.tolist() == expected_closes


def test_SRT_14_C01_completed_bar_waits_for_availability():
    frame = observations([datetime(2024, 3, 1, 14, 30, tzinfo=timezone.utc)])
    frame.loc[0, "AvailableDate"] += timedelta(seconds=1)
    prepared = prepare(frame, FeatureGraph())
    index = _Visibility(prepared._data)
    index.advance(frame.Date.iloc[0].to_pydatetime())
    assert index.count == 0


def test_SRT_14_C02_latency_exact_boundary_and_one_second_short():
    from strategy_runtime.data_preparation import causal_history

    frame = observations([datetime(2024, 3, 1, 14, 30, tzinfo=timezone.utc)])
    cutoff = frame.Date.iloc[0].to_pydatetime() + timedelta(seconds=10)
    assert len(causal_history(frame, cutoff, latency_seconds=10, minimum_observations=1)) == 1
    with pytest.raises(ValueError, match="warmup"):
        causal_history(frame, cutoff, latency_seconds=11, minimum_observations=1)


def test_SRT_20_C01_missing_feature_dependency():
    with pytest.raises(ValueError, match="undeclared"):
        FeatureGraph((Mean("mean", "absent", 3),), ("mean",))


def test_SRT_20_C02_feature_dependency_cycle():
    with pytest.raises(ValueError, match="cycle"):
        FeatureGraph((Lag("first", "second", 1), Lag("second", "first", 1)), ("first",))


def test_SRT_20_C04_insufficient_window_is_not_ready():
    frame = observations(pd.date_range("2024-03-01 14:30", periods=2, freq="30min", tz="UTC"))
    graph = FeatureGraph((RawField("close", BarField.CLOSE), Mean("mean", "close", 3)), ("mean",))
    prepared = prepare(frame, graph)
    index = _Visibility(prepared._data)
    when = frame.Date.iloc[-1].to_pydatetime()
    index.advance(when)
    assert type(_FeatureEvaluator(prepared._data, graph, index).at(when).get("mean")) is NotReady


def test_SRT_20_C06_unseen_suffix_cannot_change_current_feature():
    frame = observations(pd.date_range("2024-03-01 14:30", periods=3, freq="30min", tz="UTC"))
    graph = FeatureGraph((RawField("close", BarField.CLOSE), Mean("mean", "close", 2)), ("mean",))
    when = frame.Date.iloc[1].to_pydatetime()
    first = prepare(frame, graph)
    index = _Visibility(first._data)
    index.advance(when)
    expected = _FeatureEvaluator(first._data, graph, index).at(when).get("mean")
    changed = frame.copy()
    changed.loc[2, ["Open", "High", "Low", "Close"]] *= 9
    second = prepare(changed, graph)
    another = _Visibility(second._data)
    another.advance(when)
    assert _FeatureEvaluator(second._data, graph, another).at(when).get("mean") == expected


@pytest.mark.parametrize(
    "variant", ["dst", "missing", "today"], ids=["SRT-21-C01", "SRT-21-C02", "SRT-21-C03"]
)
def test_slot_median_uses_prior_distinct_days(variant):
    days = pd.bdate_range("2024-02-01", periods=35)
    starts = pd.DatetimeIndex(
        [
            (day + pd.Timedelta(hours=15, minutes=30))
            .tz_localize("America/New_York")
            .tz_convert("UTC")
            for day in days
        ]
    )
    frame = observations(starts)
    frame["Volume"] = range(1, len(frame) + 1)
    if variant == "missing":
        frame = frame.drop(index=20).reset_index(drop=True)
    graph = FeatureGraph(
        (RawField("volume", BarField.VOLUME), SameLocalSlotMedian("median", "volume", 20, 0)),
        ("median",),
    )
    expected = float(frame.Volume.iloc[:-1].iloc[-20:].median())
    if variant == "today":
        frame.loc[frame.index[-1], "Volume"] = 1e12
    prepared = prepare(frame, graph)
    index = _Visibility(prepared._data)
    when = frame.Date.iloc[-1].to_pydatetime()
    index.advance(when)
    assert _FeatureEvaluator(prepared._data, graph, index).at(when).get("median") == ReadyValue(
        expected
    )
    assert starts.hour.nunique() == 2
