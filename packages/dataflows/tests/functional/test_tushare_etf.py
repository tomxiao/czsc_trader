from __future__ import annotations

import pandas as pd
import pytest

from dataflows import DataRequest, Dataset, canonical_frame_sha256
from dataflows import tushare_etf


@pytest.fixture(scope="module")
def etf_adjusted_source(publication_seeds):
    class FakePro:
        def __init__(self) -> None:
            self.factor_requests: list[tuple[str, str]] = []

        def fund_daily(self, **_kwargs):
            return pd.DataFrame(
                [
                    {
                        "trade_date": "20130315",
                        "open": 1,
                        "high": 1,
                        "low": 1,
                        "close": 1,
                        "vol": 1,
                        "amount": 0.1,
                    },
                    {
                        "trade_date": "20260908",
                        "open": 2,
                        "high": 2,
                        "low": 2,
                        "close": 2,
                        "vol": 1,
                        "amount": 0.2,
                    },
                ]
            )

        def fund_basic(self, *, ts_code, fields):
            assert fields == "ts_code,list_date"
            return pd.DataFrame({"ts_code": [ts_code], "list_date": ["20130315"]})

        def fund_adj(self, *, start_date, end_date, **_kwargs):
            self.factor_requests.append((start_date, end_date))
            factors = pd.DataFrame(
                [
                    {"trade_date": "20130315", "adj_factor": 1.0},
                    {"trade_date": "20200102", "adj_factor": 1.5},
                    {"trade_date": "20260908", "adj_factor": 2.0},
                ]
            )
            return factors.loc[factors["trade_date"].between(start_date, end_date)].reset_index(
                drop=True
            )

        def trade_cal(self, *, start_date, end_date, **_kwargs):
            dates = pd.date_range(start_date, end_date).strftime("%Y%m%d")
            return pd.DataFrame(
                {
                    "cal_date": dates,
                    "is_open": dates.isin(["20130315", "20260908"]).astype(int),
                }
            )

    pro = FakePro()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(tushare_etf, "get_tushare_pro", lambda _env=None: pro)
        request = DataRequest(
            Dataset.ETF_OHLCV, "510500.SH", "2013-03-15", "2026-09-08", "2026-09-08"
        )
        path, reference = publication_seeds("etf-adjusted", None, request)
    from dataflows import Dataflows, DataSpace, ProviderConfig

    flow = Dataflows(
        base_dir=path.parent,
        space=DataSpace(path=path.relative_to(path.parent)),
        providers=ProviderConfig({}),
    )
    ready = flow.fetch(request, prepared=reference)
    assert ready.ready, ready.error
    return pro, ready.dataframe, dict(ready.identity.metadata), ready.identity


def test_DFLS_16_C01_factor_pages_cover_entire_history(etf_adjusted_source):
    pro, bars, metadata, identity = etf_adjusted_source
    assert pro.factor_requests == [
        ("20130315", "20171231"),
        ("20180101", "20221231"),
        ("20230101", "20260908"),
    ]
    assert bars.Close.tolist() == [1.0, 4.0]
    assert bars.AvailableDate.dt.strftime("%Y-%m-%d %H:%M:%S").tolist() == [
        "2013-03-15 17:00:00",
        "2026-09-08 17:00:00",
    ]
    assert metadata["adjustment_factor_source"] == "fund_adj"
    assert metadata["adjustment_factor_publication_timestamp_verified"] is False
    assert metadata["adjustment_factor_revision_history_verified"] is False
    assert metadata["availability_time_field"] == "AvailableDate"
    assert identity.source == "tushare"
    assert identity.temporal_contract.availability_time_field == "AvailableDate"
    assert identity.content_sha256 == canonical_frame_sha256(bars)


def test_DFLS_21_C06_listing_bounds_session_denominator():
    from types import SimpleNamespace
    from dataflows.ohlcv_quality import verify_daily_sessions, build_quality_evidence

    days = pd.bdate_range("2026-09-14", "2026-09-16")
    pro = SimpleNamespace(
        fund_basic=lambda **_: pd.DataFrame({"ts_code": ["588080.SH"], "list_date": ["20260915"]}),
        trade_cal=lambda **_: pd.DataFrame({"cal_date": days.strftime("%Y%m%d"), "is_open": 1}),
    )
    complete = pd.DataFrame(
        {
            "Date": days[1:],
            "Open": 10.0,
            "High": 10.0,
            "Low": 10.0,
            "Close": 10.0,
            "Volume": 100.0,
            "Amount": 1000.0,
        }
    )
    coverage = verify_daily_sessions(
        pro, "588080.SH", complete, start="2026-09-14", end="2026-09-16"
    )
    assert coverage["expected_dates"] == ["2026-09-15", "2026-09-16"]
    evidence = build_quality_evidence(complete.iloc[1:], expected_dates=coverage["expected_dates"])
    assert not evidence["sessions"]["2026-09-15"]["daily_complete"]
