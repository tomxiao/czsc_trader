from __future__ import annotations

import pandas as pd
import pytest

from dataflows import DataRequest, DataStatus, Dataset
from dataflows import tushare_etf


def test_etf_long_history_fetch_segments_adjustment_factors(flow_factory, publish_data, monkeypatch) -> None:
    class FakePro:
        def __init__(self) -> None:
            self.factor_requests: list[tuple[str, str]] = []

        def fund_daily(self, **_kwargs):
            return pd.DataFrame([
                {"trade_date": "20130315", "open": 1, "high": 1, "low": 1,
                 "close": 1, "vol": 1, "amount": 1},
                {"trade_date": "20260908", "open": 2, "high": 2, "low": 2,
                 "close": 2, "vol": 1, "amount": 1},
            ])

        def fund_adj(self, *, start_date, end_date, **_kwargs):
            self.factor_requests.append((start_date, end_date))
            factors = pd.DataFrame([
                {"trade_date": "20130315", "adj_factor": 1.0},
                {"trade_date": "20200102", "adj_factor": 1.5},
                {"trade_date": "20260908", "adj_factor": 2.0},
            ])
            return factors.loc[
                factors["trade_date"].between(start_date, end_date)
            ].reset_index(drop=True)

        def trade_cal(self, *, start_date, end_date, **_kwargs):
            dates = pd.date_range(start_date, end_date).strftime("%Y%m%d")
            return pd.DataFrame({
                "cal_date": dates,
                "is_open": dates.isin(["20130315", "20260908"]).astype(int),
            })

    pro = FakePro()
    monkeypatch.setattr(tushare_etf, "get_tushare_pro", lambda _env=None: pro)

    bars, metadata = tushare_etf.fetch_etf_ohlcv(
        "510500.SH", "2013-03-15", "2026-09-08", "daily"
    )

    assert pro.factor_requests == [
        ("20130315", "20171231"),
        ("20180101", "20221231"),
        ("20230101", "20260908"),
    ]
    assert bars["Close"].tolist() == [1.0, 4.0]
    assert metadata["adjustment_factor_source"] == "fund_adj"
    assert bars["AvailableDate"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist() == [
        "2013-03-15 17:00:00", "2026-09-08 17:00:00",
    ]
    assert metadata["adjustment_factor_publication_timestamp_verified"] is False
    assert metadata["adjustment_factor_revision_history_verified"] is False

    request = DataRequest(
        Dataset.ETF_OHLCV, "510500.SH", "2013-03-15", "2026-09-08", "2026-09-08"
    )
    ready = publish_data(flow_factory({Dataset.ETF_OHLCV.value: lambda ignored: (bars, metadata)}), request)
    assert ready.status is DataStatus.READY
    assert ready.identity is not None
    assert ready.identity.temporal_contract.availability_time_field == "AvailableDate"
    for changed_frame, changed_metadata in (
        (bars, {**metadata, "adjustment": "none"}),
        (bars, {**metadata, "adjustment_factor_publication_timestamp_verified": True}),
        (bars.assign(AvailableDate=bars["AvailableDate"] - pd.Timedelta(hours=7)), metadata),
    ):
        failed = publish_data(flow_factory({
            Dataset.ETF_OHLCV.value: lambda ignored: (changed_frame, changed_metadata)
        }), request)
        assert failed.status is DataStatus.FAILED
        assert failed.error is not None and failed.error.code == "DATA_CONTRACT_MISMATCH"


@pytest.mark.parametrize("dataset,frequency", [
    (Dataset.ETF_UNADJUSTED_DAILY, "daily"),
    (Dataset.ETF_OHLCV, "daily"),
    (Dataset.ETF_OHLCV, "weekly"),
])
@pytest.mark.parametrize("symbol,exchange", [("588080.SH", "SSE"), ("159915.SZ", "SZSE")])
def test_etf_publication_requires_verified_daily_session_coverage(
    flow_factory, publish_data, monkeypatch, dataset, frequency, symbol, exchange,
):
    expected_exchange = exchange

    class DailyPro:
        missing = False
        calendar_gap = False
        duplicate_calendar = False
        closed_day_bar = False
        invalid_flag = False

        def fund_daily(self, **kwargs):
            # The request starts before this synthetic instrument's first observation.
            dates = ["20260914", "20260916"] if self.missing else [
                "20260914", "20260915", "20260916",
            ]
            if self.closed_day_bar:
                dates.insert(0, "20260913")
            return pd.DataFrame({
                "trade_date": dates, "open": 10., "high": 10., "low": 10.,
                "close": 10., "vol": 100., "amount": 100.,
            })

        def fund_adj(self, **kwargs):
            return pd.DataFrame({
                "trade_date": ["20260913", "20260914", "20260915", "20260916"],
                "adj_factor": 1.,
            })

        def trade_cal(self, *, exchange, start_date, end_date, **kwargs):
            assert exchange == expected_exchange
            dates = pd.date_range(start_date, end_date)
            calendar = pd.DataFrame({
                "cal_date": dates.strftime("%Y%m%d"),
                "is_open": (dates.dayofweek < 5).astype(int),
            })
            if self.calendar_gap:
                calendar = calendar.loc[calendar.cal_date.ne("20260915")]
            if self.duplicate_calendar:
                calendar = pd.concat([calendar, calendar.iloc[:1]], ignore_index=True)
            if self.invalid_flag:
                calendar.loc[0, "is_open"] = 2
            return calendar.iloc[::-1]

    pro = DailyPro()
    monkeypatch.setattr(tushare_etf, "get_tushare_pro", lambda _: pro)
    request = DataRequest(dataset, symbol, "2026-09-12", "2026-09-16",
                          "2026-09-16", frequency=frequency)
    flows = flow_factory()
    ready = publish_data(flows, request)
    assert ready.ready, ready.error

    pro.missing = True
    missing = publish_data(flows, request)
    assert missing.status is DataStatus.INCOMPLETE
    assert missing.error.context["missing_dates"] == ["2026-09-15"]
    assert missing.error.context["absence_reason"] == "UNVERIFIED"
    assert missing.dataframe.empty
    assert ready.identity.metadata["daily_session_coverage"]["verified_sessions"] == 3
    # A rejected refresh cannot mutate a previously pinned, complete publication.
    old = flows.fetch(request, prepared=ready.prepared)
    assert old.ready and old.identity.content_sha256 == ready.identity.content_sha256

    pro.missing = False
    pro.calendar_gap = True
    unavailable_calendar = publish_data(flows, request)
    assert unavailable_calendar.status is DataStatus.INCOMPLETE
    assert unavailable_calendar.error.code == "INCOMPLETE_DATA"
    pro.calendar_gap = False
    pro.duplicate_calendar = True
    malformed = publish_data(flows, request)
    assert malformed.status is DataStatus.FAILED
    assert malformed.error.code == "DATA_CONTRACT_MISMATCH"
    pro.duplicate_calendar = False
    pro.invalid_flag = True
    malformed_flag = publish_data(flows, request)
    assert malformed_flag.status is DataStatus.FAILED
    assert malformed_flag.error.code == "DATA_CONTRACT_MISMATCH"
    pro.invalid_flag = False
    pro.closed_day_bar = True
    closed_day = publish_data(flows, request)
    assert closed_day.status is DataStatus.FAILED
    assert closed_day.error.code == "DATA_CONTRACT_MISMATCH"
