from __future__ import annotations

import pandas as pd
import pytest

from dataflows import (
    DataCoverageRequirement,
    DataRequest,
    DataStatus,
    DataTemporalContract,
    DataTemporalRequirement,
    Dataflows,
    Dataset,
    RequestRangePolicy,
    TemporalAlignment,
    align_temporal_frame,
)


def _contract() -> DataTemporalContract:
    return DataTemporalContract(
        source_time_field="Date",
        availability_time_field="AvailableDate",
        source_calendar="SOURCE_CALENDAR",
        available_at="published before market open",
        request_range_policy=RequestRangePolicy.EXACT,
    )


def _source() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date": ["2026-09-01", "2026-09-03"],
            "AvailableDate": ["2026-09-02", "2026-09-04"],
            "Value": [1.0, 2.0],
        }
    )


def test_strict_prior_excludes_same_session_information() -> None:
    result = align_temporal_frame(
        _source(),
        ["2026-09-02", "2026-09-03", "2026-09-04"],
        contract=_contract(),
        requirement=DataTemporalRequirement(
            TemporalAlignment.STRICT_PRIOR,
            decision_time="SSE open",
            warmup_sessions=1,
        ),
    )

    assert result.unmatched_prefix_rows == 1
    assert result.dataframe["Value"].tolist()[1:] == [1.0, 1.0]


def test_latest_available_includes_same_session_information() -> None:
    result = align_temporal_frame(
        _source(),
        ["2026-09-02", "2026-09-03", "2026-09-04"],
        contract=_contract(),
        requirement=DataTemporalRequirement(
            TemporalAlignment.LATEST_AVAILABLE,
            decision_time="SSE close",
        ),
    )

    assert result.unmatched_prefix_rows == 0
    assert result.dataframe["Value"].tolist() == [1.0, 1.0, 2.0]


def test_alignment_rejects_undeclared_warmup_and_stale_values() -> None:
    with pytest.raises(ValueError, match="warmup_sessions"):
        align_temporal_frame(
            _source(),
            ["2026-09-01", "2026-09-02"],
            contract=_contract(),
            requirement=DataTemporalRequirement(
                TemporalAlignment.LATEST_AVAILABLE,
                decision_time="SSE close",
            ),
        )

    with pytest.raises(ValueError, match="max_staleness_days"):
        align_temporal_frame(
            _source(),
            ["2026-09-02", "2026-09-10"],
            contract=_contract(),
            requirement=DataTemporalRequirement(
                TemporalAlignment.LATEST_AVAILABLE,
                decision_time="SSE close",
                max_staleness_days=2,
            ),
        )


def test_strict_coverage_blocks_truncated_history_without_provider_hint() -> None:
    frame = pd.DataFrame({"Date": ["2026-09-10"], "OvernightRate": [1.5]})
    request = DataRequest(
        Dataset.SHIBOR_DAILY,
        None,
        "2026-09-01",
        "2026-09-10",
        "2026-09-10",
        coverage=DataCoverageRequirement(maximum_start_lag_days=1),
    )

    result = Dataflows(
        {Dataset.SHIBOR_DAILY.value: lambda ignored: (frame, {"vendor": "test"})}
    ).fetch(request)

    assert result.status is DataStatus.INCOMPLETE
    assert result.error is not None
    assert result.error.context["maximum_start_lag_days"] == 1


def test_ready_identity_exposes_typed_temporal_contract() -> None:
    frame = pd.DataFrame({"Date": ["2026-09-01"], "OvernightRate": [1.5]})
    result = Dataflows(
        {Dataset.SHIBOR_DAILY.value: lambda ignored: (frame, {"vendor": "test"})}
    ).fetch(
        DataRequest(
            Dataset.SHIBOR_DAILY,
            None,
            "2026-09-01",
            "2026-09-01",
            "2026-09-01",
        )
    )

    assert result.status is DataStatus.READY
    assert result.identity is not None
    assert result.identity.temporal_contract == DataTemporalContract(
        source_time_field="Date",
        availability_time_field="Date",
        source_calendar="SOURCE_NATIVE",
        available_at="SOURCE_PERIOD_CLOSE",
        request_range_policy=RequestRangePolicy.EXACT,
    )
