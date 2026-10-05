"""Scheduled HFQ times must remain distinct from verified historical publication."""

from __future__ import annotations

import pandas as pd
import pytest
from conftest import ohlcv_fixture_metadata
from dataflows.ohlcv_quality import bind_quality_frame

from dataflows import DataRequest, DataStatus, Dataset
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


@pytest.mark.parametrize("mutation", ["schedule", "hash"])
def test_stock_daily_uses_conservative_after_close_time(clone_published_flow, publish_data, mutation) -> None:
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
    metadata.update(ohlcv_fixture_metadata(
        frame, start="2026-09-08", end="2026-09-08",
    ))
    metadata["ohlcv_quality_evidence"] = bind_quality_frame(metadata["ohlcv_quality_evidence"], frame, adjustment="hfq")
    supplied_metadata = metadata.copy()
    flows, ready = clone_published_flow("stock-hfq", {
        request.dataset: lambda _: (frame, supplied_metadata),
    }, request)
    assert ready.status is DataStatus.READY
    if mutation == "schedule":
        supplied_metadata["adjustment_factor_publication_schedule"] = "unknown"
    else:
        supplied_metadata["adjustment_factor_sha256"] = "not-a-hash"
    failed = publish_data(flows, request)
    assert failed.status is DataStatus.FAILED
    assert failed.error.code == "DATA_CONTRACT_MISMATCH"
    old = flows.fetch(request, prepared=ready.prepared)
    assert old.ready and old.identity == ready.identity
    pd.testing.assert_frame_equal(old.dataframe, ready.dataframe)
