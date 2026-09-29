"""The close-only index contract must not fabricate missing intraday prices."""

from __future__ import annotations

import pandas as pd
import pytest

from dataflows import DataRequest, DataStatus, Dataflows, Dataset
from dataflows.tushare_strategy_data import (
    fetch_domestic_index_close_daily,
    fetch_domestic_index_close_turnover_daily,
    fetch_domestic_index_daily,
)


class _IndexPro:
    def __init__(self, *, bad_change: bool = False, bad_close: bool = False,
                 overrides: dict[str, object] | None = None, duplicate: bool = False) -> None:
        self.bad_change = bad_change
        self.bad_close = bad_close
        self.overrides = overrides or {}
        self.duplicate = duplicate
        self.fields: list[str] = []

    def index_daily(self, *, ts_code: str, start_date: str, end_date: str, fields: str):
        assert ts_code == "931994.CSI"
        assert start_date <= "20240909" <= end_date
        self.fields.append(fields)
        row = {
            "trade_date": "20240909",
            "open": None,
            "high": None,
            "low": None,
            "close": None if self.bad_close else 1677.2731,
            "pre_close": 1686.8639,
            "change": -9.0 if self.bad_change else -9.5908,
            "pct_chg": -0.56855,
            "vol": 6861825.38,
            "amount": 7094224.474,
        }
        row.update(self.overrides)
        return pd.DataFrame([row, row] if self.duplicate else [row])


def _request(dataset: Dataset) -> DataRequest:
    return DataRequest(dataset, "931994.CSI", "2024-09-09", "2024-09-09", "2024-09-09")


def test_close_only_index_publishes_verified_close_with_causal_identity() -> None:
    pro = _IndexPro()
    flows = Dataflows(providers={
        Dataset.DOMESTIC_INDEX_CLOSE_DAILY.value: lambda request: fetch_domestic_index_close_daily(
            request.symbol, request.start, request.end, pro=pro
        ),
        Dataset.DOMESTIC_INDEX_DAILY.value: lambda request: fetch_domestic_index_daily(
            request.symbol, request.start, request.end, pro=pro
        ),
    })

    close = flows.fetch(_request(Dataset.DOMESTIC_INDEX_CLOSE_DAILY))
    full = flows.fetch(_request(Dataset.DOMESTIC_INDEX_DAILY))

    assert close.status is DataStatus.READY
    assert list(close.dataframe.columns) == ["Date", "Close"]
    assert close.dataframe.loc[0, "Close"] == 1677.2731
    assert close.identity is not None
    assert close.identity.temporal_contract.available_at == "current session after market close"
    assert close.identity.metadata["price_scope"] == "CLOSE_ONLY"
    assert full.status is DataStatus.FAILED
    assert full.error is not None and full.error.code == "DATA_CONTRACT_MISMATCH"
    assert "open" not in pro.fields[0]


def test_close_only_index_rejects_inconsistent_vendor_change() -> None:
    pro = _IndexPro(bad_change=True)
    flows = Dataflows(providers={
        Dataset.DOMESTIC_INDEX_CLOSE_DAILY.value: lambda request: fetch_domestic_index_close_daily(
            request.symbol, request.start, request.end, pro=pro
        ),
    })

    result = flows.fetch(_request(Dataset.DOMESTIC_INDEX_CLOSE_DAILY))

    assert result.status is DataStatus.FAILED
    assert result.error is not None and result.error.code == "DATA_CONTRACT_MISMATCH"


def test_close_only_index_rejects_missing_vendor_close() -> None:
    pro = _IndexPro(bad_close=True)
    flows = Dataflows(providers={
        Dataset.DOMESTIC_INDEX_CLOSE_DAILY.value: lambda request: fetch_domestic_index_close_daily(
            request.symbol, request.start, request.end, pro=pro
        ),
    })

    result = flows.fetch(_request(Dataset.DOMESTIC_INDEX_CLOSE_DAILY))

    assert result.status is DataStatus.FAILED
    assert result.error is not None and result.error.code == "DATA_CONTRACT_MISMATCH"


def test_close_turnover_publishes_only_verified_fields_and_preserves_close_contract() -> None:
    pro = _IndexPro()
    flows = Dataflows(providers={
        Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY.value: lambda request:
            fetch_domestic_index_close_turnover_daily(
                request.symbol, request.start, request.end, pro=pro,
            ),
        Dataset.DOMESTIC_INDEX_CLOSE_DAILY.value: lambda request:
            fetch_domestic_index_close_daily(
                request.symbol, request.start, request.end, pro=pro,
            ),
        Dataset.DOMESTIC_INDEX_DAILY.value: lambda request: fetch_domestic_index_daily(
            request.symbol, request.start, request.end, pro=pro,
        ),
    })

    turnover = flows.fetch(_request(Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY))
    close = flows.fetch(_request(Dataset.DOMESTIC_INDEX_CLOSE_DAILY))
    full = flows.fetch(_request(Dataset.DOMESTIC_INDEX_DAILY))

    assert turnover.status is DataStatus.READY
    assert list(turnover.dataframe.columns) == ["Date", "Close", "Volume", "Amount"]
    assert turnover.dataframe.loc[0, "Close"] == close.dataframe.loc[0, "Close"]
    assert turnover.dataframe.loc[0, "Volume"] == 6861825.38
    assert turnover.identity is not None
    assert turnover.identity.temporal_contract.available_at == "current session after market close"
    assert turnover.identity.metadata["volume_unit"] == "hand"
    assert turnover.identity.metadata["amount_unit"] == "thousand_cny"
    assert turnover.identity.metadata["source_publication_timestamp_verified"] is False
    assert turnover.identity.metadata["historical_revision_history_verified"] is False
    assert "open" not in pro.fields[0] and "vol" in pro.fields[0]
    assert close.status is DataStatus.READY
    assert full.status is DataStatus.FAILED


@pytest.mark.parametrize("overrides", [
    {"close": None}, {"change": -9.0}, {"pct_chg": -0.3},
    {"vol": None}, {"vol": -1.0}, {"amount": None}, {"amount": -1.0},
])
def test_close_turnover_rejects_invalid_vendor_fields(overrides: dict[str, object]) -> None:
    pro = _IndexPro(overrides=overrides)
    flows = Dataflows(providers={
        Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY.value: lambda request:
            fetch_domestic_index_close_turnover_daily(
                request.symbol, request.start, request.end, pro=pro,
            ),
    })

    result = flows.fetch(_request(Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY))

    assert result.status is DataStatus.FAILED
    assert result.error is not None and result.error.code == "DATA_CONTRACT_MISMATCH"


def test_close_turnover_rejects_duplicate_dates() -> None:
    pro = _IndexPro(duplicate=True)
    flows = Dataflows(providers={
        Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY.value: lambda request:
            fetch_domestic_index_close_turnover_daily(
                request.symbol, request.start, request.end, pro=pro,
            ),
    })

    result = flows.fetch(_request(Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY))

    assert result.status is DataStatus.FAILED
    assert result.error is not None and result.error.code == "DATA_CONTRACT_MISMATCH"


@pytest.mark.parametrize("metadata_change", [
    {"price_scope": "CLOSE_ONLY"}, {"volume_unit": "share"},
    {"amount_unit": "cny"}, {"frequency": "weekly"},
    {"available_at": "intraday"}, {"vendor_update_window": "unknown"},
    {"source_publication_timestamp_verified": True},
    {"historical_revision_history_verified": True},
])
def test_close_turnover_facade_rejects_false_metadata(metadata_change: dict[str, object]) -> None:
    frame, metadata = fetch_domestic_index_close_turnover_daily(
        "931994.CSI", "2024-09-09", "2024-09-09", pro=_IndexPro(),
    )
    metadata.update(metadata_change)
    flows = Dataflows(providers={
        Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY.value: lambda _request: (frame, metadata),
    })

    result = flows.fetch(_request(Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY))

    assert result.status is DataStatus.FAILED
    assert result.error is not None and result.error.code == "DATA_CONTRACT_MISMATCH"


def test_close_turnover_rejects_wrong_frequency_and_options_before_vendor_call() -> None:
    flows = Dataflows()
    wrong_frequency = DataRequest(
        Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY, "931994.CSI",
        "2024-09-09", "2024-09-09", None, "30m",
    )
    wrong_options = DataRequest(
        Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY, "931994.CSI",
        "2024-09-09", "2024-09-09", None, "daily", {"fallback": True},
    )

    for request in (wrong_frequency, wrong_options):
        result = flows.fetch(request)
        assert result.status is DataStatus.FAILED
        assert result.error is not None and result.error.code == "DATA_CONTRACT_MISMATCH"
