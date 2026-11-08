"""Shared source preparation preserves identities and causal observation boundaries."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from strategy_runtime.data_preparation import (
    CalendarCoverage, causal_history, fetch_prepared_products,
)
from strategy_runtime.equity_features import FeatureGraph
from strategy_runtime.equity_replay import PreparedObservations


def _request(symbol="TEST"):
    return SimpleNamespace(dataset="bars", symbol=symbol, start="2024-01-01", end="2024-01-03",
        required_cutoff=None, frequency="daily", parameters=None, coverage=None)


def _result(day="2024-01-01", digest="a"):
    return SimpleNamespace(ready=True, error=None, dataframe=pd.DataFrame({"value": [1]}),
        identity=SimpleNamespace(content_sha256=digest,
            metadata={"sessions": [{"session_date": day, "close": "16:00"}]}))


def _bars():
    dates = pd.date_range("2024-01-01 16:00", periods=3, freq="D", tz="UTC")
    return pd.DataFrame({"BarStart": dates - pd.Timedelta(hours=6), "Date": dates,
        "AvailableDate": dates, "Open": 10., "High": 11., "Low": 9., "Close": 10.,
        "Volume": 100., "Amount": 1000.})


def test_physical_request_is_read_once_but_each_role_hash_is_checked():
    calls = []
    def fetch(request, *, prepared):
        calls.append(request)
        return _result()
    flows = SimpleNamespace(fetch=fetch)
    query = _request()
    prepared = fetch_prepared_products(flows, (("bars", query), ("execution:bars", query)),
        prepared=None, expected_identities={"bars": "a", "execution:bars": "a"})
    assert len(calls) == 1
    assert prepared.products["bars"] is prepared.products["execution:bars"]
    with pytest.raises(ValueError, match="identity differs"):
        fetch_prepared_products(flows, (("bars", query), ("execution:bars", query)),
            prepared=None, expected_identities={"bars": "a", "execution:bars": "b"})


def test_forward_calendar_overlap_does_not_allow_conflicting_sessions():
    results = {"TEST": _result(), "NEXT": _result("2024-01-02")}
    flows = SimpleNamespace(fetch=lambda request, **_: results[request.symbol])
    items = (("bars", _request()), ("sessions", _request("NEXT")))
    with pytest.raises(ValueError, match="calendars differ"):
        fetch_prepared_products(flows, items, prepared=None)
    fetch_prepared_products(flows, items, prepared=None,
        calendar_coverage=CalendarCoverage.OVERLAPPING_SESSIONS)
    results["NEXT"] = _result()
    results["NEXT"].identity.metadata["sessions"][0]["close"] = "15:00"
    with pytest.raises(ValueError, match="calendars differ"):
        fetch_prepared_products(flows, items, prepared=None,
            calendar_coverage=CalendarCoverage.OVERLAPPING_SESSIONS)


def test_missing_identity_and_duplicate_roles_fail_before_observation_preparation():
    flows = SimpleNamespace(fetch=lambda *args, **kwargs: _result())
    with pytest.raises(ValueError, match="lacks required products"):
        fetch_prepared_products(flows, (("bars", _request()),), prepared=None,
            expected_identities={"bars": "a", "sessions": "a"})
    with pytest.raises(ValueError, match="unique"):
        fetch_prepared_products(flows, (("bars", _request()), ("bars", _request())), prepared=None)


def test_observation_preparation_has_no_execution_constraints():
    prepared = PreparedObservations.from_frames(_bars(), FeatureGraph())
    assert len(prepared._data.rows) == 3
    assert not hasattr(prepared._data, "constraints")
    assert prepared.with_graph(FeatureGraph()).identity == prepared.identity


def test_causal_history_requires_completion_and_availability_with_latency():
    bars = _bars()
    bars.loc[0, "AvailableDate"] = bars.Date.iloc[1] + pd.Timedelta(hours=1)
    cutoff = datetime(2024, 1, 2, 16, 0, 10, tzinfo=timezone.utc)
    selected = causal_history(bars, cutoff, latency_seconds=10, minimum_observations=1)
    assert tuple(selected.index) == (1,)
    selected.loc[1, "Close"] = 999.
    assert bars.loc[1, "Close"] == 10.
    with pytest.raises(ValueError, match="warmup"):
        causal_history(bars, cutoff, latency_seconds=11, minimum_observations=1)


@pytest.mark.parametrize('market_name', ('CN', 'US'))
def test_forward_selection_only_requests_completed_hfq_observations(market_name, tmp_path):
    from datetime import date, timedelta
    from zoneinfo import ZoneInfo
    from dataflows import MarketId, EquityProduct, TradingSession, TimeInterval
    from dataflows.equity_data import session_record
    from strategy_runtime.data_preparation import forward_requests
    from test_equity_adjusted_binding import binding_fixture
    original, _ = binding_fixture(MarketId(market_name))
    binding = original.for_observations()
    zone = ZoneInfo(binding.instrument.timezone)
    sessions = tuple(TradingSession(date(2026, 10, day), str(zone), (
        TimeInterval(datetime(2026, 10, day, 9, 30, tzinfo=zone),
                     datetime(2026, 10, day, 16, tzinfo=zone)),)) for day in (14, 15, 16, 19))
    frame = pd.DataFrame({'SessionDate': [s.session_date.isoformat() for s in sessions],
                          'AvailableDate': [s.segments[0].start for s in sessions]})
    result = SimpleNamespace(dataframe=frame,
        identity=SimpleNamespace(metadata={'sessions': [session_record(s) for s in sessions]}))
    calendars = {role: result for role, p in binding.request_bindings if p.query.product is EquityProduct.SESSIONS}
    interval = sessions[2].segments[0]
    definition = SimpleNamespace(instrument=binding.instrument, observation_inputs=())
    requests, items, observation_items, _ = forward_requests(None, binding, interval, definition,
        tmp_path, calendars, cutoff=interval.start)
    assert not observation_items
    assert len(requests) == len({r.parameters for r in requests})
    for _, parameters in items:
        expected = {EquityProduct.BARS: date(2026, 10, 15),
                    EquityProduct.SESSIONS: date(2026, 10, 16) + timedelta(days=14)}
        assert parameters.query.end == expected[parameters.query.product]
    with pytest.raises(ValueError, match='explicit observation-only input migration'):
        forward_requests(None, original, interval, definition, tmp_path, calendars, cutoff=interval.start)
