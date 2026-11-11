"""Shared market features respect as-of windows and declared parameters."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from strategy_runtime import equity_source_runtime
from strategy_runtime import MarketFeature, MarketWindow
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
    early = HistoryView(when, first, 1)
    late = HistoryView(later, second, 2)
    candidate = SimpleNamespace(definition=SimpleNamespace(source_sha256="source", dependencies=(), parameters={'scale': 2}))
    prepared = SimpleNamespace(identity="market-a")
    declaration = MarketFeature('sum_close', 'test_market_features:_sum_close', (MarketWindow(None, 2),), ('scale',))
    narrow = MarketFeature('sum_close', 'test_market_features:_sum_close', (MarketWindow(None, 1),), ('scale',))
    invalid = MarketFeature('mutable', 'test_market_features:_mutable', (MarketWindow(None, 1),))
    monkeypatch.setattr(equity_source_runtime, "active_invocation",
                        lambda _: SimpleNamespace(market_functions={'sum_close': _sum_close, 'mutable': _mutable}))
    _market_cache.cache_clear()
    _calls.clear()
    try:
        assert _market_feature(candidate, prepared, declaration, early, {}, {}, None) == 20.0
        other_candidate = SimpleNamespace(definition=candidate.definition)
        assert _market_feature(other_candidate, prepared, declaration, early, {}, {}, None) == 20.0
        assert _market_feature(candidate, prepared, declaration, late, {}, {}, None) == 60.0
        candidate.definition.parameters['scale'] = 3
        assert _market_feature(candidate, prepared, declaration, late, {}, {}, None) == 90.0
        candidate.definition.parameters['scale'] = 2
        assert _market_feature(candidate, prepared, narrow, late, {}, {}, None) == 40.0
        assert _market_feature(candidate, SimpleNamespace(identity="market-b"), declaration, early, {}, {}, None) == 20.0
        assert _calls == [1, 2, 2, 1, 1]
        with pytest.raises(TypeError, match="immutable"):
            _market_feature(candidate, prepared, invalid, early, {}, {}, None)
    finally:
        _market_cache.cache_clear()
