"""Market isolation and immutable preparation through the real DFLS facade."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import pandas as pd
import pytest

from dataflows import (AssetClass, BarFrequency, DataSpace, Dataflows, EquityDataRequest,
                      EquityProduct, EquityQuery, InstrumentId, MarketId, PreparePolicy,
                      ProviderBinding, ProviderConfig, ProviderKey, SourceRef,
                      TimeInterval, TradingSession)
from dataflows.equity_data import equity_metadata


def fixture_product():
    instrument = InstrumentId(MarketId.US, AssetClass.STOCK, "LITE")
    source = SourceRef("fixture", "v1")
    query = EquityQuery(EquityProduct.BARS, date(2026, 10, 1), date(2026, 10, 1))
    request = EquityDataRequest(instrument, source, query)
    zone = ZoneInfo(instrument.timezone)
    session = TradingSession(query.start, instrument.timezone, (TimeInterval(
        datetime(2026, 10, 1, 9, 30, tzinfo=zone), datetime(2026, 10, 1, 16, tzinfo=zone)),))
    bars = session.bars(BarFrequency.M30)
    frame = pd.DataFrame({"Date": [b.end for b in bars], "BarStart": [b.start for b in bars],
                          "AvailableDate": [b.end for b in bars],
                          "Open": 10., "High": 11., "Low": 9., "Close": 10.,
                          "Volume": 100., "Amount": 1000.})
    metadata = equity_metadata(request, (session,), availability_basis="BAR_CLOSE_RESEARCH_ASSUMPTION")
    return request, frame, metadata


def test_equity_source_identity_and_pinned_publication(tmp_path):
    request, frame, metadata = fixture_product()
    calls = []

    def fetch(req):
        calls.append(req)
        return frame.copy(), dict(metadata)

    key = request.parameters.provider_key
    flows = Dataflows(base_dir=tmp_path, space=DataSpace(Path("assets")),
                     providers=ProviderConfig(bindings={}, equity_bindings={
                         key: ProviderBinding("fixture", "v1", fetch)}))
    prepared = flows.prepare((request,), policy=PreparePolicy.REUSE)
    assert flows.datasets == ("equity.bars",)
    assert prepared.ready, prepared.items[0].error
    result = flows.fetch(request, prepared=prepared.reference)
    assert result.ready, result.error
    assert len(result.dataframe) == 13 and len(calls) == 1
    changed = EquityDataRequest(request.parameters.instrument, SourceRef("fixture", "v2"), request.parameters.query)
    assert not flows.fetch(changed, prepared=prepared.reference).ready
    assert not flows.prepare((changed,), policy=PreparePolicy.REUSE).ready
    assert len(calls) == 1
    assert flows.fetch(request, prepared=prepared.reference).identity.content_sha256 == result.identity.content_sha256


@pytest.mark.parametrize("defect", ["missing", "future", "market", "source"])
def test_equity_rejects_bad_source_at_publication(tmp_path, defect):
    request, frame, metadata = fixture_product()
    if defect == "missing":
        frame = frame.iloc[:-1]
    elif defect == "future":
        frame.loc[0, "AvailableDate"] = frame.loc[0, "BarStart"]
    elif defect == "market":
        metadata["instrument"] = {**metadata["instrument"], "market": "CN"}
    else:
        metadata["source_revision"] = "other"
    flows = Dataflows(base_dir=tmp_path, space=DataSpace(Path("assets")),
                     providers=ProviderConfig(bindings={}, equity_bindings={request.parameters.provider_key:
                         ProviderBinding("fixture", "v1", lambda _: (frame, metadata))}))
    prepared = flows.prepare((request,), policy=PreparePolicy.REUSE)
    assert not prepared.ready and prepared.reference is None


def test_session_grid_uses_exchange_timezone_and_half_day():
    zone = ZoneInfo("America/New_York")
    winter = TradingSession(date(2026, 11, 27), str(zone), (TimeInterval(
        datetime(2026, 11, 27, 9, 30, tzinfo=zone), datetime(2026, 11, 27, 13, tzinfo=zone)),))
    assert len(winter.bars(BarFrequency.M30)) == 7
    assert winter.bars(BarFrequency.M30)[0].start.hour == 14
    _, summer, _ = fixture_product()
    assert summer.BarStart.iloc[0].hour == 13
    with pytest.raises(ValueError):
        InstrumentId(MarketId.CN, AssetClass.STOCK, "LITE")
    with pytest.raises(ValueError):
        InstrumentId(MarketId.US, AssetClass.STOCK, "US.LITE")
    with pytest.raises(TypeError):
        ProviderKey("equity.bars", MarketId.US, SourceRef("fixture", "v1"))
