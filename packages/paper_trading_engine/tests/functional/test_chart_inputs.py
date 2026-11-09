from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from dataflows import (
    AssetClass, BarFrequency, EquityDataRequest, EquityProduct,
    EquityQuery, InstrumentId, MarketId, PreparePolicy, PriceAdjustment, SourceRef, TimeInterval, TradingSession,
)
from dataflows.equity_data import equity_metadata

from paper_trading_engine.chart_market_data import AccountChartMarketData
from paper_trading_engine.account_chart import AccountChartService


# Independent risk: PTE24; responsibility-level assertions.
@pytest.mark.parametrize('day,close', [
    (date(2026, 7, 2), 16),
], ids=['PTE24-C01'])
def test_v4_us_chart_uses_bound_source_and_actual_new_york_close(monkeypatch, day, close):
    zone = ZoneInfo("America/New_York")
    prior = day - timedelta(days=1)
    sessions = tuple(TradingSession(session, zone.key, (TimeInterval(
        datetime(session.year, session.month, session.day, 9, 30, tzinfo=zone),
        datetime(session.year, session.month, session.day, hour, tzinfo=zone),
    ),)) for session, hour in ((prior, 16), (day, close)))
    moment = [sessions[-1].segments[-1].end - timedelta(minutes=1)]
    source = SourceRef("bound-feed", "v1")
    instrument = InstrumentId(MarketId.US, AssetClass.STOCK, "MU")
    binding = SimpleNamespace(instrument=instrument, request_bindings=tuple(
        (role, EquityDataRequest(instrument, source, EquityQuery(product, prior, day)).parameters)
        for role, product in (("bars", EquityProduct.BARS), ("sessions", EquityProduct.SESSIONS))
    ))
    adapter = AccountChartMarketData(dataflows=None, now=lambda: moment[0],
                                     formal_inputs=lambda account_id: SimpleNamespace(binding=binding))
    seen = []

    def fetch(request, policy):
        seen.append((request.parameters, policy))
        if request.parameters.query.product is EquityProduct.SESSIONS:
            frame = pd.DataFrame({"SessionDate": [session.session_date for session in sessions],
                                  "AvailableDate": [session.segments[0].start for session in sessions]})
            return SimpleNamespace(dataframe=frame, identity=SimpleNamespace(
                metadata=equity_metadata(request, sessions, availability_basis="TEST")))
        ends = [session.segments[-1].end for session in sessions
                if session.session_date <= request.parameters.query.end]
        return SimpleNamespace(dataframe=pd.DataFrame({"Date": ends, "AvailableDate": [
            end + timedelta(minutes=5) for end in ends
        ], "Open": 10.0, "High": 10.0,
                                                       "Low": 10.0, "Close": 10.0}))

    monkeypatch.setattr(adapter, "_fetch", fetch)
    args = dict(symbol="MU", asset="stock", account_id="us-v4", selection_data_cutoff=prior.isoformat(),
                context_sessions=20)
    assert adapter.scheduled_session_ready("us-v4", moment[0]) is False
    assert adapter.history(**args)[1].Date.max() == prior
    moment[0] = sessions[-1].segments[-1].end
    assert adapter.scheduled_session_ready("us-v4", moment[0]) is True
    assert adapter.history(**args)[1].Date.max() == prior
    moment[0] += timedelta(minutes=5)
    assert adapter.history(**args, refresh_source=True)[1].Date.max() == day
    parameters, policy = seen[-1]
    assert (parameters.instrument, parameters.source, parameters.query.frequency, parameters.query.adjustment) == (
        instrument, source, BarFrequency.DAILY, PriceAdjustment.BACKWARD,
    )
    assert policy is PreparePolicy.REFRESH
    assert AccountChartService._fact_date(
        {"occurred_at": "2026-11-07T03:30:00+08:00"}, ("occurred_at",), zone,
    ) == "2026-11-06"
