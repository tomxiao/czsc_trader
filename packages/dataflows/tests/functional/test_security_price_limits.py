"""Daily raw price boundaries publish only with complete source evidence."""

import pandas as pd
import pytest

from dataflows import DataRequest, DataStatus, Dataset, PreparePolicy
from dataflows import security_price_limits as limits
from dataflows.errors import DataContractError, IncompleteDataError


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
        return pd.DataFrame(
            {"cal_date": dates.strftime("%Y%m%d"), "is_open": (dates.dayofweek < 5).astype(int)}
        )

    def _fetch(self, api, **kwargs):
        self.calls.append((api, kwargs))
        dates = pd.bdate_range(kwargs["start_date"], kwargs["end_date"])
        frame = pd.DataFrame(
            {
                "ts_code": self.symbol,
                "trade_date": dates.strftime("%Y%m%d"),
                "up_limit": 11.0,
                "down_limit": 9.0,
                "asset_type": "ETF" if self.symbol.startswith("5") else "STK",
                "exchange": "SSE",
            }
        )
        anomaly = self.anomaly
        if anomaly == "empty":
            return frame.iloc[:0]
        if anomaly == "missing":
            return frame.iloc[:-1]
        if anomaly == "duplicate":
            return pd.concat([frame, frame.iloc[:1]], ignore_index=True)
        if anomaly in {"zero", "negative", "nan", "infinite", "reverse", "equal"}:
            frame.loc[0, "up_limit"] = {
                "zero": 0.0,
                "negative": -1.0,
                "nan": float("nan"),
                "infinite": float("inf"),
                "reverse": 8.0,
                "equal": 9.0,
            }[anomaly]
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


@pytest.mark.parametrize(
    "symbol,api",
    [
        ("600722.SH", "stk_limit"),
        ("510300.SH", "etf_limit"),
    ],
    ids=["DFLS-25-C01", "DFLS-25-C02"],
)
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


@pytest.mark.parametrize(
    "anomaly,error",
    [
        ("missing", IncompleteDataError),
        ("reverse", DataContractError),
    ],
    ids=["DFLS-25-C05", "DFLS-25-C03"],
)
def test_invalid_source_rejected_by_real_adapter(monkeypatch, anomaly, error):
    # Generic facade state mapping lives in test_contract; provider admission
    # remains covered below without storing every invalid source variant.
    pro = LimitPro(anomaly=anomaly)
    monkeypatch.setattr(limits, "get_tushare_pro", lambda _: pro)
    with pytest.raises(error):
        limits.fetch_security_price_limits(request())
    assert len(pro.calls) == 1  # No alternate source or silent retry.


def test_DFLS_25_C04_infinite_upper_limit_rejected(monkeypatch):
    pro = LimitPro()
    original = pro.stk_limit

    def invalid(**kwargs):
        frame = original(**kwargs)
        frame.loc[0, "up_limit"] = float("inf")
        return frame

    monkeypatch.setattr(pro, "stk_limit", invalid)
    monkeypatch.setattr(limits, "get_tushare_pro", lambda _: pro)
    with pytest.raises(DataContractError):
        limits.fetch_security_price_limits(request())
    assert len(pro.calls) == 1


def test_DFLS_25_C07_provider_hfq_claim_cannot_publish(flow_factory, monkeypatch):
    monkeypatch.setattr(limits, "get_tushare_pro", lambda _: LimitPro())
    frame, meta = limits.fetch_security_price_limits(request())
    meta["adjustment"] = "hfq"
    prepared = flow_factory({Dataset.SECURITY_PRICE_LIMITS: lambda _: (frame, meta)}).prepare(
        (request(),), policy=PreparePolicy.REFRESH
    )
    assert prepared.reference is None
    (item,) = prepared.items
    assert item.status is DataStatus.FAILED and item.identity is None
    assert item.error.code == "DATA_CONTRACT_MISMATCH"
