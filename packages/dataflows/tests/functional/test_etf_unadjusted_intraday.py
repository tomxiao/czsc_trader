from __future__ import annotations

import pandas as pd
import pytest

from dataflows import DataRequest, DataStatus, Dataset
from dataflows import tushare_etf


class FakePro:
    def __init__(self, *, mismatch=False):
        self.mismatch = mismatch
        self.calls = 0

    def etf_mins(self, **kwargs):
        self.calls += 1
        times = pd.date_range("2026-09-29 09:35", "2026-09-29 11:30", freq="5min").append(
            pd.date_range("2026-09-29 13:05", "2026-09-29 15:00", freq="5min")
        )
        return pd.DataFrame({"trade_time": times, "open": 4., "high": 4.,
                             "low": 4., "close": 4., "vol": 100., "amount": 400.})

    def fund_daily(self, **kwargs):
        return pd.DataFrame([{"trade_date": "20260929", "open": 4., "high": 4.,
                              "low": 4., "close": 4., "vol": 48. if not self.mismatch else 49.,
                              "amount": 19.2}])

    def fund_adj(self, **kwargs):
        pytest.fail("Raw minute prices must not fetch adjustment factors")

    def trade_cal(self, *, start_date, end_date, **kwargs):
        dates = pd.date_range(start_date, end_date)
        return pd.DataFrame({"cal_date": dates.strftime("%Y%m%d"),
                             "is_open": (dates.dayofweek < 5).astype(int)})


def request(frequency="5m"):
    return DataRequest(Dataset.ETF_UNADJUSTED_INTRADAY, "518850.SH", "2026-09-29",
                       "2026-09-29", None, frequency=frequency)


def test_raw_intraday_routes_validates_and_preserves_market_timing(flow_factory, publish_data, monkeypatch):
    pro = FakePro()
    monkeypatch.setattr(tushare_etf, "get_tushare_pro", lambda _: pro)
    flows = flow_factory()
    result = publish_data(flows, request())
    assert result.status is DataStatus.READY, result.error
    assert len(result.dataframe) == 48
    assert result.dataframe.Close.eq(4.).all()
    assert result.dataframe.Volume.sum() == 4800.
    pd.testing.assert_series_equal(result.dataframe.AvailableDate,
                                   pd.to_datetime(result.dataframe.Date), check_names=False)
    meta = result.identity.metadata
    assert meta["availability_basis"] == "MARKET_BAR_CLOSE_ASSUMPTION"
    assert meta["source_publication_timestamp_verified"] is False
    assert meta["live_feed_latency_verified"] is False
    assert meta["adjustment"] == "none"
    assert len(meta["reference_daily_sha256"]) == 64
    original = result
    # A subday refresh still reconciles the full source session before slicing.
    result = publish_data(flows, DataRequest(
        Dataset.ETF_UNADJUSTED_INTRADAY, "518850.SH",
        "2026-09-29 10:00:00", "2026-09-29 10:15:00", None, frequency="5m",
    ))
    assert result.status is DataStatus.READY, result.error
    assert result.dataframe.Date.tolist() == [
        f"2026-09-29 10:{minute:02d}:00" for minute in (0, 5, 10, 15)
    ]
    pro.mismatch = True
    result = publish_data(flows, request())
    assert result.status is DataStatus.FAILED
    assert result.dataframe.empty
    assert result.error.code == "DATA_REPAIR_FAILED"
    old = flows.fetch(request(), prepared=original.prepared)
    assert old.ready and old.identity.content_sha256 == original.identity.content_sha256


def test_raw_intraday_rejects_a_day_missing_from_both_sources(flow_factory, publish_data, monkeypatch):
    class GappedPro(FakePro):
        def etf_mins(self, **kwargs):
            original = super().etf_mins(**kwargs)
            return pd.concat([
                original.assign(trade_time=original.trade_time - pd.Timedelta(days=days))
                for days in (4, 0)
            ], ignore_index=True)

        def fund_daily(self, **kwargs):
            original = super().fund_daily(**kwargs)
            return pd.concat([
                original.assign(trade_date=day) for day in ("20260925", "20260929")
            ], ignore_index=True)

    monkeypatch.setattr(tushare_etf, "get_tushare_pro", lambda _: GappedPro())
    result = publish_data(flow_factory(), DataRequest(
        Dataset.ETF_UNADJUSTED_INTRADAY, "518850.SH", "2026-09-25", "2026-09-29",
        "2026-09-29", frequency="5m",
    ))
    assert result.status is DataStatus.INCOMPLETE
    assert result.error.context["missing_dates"] == ["2026-09-28"]
    assert result.dataframe.empty


@pytest.mark.parametrize("frequency", ["daily", "weekly", "60m"])
def test_raw_intraday_rejects_nonintraday_frequency_before_fetch(monkeypatch, frequency):
    def forbidden(_):
        pytest.fail("Invalid frequency must fail before supplier access")
    monkeypatch.setattr(tushare_etf, "get_tushare_pro", forbidden)
    with pytest.raises(ValueError):
        request(frequency)


@pytest.fixture(scope="module")
def raw_intraday_source():
    # Patch only the vendor transport while generating the immutable source once.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(tushare_etf, "get_tushare_pro", lambda _: FakePro())
        return tushare_etf.fetch_etf_unadjusted_intraday(
            "518850.SH", "2026-09-29", "2026-09-29", "5m")


@pytest.mark.parametrize("mutation", ["early", "missing", "hfq", "verified", "basis"])
def test_raw_intraday_facade_rejects_false_timing_or_price_claims(
    clone_published_flow, publish_data, raw_intraday_source, mutation,
):
    frame, meta = raw_intraday_source
    supplied_frame, supplied_meta = frame.copy(deep=True), meta.copy()
    flows, ready = clone_published_flow("raw-intraday", {
        Dataset.ETF_UNADJUSTED_INTRADAY: lambda _: (supplied_frame, supplied_meta),
    }, request())
    if mutation == "early":
        supplied_frame.AvailableDate -= pd.Timedelta(minutes=5)
    elif mutation == "missing":
        supplied_frame = supplied_frame.drop(columns="AvailableDate")
    elif mutation == "hfq":
        supplied_meta["adjustment"] = "hfq"
    elif mutation == "verified":
        supplied_meta["source_publication_timestamp_verified"] = True
    else:
        supplied_meta["availability_basis"] = "VERIFIED_LIVE_FEED"
    result = publish_data(flows, request())
    assert result.status is DataStatus.FAILED
    assert result.error.code == "DATA_CONTRACT_MISMATCH"
    old = flows.fetch(request(), prepared=ready.prepared)
    assert old.ready and old.identity.content_sha256 == ready.identity.content_sha256
