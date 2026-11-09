"""Market isolation and immutable preparation through the real DFLS facade."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from dataflows import (
    AssetClass,
    BarFrequency,
    Dataflows,
    EquityDataRequest,
    EquityProduct,
    EquityQuery,
    InstrumentId,
    MarketId,
    PreparePolicy,
    ProviderBinding,
    ProviderConfig,
    SourceRef,
    TimeInterval,
    TradingSession,
)
from dataflows.equity_data import equity_metadata
from dataflows.equity_data import validate_equity_frame
from dataflows.errors import DataContractError


def fixture_product():
    instrument = InstrumentId(MarketId.US, AssetClass.STOCK, "LITE")
    source = SourceRef("fixture", "v1")
    query = EquityQuery(EquityProduct.BARS, date(2026, 10, 1), date(2026, 10, 1))
    request = EquityDataRequest(instrument, source, query)
    zone = ZoneInfo(instrument.timezone)
    session = TradingSession(
        query.start,
        instrument.timezone,
        (
            TimeInterval(
                datetime(2026, 10, 1, 9, 30, tzinfo=zone), datetime(2026, 10, 1, 16, tzinfo=zone)
            ),
        ),
    )
    bars = session.bars(BarFrequency.M30)
    frame = pd.DataFrame(
        {
            "Date": [b.end for b in bars],
            "BarStart": [b.start for b in bars],
            "AvailableDate": [b.end for b in bars],
            "Open": 10.0,
            "High": 11.0,
            "Low": 9.0,
            "Close": 10.0,
            "Volume": 100.0,
            "Amount": 1000.0,
        }
    )
    metadata = equity_metadata(
        request, (session,), availability_basis="BAR_CLOSE_RESEARCH_ASSUMPTION"
    )
    return request, frame, metadata


def test_DFLS_19_C06_source_identity_and_pinned_publication(tmp_path, empty_space_factory):
    request, frame, metadata = fixture_product()
    calls = []

    def fetch(req):
        calls.append(req)
        return frame.copy(), dict(metadata)

    key = request.parameters.provider_key
    flows = Dataflows(
        base_dir=tmp_path,
        space=empty_space_factory("assets"),
        providers=ProviderConfig(
            bindings={}, equity_bindings={key: ProviderBinding("fixture", "v1", fetch)}
        ),
    )
    prepared = flows.prepare((request,), policy=PreparePolicy.REUSE)
    assert flows.datasets == ("equity.bars",)
    assert prepared.ready, prepared.items[0].error
    result = flows.fetch(request, prepared=prepared.reference)
    assert result.ready, result.error
    assert len(result.dataframe) == 13 and len(calls) == 1
    changed = EquityDataRequest(
        request.parameters.instrument, SourceRef("fixture", "v2"), request.parameters.query
    )
    assert not flows.fetch(changed, prepared=prepared.reference).ready
    assert not flows.prepare((changed,), policy=PreparePolicy.REUSE).ready
    assert len(calls) == 1
    assert (
        flows.fetch(request, prepared=prepared.reference).identity.content_sha256
        == result.identity.content_sha256
    )


@pytest.mark.parametrize(
    "defect,error",
    [
        ("symbol", DataContractError),
        ("source", DataContractError),
    ],
    ids=["DFLS-19-C05", "DFLS-19-C04"],
)
def test_equity_source_validation_at_its_responsibility_boundary(defect, error):
    request, frame, metadata = fixture_product()
    if defect == "missing":
        frame = frame.iloc[:-1]
    elif defect == "future":
        frame.loc[0, "AvailableDate"] = frame.loc[0, "BarStart"]
    elif defect == "symbol":
        metadata["instrument"] = {**metadata["instrument"], "symbol": "MU"}
    else:
        metadata["source_revision"] = "other"
    with pytest.raises(error):
        validate_equity_frame(frame, request, metadata)


def test_DFLS_19_C03_adjusted_provider_requires_acquisition_method():
    from dataclasses import replace
    from dataflows import PriceAdjustment
    from dataflows.equity_data import validate_equity_frame
    from dataflows.errors import DataContractError

    request, frame, metadata = fixture_product()
    adjusted = EquityDataRequest(
        request.parameters.instrument,
        request.parameters.source,
        replace(request.parameters.query, adjustment=PriceAdjustment.BACKWARD),
    )
    metadata["adjustment"] = "hfq"
    with pytest.raises(DataContractError, match="acquisition method"):
        validate_equity_frame(frame, adjusted, metadata)


def test_DFLS_21_C05_dst_grid_uses_local_rth():
    from datetime import timezone

    instrument = InstrumentId(MarketId.US, AssetClass.STOCK, "LITE")
    query = EquityQuery(EquityProduct.BARS, date(2026, 10, 30), date(2026, 11, 2))
    request = EquityDataRequest(instrument, SourceRef("fixture", "v1"), query)
    zone = ZoneInfo(instrument.timezone)
    sessions = tuple(
        TradingSession(
            day,
            instrument.timezone,
            (
                TimeInterval(
                    datetime.combine(day, datetime.min.time().replace(hour=9, minute=30), zone),
                    datetime.combine(day, datetime.min.time().replace(hour=16), zone),
                ),
            ),
        )
        for day in (date(2026, 10, 30), date(2026, 11, 2))
    )
    bars = [bar for session in sessions for bar in session.bars(BarFrequency.M30)]
    frame = pd.DataFrame(
        {
            "Date": [b.end for b in bars],
            "BarStart": [b.start for b in bars],
            "AvailableDate": [b.end for b in bars],
            "Open": 10.0,
            "High": 10.0,
            "Low": 10.0,
            "Close": 10.0,
            "Volume": 100.0,
            "Amount": 1000.0,
        }
    )
    metadata = equity_metadata(
        request, sessions, availability_basis="BAR_CLOSE_RESEARCH_ASSUMPTION"
    )
    validate_equity_frame(frame, request, metadata)
    assert len(frame) == 26
    assert [
        sessions[0].segments[0].start.astimezone(timezone.utc).hour,
        sessions[1].segments[0].start.astimezone(timezone.utc).hour,
    ] == [13, 14]
