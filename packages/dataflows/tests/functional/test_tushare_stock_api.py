"""A-share bars reuse the explicit Tushare client without profile writes."""

from __future__ import annotations

import pandas as pd
import pytest

from dataflows import DataRequest, DataStatus, Dataset
from dataflows import tushare_stock


@pytest.mark.parametrize("dataset", [Dataset.STOCK_UNADJUSTED_DAILY, Dataset.STOCK_OHLCV],
                         ids=["raw-execution", "hfq-research"])
def test_stock_daily_pro_bar_receives_explicit_api(
    flow_factory, publish_data, monkeypatch, dataset,
) -> None:
    calls, factor_calls = [], []

    class StockPro:
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
            "trade_time": times, "trade_date": "20260929", "open": 4., "high": 4., "low": 4.,
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
        assert result.error.code == "DATA_CONTRACT_MISMATCH"
        assert result.dataframe.empty
        return
    assert result.status is DataStatus.READY, result.error
    assert len(result.dataframe) == 4
    assert result.dataframe.Close.eq(4.).all()
    assert pd.to_datetime(result.dataframe.Date).tolist() == pd.date_range("2026-09-29 10:00", periods=4, freq="5min").tolist()
    assert result.dataframe.Volume.tolist() == [100.] * 4
    assert result.dataframe.Amount.tolist() == [400.] * 4
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
