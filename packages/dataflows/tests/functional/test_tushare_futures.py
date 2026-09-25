from __future__ import annotations

import pandas as pd
import pytest

from dataflows import DataRequest, DataStatus, Dataflows, Dataset
from dataflows.errors import DataContractError
from dataflows.tushare_futures import (
    fetch_shfe_gold_daily,
    fetch_shfe_gold_holding,
    fetch_shfe_gold_mapping,
)


class FakeFuturesPro:
    def __init__(self) -> None:
        self.daily_calls: list[dict[str, str]] = []
        self.mapping_calls: list[dict[str, str]] = []
        self.holding_calls: list[dict[str, str]] = []

    def fut_basic(self, **kwargs):
        return pd.DataFrame(
            {
                "ts_code": ["AU2406.SHF", "AU2408.SHF"],
                "symbol": ["AU2406", "AU2408"],
                "exchange": ["SHFE", "SHFE"],
                "fut_code": ["AU", "AU"],
                "list_date": ["20240101", "20240201"],
                "delist_date": ["20240617", "20240815"],
                "d_month": ["202406", "202408"],
            }
        )

    def fut_daily(self, **kwargs):
        self.daily_calls.append(kwargs)
        offset = 0.0 if kwargs["ts_code"] == "AU2406.SHF" else 10.0
        return pd.DataFrame(
            {
                "ts_code": [kwargs["ts_code"], kwargs["ts_code"]],
                "trade_date": ["20240603", "20240604"],
                "close": [551.0 + offset, 552.0 + offset],
                "settle": [550.5 + offset, 551.5 + offset],
                "vol": [1000.0, 1100.0],
                "amount": [10000.0, 11000.0],
                "oi": [5000.0, 5100.0],
            }
        )

    def fut_mapping(self, **kwargs):
        self.mapping_calls.append(kwargs)
        return pd.DataFrame(
            {
                "ts_code": ["AU.SHF", "AU.SHF"],
                "trade_date": ["20240603", "20240604"],
                "mapping_ts_code": ["AU2406.SHF", "AU2408.SHF"],
            }
        )

    def fut_holding(self, **kwargs):
        self.holding_calls.append(kwargs)
        symbol = kwargs["symbol"]
        return pd.DataFrame(
            {
                "trade_date": ["20240603", "20240603", "20240604", "20240604"],
                "symbol": [symbol] * 4,
                "broker": ["甲", "乙", "甲", "乙"],
                "vol": [100.0, None, 110.0, None],
                "vol_chg": [1.0, None, 2.0, None],
                "long_hld": [80.0, 60.0, 90.0, 70.0],
                "long_chg": [5.0, -3.0, 4.0, -2.0],
                "short_hld": [None, 50.0, None, 55.0],
                "short_chg": [None, 2.0, None, 1.0],
            }
        )


def test_shfe_gold_contract_curve_is_canonical_and_complete() -> None:
    pro = FakeFuturesPro()

    frame, metadata = fetch_shfe_gold_daily("AU.SHFE", "2024-06-03", "2024-06-04", pro=pro)

    assert len(frame) == 4
    assert frame["Contract"].unique().tolist() == ["AU2406.SHF", "AU2408.SHF"]
    assert frame.loc[0, "MaturityDate"] == pd.Timestamp("2024-06-17")
    assert len(pro.daily_calls) == 2
    assert metadata["primary_key"] == ["Date", "Contract"]
    assert metadata["source_calendar"] == "SHFE"
    assert "next China trading session" in metadata["available_at"]


def test_shfe_gold_mapping_is_year_chunked_and_canonical() -> None:
    pro = FakeFuturesPro()

    frame, metadata = fetch_shfe_gold_mapping("AU.SHFE", "2024-06-03", "2024-06-04", pro=pro)

    assert frame["ContinuousSymbol"].unique().tolist() == ["AU.SHFE"]
    assert frame["Contract"].tolist() == ["AU2406.SHF", "AU2408.SHF"]
    assert len(pro.mapping_calls) == 1
    assert metadata["primary_key"] == ["Date", "ContinuousSymbol"]


def test_holding_uses_mapped_contracts_and_preserves_missing_rank_semantics() -> None:
    pro = FakeFuturesPro()

    frame, metadata = fetch_shfe_gold_holding("AU.SHFE", "2024-06-03", "2024-06-04", pro=pro)

    assert len(frame) == 4
    assert (
        frame.loc[frame["Date"].eq(pd.Timestamp("2024-06-03")), "Contract"].eq("AU2406.SHF").all()
    )
    assert (
        frame.loc[frame["Date"].eq(pd.Timestamp("2024-06-04")), "Contract"].eq("AU2408.SHF").all()
    )
    assert {call["symbol"] for call in pro.holding_calls} == {"AU2406", "AU2408"}
    assert frame["ShortHolding"].isna().any()
    assert metadata["missing_rank_semantics"].startswith("null means")


@pytest.mark.parametrize(
    "fetcher",
    [fetch_shfe_gold_daily, fetch_shfe_gold_mapping, fetch_shfe_gold_holding],
)
def test_shfe_gold_datasets_reject_ambiguous_symbols(fetcher) -> None:
    with pytest.raises(DataContractError, match="only support AU.SHFE"):
        fetcher("AU.SHF", "2024-06-03", "2024-06-04", pro=FakeFuturesPro())


def test_facade_accepts_futures_frames_and_nullable_holding_rankings() -> None:
    pro = FakeFuturesPro()
    daily = fetch_shfe_gold_daily("AU.SHFE", "2024-06-03", "2024-06-04", pro=pro)
    mapping = fetch_shfe_gold_mapping("AU.SHFE", "2024-06-03", "2024-06-04", pro=pro)
    holding = fetch_shfe_gold_holding("AU.SHFE", "2024-06-03", "2024-06-04", pro=pro)
    providers = {
        Dataset.FUTURES_SHFE_GOLD_DAILY.value: lambda ignored: daily,
        Dataset.FUTURES_SHFE_GOLD_MAPPING.value: lambda ignored: mapping,
        Dataset.FUTURES_SHFE_GOLD_HOLDING.value: lambda ignored: holding,
    }

    for dataset in (
        Dataset.FUTURES_SHFE_GOLD_DAILY,
        Dataset.FUTURES_SHFE_GOLD_MAPPING,
        Dataset.FUTURES_SHFE_GOLD_HOLDING,
    ):
        result = Dataflows(providers).fetch(
            DataRequest(
                dataset,
                "AU.SHFE",
                "2024-06-03",
                "2024-06-04",
                "2024-06-04",
            )
        )
        assert result.status is DataStatus.READY
        assert result.identity is not None
        assert result.identity.metadata["available_at"].startswith("source trade date T")


def test_facade_rejects_holding_row_without_any_ranking_value() -> None:
    frame = pd.DataFrame(
        {
            "Date": ["2024-06-04"],
            "Contract": ["AU2408.SHF"],
            "Broker": ["甲"],
            "Volume": [None],
            "VolumeChange": [None],
            "LongHolding": [None],
            "LongChange": [None],
            "ShortHolding": [None],
            "ShortChange": [None],
        }
    )
    result = Dataflows(
        {
            Dataset.FUTURES_SHFE_GOLD_HOLDING.value: lambda ignored: (
                frame,
                {
                    "vendor": "test",
                    "vendor_symbol": "AU.SHFE",
                    "primary_key": ["Date", "Contract", "Broker"],
                },
            )
        }
    ).fetch(
        DataRequest(
            Dataset.FUTURES_SHFE_GOLD_HOLDING,
            "AU.SHFE",
            "2024-06-04",
            "2024-06-04",
            "2024-06-04",
        )
    )

    assert result.status is DataStatus.FAILED
    assert result.error is not None
    assert result.error.code == "DATA_CONTRACT_MISMATCH"


def test_default_registry_exposes_shfe_gold_research_datasets() -> None:
    assert {
        Dataset.FUTURES_SHFE_GOLD_DAILY.value,
        Dataset.FUTURES_SHFE_GOLD_MAPPING.value,
        Dataset.FUTURES_SHFE_GOLD_HOLDING.value,
    }.issubset(Dataflows().datasets)
