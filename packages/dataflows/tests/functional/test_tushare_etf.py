from __future__ import annotations

import pandas as pd

from dataflows import DataRequest, DataStatus, Dataflows, Dataset
from dataflows import tushare_etf


def test_etf_long_history_fetch_segments_adjustment_factors(monkeypatch) -> None:
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
    ready = Dataflows({Dataset.ETF_OHLCV.value: lambda ignored: (bars, metadata)}).fetch(request)
    assert ready.status is DataStatus.READY
    assert ready.identity is not None
    assert ready.identity.temporal_contract.availability_time_field == "AvailableDate"
    for changed_frame, changed_metadata in (
        (bars, {**metadata, "adjustment": "none"}),
        (bars, {**metadata, "adjustment_factor_publication_timestamp_verified": True}),
        (bars.assign(AvailableDate=bars["AvailableDate"] - pd.Timedelta(hours=7)), metadata),
    ):
        failed = Dataflows({
            Dataset.ETF_OHLCV.value: lambda ignored: (changed_frame, changed_metadata)
        }).fetch(request)
        assert failed.status is DataStatus.FAILED
        assert failed.error is not None and failed.error.code == "DATA_CONTRACT_MISMATCH"
