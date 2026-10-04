from __future__ import annotations

from hashlib import sha256

import pandas as pd
import pytest

from dataflows import (
    DataRequest,
    EvidenceParameters,
    DataStatus,
    Dataset,
    IncompleteDataError,
    SourceNotReadyError,
)
from dataflows.errors import EmptyDataError
from dataflows import tushare_common


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date": ["2026-09-14", "2026-09-15"],
            "Open": [1.0, 1.1],
            "High": [1.2, 1.3],
            "Low": [0.9, 1.0],
            "Close": [1.1, 1.2],
            "Volume": [100, 120],
            "Amount": [105.0, 138.0],
        }
    )


def _request(dataset: str | Dataset = Dataset.ETF_OHLCV) -> DataRequest:
    return DataRequest(dataset, "588080.SH", "2026-09-14", "2026-09-15", "2026-09-15")


def test_ready_result_has_stable_identity_and_detached_data(flow_factory, publish_data) -> None:
    source = _frame()
    dataflows = flow_factory({Dataset.ETF_OHLCV.value: lambda request: (source, {"vendor": "test"})})

    first = publish_data(dataflows, _request())
    second = publish_data(dataflows, _request())

    assert first.status is DataStatus.READY
    assert first.ready
    assert first.identity is not None
    assert first.identity.source == "test"
    assert first.identity.data_cutoff == "2026-09-15T00:00:00"
    assert first.identity.metadata["source_time_field"] == "Date"
    assert first.identity.metadata["availability_time_field"] == "Date"
    assert first.identity.metadata["source_calendar"] == "SOURCE_NATIVE"
    assert first.identity.metadata["available_at"] == "SOURCE_PERIOD_CLOSE"
    assert first.identity.metadata["request_range_policy"] == "EXACT"
    assert first.identity.content_sha256 == second.identity.content_sha256
    first.dataframe.loc[0, "Close"] = 99
    assert source.loc[0, "Close"] == 1.1


def test_ready_result_validates_declared_source_time_metadata(flow_factory, publish_data) -> None:
    result = publish_data(flow_factory(
        {
            Dataset.FXCM_DAILY.value: lambda request: (
                pd.DataFrame(
                    {
                        "Date": ["2026-09-15"],
                        "BidOpen": [1.0],
                        "BidHigh": [1.1],
                        "BidLow": [0.9],
                        "BidClose": [1.0],
                        "AskOpen": [1.1],
                        "AskHigh": [1.2],
                        "AskLow": [1.0],
                        "AskClose": [1.1],
                        "TickQuantity": [10.0],
                    }
                ),
                {
                    "vendor": "test",
                    "source_time_field": "Missing",
                    "source_calendar": "FXCM_24X5",
                    "available_at": "GMT daily close",
                },
            )
        }
    ),
        DataRequest(
            Dataset.FXCM_DAILY,
            "XAUUSD.FXCM",
            "2026-09-15",
            "2026-09-15",
            "2026-09-15",
        )
    )

    assert result.status is DataStatus.FAILED
    assert result.error is not None
    assert result.error.code == "DATA_CONTRACT_MISMATCH"


def test_tushare_pro_client_does_not_persist_global_token(monkeypatch) -> None:
    observed: dict[str, str] = {}

    monkeypatch.setenv("TUSHARE_TOKEN", "test-token")
    monkeypatch.setattr(
        tushare_common.ts,
        "set_token",
        lambda token: (_ for _ in ()).throw(AssertionError("Pro client must not persist tk.csv")),
    )
    monkeypatch.setattr(
        tushare_common.ts,
        "pro_api",
        lambda token: observed.setdefault("token", token),
    )

    client = tushare_common.get_tushare_pro()

    assert client == "test-token"
    assert observed == {"token": "test-token"}


def test_unknown_dataset_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError):
        _request("unknown.dataset")


def test_provider_states_are_not_reported_as_ready(flow_factory, publish_data) -> None:
    def waiting(request: DataRequest):
        raise SourceNotReadyError("daily source has not been published", available_at="20:30")

    def incomplete(request: DataRequest):
        raise IncompleteDataError("one dependency is missing", dependency="shibor")

    waiting_result = publish_data(flow_factory({Dataset.ETF_OHLCV.value: waiting}), _request())
    incomplete_result = publish_data(flow_factory({Dataset.ETF_OHLCV.value: incomplete}), _request())

    assert waiting_result.status is DataStatus.WAITING_SOURCE
    assert waiting_result.error is not None and waiting_result.error.retryable
    assert waiting_result.dataframe.empty
    assert incomplete_result.status is DataStatus.INCOMPLETE
    assert incomplete_result.error is not None
    assert incomplete_result.error.context["dependency"] == "shibor"


def test_legacy_empty_error_remains_value_error_and_maps_to_empty(flow_factory, publish_data) -> None:
    def empty(request: DataRequest):
        raise EmptyDataError("vendor returned no data")

    error = EmptyDataError("vendor returned no data")
    result = publish_data(flow_factory({Dataset.ETF_OHLCV.value: empty}), _request())

    assert isinstance(error, ValueError)
    assert result.status is DataStatus.EMPTY
    assert result.error is not None and result.error.code == "EMPTY_DATA"


def test_out_of_boundary_data_fails_contract(flow_factory, publish_data) -> None:
    frame = _frame()
    frame.loc[1, "Date"] = "2026-09-16"
    result = publish_data(flow_factory(
        {Dataset.ETF_OHLCV.value: lambda request: (frame, {"vendor": "test"})}
    ), _request())

    assert result.status is DataStatus.FAILED
    assert result.error is not None
    assert result.error.code == "DATA_CONTRACT_MISMATCH"


def test_date_only_end_includes_intraday_rows(flow_factory, publish_data) -> None:
    frame = pd.concat([_frame().iloc[[0]].copy()] * 8, ignore_index=True)
    frame["Date"] = [
        f"2026-09-14 {value}:00"
        for value in (
            "10:00",
            "10:30",
            "11:00",
            "11:30",
            "13:30",
            "14:00",
            "14:30",
            "15:00",
        )
    ]
    request = DataRequest(
        Dataset.ETF_OHLCV,
        "588080.SH",
        "2026-09-14",
        "2026-09-14",
        "2026-09-14",
        "30m",
    )

    result = publish_data(flow_factory(
        {Dataset.ETF_OHLCV.value: lambda ignored: (frame, {"vendor": "test"})}
    ), request)

    assert result.status is DataStatus.READY


def test_facade_blocks_semantically_invalid_ohlcv_before_ready(flow_factory, publish_data) -> None:
    frame = _frame()
    frame.loc[1, "High"] = 0.5

    result = publish_data(flow_factory(
        {Dataset.ETF_OHLCV.value: lambda ignored: (frame, {"vendor": "test"})}
    ), _request())

    assert result.status is DataStatus.FAILED
    assert result.error is not None
    assert result.error.code == "DATA_CONTRACT_MISMATCH"


def test_facade_blocks_invalid_calendar_before_ready(flow_factory, publish_data) -> None:
    calendar = pd.DataFrame({"Date": ["2026-09-14", "2026-09-15"], "IsOpen": [1, 2]})
    request = DataRequest(
        Dataset.TRADING_CALENDAR,
        "SSE",
        "2026-09-14",
        "2026-09-15",
        "2026-09-15",
    )

    result = publish_data(flow_factory(
        {
            Dataset.TRADING_CALENDAR.value: lambda ignored: (
                calendar,
                {"vendor": "test", "primary_key": ["Date"]},
            )
        }
    ), request)

    assert result.status is DataStatus.FAILED
    assert result.error is not None
    assert result.error.code == "DATA_CONTRACT_MISMATCH"


def test_multi_entity_dataset_uses_declared_primary_key(flow_factory, publish_data) -> None:
    frame = pd.DataFrame(
        {
            "Date": ["2026-09-15", "2026-09-15"],
            "Symbol": ["000001.SZ", "600000.SH"],
            "NetMoneyflowAmount": [1.0, -2.0],
        }
    )
    result = publish_data(flow_factory(
        {
            Dataset.STOCK_MONEYFLOW.value: lambda ignored: (
                frame,
                {"vendor": "test", "primary_key": ["Date", "Symbol"]},
            )
        }
    ),
        DataRequest(
            Dataset.STOCK_MONEYFLOW,
            None,
            "2026-09-15",
            "2026-09-15",
            "2026-09-15",
        )
    )

    assert result.status is DataStatus.READY
    assert len(result.dataframe) == 2


def test_default_registry_covers_all_active_frozen_strategy_inputs(flow_factory) -> None:
    expected = {
        Dataset.ETF_OHLCV.value,
        Dataset.ETF_UNADJUSTED_DAILY.value,
        Dataset.SHIBOR_DAILY.value,
        Dataset.US_REAL_YIELD_DAILY.value,
        Dataset.USDCNH_DAILY.value,
        Dataset.FXCM_DAILY.value,
        Dataset.SGE_GOLD_DAILY.value,
        Dataset.DOMESTIC_INDEX_DAILY.value,
        Dataset.CN_CPI_MONTHLY.value,
        Dataset.CN_PPI_MONTHLY.value,
        Dataset.CN_MONEY_MONTHLY.value,
        Dataset.INDEX_DAILY_BASIC.value,
        Dataset.ETF_SHARE_SIZE.value,
        Dataset.GLOBAL_INDEX_DAILY.value,
        Dataset.VIX_DAILY.value,
        Dataset.INDEX_CONSTITUENT_WEIGHT.value,
        Dataset.STOCK_MONEYFLOW.value,
        Dataset.TRADING_CALENDAR.value,
        Dataset.STRATEGY_FEATURE_EVIDENCE.value,
    }

    assert expected.issubset(flow_factory().datasets)


def test_strategy_feature_evidence_is_hash_pinned_and_bounded(flow_factory, publish_data, tmp_path) -> None:
    source = tmp_path / "evidence.csv"
    source.write_text(
        "date,feature\n2026-09-01,1.0\n2026-09-02,2.0\n",
        encoding="utf-8",
    )
    request = DataRequest(
        Dataset.STRATEGY_FEATURE_EVIDENCE,
        "S007-v1",
        "2026-09-02",
        "2026-09-03",
        None,
        parameters=EvidenceParameters(
            repository_root=tmp_path,
            source_path=source.name,
            source_sha256=sha256(source.read_bytes()).hexdigest(),
        ),
    )

    result = publish_data(flow_factory(), request)

    assert result.status is DataStatus.READY
    assert result.dataframe["Date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-09-02"]
    assert result.identity is not None
    assert result.identity.source == "repository"


def test_required_cutoff_prevents_stale_data_from_becoming_ready(flow_factory, publish_data) -> None:
    frame = _frame().iloc[[0]].copy()
    request = DataRequest(
        Dataset.ETF_OHLCV,
        "588080.SH",
        "2026-09-14",
        "2026-09-15",
        "2026-09-15",
    )

    result = publish_data(flow_factory(
        {Dataset.ETF_OHLCV.value: lambda ignored: (frame, {"vendor": "test"})}
    ), request)

    assert result.status is DataStatus.INCOMPLETE
    assert result.error is not None
    assert result.error.code == "INCOMPLETE_DATA"


def test_declared_start_coverage_prevents_truncated_history_from_becoming_ready(flow_factory, publish_data) -> None:
    frame = pd.DataFrame(
        {
            "Date": ["2016-11-29", "2024-12-31"],
            "OvernightRate": [2.30, 1.50],
        }
    )
    request = DataRequest(
        Dataset.SHIBOR_DAILY,
        None,
        "2013-07-29",
        "2024-12-31",
        "2024-12-31",
    )

    result = publish_data(flow_factory(
        {
            Dataset.SHIBOR_DAILY.value: lambda ignored: (
                frame,
                {
                    "vendor": "test",
                    "primary_key": ["Date"],
                    "maximum_start_lag_days": 10,
                },
            )
        }
    ), request)

    assert result.status is DataStatus.INCOMPLETE
    assert result.error is not None
    assert result.error.code == "INCOMPLETE_DATA"
    assert result.error.context["actual_start"].startswith("2016-11-29")


def test_vix_dataset_rejects_invalid_price_bars(flow_factory, publish_data) -> None:
    frame = pd.DataFrame(
        {
            "Date": ["2026-09-15"],
            "Open": [20.0],
            "High": [19.0],
            "Low": [18.0],
            "Close": [21.0],
            "PercentChange": [0.05],
        }
    )
    result = publish_data(flow_factory(
        {Dataset.VIX_DAILY.value: lambda ignored: (frame, {"vendor": "test"})}
    ),
        DataRequest(
            Dataset.VIX_DAILY,
            "VIX",
            "2026-09-15",
            "2026-09-15",
            "2026-09-15",
        )
    )

    assert result.status is DataStatus.FAILED
    assert result.error is not None
    assert result.error.code == "DATA_CONTRACT_MISMATCH"
