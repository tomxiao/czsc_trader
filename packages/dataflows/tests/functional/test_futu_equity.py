"""Quote adapter normalization without a running OpenD or broker connection."""
from datetime import date, datetime, timezone
from pathlib import Path
import pandas as pd
import pytest

from dataflows import (AssetClass, EquityDataRequest, EquityProduct, EquityQuery, InstrumentId,
                       MarketId, SourceRef, futu_equity_bindings, UsEquityBarPolicy, TimeInterval,
                       Dataflows, DataSpace, ProviderConfig, PreparePolicy, ProviderBinding)
from dataflows.equity_data import validate_equity_frame
from dataflows.errors import DataContractError, IncompleteDataError


class Quotes:
    def __init__(self):
        self.calls = []
        self.action = pd.DataFrame()
        self.repeat = False

    def request_trading_days(self, **kwargs):
        return 0, [{"time": "2026-11-27", "trade_date_type": "MORNING"}]

    def get_rehab(self, code):
        return 0, self.action

    def request_history_kline(self, code, **kwargs):
        self.calls.append(kwargs)
        frame = pd.DataFrame({"code": code, "time_key": pd.date_range("2026-11-27 10:00", periods=7, freq="30min").astype(str),
                              "open": 10., "high": 11., "low": 9., "close": 10., "volume": 100., "turnover": 1000.})
        return 0, frame, b"same" if self.repeat else None


def request(product):
    return EquityDataRequest(InstrumentId(MarketId.US, AssetClass.STOCK, "LITE"), SourceRef("futu", "test-v1"),
                              EquityQuery(product, date(2026, 11, 27), date(2026, 11, 27)))


def test_quote_adapter_half_day_timezone_and_unadjusted_request():
    quotes = Quotes()
    req = request(EquityProduct.BARS)
    bindings = futu_equity_bindings(source=req.parameters.source, quote_context=quotes)
    frame, metadata = bindings[req.parameters.provider_key].fetch(req)
    validate_equity_frame(frame, req, metadata)
    assert len(frame) == 7 and frame.BarStart.iloc[0].hour == 14
    assert quotes.calls[0]["autype"] == "None" and quotes.calls[0]["session"] == "RTH"


def test_quote_adapter_split_ratio_and_unsupported_cash_dividend():
    quotes = Quotes()
    quotes.action = pd.DataFrame([{"ex_div_date": "2026-11-27", "split_ratio": 5., "per_cash_div": 0.}])
    req = request(EquityProduct.ACTIONS)
    fetch = futu_equity_bindings(source=req.parameters.source, quote_context=quotes)[req.parameters.provider_key].fetch
    frame, metadata = fetch(req)
    validate_equity_frame(frame, req, metadata)
    assert frame.Ratio.iloc[0] == 5.  # SDK contract: one old share becomes five.
    quotes.action.loc[0, "per_cash_div"] = .2
    with pytest.raises(DataContractError, match="payment evidence"):
        fetch(req)


def test_repeated_page_key_is_a_failure():
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
            frame.loc[0, "time_key"] = "2026-11-27 09:45"
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


def test_explicit_gap_policy_prepares_and_pins_all_four_products(tmp_path):
    block = TimeInterval(datetime(2026, 11, 27, 16, 5, tzinfo=timezone.utc),
                         datetime(2026, 11, 27, 16, 10, tzinfo=timezone.utc))
    policy = UsEquityBarPolicy(1, .01, (block,))
    quotes = GappedQuotes()
    flows = gap_flows(tmp_path, quotes, policy)
    requests = tuple(request(p) for p in EquityProduct)
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
    constraints = flows.fetch(requests[3], prepared=prepared.reference)
    assert constraints.ready and constraints.dataframe.Tradable.all()
    assert constraints.dataframe.AvailableDate.equals(constraints.dataframe.Date)
    assert constraints.identity.metadata["tradability_basis"] == "RESEARCH_ASSUMPTION_NOT_HISTORICAL_HALT_EVIDENCE"
    # Reloaded, pinned content retains missing values and its content identity.
    reloaded = gap_flows(tmp_path, GappedQuotes("request_failure"), policy).fetch(requests[0], prepared=prepared.reference)
    assert reloaded.ready and reloaded.identity.content_sha256 == fetched.identity.content_sha256
    pd.testing.assert_frame_equal(reloaded.dataframe, bars)


@pytest.mark.parametrize("defect", ["request_failure", "empty", "duplicate", "outside_grid", "bad_ohlc", "pagination"])
def test_research_gap_policy_does_not_mask_source_failures(tmp_path, defect):
    quotes = GappedQuotes(defect)
    quotes.repeat = defect == "pagination"
    result = gap_flows(tmp_path, quotes, UsEquityBarPolicy(1, .01)).prepare(
        (request(EquityProduct.BARS),), policy=PreparePolicy.REFRESH)
    assert not result.ready and result.reference is None


def test_default_adapter_remains_strict_and_does_not_bind_constraints(tmp_path):
    flows = gap_flows(tmp_path, GappedQuotes(), None)
    assert "equity.constraints" not in flows.datasets
    result = flows.prepare((request(EquityProduct.BARS),), policy=PreparePolicy.REUSE)
    assert not result.ready and result.items[0].error.code == "INCOMPLETE_DATA"


@pytest.mark.parametrize("defect", ["missing_policy", "incomplete_download", "fake_missing_price", "wrong_zero",
                                   "wrong_block", "unknown_status", "cn_market", "wrong_constraints"])
def test_gap_declarations_are_validated_at_publication(tmp_path, defect):
    req = request(EquityProduct.CONSTRAINTS if defect == "wrong_constraints" else EquityProduct.BARS)
    binding = futu_equity_bindings(source=req.parameters.source, quote_context=GappedQuotes(),
                                  research_policy=UsEquityBarPolicy(1, .01))[req.parameters.provider_key]
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
    else:
        frame.loc[1, "Tradable"] = False
    flows = Dataflows(base_dir=tmp_path, space=DataSpace(Path("assets")), providers=ProviderConfig(bindings={},
        equity_bindings={req.parameters.provider_key: ProviderBinding("futu", "test-v1", lambda _: (frame, metadata))}))
    prepared = flows.prepare((req,), policy=PreparePolicy.REFRESH)
    assert not prepared.ready and prepared.reference is None


@pytest.mark.parametrize("step,tick", [(True, .01), (0, .01), (1, True), (1, float("nan")), (1, 0.)])
def test_research_policy_rejects_invalid_order_rules(step, tick):
    with pytest.raises(ValueError):
        UsEquityBarPolicy(step, tick)
