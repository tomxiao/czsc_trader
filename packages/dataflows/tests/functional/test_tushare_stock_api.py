"""A-share bars reuse the explicit Tushare client without profile writes."""

from __future__ import annotations

import pandas as pd
import pytest

from dataflows import DataRequest, DataStatus, Dataset
from dataflows import tushare_stock


def test_stock_daily_pro_bar_receives_explicit_api(monkeypatch) -> None:
    client = object()
    calls: list[dict] = []
    monkeypatch.setattr(tushare_stock, "get_tushare_pro", lambda _env: client)

    def fake_pro_bar(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame([{
            "ts_code": "600406.SH", "trade_date": "20260928",
            "open": 24.0, "high": 24.5, "low": 23.8, "close": 24.2,
            "vol": 100.0, "amount": 240.0,
        }])

    monkeypatch.setattr(tushare_stock.ts, "pro_bar", fake_pro_bar)

    bars, market, symbol = tushare_stock._fetch_tushare_ohlcv(
        "600406.SH", "2026-09-28", "2026-09-28", env_file=".env"
    )

    assert len(calls) == 1
    assert calls[0]["api"] is client
    assert calls[0]["ts_code"] == "600406.SH"
    assert calls[0]["freq"] == "D"
    assert calls[0]["asset"] == "E"
    assert (market, symbol) == (tushare_stock.MARKET_A_SHARE, "600406.SH")
    assert bars.loc[0, "Close"] == 24.2


def test_stock_minute_prefers_trade_time_over_pro_bar_derived_trade_date() -> None:
    raw = pd.DataFrame([{
        "ts_code": "600089.SH", "trade_time": "2025-03-03 09:35:00",
        "trade_date": "20250303", "open": 10.0, "high": 10.2,
        "low": 9.9, "close": 10.1, "vol": 100.0, "amount": 1000.0,
    }])

    bars = tushare_stock._standardize_a_share_tushare_ohlcv(raw, intraday=True)

    assert bars["Date"].tolist() == ["2025-03-03 09:35:00"]
    assert bars.loc[0, "Close"] == 10.1
    assert "trade_date" in raw.columns


@pytest.mark.parametrize("mismatch", [False, True])
def test_raw_stock_intraday_publishes_requested_window_with_daily_reconciliation(
    flow_factory, publish_data, monkeypatch, mismatch,
) -> None:
    client = object()
    calls = []
    monkeypatch.setattr(tushare_stock, "get_tushare_pro", lambda _: client)

    def fake_pro_bar(**kwargs):
        calls.append(kwargs)
        assert kwargs["adj"] is None
        assert kwargs["start_date"] == (
            "20260929" if kwargs["freq"] == "D" else "20260929 00:00:00"
        )
        if kwargs["freq"] == "D":
            return pd.DataFrame([{
                "trade_date": "20260929", "open": 4., "high": 4.,
                "low": 4., "close": 4., "vol": 49. if mismatch else 48.,
                "amount": 19.2,
            }])
        times = pd.date_range("2026-09-29 09:35", "2026-09-29 11:30", freq="5min").append(
            pd.date_range("2026-09-29 13:05", "2026-09-29 15:00", freq="5min")
        )
        return pd.DataFrame({
            "trade_time": times, "open": 4., "high": 4., "low": 4.,
            "close": 4., "vol": 100., "amount": 400.,
        })

    monkeypatch.setattr(tushare_stock.ts, "pro_bar", fake_pro_bar)
    result = publish_data(flow_factory(), DataRequest(
        Dataset.STOCK_UNADJUSTED_INTRADAY, "600406.SH",
        "2026-09-29 10:00:00", "2026-09-29 10:15:00", None, frequency="5m",
    ))
    assert {call["freq"] for call in calls} == {"D", "5min"}
    if mismatch:
        assert result.status is DataStatus.FAILED
        assert result.dataframe.empty
        return
    assert result.status is DataStatus.READY, result.error
    assert len(result.dataframe) == 4
    assert result.dataframe.Close.eq(4.).all()
    assert result.identity.metadata["adjustment"] == "none"
    assert result.identity.metadata["source_publication_timestamp_verified"] is False
    assert len(result.identity.metadata["reference_daily_sha256"]) == 64
    pd.testing.assert_series_equal(
        result.dataframe.AvailableDate, pd.to_datetime(result.dataframe.Date), check_names=False,
    )


@pytest.mark.parametrize("symbol,period", [("00700.HK", "5m"), ("600406.SH", "daily")])
def test_raw_stock_intraday_rejects_unsupported_requests_before_source(monkeypatch, symbol, period):
    monkeypatch.setattr(tushare_stock, "get_tushare_pro", lambda _: pytest.fail("source called"))
    with pytest.raises(tushare_stock.DataContractError):
        tushare_stock.fetch_stock_unadjusted_intraday(symbol, "2026-09-29", "2026-09-29", period)
