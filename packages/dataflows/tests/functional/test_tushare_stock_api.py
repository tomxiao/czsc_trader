"""A-share bars reuse the explicit Tushare client without profile writes."""

from __future__ import annotations

import pandas as pd
import pytest

from dataflows import DataRequest, DataStatus, Dataset
from dataflows import tushare_stock


class _StockCalendarPro:
    def stock_basic(self, *, ts_code, fields):
        assert fields == "ts_code,list_date"
        return pd.DataFrame({"ts_code": [ts_code], "list_date": ["20000101"]})

    def trade_cal(self, *, exchange, start_date, end_date):
        assert exchange == "SSE"
        dates = pd.date_range(start_date, end_date)
        return pd.DataFrame({
            "cal_date": dates.strftime("%Y%m%d"),
            "is_open": (dates.dayofweek < 5).astype(int),
        })

    def adj_factor(self, *, ts_code, start_date, end_date):
        dates = pd.date_range(start_date, end_date)
        return pd.DataFrame({"trade_date": dates.strftime("%Y%m%d"), "adj_factor": 2.})




@pytest.mark.parametrize('dataset,anomaly', [
    (Dataset.STOCK_UNADJUSTED_INTRADAY, None),
    (Dataset.STOCK_UNADJUSTED_INTRADAY, "volume_mismatch"),
], ids=['DFLS-16-C02', 'DFLS-22-C01'])
def test_stock_intraday_publishes_requested_window_with_daily_reconciliation(
    flow_factory, publish_data, monkeypatch, anomaly, dataset,
) -> None:
    client = _StockCalendarPro()
    calls = []
    monkeypatch.setattr(tushare_stock, "get_tushare_pro", lambda _: client)

    def fake_source(method, **kwargs):
        calls.append({"method": method, **kwargs})
        assert kwargs["start_date"] == (
            "20260929" if method == "daily" else "20260929 00:00:00"
        )
        if method == "daily":
            return pd.DataFrame([{
                "trade_date": "20260929", "open": 4., "high": 4.,
                "low": 4., "close": 4., "vol": 49. if anomaly == "volume_mismatch" else 48.,
                "amount": 19.2,
            }])
        assert kwargs["freq"] == "5min"
        times = pd.date_range("2026-09-29 09:35", "2026-09-29 11:30", freq="5min").append(
            pd.date_range("2026-09-29 13:05", "2026-09-29 15:00", freq="5min")
        )
        if anomaly == "missing_bar":
            times = times.delete(3)
        return pd.DataFrame({
            "trade_time": times, "trade_date": "20260929", "open": 4., "high": 4., "low": 4.,
            "close": 4., "vol": 100., "amount": 400.,
        })

    monkeypatch.setattr(client, "daily", lambda **kwargs: fake_source("daily", **kwargs), raising=False)
    monkeypatch.setattr(client, "stk_mins", lambda **kwargs: fake_source("stk_mins", **kwargs), raising=False)
    result = publish_data(flow_factory(), DataRequest(
        dataset, "600406.SH",
        "2026-09-29 10:00:00", "2026-09-29 10:15:00", None, frequency="5m",
    ))
    assert {call["method"] for call in calls} == {"daily", "stk_mins"}
    if anomaly is not None:
        assert result.status is (DataStatus.INCOMPLETE if anomaly == "missing_bar" else DataStatus.FAILED)
        if anomaly == "volume_mismatch":
            assert result.error.code == "DATA_CONTRACT_MISMATCH"
        assert result.dataframe.empty
        return
    assert result.status is DataStatus.READY, result.error
    assert len(result.dataframe) == 4
    adjusted = dataset is Dataset.STOCK_OHLCV
    assert result.dataframe.Close.eq(8. if adjusted else 4.).all()
    assert pd.to_datetime(result.dataframe.Date).tolist() == pd.date_range("2026-09-29 10:00", periods=4, freq="5min").tolist()
    assert result.dataframe.Volume.tolist() == [50. if adjusted else 100.] * 4
    assert result.dataframe.Amount.tolist() == [400.] * 4
    assert result.identity.metadata["adjustment"] == ("hfq" if adjusted else "none")
    quality = result.identity.metadata["ohlcv_quality_evidence"]
    assert quality["sessions"]["2026-09-29"]["daily_accurate"] is True
    assert quality["sessions"]["2026-09-29"]["minute_accurate"] is True
    assert result.identity.metadata["daily_session_coverage"]["expected_dates"] == ["2026-09-29"]
    if not adjusted:
        assert result.identity.metadata["source_publication_timestamp_verified"] is False
        assert len(result.identity.metadata["reference_daily_sha256"]) == 64
    pd.testing.assert_series_equal(
        result.dataframe.AvailableDate, pd.to_datetime(result.dataframe.Date), check_names=False,
    )
