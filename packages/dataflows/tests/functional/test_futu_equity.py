"""Quote adapter normalization without a running OpenD or broker connection."""
from datetime import date, datetime, timezone
from pathlib import Path
import pandas as pd
import pytest

from dataflows import (AssetClass, EquityDataRequest, EquityProduct, EquityQuery, InstrumentId,
                       MarketId, SourceRef, futu_equity_bindings, UsEquityBarPolicy, TimeInterval,
                       Dataflows, DataSpace, ProviderConfig, PreparePolicy, ProviderBinding, PriceAdjustment,
                       BarFrequency)
from dataflows.equity_data import validate_equity_frame
from dataflows.errors import IncompleteDataError, DataContractError, SourceRequestError


class Quotes:
    def __init__(self):
        self.calls = []
        self.repeat = False

    def request_trading_days(self, **kwargs):
        return 0, [{"time": "2026-11-27", "trade_date_type": "MORNING"}]

    def request_history_kline(self, code, **kwargs):
        assert kwargs["autype"] in {"None", "qfq", "hfq"}  # SDK values are case-sensitive.
        self.calls.append(kwargs)
        frame = pd.DataFrame({"code": code, "time_key": pd.date_range("2026-11-27 10:00", periods=7, freq="30min").astype(str),
                              "open": 10., "high": 11., "low": 9., "close": 10., "volume": 100., "turnover": 1000.})
        if kwargs["ktype"] == "K_DAY":
            frame = frame.iloc[:1].copy()
            frame["time_key"] = "2026-11-27 00:00:00"
        return 0, frame, b"same" if self.repeat else None


def request(product, adjustment=PriceAdjustment.NONE, frequency=BarFrequency.M30):
    return EquityDataRequest(InstrumentId(MarketId.US, AssetClass.STOCK, "LITE"), SourceRef("futu", "test-v1"),
                              EquityQuery(product, date(2026, 11, 27), date(2026, 11, 27), frequency, adjustment))


@pytest.mark.parametrize("adjustment,autype,frequency", [
    (PriceAdjustment.BACKWARD, "hfq", BarFrequency.DAILY),
    (PriceAdjustment.NONE, "None", BarFrequency.M30),
    (PriceAdjustment.FORWARD, "qfq", BarFrequency.M30),
], ids=['DFLS-17-C01', 'DFLS-17-C02', 'DFLS-17-C03'])
def test_quote_adapter_half_day_timezone_and_adjustment_request(adjustment, autype, frequency):
    quotes = Quotes()
    req = request(EquityProduct.BARS, adjustment, frequency)
    bindings = futu_equity_bindings(source=req.parameters.source, quote_context=quotes)
    frame, metadata = bindings[req.parameters.provider_key].fetch(req)
    validate_equity_frame(frame, req, metadata)
    assert len(frame) == (7 if frequency is BarFrequency.M30 else 1) and frame.BarStart.iloc[0].hour == 14
    assert frame.Date.iloc[-1].hour == 18  # 13:00 local half-day close.
    assert quotes.calls[0]["autype"] == autype and quotes.calls[0]["session"] == "RTH"
    assert metadata["adjustment"] == adjustment.value
    assert metadata['acquisition_method'] == ('PROVIDER_RAW' if adjustment is PriceAdjustment.NONE else 'PROVIDER_ADJUSTED')


def test_DFLS_17_C04_repeated_page_key_is_a_failure():
    quotes = Quotes()
    quotes.repeat = True
    req = request(EquityProduct.BARS)
    fetch = futu_equity_bindings(source=req.parameters.source, quote_context=quotes)[req.parameters.provider_key].fetch
    with pytest.raises(IncompleteDataError, match="pagination key"):
        fetch(req)


class GappedQuotes(Quotes):
    def __init__(self, defect=None):
        super().__init__()
        self.defect = defect

    def request_history_kline(self, code, **kwargs):
        ret, frame, key = super().request_history_kline(code, **kwargs)
        if self.defect == "request_failure":
            return -1, "quote failure", None
        if self.defect == "empty":
            return ret, frame.iloc[:0], None
        if self.defect == "duplicate":
            return ret, pd.concat((frame, frame.iloc[:1]), ignore_index=True), None
        if self.defect == "outside_grid":
            frame.loc[0, "time_key"] = "2026-11-27 09:45:00"
        if self.defect == "bad_ohlc":
            frame.loc[0, "high"] = 1.
        frame.loc[2, "volume"] = 0.
        frame.loc[2, "turnover"] = 0.
        return ret, frame.drop(index=1).reset_index(drop=True), key


def gap_flows(tmp_path, quotes, policy):
    req = request(EquityProduct.BARS)
    bindings = futu_equity_bindings(source=req.parameters.source, quote_context=quotes, research_policy=policy)
    return Dataflows(base_dir=tmp_path, space=DataSpace(Path("assets")),
                     providers=ProviderConfig(bindings={}, equity_bindings=bindings))


def test_DFLS_18_C01_explicit_gap_policy_prepares_and_pins_observations(tmp_path):
    block = TimeInterval(datetime(2026, 11, 27, 16, 5, tzinfo=timezone.utc),
                         datetime(2026, 11, 27, 16, 10, tzinfo=timezone.utc))
    policy = UsEquityBarPolicy((block,))
    quotes = GappedQuotes()
    flows = gap_flows(tmp_path, quotes, policy)
    requests = tuple(request(p) for p in (EquityProduct.BARS, EquityProduct.SESSIONS))
    prepared = flows.prepare(requests, policy=PreparePolicy.REUSE)
    assert prepared.ready, [i.error for i in prepared.items]
    fetched = flows.fetch(requests[0], prepared=prepared.reference)
    assert fetched.ready, fetched.error
    bars = fetched.dataframe
    assert len(bars) == 7 and len(quotes.calls) == 1
    assert list(bars.BarStatus) == ["OBSERVED", "MISSING", "ZERO_VOLUME"] + ["OBSERVED"] * 4
    assert bars.loc[1, ["Open", "High", "Low", "Close", "Volume", "Amount"]].isna().all()
    assert bars.AvailableDate.iloc[1] == bars.Date.iloc[1]
    assert list(bars.ExecutionBlocked) == [False, False, False, True, False, False, False]
    assert "equity.trading_facts" not in flows.datasets and "equity.actions" not in flows.datasets
    # Reloaded, pinned content retains missing values and its content identity.
    reloaded = gap_flows(tmp_path, GappedQuotes("request_failure"), policy).fetch(requests[0], prepared=prepared.reference)
    assert reloaded.ready and reloaded.identity.content_sha256 == fetched.identity.content_sha256
    pd.testing.assert_frame_equal(reloaded.dataframe, bars)


@pytest.mark.parametrize("defect,error", [
    ('request_failure', SourceRequestError),
], ids=['DFLS-18-C03'])
def test_research_gap_policy_does_not_mask_source_failures(defect, error):
    quotes = GappedQuotes(defect)
    quotes.repeat = defect == "pagination"
    req = request(EquityProduct.BARS)
    binding = futu_equity_bindings(source=req.parameters.source,quote_context=quotes,
        research_policy=UsEquityBarPolicy())[req.parameters.provider_key]
    with pytest.raises(error):
        frame, metadata = binding.fetch(req)
        validate_equity_frame(frame, req, metadata)


def test_DFLS_18_C05_default_adapter_requires_complete_grid():
    req = request(EquityProduct.BARS)
    bindings = futu_equity_bindings(source=req.parameters.source,quote_context=GappedQuotes())
    with pytest.raises(IncompleteDataError):
        frame, metadata = bindings[req.parameters.provider_key].fetch(req)
        validate_equity_frame(frame, req, metadata)


def test_DFLS_18_C02_zero_volume_is_distinct_from_missing_bar():
    req = request(EquityProduct.BARS)
    binding = futu_equity_bindings(source=req.parameters.source,quote_context=GappedQuotes(),
        research_policy=UsEquityBarPolicy())[req.parameters.provider_key]
    frame, metadata = binding.fetch(req)
    validate_equity_frame(frame, req, metadata)
    assert frame.loc[2,'BarStatus'] == 'ZERO_VOLUME' and frame.loc[2,'Volume'] == 0
    assert frame.loc[2,'Close'] == 10.
    assert frame.loc[1,'BarStatus'] == 'MISSING' and pd.isna(frame.loc[1,'Close'])


@pytest.mark.parametrize("defect", [
    'fake_missing_price',
], ids=['DFLS-18-C04'])
def test_gap_declarations_are_validated_at_the_responsible_boundary(tmp_path, empty_space_factory, defect):
    req = request(EquityProduct.BARS)
    binding = futu_equity_bindings(source=req.parameters.source, quote_context=GappedQuotes(),
                                  research_policy=UsEquityBarPolicy())[req.parameters.provider_key]
    frame, metadata = binding.fetch(req)
    if defect == "missing_policy":
        del metadata["research_bar_policy"]
    elif defect == "incomplete_download":
        metadata["download_receipts"][-1]["more_pages"] = True
    elif defect == "fake_missing_price":
        frame.loc[1, "Close"] = 10.
    elif defect == "wrong_zero":
        frame.loc[2, "BarStatus"] = "OBSERVED"
    elif defect == "wrong_block":
        frame.loc[3, "ExecutionBlocked"] = True
    elif defect == "unknown_status":
        frame.loc[0, "BarStatus"] = "HALTED"
    elif defect == "cn_market":
        req = EquityDataRequest(InstrumentId(MarketId.CN, AssetClass.STOCK, "600000.SH"), req.parameters.source, req.parameters.query)
    if defect == 'fake_missing_price':
        # One public admission proves custom bindings cannot bypass validation;
        # the remaining malformed-field matrix belongs to the validator itself.
        flows = Dataflows(base_dir=tmp_path, space=empty_space_factory("assets"), providers=ProviderConfig(bindings={},
            equity_bindings={req.parameters.provider_key: ProviderBinding("futu", "test-v1", lambda _: (frame, metadata))}))
        prepared = flows.prepare((req,), policy=PreparePolicy.REFRESH)
        assert not prepared.ready and prepared.reference is None
        assert prepared.items[0].identity is None
        assert prepared.items[0].error.code == 'DATA_CONTRACT_MISMATCH'
    else:
        with pytest.raises(IncompleteDataError if defect == 'incomplete_download' else DataContractError):
            validate_equity_frame(frame, req, metadata)



def test_partial_session_publishes_completed_grid_without_filling_missing_bars(tmp_path):
    from dataclasses import replace

    full = request(EquityProduct.BARS)
    p = full.parameters
    cutoff = datetime(2026, 11, 27, 15, 30, tzinfo=timezone.utc)
    partial = EquityDataRequest(p.instrument, p.source, replace(p.query, completed_through=cutoff))
    flows = gap_flows(tmp_path, Quotes(), None)
    result = flows.prepare((partial, full), policy=PreparePolicy.REUSE)
    assert result.ready
    partial_frame = flows.fetch(partial, prepared=result.reference).dataframe
    assert len(partial_frame) == 2 and partial_frame.Date.iloc[-1] == cutoff
    assert len(flows.fetch(full, prepared=result.reference).dataframe) == 7
    incomplete = gap_flows(tmp_path / 'missing', GappedQuotes(), None)
    assert not incomplete.prepare((partial,), policy=PreparePolicy.REUSE).ready
