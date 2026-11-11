"""Shared market features respect as-of windows and declared parameters."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from strategy_runtime import equity_source_runtime
from strategy_runtime.equity_features import HistoryView, _HistoryAppend
from strategy_runtime.equity_replay import _Row
from strategy_runtime.market_features import _market_cache, _market_feature


_calls = []


def _sum_close(windows, scale):
    _calls.append(len(windows[0]))
    return sum(row["Close"] for row in windows[0]) * scale


def _mutable(windows):
    return [windows[0][0]["Close"]]


def test_shared_market_windows_are_causal_and_isolated(monkeypatch):
    when = datetime(2026, 1, 2, tzinfo=timezone.utc)
    later = when + timedelta(minutes=30)
    first = _HistoryAppend(_Row({"Close": 10.0}), None, 1, when)
    second = _HistoryAppend(_Row({"Close": 20.0}), first, 2, later)
    early = SimpleNamespace(history=HistoryView(when, first, 1), auxiliary_histories={})
    late = SimpleNamespace(history=HistoryView(later, second, 2), auxiliary_histories={})
    candidate = SimpleNamespace(definition=SimpleNamespace(source_sha256="source", dependencies=()))
    prepared = SimpleNamespace(identity="market-a")
    monkeypatch.setattr(equity_source_runtime, "active_invocation",
                        lambda _: SimpleNamespace(prefix=__name__))
    _market_cache.cache_clear()
    _calls.clear()
    try:
        assert _market_feature(candidate, prepared, early, _sum_close, ((None, 2),), (2,)) == 20.0
        other_candidate = SimpleNamespace(definition=candidate.definition)
        assert _market_feature(other_candidate, prepared, early, _sum_close, ((None, 2),), (2,)) == 20.0
        assert _market_feature(candidate, prepared, late, _sum_close, ((None, 2),), (2,)) == 60.0
        assert _market_feature(candidate, prepared, late, _sum_close, ((None, 2),), (3,)) == 90.0
        assert _market_feature(candidate, prepared, late, _sum_close, ((None, 1),), (2,)) == 40.0
        assert _market_feature(candidate, SimpleNamespace(identity="market-b"), early, _sum_close,
                               ((None, 2),), (2,)) == 20.0
        assert _calls == [1, 2, 2, 1, 1]
        with pytest.raises(TypeError, match="immutable"):
            _market_feature(candidate, prepared, early, _mutable, ((None, 1),), ())
    finally:
        _market_cache.cache_clear()
