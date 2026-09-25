"""Causal alignment helpers built on typed DFLS time semantics."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

import pandas as pd

from .contract import DataTemporalContract, DataTemporalRequirement, TemporalAlignment


@dataclass(frozen=True, slots=True)
class TemporalAlignmentResult:
    dataframe: pd.DataFrame
    first_valid_decision: str
    unmatched_prefix_rows: int


def align_temporal_frame(
    dataframe: pd.DataFrame,
    decision_dates: Sequence[object],
    *,
    contract: DataTemporalContract,
    requirement: DataTemporalRequirement,
) -> TemporalAlignmentResult:
    """Align one single-valued source series without hiding causal gaps."""

    if not isinstance(contract, DataTemporalContract):
        raise TypeError("contract must be DataTemporalContract")
    if not isinstance(requirement, DataTemporalRequirement):
        raise TypeError("requirement must be DataTemporalRequirement")
    missing = {
        contract.source_time_field,
        contract.availability_time_field,
    }.difference(dataframe.columns)
    if missing:
        raise ValueError(f"temporal source fields are missing: {sorted(missing)}")
    source = dataframe.copy()
    available = pd.to_datetime(source[contract.availability_time_field], errors="coerce")
    source_time = pd.to_datetime(source[contract.source_time_field], errors="coerce")
    if available.isna().any() or source_time.isna().any():
        raise ValueError("temporal source fields contain invalid timestamps")
    if available.duplicated().any():
        raise ValueError("temporal source must be single-valued by availability time")
    source["SourceAvailableAt"] = available
    source["SourceTime"] = source_time
    source = source.sort_values("SourceAvailableAt").reset_index(drop=True)

    decisions = pd.to_datetime(pd.Series(tuple(decision_dates)), errors="coerce")
    if decisions.empty or decisions.isna().any():
        raise ValueError("decision_dates must contain valid timestamps")
    if decisions.duplicated().any() or not decisions.is_monotonic_increasing:
        raise ValueError("decision_dates must be unique and ordered")
    left = pd.DataFrame({"DecisionDate": decisions})
    if requirement.alignment is TemporalAlignment.EXACT_SESSION:
        aligned = left.merge(
            source,
            left_on="DecisionDate",
            right_on="SourceAvailableAt",
            how="left",
            validate="one_to_one",
        )
    else:
        aligned = pd.merge_asof(
            left,
            source,
            left_on="DecisionDate",
            right_on="SourceAvailableAt",
            direction="backward",
            allow_exact_matches=(requirement.alignment is TemporalAlignment.LATEST_AVAILABLE),
        )

    matched = aligned["SourceAvailableAt"].notna()
    if not matched.any():
        raise ValueError("temporal alignment produced no usable decisions")
    first_valid = int(matched.to_numpy().argmax())
    if (~matched.iloc[first_valid:]).any():
        raise ValueError("temporal alignment contains a gap after the warmup prefix")
    if first_valid > requirement.warmup_sessions:
        raise ValueError(
            "temporal alignment exceeds the declared warmup_sessions: "
            f"{first_valid} > {requirement.warmup_sessions}"
        )
    aligned["StalenessDays"] = (
        aligned["DecisionDate"] - aligned["SourceAvailableAt"]
    ).dt.total_seconds() / 86400.0
    if requirement.max_staleness_days is not None:
        stale = aligned.loc[matched, "StalenessDays"] > requirement.max_staleness_days
        if stale.any():
            raise ValueError("temporal alignment exceeds max_staleness_days")
    return TemporalAlignmentResult(
        dataframe=aligned,
        first_valid_decision=aligned.loc[first_valid, "DecisionDate"].isoformat(),
        unmatched_prefix_rows=first_valid,
    )


__all__ = ["TemporalAlignmentResult", "align_temporal_frame"]
