from __future__ import annotations

import pandas as pd
import pytest

from strategy_runtime import (
    AlignmentRule,
    CutoffRule,
    DecisionContract,
    ExecutionPolicy,
    ImplementationRef,
    InputAlignment,
    InputContract,
    InputRequirement,
    MonitoringPolicy,
    ParameterSet,
    RequiredCapabilities,
    RuntimeDefinition, ObservationDefinition,
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


def test_c03_strict_prior_preserves_foreign_holiday_observations_and_lineage() -> None:
    result = align_input_history(
        pd.DataFrame({
            "Date": ["2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02",
                     "2026-10-07", "2026-10-08"],
            "Value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        }),
        ["2026-09-30", "2026-10-06", "2026-10-08"],
        _strict_prior(),
        value_columns=("Value",),
    ).dataframe

    assert result["source_time"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-09-29", "2026-10-02", "2026-10-07",
    ]
    assert result["Value"].tolist() == [1.0, 4.0, 5.0]
    assert result["staleness_days"].tolist() == [1, 4, 1]
    assert (result["source_time"] < result["decision_time"]).all()


def test_c03_same_day_value_is_forbidden_even_when_present() -> None:
    source = pd.DataFrame(
        {
            "Date": ["2026-10-07 23:00:00", "2026-10-08 01:00:00"],
            "Value": [5.0, 6.0],
        }
    )
    result = align_input_history(
        source,
        ["2026-10-08 15:00:00"],
        _strict_prior(),
        value_columns=("Value",),
    ).dataframe.iloc[0]

    assert result["source_time"] == pd.Timestamp("2026-10-07 23:00:00")
    assert result["Value"] == 5.0


def test_c03_exact_and_latest_available_distinguish_missing_exact_matches() -> None:
    source = pd.DataFrame({"Date": ["2026-10-07", "2026-10-08"], "Value": [5.0, 6.0]})
    exact = InputAlignment(AlignmentRule.EXACT, "Date", "FXCM_24X5", "SSE", 0, True)
    latest = InputAlignment(
        AlignmentRule.LATEST_AVAILABLE, "Date", "FXCM_24X5", "SSE", 1, True
    )

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


def test_c03_foreign_gap_over_staleness_limit_is_blocked() -> None:
    source = pd.DataFrame({"Date": ["2026-10-02"], "Value": [4.0]})

    with pytest.raises(RuntimeContractError, match="exceeds maximum staleness"):
        align_input_history(source, ["2026-10-13"], _strict_prior())


def test_c03_alignment_contract_participates_in_input_identity() -> None:
    requirement = InputRequirement(
        "xauusd_daily",
        "fx.fxcm_daily",
        "XAUUSD.FXCM",
        "daily",
        150,
        CutoffRule.LATEST_AVAILABLE,
        7,
        _strict_prior(),
    )

    assert requirement.alignment is not None
    assert requirement.alignment.identity_payload() == {
        "rule": "STRICT_PRIOR",
        "source_time_column": "Date",
        "source_calendar": "FXCM_24X5",
        "decision_calendar": "SSE",
        "maximum_staleness_days": 7,
        "allow_same_day": False,
    }
    common = {
        "schema_version": 3,
        "observation": ObservationDefinition((),()),
        "strategy_family_id": "S900",
        "version": None,
        "release_id": "S900-C0064",
        "release_hash": "a" * 64,
        "implementation": ImplementationRef("runtime", "Strategy", 1, "b" * 64),
        "parameters": ParameterSet({"prototype": "P04"}),
        "decision": DecisionContract("TARGET_POSITION", 0.0, 1.0, "NEXT_SESSION"),
        "execution": ExecutionPolicy("LIMIT", {}),
        "monitoring": MonitoringPolicy("ROLLING", {}),
        "capabilities": RequiredCapabilities(("fx.fxcm_daily",), ("LIMIT",)),
        "tradable_symbol": "518880.SH",
        "identity_kind": "CANDIDATE",
        "candidate_id": "C0064",
    }
    unaligned = InputRequirement(
        "xauusd_daily",
        "fx.fxcm_daily",
        "XAUUSD.FXCM",
        "daily",
        150,
        CutoffRule.LATEST_AVAILABLE,
        7,
    )

    aligned_identity = RuntimeDefinition(
        **common, inputs=InputContract((requirement,))
    ).runtime_sha256
    unaligned_identity = RuntimeDefinition(
        **common, inputs=InputContract((unaligned,))
    ).runtime_sha256

    assert aligned_identity != unaligned_identity


def test_c03_alignment_rejects_ambiguous_contracts_and_unordered_times() -> None:
    with pytest.raises(RuntimeContractError, match="STRICT_PRIOR cannot allow"):
        InputAlignment(AlignmentRule.STRICT_PRIOR, "Date", "FXCM", "SSE", 7, True)
    with pytest.raises(RuntimeContractError, match="decision time must be unique and ordered"):
        align_input_history(
            pd.DataFrame({"Date": ["2026-10-01"], "Value": [1.0]}),
            ["2026-10-08", "2026-10-07"],
            _strict_prior(),
        )
