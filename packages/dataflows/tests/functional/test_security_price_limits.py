"""Daily raw price boundaries publish only with complete source evidence."""

from copy import deepcopy

import pandas as pd
import pytest

from dataflows import DataRequest, DataStatus, Dataset
from dataflows import security_price_limits as limits


class LimitPro:
    def __init__(self, symbol="600722.SH", anomaly=None):
        self.symbol, self.anomaly, self.calls = symbol, anomaly, []

    def stock_basic(self, *, ts_code, fields):
        return pd.DataFrame({"ts_code": [ts_code], "list_date": ["20000101"]})

    fund_basic = stock_basic

    def trade_cal(self, *, exchange, start_date, end_date):
        dates = pd.date_range(start_date, end_date)
        if self.anomaly == "calendar_gap":
            dates = dates[:-1]
        return pd.DataFrame({"cal_date": dates.strftime("%Y%m%d"),
                             "is_open": (dates.dayofweek < 5).astype(int)})

    def _fetch(self, api, **kwargs):
        self.calls.append((api, kwargs))
        dates = pd.bdate_range(kwargs["start_date"], kwargs["end_date"])
        frame = pd.DataFrame({"ts_code": self.symbol, "trade_date": dates.strftime("%Y%m%d"),
                              "up_limit": 11., "down_limit": 9.,
                              "asset_type": "ETF" if self.symbol.startswith("5") else "STK",
                              "exchange": "SSE"})
        anomaly = self.anomaly
        if anomaly == "empty":
            return frame.iloc[:0]
        if anomaly == "missing":
            return frame.iloc[:-1]
        if anomaly == "duplicate":
            return pd.concat([frame, frame.iloc[:1]], ignore_index=True)
        if anomaly in {"zero", "negative", "nan", "infinite", "reverse", "equal"}:
            frame.loc[0, "up_limit"] = {"zero": 0., "negative": -1., "nan": float("nan"),
                                         "infinite": float("inf"), "reverse": 8., "equal": 9.}[anomaly]
        if anomaly == "wrong_symbol":
            frame.loc[0, "ts_code"] = "600000.SH"
        if anomaly == "wrong_asset":
            frame.loc[0, "asset_type"] = "OTHER"
        if anomaly == "wrong_exchange":
            frame.loc[0, "exchange"] = "SZSE"
        if anomaly == "invalid_date":
            frame.loc[0, "trade_date"] = "invalid"
        if anomaly == "source_field":
            frame = frame.drop(columns="up_limit")
        return frame

    def stk_limit(self, **kwargs):
        return self._fetch("stk_limit", **kwargs)

    def etf_limit(self, **kwargs):
        return self._fetch("etf_limit", **kwargs)


def request(symbol="600722.SH", start="2026-09-28", end="2026-09-30"):
    return DataRequest(Dataset.SECURITY_PRICE_LIMITS, symbol, start, end, end)


@pytest.mark.parametrize("symbol,api", [("600722.SH", "stk_limit"), ("510300.SH", "etf_limit")])
def test_publish_raw_security_price_limits(flow_factory, publish_data, monkeypatch, symbol, api):
    pro = LimitPro(symbol)
    monkeypatch.setattr(limits, "get_tushare_pro", lambda _: pro)
    flows = flow_factory()
    result = publish_data(flows, request(symbol))
    assert result.ready, result.error
    assert result.dataframe.columns.tolist() == ["Date", "UpLimit", "DownLimit"]
    assert result.dataframe.Date.tolist() == ["2026-09-28", "2026-09-29", "2026-09-30"]
    metadata = result.identity.metadata
    assert metadata["vendor_interface"] == api
    assert metadata["adjustment"] == "none"
    assert metadata["historical_revision_history_verified"] is False
    assert metadata["source_publication_timestamp_verified"] is False
    assert len(pro.calls) == 1 and pro.calls[0][0] == api


@pytest.mark.parametrize("anomaly,status", [
    ("empty", DataStatus.EMPTY), ("missing", DataStatus.INCOMPLETE),
    ("calendar_gap", DataStatus.INCOMPLETE), ("duplicate", DataStatus.FAILED),
    ("zero", DataStatus.FAILED), ("negative", DataStatus.FAILED),
    ("nan", DataStatus.FAILED), ("infinite", DataStatus.FAILED),
    ("reverse", DataStatus.FAILED), ("equal", DataStatus.FAILED),
    ("wrong_symbol", DataStatus.FAILED), ("wrong_asset", DataStatus.FAILED),
    ("wrong_exchange", DataStatus.FAILED), ("invalid_date", DataStatus.FAILED),
    ("source_field", DataStatus.FAILED),
])
def test_invalid_source_never_ready(flow_factory, publish_data, monkeypatch, anomaly, status):
    pro = LimitPro(anomaly=anomaly)
    monkeypatch.setattr(limits, "get_tushare_pro", lambda _: pro)
    result = publish_data(flow_factory(), request())
    assert result.status is status, result.error
    assert result.dataframe.empty
    assert len(pro.calls) == 1  # No alternate source or silent retry.


@pytest.mark.parametrize("symbol", ["AAPL", "00700.HK", "920001.BJ"])
def test_unsupported_market_fails_before_source(flow_factory, publish_data, monkeypatch, symbol):
    monkeypatch.setattr(limits, "get_tushare_pro", lambda _: pytest.fail("must reject before provider"))
    result = publish_data(flow_factory(), request(symbol))
    assert result.status is DataStatus.FAILED


def test_request_rejects_missing_symbol_frequency_and_timestamp():
    with pytest.raises(ValueError, match="require a symbol"):
        request(None)
    with pytest.raises(ValueError, match="frequency"):
        DataRequest(Dataset.SECURITY_PRICE_LIMITS, "600722.SH", "2026-09-28", "2026-09-30", None, "30m")
    with pytest.raises(ValueError, match="ISO date"):
        request(start="2026-09-28 09:30:00")


@pytest.mark.parametrize("tamper", ["session", "hash", "lineage"])
def test_facade_revalidates_bound_provider(flow_factory, publish_data, monkeypatch, tamper):
    pro = LimitPro()
    monkeypatch.setattr(limits, "get_tushare_pro", lambda _: pro)
    frame, metadata = limits.fetch_security_price_limits(request())
    if tamper == "session":
        frame = frame.iloc[:-1]
    elif tamper == "hash":
        metadata = deepcopy(metadata)
        metadata["daily_session_coverage"]["calendar_sha256"] = "0" * 64
    else:
        metadata["adjustment"] = "hfq"
    flows = flow_factory({Dataset.SECURITY_PRICE_LIMITS: lambda _: (frame, metadata)})
    result = publish_data(flows, request())
    assert result.status is (DataStatus.INCOMPLETE if tamper == "session" else DataStatus.FAILED)


def test_large_range_is_deterministically_chunked(monkeypatch):
    pro = LimitPro()
    monkeypatch.setattr(limits, "get_tushare_pro", lambda _: pro)
    frame, _ = limits.fetch_security_price_limits(request(start="2025-12-31", end="2026-01-02"))
    assert len(pro.calls) == 2 and len(frame) == 3
    assert pro.calls[0][1]["end_date"] == "20251231"
    assert pro.calls[1][1]["start_date"] == "20260101"
