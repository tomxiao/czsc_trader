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


@pytest.mark.parametrize("defect", ["bad_change", "bad_close"])
def test_close_only_rejects_invalid_source(clone_published_flow, publish_data, defect):
    pro = _IndexPro()
    request = _request(Dataset.DOMESTIC_INDEX_CLOSE_DAILY)
    flows, ready = clone_published_flow("close-only", {
        request.dataset: lambda r: fetch_domestic_index_close_daily(r.symbol, r.start, r.end, pro=pro),
    }, request)
    setattr(pro, defect, True)
    result = publish_data(flows, request)
    assert result.status is DataStatus.FAILED
    assert result.error.code == "DATA_CONTRACT_MISMATCH"
    old = flows.fetch(request, prepared=ready.prepared)
    assert old.ready and old.identity.content_sha256 == ready.identity.content_sha256


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


@pytest.mark.parametrize("overrides,duplicate", [
    ({"close": None}, False), ({"change": -9.0}, False), ({"pct_chg": -0.3}, False),
    ({"vol": None}, False), ({"vol": -1.0}, False), ({"amount": None}, False),
    ({"amount": -1.0}, False), ({}, True),
], ids=["missing-close", "change", "percentage", "missing-volume", "negative-volume",
        "missing-amount", "negative-amount", "duplicate-date"])
def test_close_turnover_rejects_invalid_vendor_fields_and_duplicate_dates(
    clone_published_flow, publish_data, overrides, duplicate,
) -> None:
    pro = _IndexPro()
    request = _request(Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY)
    flows, ready = clone_published_flow("close-turnover", {
        request.dataset: lambda request: fetch_domestic_index_close_turnover_daily(
            request.symbol, request.start, request.end, pro=pro,
        ),
    }, request)
    pro.overrides, pro.duplicate = overrides, duplicate
    result = publish_data(flows, request)
    assert result.status is DataStatus.FAILED
    assert result.error.code == "DATA_CONTRACT_MISMATCH"
    old = flows.fetch(request, prepared=ready.prepared)
    assert old.ready and old.identity.content_sha256 == ready.identity.content_sha256


@pytest.fixture(scope="module")
def close_turnover_source():
    return fetch_domestic_index_close_turnover_daily(
        "931994.CSI", "2024-09-09", "2024-09-09", pro=_IndexPro(),
    )


@pytest.mark.parametrize("key,value", [
    ("price_scope", "CLOSE_ONLY"), ("volume_unit", "share"),
    ("amount_unit", "cny"), ("frequency", "weekly"),
    ("available_at", "intraday"), ("vendor_update_window", "unknown"),
    ("source_publication_timestamp_verified", True), ("historical_revision_history_verified", True),
], ids=["scope", "volume-unit", "amount-unit", "frequency", "availability", "update-window",
        "publication-claim", "revision-claim"])
def test_close_turnover_facade_rejects_false_metadata(
    clone_published_flow, publish_data, close_turnover_source, key, value,
) -> None:
    frame, metadata = close_turnover_source
    supplied_metadata = metadata.copy()
    request = _request(Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY)
    flows, ready = clone_published_flow("close-turnover", {
        request.dataset: lambda _: (frame.copy(deep=True), supplied_metadata),
    }, request)
    supplied_metadata[key] = value
    result = publish_data(flows, request)
    assert result.status is DataStatus.FAILED
    assert result.error.code == "DATA_CONTRACT_MISMATCH"
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
