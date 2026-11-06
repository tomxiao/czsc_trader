"""Exact dynamic facts for both markets through the DFLS preparation boundary."""

from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from dataflows import (
    AssetClass, BarFrequency, Dataflows, DataSpace, EquityDataRequest, EquityProduct, EquityQuery,
    InstrumentId, MarketId, PreparePolicy, ProviderBinding, ProviderConfig, SourceRef,
    TimeInterval, TradingSession,
)
from dataflows.equity_data import equity_metadata
from dataflows.equity_dynamic import dynamic_equity_bindings
from dataflows.errors import DataContractError, IncompleteDataError


def setup(market, frequency, defect):
    cn = market is MarketId.CN
    instrument = InstrumentId(market, AssetClass.ETF if cn else AssetClass.STOCK,
                              "588080.SH" if cn else "MU")
    day, following = date(2026, 11, 6), date(2026, 11, 9)
    source, clock = SourceRef("dynamic-fixture", "v2"), SourceRef("calendar-fixture", "v1")
    zone = ZoneInfo(instrument.timezone)

    def session(local_day):
        hours = ((9, 30, 11, 30), (13, 0, 15, 0)) if cn else ((9, 30, 16, 0),)
        return TradingSession(local_day, instrument.timezone, tuple(TimeInterval(
            datetime(local_day.year, local_day.month, local_day.day, a, b, tzinfo=zone),
            datetime(local_day.year, local_day.month, local_day.day, c, d, tzinfo=zone))
            for a, b, c, d in hours))

    def calendar(request):
        selected = [s for s in (session(day), session(following))
                    if request.parameters.query.start <= s.session_date <= request.parameters.query.end]
        starts = [s.segments[0].start for s in selected]
        return pd.DataFrame(dict(Date=starts, AvailableDate=starts,
            SessionDate=[s.session_date.isoformat() for s in selected])), equity_metadata(
            request, selected, availability_basis="FIXTURE_CALENDAR")

    def response(url):
        selection = dict(parse_qsl(urlsplit(url).query))
        assert selection["symbol"] == instrument.symbol
        assert selection["start"] == selection["end"] == day.isoformat()
        grid = session(day).bars(frequency)
        rows = [dict(Date=bar.start.isoformat(), AvailableDate=bar.start.isoformat(),
                     Tradable=index != 0, PriceLimitLower=5. if cn and index else None,
                     PriceLimitUpper=15. if cn and index else None)
                for index, bar in enumerate(grid)] if selection["product"] == EquityProduct.TRADING_FACTS else []
        if defect == "split":
            stamp = grid[0].start.isoformat()
            rows = [dict(Date=stamp, AvailableDate=stamp, EventId="split-1",
                         Kind="SPLIT", Ratio=2., CashPerShare=0., PayAt=None)]
        if defect == "gap":
            rows.pop()
        elif defect == "static":
            rows[0]["QuantityStep"] = 100
        elif defect == "late":
            rows[0]["AvailableDate"] = grid[0].end.isoformat()
        return dict(source=asdict(source), selection=selection, rows=rows,
                    coverage=dict(start=selection["start"], end=selection["end"],
                                  complete=defect != "unverified", receipt="isolated-fixture"))

    bindings = dynamic_equity_bindings(source=source, market=market, endpoint="https://feed.example.test/equity",
        calendar_source=clock, calendar_binding=ProviderBinding(clock.provider, clock.revision, calendar),
        read_json=response)

    def request(product):
        return EquityDataRequest(instrument, source, EquityQuery(product, day, day, frequency))

    return bindings, request


@pytest.mark.parametrize("market", [MarketId.CN, MarketId.US])
@pytest.mark.parametrize("frequency", [BarFrequency.DAILY, BarFrequency.M30])
def test_verified_dynamic_facts_and_known_no_events(tmp_path, market, frequency):
    bindings, request = setup(market, frequency, None)
    flows = Dataflows(base_dir=tmp_path, space=DataSpace(Path("assets")),
                      providers=ProviderConfig(bindings={}, equity_bindings=bindings))
    facts, actions = (request(p) for p in (EquityProduct.TRADING_FACTS, EquityProduct.ACTIONS))
    result = flows.prepare((facts, actions), policy=PreparePolicy.REUSE)
    assert result.ready, [item.error for item in result.items]
    trading = flows.fetch(facts, prepared=result.reference)
    assert trading.ready and not trading.dataframe.Tradable.iloc[0]
    assert set(trading.dataframe) == {"Date", "AvailableDate", "Tradable", "PriceLimitLower", "PriceLimitUpper"}
    if market is MarketId.CN:
        assert trading.identity.metadata["following_session"]["session_date"] == "2026-11-09"
    events = flows.fetch(actions, prepared=result.reference)
    assert events.ready and events.identity.metadata["no_actions_verified"]


@pytest.mark.parametrize("defect,error", [("gap", IncompleteDataError), ("static", DataContractError),
    ("late", DataContractError), ("unverified", IncompleteDataError)])
def test_dynamic_facts_reject_unknown_and_out_of_contract_rows(defect, error):
    bindings, request = setup(MarketId.CN, BarFrequency.M30, defect)
    req = request(EquityProduct.TRADING_FACTS)
    with pytest.raises(error):
        bindings[req.parameters.provider_key].fetch(req)


def test_mechanical_split_preserves_effective_and_available_dates():
    bindings, request = setup(MarketId.US, BarFrequency.DAILY, "split")
    req = request(EquityProduct.ACTIONS)
    rows, meta = bindings[req.parameters.provider_key].fetch(req)
    assert rows[["Kind", "Ratio"]].values.tolist() == [["SPLIT", 2.0]]
    assert rows.Date.equals(rows.AvailableDate)
    assert meta["action_history_complete"]
