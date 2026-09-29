"""Scheduled HFQ times must remain distinct from verified historical publication."""

from __future__ import annotations

import pandas as pd

from dataflows import DataRequest, DataStatus, Dataflows, Dataset
from dataflows.bar_utils import with_scheduled_hfq_availability


def _bars(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame({
        "Date": dates,
        "Open": [1.0] * len(dates), "High": [1.1] * len(dates),
        "Low": [0.9] * len(dates), "Close": [1.0] * len(dates),
        "Volume": [100.0] * len(dates), "Amount": [100.0] * len(dates),
    })


def test_stock_intraday_uses_completed_bar_time_after_premarket_factor() -> None:
    raw = _bars(["2026-09-08 09:35:00", "2026-09-08 09:40:00"])
    result = with_scheduled_hfq_availability(
        raw, factor_source="adj_factor", period="5m"
    )
    assert result["AvailableDate"].tolist() == pd.to_datetime(raw["Date"]).tolist()


def test_stock_daily_uses_conservative_after_close_time() -> None:
    frame = with_scheduled_hfq_availability(
        _bars(["2026-09-08"]), factor_source="adj_factor", period="daily"
    )
    assert frame["AvailableDate"].iloc[0] == pd.Timestamp("2026-09-08 17:00:00")

    metadata = {
        "vendor": "tushare", "market": "a_share", "period": "daily",
        "asset_type": "stock", "adjustment": "hfq",
        "adjustment_factor_source": "adj_factor",
        "adjustment_factor_sha256": "a" * 64,
        "adjustment_factor_publication_schedule": "trade day 09:15-09:20 Asia/Shanghai",
        "adjustment_factor_publication_timestamp_verified": False,
        "adjustment_factor_revision_history_verified": False,
        "availability_time_field": "AvailableDate",
        "available_at": (
            "intraday bar close or daily 17:00 Asia/Shanghai conservative; "
            "historical publication unverified"
        ),
    }
    request = DataRequest(
        Dataset.STOCK_OHLCV, "600089.SH", "2026-09-08", "2026-09-08", "2026-09-08"
    )
    ready = Dataflows({Dataset.STOCK_OHLCV.value: lambda ignored: (frame, metadata)}).fetch(request)
    assert ready.status is DataStatus.READY
    missing = {**metadata, "adjustment_factor_publication_schedule": "unknown"}
    failed = Dataflows({Dataset.STOCK_OHLCV.value: lambda ignored: (frame, missing)}).fetch(request)
    assert failed.status is DataStatus.FAILED
    assert failed.error is not None and failed.error.code == "DATA_CONTRACT_MISMATCH"
    bad_hash = {**metadata, "adjustment_factor_sha256": "not-a-hash"}
    failed_hash = Dataflows({
        Dataset.STOCK_OHLCV.value: lambda ignored: (frame, bad_hash)
    }).fetch(request)
    assert failed_hash.status is DataStatus.FAILED
    assert failed_hash.error is not None and failed_hash.error.code == "DATA_CONTRACT_MISMATCH"
