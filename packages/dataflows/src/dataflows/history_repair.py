"""Validation-triggered execution of source-bound history repair patches."""

from __future__ import annotations

from typing import Mapping, Sequence

import pandas as pd

from .errors import DataRepairError
from .history_patches import REPAIR_PATCHES, patch_for, validate_repair_patches
from .history_patches.common import frame_content_sha256, rebuild_intraday_from_1m
from .history_patches.model import RepairPatch, RepairRecord, SeriesKey
from .history_validation import ValidationFinding


def inspect_registered_source_anomalies(
    dataframe: pd.DataFrame,
    series: SeriesKey,
) -> tuple[ValidationFinding, ...]:
    """Turn exact known bad source signatures into validation failures."""

    if dataframe.empty:
        return ()
    patch = patch_for(series)
    if patch is None or patch.inspect is None:
        return ()
    return patch.inspect(dataframe, patch, series)


def apply_repairs_once(
    dataframe: pd.DataFrame,
    series: SeriesKey,
    findings: Sequence[ValidationFinding],
    *,
    references: Mapping[str, pd.DataFrame] | None = None,
    require_match: bool = True,
) -> tuple[pd.DataFrame, tuple[RepairRecord, ...]]:
    """Apply one deterministic repair transaction for the initial findings."""

    if not findings:
        return dataframe.copy(), ()
    references = references or {}
    result = dataframe.copy()
    records: list[RepairRecord] = []
    finding_codes = {item.code for item in findings}
    patch = patch_for(series)
    if patch is not None and not any(
        item.code in {"KNOWN_SOURCE_ANOMALY", "SOURCE_SIGNATURE_UNKNOWN"}
        and item.context.get("patch_id") not in {None, patch.patch_id}
        for item in findings
    ):
        before = frame_content_sha256(result)
        repaired, affected = patch.execute(
            result, patch, series, findings, references
        )
        if affected:
            result = repaired
            records.append(
                RepairRecord(
                    patch.patch_id,
                    patch.patch_version,
                    tuple(sorted(finding_codes)),
                    tuple(affected),
                    before,
                    frame_content_sha256(result),
                )
            )
    if not records and require_match:
        raise DataRepairError(
            f"no repair patch matched {series.vendor}/{series.symbol}/{series.frequency}",
            finding_codes=sorted(finding_codes),
        )
    return result, tuple(records)


__all__ = [
    "REPAIR_PATCHES",
    "RepairPatch",
    "RepairRecord",
    "SeriesKey",
    "apply_repairs_once",
    "frame_content_sha256",
    "inspect_registered_source_anomalies",
    "patch_for",
    "rebuild_intraday_from_1m",
    "validate_repair_patches",
]
