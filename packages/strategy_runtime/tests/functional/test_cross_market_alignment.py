from __future__ import annotations

import pandas as pd
import pytest

from strategy_runtime import (
    AlignmentRule,
    InputAlignment,
    RuntimeContractError,
    align_input_history,
)


def _strict_prior(maximum_staleness_days: int = 7) -> InputAlignment:
    return InputAlignment(
        AlignmentRule.STRICT_PRIOR,
        "Date",
        "FXCM_24X5",
        "SSE",
        maximum_staleness_days,
        False,
    )


def test_SRT_16_C01_c03_strict_prior_preserves_foreign_holiday_observations_and_lineage() -> None:
    result = align_input_history(
        pd.DataFrame(
            {
                "Date": [
                    "2026-09-29",
                    "2026-09-30",
                    "2026-10-01",
                    "2026-10-02",
                    "2026-10-07",
                    "2026-10-08",
                ],
                "Value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            }
        ),
        ["2026-09-30", "2026-10-06", "2026-10-08"],
        _strict_prior(),
        value_columns=("Value",),
    ).dataframe

    assert result["source_time"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-09-29",
        "2026-10-02",
        "2026-10-07",
    ]
    assert result["Value"].tolist() == [1.0, 4.0, 5.0]
    assert result["staleness_days"].tolist() == [1, 4, 1]
    assert (result["source_time"] < result["decision_time"]).all()


def test_SRT_16_C02_c03_exact_and_latest_available_distinguish_missing_exact_matches() -> None:
    source = pd.DataFrame({"Date": ["2026-10-07", "2026-10-08"], "Value": [5.0, 6.0]})
    exact = InputAlignment(AlignmentRule.EXACT, "Date", "FXCM_24X5", "SSE", 0, True)
    latest = InputAlignment(AlignmentRule.LATEST_AVAILABLE, "Date", "FXCM_24X5", "SSE", 1, True)

    decisions = ["2026-10-08", "2026-10-09"]
    exact_rows = align_input_history(source, decisions, exact).dataframe
    latest_rows = align_input_history(source, decisions, latest).dataframe

    # Both modes accept a same-day observation when the timestamp matches.
    for result in (exact_rows, latest_rows):
        assert result.iloc[0]["source_time"] == pd.Timestamp("2026-10-08")
        assert result.iloc[0]["Value"] == 6.0
        assert result.iloc[0]["staleness_days"] == 0

    # EXACT preserves missing history; LATEST_AVAILABLE uses the prior value.
    assert pd.isna(exact_rows.iloc[1]["source_time"])
    assert pd.isna(exact_rows.iloc[1]["Value"])
    assert pd.isna(exact_rows.iloc[1]["staleness_days"])
    assert latest_rows.iloc[1]["source_time"] == pd.Timestamp("2026-10-08")
    assert latest_rows.iloc[1]["Value"] == 6.0
    assert latest_rows.iloc[1]["staleness_days"] == 1


def test_SRT_16_C03_c03_foreign_gap_over_staleness_limit_is_blocked() -> None:
    source = pd.DataFrame({"Date": ["2026-10-02"], "Value": [4.0]})

    with pytest.raises(RuntimeContractError, match="exceeds maximum staleness"):
        align_input_history(source, ["2026-10-13"], _strict_prior())
