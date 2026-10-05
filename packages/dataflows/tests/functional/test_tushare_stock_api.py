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


@pytest.mark.parametrize("dataset", [Dataset.STOCK_UNADJUSTED_DAILY, Dataset.STOCK_OHLCV],
                         ids=["raw-execution", "hfq-research"])
def test_stock_daily_pro_bar_receives_explicit_api(
    flow_factory, publish_data, monkeypatch, dataset,
) -> None:
    calls, factor_calls = [], []

    class StockPro(_StockCalendarPro):
        def adj_factor(self, **kwargs):
            factor_calls.append(kwargs)
            return pd.DataFrame({"trade_date": ["20260928"], "adj_factor": [2.]})

    client = StockPro()
    monkeypatch.setattr(tushare_stock, "get_tushare_pro", lambda _: client)

    def fake_pro_bar(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame([{
            "ts_code": "600406.SH", "trade_date": "20260928",
            "open": 24.0, "high": 24.5, "low": 23.8, "close": 24.2,
            "vol": 100.0, "amount": 240.0,
        }])

    monkeypatch.setattr(tushare_stock.ts, "pro_bar", fake_pro_bar)
    request = DataRequest(dataset, "600406.SH", "2026-09-28", "2026-09-28", "2026-09-28")
    flows = flow_factory()
    result = publish_data(flows, request)
    assert result.ready, result.error
    assert len(calls) == 1
    assert calls[0] == {
        "api": client, "ts_code": "600406.SH", "start_date": "20260928",
        "end_date": "20260928", "freq": "D", "asset": "E", "adj": None,
    }
    assert result.dataframe.Amount.tolist() == [240000.]
    assert result.identity.source == "tushare"
    assert result.identity.metadata["market"] == "a_share"
    assert result.identity.metadata["vendor_symbol"] == "600406.SH"
    if dataset is Dataset.STOCK_UNADJUSTED_DAILY:
        assert result.dataframe.Volume.tolist() == [10000.]
        assert result.dataframe.Close.tolist() == [24.2]
        assert result.identity.metadata["adjustment"] == "none"
        assert not factor_calls
    else:
        assert result.dataframe.Volume.tolist() == [5000.]
        assert result.dataframe.Close.tolist() == [48.4]
        assert factor_calls == [{"ts_code": "600406.SH", "start_date": "20260928", "end_date": "20260928"}]
        assert result.dataframe.AvailableDate.tolist() == [pd.Timestamp("2026-09-28 17:00")]
        metadata = result.identity.metadata
        assert metadata["adjustment"] == "hfq"
        assert metadata["adjustment_factor_source"] == "adj_factor"
        assert len(metadata["adjustment_factor_sha256"]) == 64
        assert metadata["adjustment_factor_publication_schedule"] == "trade day 09:15-09:20 Asia/Shanghai"
        assert metadata["adjustment_factor_publication_timestamp_verified"] is False
        assert metadata["adjustment_factor_revision_history_verified"] is False
    offline = flows.fetch(request, prepared=result.prepared)
    assert offline.ready and offline.identity == result.identity and len(calls) == 1


@pytest.mark.parametrize("anomaly", [None, "volume_mismatch", "missing_bar"])
@pytest.mark.parametrize("dataset", [Dataset.STOCK_UNADJUSTED_INTRADAY, Dataset.STOCK_OHLCV],
                         ids=["raw-execution", "hfq-research"])
def test_stock_intraday_publishes_requested_window_with_daily_reconciliation(
    flow_factory, publish_data, monkeypatch, anomaly, dataset,
) -> None:
    client = _StockCalendarPro()
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
                "low": 4., "close": 4., "vol": 49. if anomaly == "volume_mismatch" else 48.,
                "amount": 19.2,
            }])
        times = pd.date_range("2026-09-29 09:35", "2026-09-29 11:30", freq="5min").append(
            pd.date_range("2026-09-29 13:05", "2026-09-29 15:00", freq="5min")
        )
        if anomaly == "missing_bar":
            times = times.delete(3)
        return pd.DataFrame({
            "trade_time": times, "trade_date": "20260929", "open": 4., "high": 4., "low": 4.,
            "close": 4., "vol": 100., "amount": 400.,
        })

    monkeypatch.setattr(tushare_stock.ts, "pro_bar", fake_pro_bar)
    result = publish_data(flow_factory(), DataRequest(
        dataset, "600406.SH",
        "2026-09-29 10:00:00", "2026-09-29 10:15:00", None, frequency="5m",
    ))
    assert {call["freq"] for call in calls} == {"D", "5min"}
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


@pytest.mark.parametrize("symbol,period", [("00700.HK", "5m"), ("600406.SH", "daily")])
def test_raw_stock_intraday_rejects_unsupported_requests_before_source(monkeypatch, symbol, period):
    monkeypatch.setattr(tushare_stock, "get_tushare_pro", lambda _: pytest.fail("source called"))
    with pytest.raises(tushare_stock.DataContractError):
        tushare_stock.fetch_stock_unadjusted_intraday(symbol, "2026-09-29", "2026-09-29", period)


@pytest.mark.parametrize("period, anomaly", [
    ("daily", None), ("weekly", None), ("30m", None),
    ("30m", "missing_bar"), ("30m", "amount_mismatch"),
])
def test_hk_stock_quality_uses_independent_daily_and_hk_calendar(
    flow_factory, publish_data, monkeypatch, period, anomaly,
):
    calls = []

    class HongKongPro:
        def hk_basic(self, *, ts_code, fields):
            calls.append("hk_basic")
            assert ts_code == "00700.HK" and fields == "ts_code,list_date"
            return pd.DataFrame({"ts_code": [ts_code], "list_date": ["20000101"]})

        def hk_tradecal(self, *, start_date, end_date):
            calls.append("hk_tradecal")
            assert start_date == end_date == "20260928"
            return pd.DataFrame({"cal_date": ["20260928"], "is_open": [1]})

        def hk_daily(self, *, ts_code, start_date, end_date):
            calls.append("hk_daily")
            assert ts_code == "00700.HK" and start_date == end_date == "20260928"
            return pd.DataFrame({"trade_date": ["20260928"], "open": [4.], "high": [4.],
                                 "low": [4.], "close": [4.], "vol": [1100.], "amount": [4400.]})

        def hk_mins(self, *, ts_code, start_date, end_date, freq):
            calls.append("hk_mins")
            assert ts_code == "00700.HK" and freq == "30min"
            assert start_date == "20260928 00:00:00" and end_date == "20260928 23:59:59"
            times = pd.to_datetime([
                f"2026-09-28 {clock}" for clock in
                ("10:00", "10:30", "11:00", "11:30", "12:00", "13:30",
                 "14:00", "14:30", "15:00", "15:30", "16:00")
            ])
            if anomaly == "missing_bar":
                times = times.delete(3)
            return pd.DataFrame({"trade_time": times, "open": 4., "high": 4., "low": 4.,
                                 "close": 4., "vol": 100.,
                                 "amount": 401. if anomaly == "amount_mismatch" else 400.})

    pro = HongKongPro()
    monkeypatch.setattr(tushare_stock, "get_tushare_pro", lambda _: pro)
    request = DataRequest(Dataset.STOCK_OHLCV, "00700.HK", "2026-09-28", "2026-09-28",
                          None, frequency=period)
    flows = flow_factory()
    result = publish_data(flows, request)
    assert calls.count("hk_daily") == calls.count("hk_basic") == calls.count("hk_tradecal") == 1
    if anomaly is not None:
        assert result.status is (DataStatus.INCOMPLETE if anomaly == "missing_bar" else DataStatus.FAILED)
        assert result.dataframe.empty
        return
    assert result.ready, result.error
    assert len(result.dataframe) == (11 if period == "30m" else 1)
    metadata = result.identity.metadata
    assert metadata["daily_session_coverage"]["source"] == "hk_tradecal"
    assert metadata["daily_session_coverage"]["listing_source"] == "hk_basic"
    assert metadata["ohlcv_quality"]["daily"]["accuracy"] == 1.
    if period == "30m":
        assert metadata["ohlcv_quality"]["minute"]["accuracy"] == 1.
    before = list(calls)
    assert flows.fetch(request, prepared=result.prepared).ready
    assert calls == before


@pytest.mark.parametrize("period, missing", [("daily", False), ("weekly", False), ("daily", True)])
def test_us_stock_quality_requires_complete_source_calendar(
    flow_factory, publish_data, monkeypatch, period, missing,
):
    calls = []

    class AmericanPro:
        def us_basic(self, *, ts_code, fields):
            calls.append("us_basic")
            assert ts_code == "AAPL" and fields == "ts_code,list_date"
            return pd.DataFrame({"ts_code": [ts_code], "list_date": ["19801212"]})

        def us_tradecal(self, *, start_date, end_date):
            calls.append("us_tradecal")
            assert start_date == "20260928" and end_date == "20260929"
            return pd.DataFrame({"cal_date": ["20260928", "20260929"], "is_open": [1, 1]})

        def us_daily(self, *, ts_code, start_date, end_date):
            calls.append("us_daily")
            assert ts_code == "AAPL" and start_date == "20260928" and end_date == "20260929"
            return pd.DataFrame({"trade_date": ["20260929"] if missing else ["20260928", "20260929"],
                                 "open": 200., "high": 210., "low": 190., "close": 205.,
                                 "vol": 100., "amount": 20000.})

    pro = AmericanPro()
    monkeypatch.setattr(tushare_stock, "get_tushare_pro", lambda _: pro)
    request = DataRequest(Dataset.STOCK_OHLCV, "AAPL", "2026-09-28", "2026-09-29", None,
                          frequency=period)
    flows = flow_factory()
    result = publish_data(flows, request)
    assert calls == ["us_daily", "us_basic", "us_tradecal"]
    if missing:
        assert result.status is DataStatus.INCOMPLETE and result.dataframe.empty
        return
    assert result.ready, result.error
    assert result.identity.metadata["ohlcv_quality"]["daily"]["accuracy"] == 1.
    assert result.identity.metadata["daily_session_coverage"]["source"] == "us_tradecal"
    assert result.identity.metadata["daily_session_coverage"]["listing_source"] == "us_basic"
    assert result.dataframe.Volume.tolist() == ([200.] if period == "weekly" else [100., 100.])
    assert flows.fetch(request, prepared=result.prepared).ready
    assert calls == ["us_daily", "us_basic", "us_tradecal"]
