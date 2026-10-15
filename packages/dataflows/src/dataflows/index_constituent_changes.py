"""Explicit, immutable official-event supplements for missing vendor history.

Date is the first session with the new constituents, not the announcement date.
AvailableDate is when the pinned official sources had been captured, never an
inferred historical publication time. These rows describe changes, not weights
or a certified continuous membership history. No network fallback is performed.
"""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping

import pandas as pd

from ._csi500_20210615 import PATCH, _IndexChangePatch
from .contract import DataRequest
from .errors import DataContractError, IncompleteDataError


_AVAILABILITY_RULE = (
    "captured official sources at observed_at_utc converted to Asia/Shanghai; "
    "historical first publication and revision visibility unverified"
)


class _UnverifiedCoverage(IncompleteDataError):
    code = "INDEX_CHANGE_COVERAGE_UNVERIFIED"
    retryable = False


def _patch_for(request: DataRequest) -> _IndexChangePatch:
    if request.symbol != PATCH.symbol:
        raise DataContractError(
            "no verified constituent-change patch for this index",
            supported_symbols=[PATCH.symbol],
        )
    if request.start != PATCH.first_session or request.end != PATCH.first_session:
        raise _UnverifiedCoverage(
            "only the verified event session is covered; other dates are not certified empty",
            verified_event_sessions=[PATCH.first_session],
            coverage_kind="VERIFIED_EVENT_ONLY",
        )
    return PATCH


def _publication(patch: _IndexChangePatch) -> tuple[pd.DataFrame, dict[str, Any]]:
    payload = json.dumps(
        {"added": patch.added, "removed": patch.removed},
        ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    if sha256(payload).hexdigest() != patch.records_sha256:
        raise DataContractError("constituent-change patch records differ from their pinned hash")
    added = {symbol for symbol, _ in patch.added}
    removed = {symbol for symbol, _ in patch.removed}
    if len(patch.added) != 50 or len(patch.removed) != 50 or len(added) != 50 or len(removed) != 50 or added & removed:
        raise DataContractError("constituent-change patch must contain 50 unique changes per side")
    observed = pd.Timestamp(patch.observed_at_utc).tz_convert("Asia/Shanghai").tz_localize(None)
    rows = [
        {"Date": pd.Timestamp(patch.first_session),
         "AnnouncementDate": pd.Timestamp(patch.announcement_date),
         "EffectiveAfterClose": pd.Timestamp(patch.effective_after_close),
         "AvailableDate": observed,
         "ConstituentSymbol": symbol, "ConstituentName": name, "Change": direction}
        for direction, changes in (("ADD", patch.added), ("REMOVE", patch.removed))
        for symbol, name in changes
    ]
    frame = pd.DataFrame(rows).sort_values(["Date", "Change", "ConstituentSymbol"]).reset_index(drop=True)
    metadata = {
        "vendor": "csindex", "vendor_symbol": patch.symbol, "frequency": "event",
        "primary_key": ["Date", "ConstituentSymbol"],
        "patch_id": patch.patch_id, "patch_version": patch.version,
        "patch_records_sha256": patch.records_sha256,
        "source_notice_id": patch.notice_id, "source_notice_url": patch.notice_url,
        "source_notice_sha256": patch.notice_sha256,
        "source_attachment_url": patch.attachment_url,
        "source_attachment_sha256": patch.attachment_sha256,
        "source_calendar_url": patch.calendar_url, "source_calendar_sha256": patch.calendar_sha256,
        "observed_at_utc": patch.observed_at_utc,
        "acquisition_mode": "CURATED_IMMUTABLE_PATCH",
        "coverage_kind": "VERIFIED_EVENT_ONLY", "verified_event_sessions": [patch.first_session],
        "complete_membership_history": False, "contains_weights": False,
        "historical_publication_time_verified": False, "historical_revision_history_verified": False,
        "source_time_field": "Date", "source_calendar": "SSE",
        "availability_time_field": "AvailableDate", "availability_timezone": "Asia/Shanghai",
        "available_at": _AVAILABILITY_RULE,
    }
    return frame, metadata


def fetch_index_constituent_changes(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
    """Publish exactly one verified event; REFRESH never downloads a newer copy."""
    return _publication(_patch_for(request))


def validate_index_constituent_changes(
    frame: pd.DataFrame, request: DataRequest, metadata: Mapping[str, Any],
) -> None:
    """Keep event data, coverage and provenance bound to the pinned patch."""
    expected_frame, expected_metadata = _publication(_patch_for(request))
    if not frame.equals(expected_frame):
        raise DataContractError("constituent changes differ from the verified official event")
    if any(metadata.get(key) != value for key, value in expected_metadata.items()):
        raise DataContractError("constituent-change provenance or coverage differs from the pinned patch")
