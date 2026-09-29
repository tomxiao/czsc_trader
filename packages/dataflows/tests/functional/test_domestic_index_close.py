"""The close-only index contract must not fabricate missing intraday prices."""

from __future__ import annotations

import pandas as pd

from dataflows import DataRequest, DataStatus, Dataflows, Dataset
from dataflows.tushare_strategy_data import (
    fetch_domestic_index_close_daily,
    fetch_domestic_index_daily,
)


class _IndexPro:
    def __init__(self, *, bad_change: bool = False, bad_close: bool = False) -> None:
        self.bad_change = bad_change
        self.bad_close = bad_close
        self.fields: list[str] = []

    def index_daily(self, *, ts_code: str, start_date: str, end_date: str, fields: str):
        assert ts_code == "931994.CSI"
        assert start_date <= "20240909" <= end_date
        self.fields.append(fields)
        return pd.DataFrame(
            [{
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
            }]
        )


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
