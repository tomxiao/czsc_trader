from __future__ import annotations

import pandas as pd
import pytest

from dataflows import DataRequest, DataStatus, Dataset, canonical_frame_sha256
from dataflows import tushare_etf


@pytest.fixture(scope="module")
def etf_adjusted_source(publication_seeds):
    class FakePro:
        def __init__(self) -> None:
            self.factor_requests: list[tuple[str, str]] = []

        def fund_daily(self, **_kwargs):
            return pd.DataFrame([
                {"trade_date": "20130315", "open": 1, "high": 1, "low": 1,
                 "close": 1, "vol": 1, "amount": 0.1},
                {"trade_date": "20260908", "open": 2, "high": 2, "low": 2,
                 "close": 2, "vol": 1, "amount": 0.2},
            ])

        def fund_basic(self, *, ts_code, fields):
            assert fields == "ts_code,list_date"
            return pd.DataFrame({"ts_code": [ts_code], "list_date": ["20130315"]})

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
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(tushare_etf, "get_tushare_pro", lambda _env=None: pro)
        request = DataRequest(Dataset.ETF_OHLCV, "510500.SH", "2013-03-15", "2026-09-08", "2026-09-08")
        path, reference = publication_seeds("etf-adjusted", None, request)
    from dataflows import Dataflows, DataSpace, ProviderConfig
    flow = Dataflows(base_dir=path.parent, space=DataSpace(path=path.relative_to(path.parent)),
                     providers=ProviderConfig({}))
    ready = flow.fetch(request, prepared=reference)
    assert ready.ready, ready.error
    return pro, ready.dataframe, dict(ready.identity.metadata), ready.identity


@pytest.mark.parametrize("mutation", ["adjustment", "publication", "early"])
def test_etf_long_history_fetch_segments_adjustment_factors(
    clone_published_flow, publish_data, etf_adjusted_source, mutation,
):
    _, bars, metadata, _ = etf_adjusted_source
    request = DataRequest(
        Dataset.ETF_OHLCV, "510500.SH", "2013-03-15", "2026-09-08", "2026-09-08"
    )
    supplied_frame, supplied_metadata = bars.copy(deep=True), metadata.copy()
    flows, ready = clone_published_flow("etf-adjusted", {
        request.dataset: lambda _: (supplied_frame, supplied_metadata),
    }, request)
    assert ready.status is DataStatus.READY
    assert ready.identity.temporal_contract.availability_time_field == "AvailableDate"
    if mutation == "early":
        supplied_frame.AvailableDate -= pd.Timedelta(hours=7)
    elif mutation == "adjustment":
        supplied_metadata["adjustment"] = "none"
    else:
        supplied_metadata["adjustment_factor_publication_timestamp_verified"] = True
    failed = publish_data(flows, request)
    assert failed.status is DataStatus.FAILED
    assert failed.error.code == "DATA_CONTRACT_MISMATCH"
    old = flows.fetch(request, prepared=ready.prepared)
    assert old.ready and old.identity == ready.identity
    pd.testing.assert_frame_equal(old.dataframe, ready.dataframe)


@pytest.mark.parametrize("dataset,frequency,symbol,exchange,defect", [
    (Dataset.ETF_UNADJUSTED_DAILY, "daily", "588080.SH", "SSE", "missing"),
    (Dataset.ETF_OHLCV, "daily", "159915.SZ", "SZSE", "missing"),
    (Dataset.ETF_OHLCV, "weekly", "588080.SH", "SSE", "missing"),
    *[(Dataset.ETF_UNADJUSTED_DAILY, "daily", "588080.SH", "SSE", defect)
      for defect in ("calendar_gap", "duplicate_calendar", "invalid_flag", "closed_day_bar")],
])
def test_etf_publication_requires_verified_daily_session_coverage(
    clone_published_flow, publish_data, monkeypatch, dataset, frequency, symbol, exchange, defect,
):
    expected_exchange = exchange

    class DailyPro:
        missing = False
        calendar_gap = False
        duplicate_calendar = False
        closed_day_bar = False
        invalid_flag = False

        def fund_basic(self, *, ts_code, fields):
            assert fields == "ts_code,list_date"
            return pd.DataFrame({"ts_code": [ts_code], "list_date": ["20260914"]})

        def fund_daily(self, **kwargs):
            # Listing evidence is independent of the first returned observation.
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
    flows, ready = clone_published_flow(f"{dataset.value}-{frequency}-{exchange}", None, request)
    setattr(pro, defect, True)
    failed = publish_data(flows, request)
    if defect in {"missing", "calendar_gap"}:
        assert failed.status is DataStatus.INCOMPLETE
        assert failed.error.code == "INCOMPLETE_DATA"
        if defect == "missing":
            if frequency == "weekly":
                assert failed.error.context["quality"]["daily"]["incomplete_dates"] == ["2026-09-15"]
            else:
                assert failed.error.context["missing_dates"] == ["2026-09-15"]
    else:
        assert failed.status is DataStatus.FAILED
        assert failed.error.code == "DATA_CONTRACT_MISMATCH"
    assert failed.dataframe.empty
    assert ready.identity.metadata["daily_session_coverage"]["verified_sessions"] == 3
    old = flows.fetch(request, prepared=ready.prepared)
    assert old.ready and old.identity.content_sha256 == ready.identity.content_sha256


def test_etf_default_long_history_publishes_segmented_hfq_identity(etf_adjusted_source):
    pro, bars, metadata, identity = etf_adjusted_source
    assert pro.factor_requests == [
        ("20130315", "20171231"), ("20180101", "20221231"), ("20230101", "20260908"),
    ]
    assert bars.Close.tolist() == [1., 4.]
    assert bars.AvailableDate.dt.strftime("%Y-%m-%d %H:%M:%S").tolist() == [
        "2013-03-15 17:00:00", "2026-09-08 17:00:00",
    ]
    assert metadata["adjustment_factor_source"] == "fund_adj"
    assert metadata["adjustment_factor_publication_timestamp_verified"] is False
    assert metadata["adjustment_factor_revision_history_verified"] is False
    assert metadata["availability_time_field"] == "AvailableDate"
    assert identity.source == "tushare"
    assert identity.temporal_contract.availability_time_field == "AvailableDate"
    assert identity.content_sha256 == canonical_frame_sha256(bars)
