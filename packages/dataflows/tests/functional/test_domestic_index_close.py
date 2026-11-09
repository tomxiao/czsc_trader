"""The close-only index contract must not fabricate missing intraday prices."""

from __future__ import annotations

import pandas as pd
import pytest

from dataflows import DataRequest, DataStatus, Dataset
from dataflows.tushare_strategy_data import (
    fetch_domestic_index_close_turnover_daily,
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


def test_DFLS_34_C07_close_only_index_publishes_verified_close_with_causal_identity(
    flow_factory, publish_data, monkeypatch,
) -> None:
    from dataflows import tushare_strategy_data
    pro = _IndexPro()
    monkeypatch.setattr(tushare_strategy_data, "get_tushare_pro", lambda _: pro)
    flows = flow_factory()
    close = publish_data(flows, _request(Dataset.DOMESTIC_INDEX_CLOSE_DAILY))
    full = publish_data(flows, _request(Dataset.DOMESTIC_INDEX_DAILY))
    assert close.status is DataStatus.READY
    assert list(close.dataframe.columns) == ["Date", "Close"]
    assert close.dataframe.loc[0, "Close"] == 1677.2731
    assert close.identity.temporal_contract.available_at == "current session after market close"
    assert close.identity.metadata["price_scope"] == "CLOSE_ONLY"
    assert full.status is DataStatus.FAILED
    assert full.error.code == "DATA_CONTRACT_MISMATCH"
    assert "open" not in pro.fields[0]
    assert len(pro.fields) == 2




def test_DFLS_34_C08_close_turnover_publishes_only_verified_fields_and_preserves_close_contract(
    flow_factory, publish_data, monkeypatch,
) -> None:
    from dataflows import tushare_strategy_data
    pro = _IndexPro()
    monkeypatch.setattr(tushare_strategy_data, "get_tushare_pro", lambda _: pro)
    turnover = publish_data(flow_factory(), _request(Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY))
    assert turnover.status is DataStatus.READY
    assert list(turnover.dataframe.columns) == ["Date", "Close", "Volume", "Amount"]
    assert turnover.dataframe.loc[0, "Close"] == 1677.2731
    assert turnover.dataframe.loc[0, "Volume"] == 6861825.38
    assert turnover.dataframe.loc[0, "Amount"] == 7094224.474
    assert turnover.identity.temporal_contract.available_at == "current session after market close"
    assert turnover.identity.metadata["volume_unit"] == "hand"
    assert turnover.identity.metadata["amount_unit"] == "thousand_cny"
    assert turnover.identity.metadata["source_publication_timestamp_verified"] is False
    assert turnover.identity.metadata["historical_revision_history_verified"] is False
    assert len(pro.fields) == 1 and "open" not in pro.fields[0] and "vol" in pro.fields[0]




@pytest.fixture(scope="module")
def close_turnover_source():
    return fetch_domestic_index_close_turnover_daily(
        "931994.CSI", "2024-09-09", "2024-09-09", pro=_IndexPro(),
    )
