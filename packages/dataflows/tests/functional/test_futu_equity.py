"""Quote adapter normalization without a running OpenD or broker connection."""
from datetime import date
import pandas as pd
import pytest

from dataflows import (AssetClass, EquityDataRequest, EquityProduct, EquityQuery, InstrumentId,
                       MarketId, SourceRef, futu_equity_bindings)
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
