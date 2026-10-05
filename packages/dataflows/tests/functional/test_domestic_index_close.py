"""The close-only index contract must not fabricate missing intraday prices."""

from __future__ import annotations

import pandas as pd
import pytest

from dataflows import DataRequest, DataStatus, Dataset
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


def test_close_only_index_publishes_verified_close_with_causal_identity(flow_factory, publish_data) -> None:
    pro = _IndexPro()
    flows = flow_factory(providers={
        Dataset.DOMESTIC_INDEX_CLOSE_DAILY.value: lambda request: fetch_domestic_index_close_daily(
            request.symbol, request.start, request.end, pro=pro
        ),
        Dataset.DOMESTIC_INDEX_DAILY.value: lambda request: fetch_domestic_index_daily(
            request.symbol, request.start, request.end, pro=pro
        ),
    })

    close = publish_data(flows, _request(Dataset.DOMESTIC_INDEX_CLOSE_DAILY))
    full = publish_data(flows, _request(Dataset.DOMESTIC_INDEX_DAILY))

    assert close.status is DataStatus.READY
    assert list(close.dataframe.columns) == ["Date", "Close"]
    assert close.dataframe.loc[0, "Close"] == 1677.2731
    assert close.identity is not None
    assert close.identity.temporal_contract.available_at == "current session after market close"
    assert close.identity.metadata["price_scope"] == "CLOSE_ONLY"
    assert full.status is DataStatus.FAILED
    assert full.error is not None and full.error.code == "DATA_CONTRACT_MISMATCH"
    assert "open" not in pro.fields[0]
    for defect in ("bad_change", "bad_close"):
        pro.bad_change, pro.bad_close = defect == "bad_change", defect == "bad_close"
        result = publish_data(flows, _request(Dataset.DOMESTIC_INDEX_CLOSE_DAILY))
        assert result.status is DataStatus.FAILED, defect
        assert result.error is not None and result.error.code == "DATA_CONTRACT_MISMATCH", defect
    old = flows.fetch(_request(Dataset.DOMESTIC_INDEX_CLOSE_DAILY), prepared=close.prepared)
    assert old.ready and old.identity.content_sha256 == close.identity.content_sha256


def test_close_turnover_publishes_only_verified_fields_and_preserves_close_contract(flow_factory, publish_data) -> None:
    pro = _IndexPro()
    flows = flow_factory(providers={
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

    turnover = publish_data(flows, _request(Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY))
    close = publish_data(flows, _request(Dataset.DOMESTIC_INDEX_CLOSE_DAILY))
    full = publish_data(flows, _request(Dataset.DOMESTIC_INDEX_DAILY))

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


def test_close_turnover_rejects_invalid_vendor_fields_and_duplicate_dates(flow_factory, publish_data) -> None:
    pro = _IndexPro()
    flows = flow_factory(providers={
        Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY.value: lambda request:
            fetch_domestic_index_close_turnover_daily(
                request.symbol, request.start, request.end, pro=pro,
            ),
    })

    request = _request(Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY)
    ready = publish_data(flows, request)
    assert ready.ready, ready.error
    # One published baseline; each independent source defect is a failed refresh.
    # Restore the fake vendor for every mutation so failures cannot mask each other.
    for defect, overrides, duplicate in (
        ("missing close", {"close": None}, False),
        ("inconsistent change", {"change": -9.0}, False),
        ("inconsistent percentage", {"pct_chg": -0.3}, False),
        ("missing volume", {"vol": None}, False),
        ("negative volume", {"vol": -1.0}, False),
        ("missing amount", {"amount": None}, False),
        ("negative amount", {"amount": -1.0}, False),
        ("duplicate date", {}, True),
    ):
        pro.overrides, pro.duplicate = overrides, duplicate
        result = publish_data(flows, request)
        assert result.status is DataStatus.FAILED, defect
        assert result.error is not None and result.error.code == "DATA_CONTRACT_MISMATCH", defect
    old = flows.fetch(request, prepared=ready.prepared)
    assert old.ready and old.identity.content_sha256 == ready.identity.content_sha256


def test_close_turnover_facade_rejects_false_metadata(flow_factory, publish_data) -> None:
    frame, metadata = fetch_domestic_index_close_turnover_daily(
        "931994.CSI", "2024-09-09", "2024-09-09", pro=_IndexPro(),
    )
    supplied_metadata = metadata.copy()
    flows = flow_factory(providers={
        Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY.value: lambda _request: (frame, supplied_metadata),
    })
    request = _request(Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY)
    ready = publish_data(flows, request)
    assert ready.ready, ready.error
    for key, value in (
        ("price_scope", "CLOSE_ONLY"), ("volume_unit", "share"),
        ("amount_unit", "cny"), ("frequency", "weekly"),
        ("available_at", "intraday"), ("vendor_update_window", "unknown"),
        ("source_publication_timestamp_verified", True),
        ("historical_revision_history_verified", True),
    ):
        supplied_metadata = {**metadata, key: value}
        result = publish_data(flows, request)
        assert result.status is DataStatus.FAILED, key
        assert result.error is not None and result.error.code == "DATA_CONTRACT_MISMATCH", key
    old = flows.fetch(request, prepared=ready.prepared)
    assert old.ready and old.identity.content_sha256 == ready.identity.content_sha256


def test_close_turnover_rejects_wrong_frequency_and_parameters_at_construction() -> None:
    with pytest.raises(ValueError):
        DataRequest(
            Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY, "931994.CSI",
            "2024-09-09", "2024-09-09", None, "30m",
        )
    with pytest.raises(TypeError):
        DataRequest(
            Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY, "931994.CSI",
            "2024-09-09", "2024-09-09", None, "daily", {"fallback": True},
        )
