"""Shared source preparation preserves identities and causal observation boundaries."""

from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from strategy_runtime.data_preparation import (
    CalendarCoverage,
    fetch_prepared_products,
)
from strategy_runtime.equity_features import FeatureGraph
from strategy_runtime.equity_replay import PreparedObservations


def _request(symbol="TEST"):
    return SimpleNamespace(
        dataset="bars",
        symbol=symbol,
        start="2024-01-01",
        end="2024-01-03",
        required_cutoff=None,
        frequency="daily",
        parameters=None,
        coverage=None,
    )


def _result(day="2024-01-01", digest="a"):
    return SimpleNamespace(
        ready=True,
        error=None,
        dataframe=pd.DataFrame({"value": [1]}),
        identity=SimpleNamespace(
            content_sha256=digest, metadata={"sessions": [{"session_date": day, "close": "16:00"}]}
        ),
    )


def _bars():
    dates = pd.date_range("2024-01-01 16:00", periods=3, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "BarStart": dates - pd.Timedelta(hours=6),
            "Date": dates,
            "AvailableDate": dates,
            "Open": 10.0,
            "High": 11.0,
            "Low": 9.0,
            "Close": 10.0,
            "Volume": 100.0,
            "Amount": 1000.0,
        }
    )


def test_SRT_10_C03_forward_calendar_overlap_does_not_allow_conflicting_sessions():
    results = {"TEST": _result(), "NEXT": _result("2024-01-02")}
    flows = SimpleNamespace(fetch=lambda request, **_: results[request.symbol])
    items = (("bars", _request()), ("sessions", _request("NEXT")))
    with pytest.raises(ValueError, match="calendars differ"):
        fetch_prepared_products(flows, items, prepared=None)
    fetch_prepared_products(
        flows, items, prepared=None, calendar_coverage=CalendarCoverage.OVERLAPPING_SESSIONS
    )
    results["NEXT"] = _result()
    results["NEXT"].identity.metadata["sessions"][0]["close"] = "15:00"
    with pytest.raises(ValueError, match="calendars differ"):
        fetch_prepared_products(
            flows, items, prepared=None, calendar_coverage=CalendarCoverage.OVERLAPPING_SESSIONS
        )


def test_SRT_09_C06_observation_preparation_has_no_execution_constraints():
    prepared = PreparedObservations.from_frames(_bars(), FeatureGraph())
    assert len(prepared._data.rows) == 3
    assert not hasattr(prepared._data, "constraints")
    assert prepared.with_graph(FeatureGraph()).identity == prepared.identity


@pytest.mark.parametrize(
    "market_name",
    [
        "CN",
        "US",
    ],
    ids=["SRT-10-C01", "SRT-10-C02"],
)
def test_forward_selection_only_requests_completed_hfq_observations(market_name, tmp_path):
    from datetime import date, timedelta
    from zoneinfo import ZoneInfo
    from dataflows import BarFrequency, MarketId, EquityProduct, TradingSession, TimeInterval
    from dataflows.equity_data import session_record
    from strategy_runtime.data_preparation import forward_requests
    from packages.strategy_runtime.tests.binding_fixture_support import binding_fixture

    original, _ = binding_fixture(MarketId(market_name))
    binding = original.for_observations()
    zone = ZoneInfo(binding.instrument.timezone)
    sessions = tuple(
        TradingSession(
            date(2026, 10, day),
            str(zone),
            (
                TimeInterval(
                    datetime(2026, 10, day, 9, 30, tzinfo=zone),
                    datetime(2026, 10, day, 16, tzinfo=zone),
                ),
            ),
        )
        for day in (14, 15, 16, 19)
    )
    frame = pd.DataFrame(
        {
            "SessionDate": [s.session_date.isoformat() for s in sessions],
            "AvailableDate": [s.segments[0].start for s in sessions],
        }
    )
    result = SimpleNamespace(
        dataframe=frame,
        identity=SimpleNamespace(metadata={"sessions": [session_record(s) for s in sessions]}),
    )
    calendars = {
        role: result
        for role, p in binding.request_bindings
        if p.query.product is EquityProduct.SESSIONS
    }
    interval = sessions[2].segments[0]
    definition = SimpleNamespace(instrument=binding.instrument, observation_inputs=(),
                                 execution_spec=SimpleNamespace(decision_clock=BarFrequency.DAILY))
    requests, items, observation_items, _ = forward_requests(
        None, binding, interval, definition, tmp_path, calendars, cutoff=interval.start
    )
    assert not observation_items
    assert len(requests) == len({r.parameters for r in requests})
    for _, parameters in items:
        expected = {
            EquityProduct.BARS: date(2026, 10, 15),
            EquityProduct.SESSIONS: date(2026, 10, 16) + timedelta(days=14),
        }
        assert parameters.query.end == expected[parameters.query.product]
    with pytest.raises(ValueError, match="explicit observation-only input migration"):
        forward_requests(
            None, original, interval, definition, tmp_path, calendars, cutoff=interval.start
        )


@pytest.mark.parametrize("different", [False, True], ids=["SRT-08-C01", "SRT-08-C02"])
def test_shared_physical_request_checks_each_role(different):
    calls = []

    def fetch(request, **_):
        calls.append(request)
        return _result()

    flows = SimpleNamespace(fetch=fetch)
    items = (("bars", _request()), ("execution:bars", _request()))
    hashes = {"bars": "a", "execution:bars": "b" if different else "a"}
    if different:
        with pytest.raises(ValueError, match="identity differs"):
            fetch_prepared_products(flows, items, prepared=None, expected_identities=hashes)
    else:
        result = fetch_prepared_products(flows, items, prepared=None, expected_identities=hashes)
        assert result.products["bars"] is result.products["execution:bars"]
    assert len(calls) == 1


@pytest.mark.parametrize("defect", ["duplicate", "missing"], ids=["SRT-08-C03", "SRT-08-C04"])
def test_input_roles_rejected_before_preparation(defect):
    calls = []

    def fetch(request, **_):
        calls.append(request)
        return _result()

    flows = SimpleNamespace(fetch=fetch)
    items = (
        (("bars", _request()), ("bars", _request()))
        if defect == "duplicate"
        else (("bars", _request()),)
    )
    expected = None if defect == "duplicate" else {"bars": "a", "sessions": "a"}
    with pytest.raises(
        ValueError, match="unique" if defect == "duplicate" else "lacks required products"
    ):
        fetch_prepared_products(flows, items, prepared=None, expected_identities=expected)
    assert len(calls) == 1


def test_SRT_10_C04_forward_requires_explicit_observation_migration(tmp_path):
    from datetime import date
    from zoneinfo import ZoneInfo
    from dataflows import MarketId, EquityProduct, TradingSession, TimeInterval
    from dataflows.equity_data import session_record
    from strategy_runtime.data_preparation import forward_requests
    from packages.strategy_runtime.tests.binding_fixture_support import binding_fixture

    original, _ = binding_fixture(MarketId.US)
    binding = original.for_observations()
    zone = ZoneInfo(binding.instrument.timezone)
    sessions = tuple(
        TradingSession(
            date(2026, 10, day),
            str(zone),
            (
                TimeInterval(
                    datetime(2026, 10, day, 9, 30, tzinfo=zone),
                    datetime(2026, 10, day, 16, tzinfo=zone),
                ),
            ),
        )
        for day in (14, 15, 16, 19)
    )
    frame = pd.DataFrame(
        {
            "SessionDate": [s.session_date.isoformat() for s in sessions],
            "AvailableDate": [s.segments[0].start for s in sessions],
        }
    )
    result = SimpleNamespace(
        dataframe=frame,
        identity=SimpleNamespace(metadata={"sessions": [session_record(s) for s in sessions]}),
    )
    calendars = {
        role: result
        for role, p in binding.request_bindings
        if p.query.product is EquityProduct.SESSIONS
    }
    interval = sessions[2].segments[0]
    definition = SimpleNamespace(instrument=binding.instrument, observation_inputs=())
    with pytest.raises(ValueError, match="explicit observation-only input migration"):
        forward_requests(
            None, original, interval, definition, tmp_path, calendars, cutoff=interval.start
        )
