"""Retrospective daily constituents from official dates and monthly snapshots."""

from __future__ import annotations

from bisect import bisect_right
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping

import numpy as np
import pandas as pd

from . import _csi500_effective_dates
from ._csi500_daily_patches import PATCHES as DAILY_PATCHES
from ._index_change_patch import _IndexChangePatch
from .contract import DataRequest, Dataset
from .errors import DataContractError, EmptyDataError, IncompleteDataError
from .index_constituent_changes import PATCHES
from .index_membership_reconstruction import reconstruct_membership
from .tushare_common import get_tushare_pro


_AVAILABILITY = "maximum actual capture time of dependent monthly snapshots, official notices, explicit patches and trading calendar"


def _json_hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _frame_hash(frame: pd.DataFrame) -> str:
    return sha256(frame.to_json(orient="split", date_format="iso", index=False).encode()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _catalog(request: DataRequest) -> dict[str, Any]:
    if request.symbol != "000905.SH":
        raise DataContractError("verified effective-date catalog is available only for 000905.SH")
    catalog = deepcopy(_csi500_effective_dates.CATALOG)
    if _json_hash(catalog) != _csi500_effective_dates.CATALOG_SHA256:
        raise DataContractError("effective-date catalog differs from its pinned source identity")
    if (request.start < catalog["coverage_start"] or request.end > catalog["coverage_end"]
            or not catalog["coverage_complete"]):
        raise IncompleteDataError("known effective-date catalog is not verified for this range",
                                  coverage_start=catalog["coverage_start"], coverage_end=catalog["coverage_end"],
                                  unresolved_notices=catalog.get("unresolved_notices", []))
    seen = {}
    for event in catalog["events"]:
        first = pd.Timestamp(event["first_session"])
        announcement = pd.Timestamp(event["announcement_date"])
        if (pd.isna(first) or pd.isna(announcement) or first.tzinfo is not None
                or announcement.tzinfo is not None or first != first.normalize()
                or announcement != announcement.normalize() or announcement > first or first.weekday() >= 5):
            raise DataContractError("official event has invalid announcement/effective dates")
        identity = str(event["notice_id"])
        if identity in seen and seen[identity] != event:
            raise DataContractError("official notice has conflicting event identities", notice_id=identity)
        seen[identity] = event
        for field in ("notice_sha256",):
            if re.fullmatch(r"[0-9a-f]{64}", event[field]) is None:
                raise DataContractError("official event is missing its source hash")
        observed = pd.Timestamp(event["observed_at_utc"])
        if observed.tzinfo is None:
            raise DataContractError("official event observation must have an explicit timezone")
    return catalog


def _event_frame(catalog: Mapping[str, Any]) -> pd.DataFrame:
    rows = [{"Date": pd.Timestamp(event["first_session"]),
             "AnnouncementDate": pd.Timestamp(event["announcement_date"]),
             "EffectiveAfterClose": pd.NaT if event["effective_after_close"] is None
             else pd.Timestamp(event["effective_after_close"]),
             "AvailableDate": pd.Timestamp(event["observed_at_utc"]).tz_convert("Asia/Shanghai").tz_localize(None),
             "NoticeId": int(event["notice_id"]), "NoticeTitle": event["title"]}
            for event in catalog["events"]]
    frame = pd.DataFrame(rows, columns=["Date", "AnnouncementDate", "EffectiveAfterClose", "AvailableDate",
                                        "NoticeId", "NoticeTitle"])
    for column in ("Date", "AnnouncementDate", "EffectiveAfterClose", "AvailableDate"):
        frame[column] = pd.to_datetime(frame[column])
    return frame.sort_values(["Date", "NoticeId"]).reset_index(drop=True)


def _metadata(catalog: Mapping[str, Any]) -> dict[str, Any]:
    return {"vendor": "csindex+tushare", "vendor_symbol": "000905.SH", "source_calendar": "SSE",
            "event_catalog_sha256": _csi500_effective_dates.CATALOG_SHA256,
            "event_coverage_start": catalog["coverage_start"], "event_coverage_end": catalog["coverage_end"],
            "event_coverage_verified": catalog.get("source_scope_review", {}).get("complete", True),
            "event_scope_review": catalog.get("source_scope_review", {"complete": True}),
            "catalog_coverage_complete": catalog["coverage_complete"],
            "event_sources": [{key: event[key] for key in ("notice_id", "notice_url", "notice_sha256",
                               "announcement_date", "first_session", "observed_at_utc")}
                              for event in catalog["events"]],
            "event_source_acquisition": [{"notice_id": event["notice_id"],
                **{key: event[key] for key in ("acquisition_mode", "boundary_kind", "detail_body_captured",
                    "source_query_url", "source_query", "source_response_sha256", "effective_date_source_url",
                    "effective_date_source_sha256") if key in event}}
                for event in catalog["events"]],
            "source_time_field": "Date", "availability_time_field": "AvailableDate",
            "availability_timezone": "Asia/Shanghai", "available_at": _AVAILABILITY,
            "historical_publication_time_verified": False, "historical_revision_history_verified": False,
            "reconstruction_kind": "RETROSPECTIVE_MEMBERSHIP_FACTS", "contains_weights": False}


def _observed_at(value: Any) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (ValueError, TypeError) as exc:
        raise DataContractError("membership source observation time is invalid") from exc
    if pd.isna(timestamp) or timestamp.tzinfo is None:
        raise DataContractError("membership source observation requires an explicit timezone")
    return timestamp.tz_convert("Asia/Shanghai").tz_localize(None)


def _patch_registry(catalog: Mapping[str, Any]) -> dict[str, _IndexChangePatch]:
    events = {(event["first_session"], str(event["notice_id"])) for event in catalog["events"]}
    registry = {}
    for item in (*PATCHES, *DAILY_PATCHES):
        if (item.first_session, str(item.notice_id)) not in events:
            continue
        if item.patch_id in registry:
            raise DataContractError("membership patch registry contains duplicate identities")
        registry[item.patch_id] = item
    return registry


def _patch_source(item: _IndexChangePatch) -> dict[str, Any]:
    return {"patch_id": item.patch_id, "patch_version": item.version,
            "notice_id": str(item.notice_id), "first_session": item.first_session,
            "records_sha256": item.records_sha256, "notice_sha256": item.notice_sha256,
            "attachment_sha256": item.attachment_sha256, "boundary_kind": item.boundary_kind,
            "effective_date_source_url": item.effective_date_source_url,
            "effective_date_source_sha256": item.effective_date_source_sha256,
            "observed_at_utc": item.observed_at_utc}


def _available_at(
    catalog: Mapping[str, Any], metadata: Mapping[str, Any], used_patches: list[_IndexChangePatch],
) -> pd.Timestamp:
    observations = [metadata["calendar_observed_at_utc"]]
    observations.extend(item["observed_at_utc"] for item in metadata["snapshot_queries"])
    observations.extend(item["observed_at_utc"] for item in catalog["events"])
    observations.extend(item.observed_at_utc for item in used_patches)
    return max(_observed_at(value) for value in observations)


def fetch_index_constituent_events(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
    """Read the once-captured official dates without accessing a website."""
    catalog = _catalog(request)
    frame = _event_frame(catalog)
    frame = frame.loc[frame.Date.between(request.start, request.end)].reset_index(drop=True)
    metadata = {**_metadata(catalog), "vendor": "csindex", "frequency": "event",
                "primary_key": ["Date", "NoticeId"]}
    return frame, metadata


def fetch_index_constituents_daily(
    request: DataRequest, *, env_file: str | Path | None = None, pro: object | None = None,
) -> tuple[pd.DataFrame, Mapping[str, Any]]:
    """Acquire monthly anchors explicitly, then reconstruct session membership."""
    catalog = _catalog(request)
    client = get_tushare_pro(env_file) if pro is None else pro
    start = pd.Timestamp(request.start).to_period("M") - 1
    end = pd.Timestamp(request.end).to_period("M")
    snapshots, source_queries, missing_months = [], [], []
    for month in pd.period_range(start, end, freq="M"):
        first, last = month.start_time.strftime("%Y%m%d"), month.end_time.strftime("%Y%m%d")
        raw = client.index_weight(index_code=request.symbol, start_date=first, end_date=last,
                                  fields="index_code,con_code,trade_date,weight")
        observed = _now()
        if not isinstance(raw, pd.DataFrame):
            raise DataContractError("index_weight did not return a dataframe")
        digest = _frame_hash(raw)
        source_queries.append({"api": "index_weight", "start_date": first, "end_date": last,
                               "sha256": digest, "observed_at_utc": observed, "rows": len(raw)})
        if raw.empty:
            missing_months.append(str(month))
            continue
        required = {"index_code", "con_code", "trade_date", "weight"}
        if not required.issubset(raw.columns) or raw["index_code"].ne(request.symbol).any():
            raise DataContractError("index_weight response is missing its identity or mixes indexes")
        if len(raw) >= 4000:
            raise IncompleteDataError("index_weight monthly response may be truncated", month=str(month))
        dates = pd.to_datetime(raw["trade_date"], format="%Y%m%d", errors="coerce")
        if dates.isna().any() or dates.dt.to_period("M").ne(month).any():
            raise DataContractError("index_weight returned dates outside the requested month")
        weights = pd.to_numeric(raw["weight"], errors="coerce")
        if weights.isna().any() or not np.isfinite(weights).all() or (weights < 0).any():
            raise DataContractError("index_weight returned invalid weights")
        snapshots.append(pd.DataFrame({"Date": dates, "ConstituentSymbol": raw["con_code"],
                                        "ObservedAt": observed, "SnapshotSha256": digest}))
    if not snapshots:
        raise IncompleteDataError("no monthly membership anchor exists for the requested interval")
    snapshot_frame = pd.concat(snapshots, ignore_index=True)
    calendar = client.trade_cal(exchange="SSE", start_date=start.start_time.strftime("%Y%m%d"),
                                end_date=end.end_time.strftime("%Y%m%d"),
                                fields="exchange,cal_date,is_open,pretrade_date")
    calendar_observed = _now()
    if not isinstance(calendar, pd.DataFrame) or not {"cal_date", "is_open", "exchange"}.issubset(calendar.columns):
        raise IncompleteDataError("a complete SSE calendar is required for daily membership")
    calendar_dates = pd.to_datetime(calendar["cal_date"], format="%Y%m%d", errors="coerce")
    expected_days = pd.date_range(start.start_time, end.end_time.normalize())
    if (calendar_dates.isna().any() or calendar_dates.duplicated().any()
            or not pd.DatetimeIndex(calendar_dates).sort_values().equals(expected_days)
            or calendar["exchange"].ne("SSE").any()
            or not calendar["is_open"].isin([0, 1]).all()):
        raise IncompleteDataError("SSE calendar is incomplete or ambiguous")
    open_days = pd.DatetimeIndex(calendar_dates.loc[calendar["is_open"].eq(1)]).sort_values()
    for event in catalog["events"]:
        effective_day = pd.Timestamp(event["first_session"])
        if expected_days[0] <= effective_day <= expected_days[-1] and effective_day not in open_days:
            raise DataContractError("official first effective session is not an SSE trading session")
    if not snapshot_frame.Date.isin(open_days).all():
        raise DataContractError("monthly snapshot date is not an SSE trading session")
    sessions = open_days[(open_days >= request.start) & (open_days <= request.end)]
    if sessions.empty:
        raise EmptyDataError("requested interval contains no SSE trading session")
    events = _event_frame(catalog).rename(columns={"AvailableDate": "ObservedAt"})
    # ObservedAt is explicitly UTC input for the pure calculator.
    events["ObservedAt"] = [event["observed_at_utc"] for event in sorted(
        catalog["events"], key=lambda item: (item["first_session"], item["notice_id"]))]
    event_dates = set(events.Date.dt.strftime("%Y-%m-%d"))
    patches = tuple(patch for patch in (*PATCHES, *DAILY_PATCHES) if patch.first_session in event_dates)
    frame, reconstruction = reconstruct_membership(snapshot_frame, events, sessions, patches)
    used_ids = {patch_id for segment in reconstruction["reconstruction_segments"] for patch_id in segment["patch_ids"]}
    registry = _patch_registry(catalog)
    publication_available = _available_at(catalog, {
        "calendar_observed_at_utc": calendar_observed, "snapshot_queries": source_queries,
    }, [registry[patch_id] for patch_id in sorted(used_ids)])
    frame["AvailableDate"] = publication_available
    # Pin each reconstructed segment to its 500-symbol set, not just its row count.
    segments = reconstruction["reconstruction_segments"]
    for segment in segments:
        segment["available_date"] = publication_available.isoformat()
        members = frame.loc[frame.Date.eq(pd.Timestamp(segment["session_start"])), "ConstituentSymbol"].tolist()
        segment["membership_sha256"] = _json_hash(members)
    metadata = {**_metadata(catalog), **reconstruction, "vendor": "dfls", "frequency": "daily",
                "primary_key": ["Date", "ConstituentSymbol"], "available_at": _AVAILABILITY,
                "expected_sessions": sessions.strftime("%Y-%m-%d").tolist(),
                "snapshot_queries": source_queries, "missing_snapshot_months": missing_months,
                "calendar_sha256": _frame_hash(calendar), "calendar_observed_at_utc": calendar_observed}
    return frame, metadata


def validate_index_membership(frame: pd.DataFrame, request: DataRequest, metadata: Mapping[str, Any]) -> None:
    """Validate cached/public outputs without network or recapturing sources."""
    catalog = _catalog(request)
    expected_meta = _metadata(catalog)
    for key in ("event_catalog_sha256", "event_coverage_start", "event_coverage_end", "event_coverage_verified",
                "event_scope_review",
                "event_sources", "event_source_acquisition", "catalog_coverage_complete",
                "historical_publication_time_verified", "historical_revision_history_verified",
                "reconstruction_kind", "contains_weights", "available_at", "availability_time_field"):
        if metadata.get(key) != expected_meta[key]:
            raise DataContractError("membership provenance differs from its pinned source contract", field=key)
    if request.dataset is Dataset.INDEX_CONSTITUENT_EVENTS:
        expected = _event_frame(catalog)
        expected = expected.loc[expected.Date.between(request.start, request.end)].reset_index(drop=True)
        if not frame.equals(expected):
            raise DataContractError("published effective dates differ from official source records")
        return
    if "Weight" in frame.columns:
        raise DataContractError("daily membership must not expose monthly weights as daily weights")
    days = pd.to_datetime(frame["Date"], errors="coerce")
    available = pd.to_datetime(frame["AvailableDate"], errors="coerce")
    snapshots = pd.to_datetime(frame["SourceSnapshotDate"], errors="coerce")
    if days.isna().any() or available.isna().any() or snapshots.isna().any():
        raise DataContractError("daily membership has missing source or availability dates")
    queries = metadata.get("snapshot_queries")
    months = pd.period_range(pd.Timestamp(request.start).to_period("M") - 1,
                             pd.Timestamp(request.end).to_period("M"), freq="M")
    expected_queries = [(month.start_time.strftime("%Y%m%d"), month.end_time.strftime("%Y%m%d"))
                        for month in months]
    if not isinstance(queries, list) or len(queries) != len(expected_queries):
        raise DataContractError("daily membership monthly source queries are incomplete")
    for query, (first, last) in zip(queries, expected_queries):
        if (not isinstance(query, Mapping) or query.get("api") != "index_weight"
                or query.get("start_date") != first or query.get("end_date") != last
                or type(query.get("rows")) is not int or query["rows"] < 0
                or not isinstance(query.get("sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", query["sha256"]) is None):
            raise DataContractError("daily membership monthly query identity is invalid")
        _observed_at(query.get("observed_at_utc"))
    if (not isinstance(metadata.get("calendar_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", metadata["calendar_sha256"]) is None):
        raise DataContractError("daily membership calendar source hash is invalid")
    _observed_at(metadata.get("calendar_observed_at_utc"))

    def verify_snapshot(day: Any, digest: Any) -> pd.Timestamp:
        try:
            timestamp = pd.Timestamp(day)
        except (TypeError, ValueError) as exc:
            raise DataContractError("membership snapshot source date is invalid") from exc
        if pd.isna(timestamp) or timestamp.tzinfo is not None or timestamp != timestamp.normalize():
            raise DataContractError("membership snapshot source date must be a calendar date")
        compact = timestamp.strftime("%Y%m%d")
        if not any(query["sha256"] == digest and query["start_date"] <= compact <= query["end_date"]
                   and query["rows"] >= 500 for query in queries):
            raise DataContractError("membership snapshot does not match a captured monthly query")
        return timestamp

    event_groups: dict[pd.Timestamp, set[str]] = {}
    for event in catalog["events"]:
        event_groups.setdefault(pd.Timestamp(event["first_session"]), set()).add(str(event["notice_id"]))
    boundaries = sorted(event_groups)
    registry = _patch_registry(catalog)
    expected_sessions = metadata.get("expected_sessions")
    if (not isinstance(expected_sessions, list) or days.dt.strftime("%Y-%m-%d").drop_duplicates().tolist() != expected_sessions
            or metadata.get("expected_constituents") != 500 or metadata.get("verified_session_count") != len(expected_sessions)
            or frame.groupby("Date").size().ne(500).any()
            or frame.duplicated(["Date", "ConstituentSymbol"]).any()
            or not frame["ConstituentSymbol"].astype(str).str.fullmatch(r"\d{6}\.(SH|SZ)").all()):
        raise DataContractError("daily membership sessions or constituent identity are incomplete")
    segments = metadata.get("reconstruction_segments")
    if not isinstance(segments, list) or not segments:
        raise DataContractError("daily membership is missing its reconstruction evidence")
    assigned = set()
    used_ids = set()
    patched_sessions = 0
    for segment in segments:
        selected = frame.loc[days.between(segment["session_start"], segment["session_end"])]
        segment_days = selected.Date.dt.strftime("%Y-%m-%d").unique().tolist()
        if (not len(selected) or assigned.intersection(segment_days) or len(segment_days) != segment["session_count"]
                or not selected.SourceSnapshotDate.eq(pd.Timestamp(segment["source_snapshot_date"])).all()
                or not selected.AvailableDate.eq(pd.Timestamp(segment["available_date"])).all()):
            raise DataContractError("daily membership segment provenance is inconsistent")
        assigned.update(segment_days)
        source_day = verify_snapshot(segment.get("source_snapshot_date"), segment.get("source_snapshot_sha256"))
        target_index = bisect_right(boundaries, pd.Timestamp(segment_days[0]))
        if any(bisect_right(boundaries, pd.Timestamp(day)) != target_index for day in segment_days):
            raise DataContractError("daily membership segment crosses an effective-event boundary")
        lower = boundaries[target_index - 1] if target_index else None
        upper = boundaries[target_index] if target_index < len(boundaries) else None
        if (segment.get("segment_start") != (None if lower is None else lower.date().isoformat())
                or segment.get("segment_end_exclusive") != (None if upper is None else upper.date().isoformat())):
            raise DataContractError("daily membership segment event boundaries differ from the catalog")
        source_index = bisect_right(boundaries, source_day)
        patch_ids = segment.get("patch_ids")
        hashes = segment.get("patch_records_sha256")
        anchors = segment.get("verified_snapshots")
        if segment.get("source") == "TUSHARE_SNAPSHOT":
            if source_index != target_index or patch_ids != [] or hashes != [] or not isinstance(anchors, list) or not anchors:
                raise DataContractError("Tushare membership segment has invalid patch or anchor provenance")
            for anchor in anchors:
                if (not isinstance(anchor, Mapping)
                        or bisect_right(boundaries, verify_snapshot(anchor.get("date"), anchor.get("sha256"))) != target_index):
                    raise DataContractError("Tushare membership anchor belongs to another event segment")
            if {"date": source_day.date().isoformat(), "sha256": segment["source_snapshot_sha256"]} not in anchors:
                raise DataContractError("Tushare segment source is absent from its verified anchors")
        elif segment.get("source") == "OFFICIAL_CHANGE_PATCH":
            if (not isinstance(patch_ids, list) or not patch_ids or any(not isinstance(item, str) for item in patch_ids)
                    or len(set(patch_ids)) != len(patch_ids) or anchors != [] or source_index == target_index):
                raise DataContractError("patched membership segment has invalid source identities")
            path = boundaries[min(source_index, target_index):max(source_index, target_index)]
            if source_index > target_index:
                path = path[::-1]
            expected_ids = []
            for boundary in path:
                boundary_patches = sorted((item for item in registry.values()
                                           if pd.Timestamp(item.first_session) == boundary), key=lambda item: item.patch_id)
                if not boundary_patches or {str(item.notice_id) for item in boundary_patches} != event_groups[boundary]:
                    raise DataContractError("patched membership source path lacks a complete official event")
                expected_ids.extend(item.patch_id for item in boundary_patches)
            if patch_ids != expected_ids or hashes != [registry[item].records_sha256 for item in expected_ids]:
                raise DataContractError("membership supplement identities differ from the verified event path")
            used_ids.update(patch_ids)
            patched_sessions += len(segment_days)
        else:
            raise DataContractError("daily membership segment has an unknown source kind")
        if any(_json_hash(part.ConstituentSymbol.tolist()) != segment.get("membership_sha256")
               for _, part in selected.groupby("Date", sort=True)):
            raise DataContractError("daily constituent set differs from its pinned reconstructed segment")
    if assigned != set(expected_sessions):
        raise DataContractError("daily membership has uncovered sessions")
    used_patches = [registry[item] for item in sorted(used_ids)]
    if (metadata.get("patched_session_count") != patched_sessions
            or metadata.get("official_patch_sources") != [_patch_source(item) for item in used_patches]):
        raise DataContractError("daily membership patch counts or source registry identity differ")
    expected_available = _available_at(catalog, metadata, used_patches)
    if (not available.eq(expected_available).all()
            or any(pd.Timestamp(segment["available_date"]) != expected_available for segment in segments)):
        raise DataContractError("daily membership availability differs from actual source capture times")
