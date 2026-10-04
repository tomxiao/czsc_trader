"""Read-only publication of immutable strategy research evidence."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .contract import DataRequest, EvidenceParameters
from .errors import DataContractError, EmptyDataError


def fetch_strategy_feature_evidence(
    request: DataRequest,
) -> tuple[pd.DataFrame, Mapping[str, Any]]:
    """Publish a bounded slice of a hash-pinned repository evidence file."""

    if not isinstance(request.parameters, EvidenceParameters):
        raise DataContractError("strategy evidence requires EvidenceParameters")
    root_value = request.parameters.repository_root
    source_value = request.parameters.source_path
    expected_sha256 = request.parameters.source_sha256
    root = Path(str(root_value)).resolve()
    source = (root / str(source_value)).resolve()
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise DataContractError("strategy evidence source escapes repository root") from exc
    if not source.is_file():
        raise DataContractError("strategy evidence source is missing", path=str(source))
    actual_sha256 = sha256(source.read_bytes()).hexdigest()
    if actual_sha256 != expected_sha256:
        raise DataContractError(
            "strategy evidence source hash differs",
            expected_sha256=expected_sha256,
            actual_sha256=actual_sha256,
        )
    frame = pd.read_csv(source)
    date_column = "date" if "date" in frame else "Date" if "Date" in frame else None
    if date_column is None:
        raise DataContractError("strategy evidence source has no date column")
    frame = frame.rename(columns={date_column: "Date"})
    frame["Date"] = pd.to_datetime(frame["Date"], errors="raise").dt.normalize()
    start = pd.Timestamp(request.start).normalize()
    end = pd.Timestamp(request.end).normalize()
    frame = frame.loc[frame["Date"].between(start, end)].sort_values("Date").reset_index(drop=True)
    if frame.empty:
        raise EmptyDataError("strategy evidence has no rows in the requested interval")
    return frame, {
        "vendor": "repository",
        "primary_key": ["Date"],
        "release_id": request.symbol,
        "source_path": str(source_value),
        "source_sha256": actual_sha256,
    }
