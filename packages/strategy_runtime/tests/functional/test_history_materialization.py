"""Visible-window reuse preserves pandas semantics and mutable-copy isolation."""
import pickle

import pandas as pd
import pytest

from strategy_runtime.equity_features import FeatureGraph, _HistoryFrames
from strategy_runtime.equity_replay import PreparedObservations, _Visibility


def data():
    starts = pd.date_range("2024-03-01 14:30", periods=8, freq="30min", tz="UTC")
    return pd.DataFrame({"BarStart": starts, "Date": starts + pd.Timedelta(minutes=30),
        "AvailableDate": starts + pd.Timedelta(minutes=30),
        "Open": [10.] * 8, "High": [11.] * 8, "Low": [9.] * 8,
        "Close": [10.] * 8, "Volume": [100.] * 8, "Amount": [1000.] * 8})


@pytest.mark.parametrize("tail", [None, 1, 3, 99])
def test_visible_history_frames_preserve_dtypes_and_independent_copies(tail):
    source = data()
    prepared = PreparedObservations.from_frames(source, FeatureGraph())
    visibility = _Visibility(prepared._data)
    when = source.Date.iloc[4].to_pydatetime()
    visibility.advance(when)
    retained = visibility.history_view(when)
    expected = source.iloc[:5].tail(tail if tail is not None else 5).reset_index(drop=True)
    # Preparation canonicalizes row values; compare the established records
    # constructor, including exact timestamp/string/numeric dtypes and index.
    expected = pd.DataFrame(expected.to_dict("records"), columns=expected.columns)
    first = retained.to_frame(tail=tail)
    pd.testing.assert_frame_equal(first, expected)
    first.loc[0, "Close"] = -100.
    first.rename(columns={"Open": "mutated"}, inplace=True)
    visibility.advance(source.Date.iloc[-1].to_pydatetime())
    pd.testing.assert_frame_equal(retained.to_frame(tail=tail), expected)
    pd.testing.assert_frame_equal(pickle.loads(pickle.dumps(retained)).to_frame(tail=tail), expected)
    assert len(visibility.history_view(source.Date.iloc[-1].to_pydatetime())) == 8


def test_window_cache_separates_equal_sized_sources_and_limits_retention():
    cache = _HistoryFrames()
    cache.max_entries = 2
    cache.max_bytes = 1024
    first = ({"Close": 1.}, {"Close": 2.})
    second = ({"Close": 11.}, {"Close": 12.})
    third = ({"Close": 21.}, {"Close": 22.})
    assert cache.frame(first, ("Close",)).Close.tolist() == [1., 2.]
    assert cache.frame(second, ("Close",)).Close.tolist() == [11., 12.]
    changed = cache.frame(first, ("Close",))
    changed.loc[0, "Close"] = -1.
    assert cache.frame(first, ("Close",)).Close.tolist() == [1., 2.]
    cache.frame(third, ("Close",))
    assert len(cache.entries) <= cache.max_entries and cache.bytes <= cache.max_bytes
    # A window larger than the retained-byte budget is still returned in full.
    large = ({"text": "a" * 2000}, {"text": "b" * 2000})
    assert cache.frame(large, ("text",)).text.tolist() == ["a" * 2000, "b" * 2000]
    assert len(cache.entries) <= cache.max_entries and cache.bytes <= cache.max_bytes
