"""Pure, retrospective membership reconstruction from pinned source frames.

The caller certifies announcement coverage and the complete trading calendar.
This module neither downloads data nor infers that missing announcements mean
no changes. ObservedAt values are interpreted as UTC when no zone is supplied.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, replace
from hashlib import sha256
import json
import re
from typing import Any

import pandas as pd

from ._index_change_patch import _IndexChangePatch
from .errors import DataContractError, IncompleteDataError


_SYMBOL = re.compile(r"\d{6}\.(?:SH|SZ)\Z")


@dataclass(frozen=True)
class _State:
    members: frozenset[str]
    snapshot_date: pd.Timestamp
    snapshot_hash: str
    available: pd.Timestamp
    patch_ids: tuple[str, ...] = ()
    patch_hashes: tuple[str, ...] = ()


def _day(value: Any, field: str) -> pd.Timestamp:
    try:
        result = pd.Timestamp(value)
    except (ValueError, TypeError) as exc:
        raise DataContractError(f"invalid membership {field}") from exc
    if pd.isna(result) or result.tzinfo is not None or result != result.normalize():
        raise DataContractError(f"membership {field} must be a timezone-free calendar date")
    return result


def _observed(value: Any) -> pd.Timestamp:
    try:
        result = pd.to_datetime(value, utc=True)
    except (ValueError, TypeError) as exc:
        raise DataContractError("invalid membership source observation time") from exc
    if not isinstance(result, pd.Timestamp) or pd.isna(result):
        raise DataContractError("missing membership source observation time")
    return result.tz_convert("Asia/Shanghai").tz_localize(None)


def _symbols(values: Any, expected: int | None = None) -> frozenset[str]:
    sequence = list(values)
    if any(not isinstance(item, str) or _SYMBOL.fullmatch(item) is None for item in sequence):
        raise DataContractError("membership contains an invalid constituent symbol")
    result = frozenset(sequence)
    if len(result) != len(sequence) or (expected is not None and len(result) != expected):
        raise DataContractError("membership contains duplicates or an unexpected constituent count")
    return result


def reconstruct_membership(
    snapshots: pd.DataFrame,
    events: pd.DataFrame,
    sessions: pd.DatetimeIndex,
    patches: tuple[_IndexChangePatch, ...],
    *,
    expected_members: int = 500,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Reconstruct trading-session membership; unavailable segments fail closed.

    Every event starts a new segment. Snapshots anchor segments, never adjacent
    segments. Only explicit official deltas may bridge an unanchored segment.
    Future snapshots are usable as retrospective facts, not historical access.
    """
    if type(expected_members) is not int or expected_members <= 0:
        raise DataContractError("expected_members must be a positive integer")
    required_snapshots = {"Date", "ConstituentSymbol", "ObservedAt", "SnapshotSha256"}
    required_events = {"Date", "AnnouncementDate", "ObservedAt", "NoticeId"}
    if not required_snapshots.issubset(snapshots.columns):
        raise DataContractError("membership snapshots are missing required columns")
    if not required_events.issubset(events.columns):
        raise DataContractError("membership events are missing required columns")
    if not isinstance(sessions, pd.DatetimeIndex):
        raise DataContractError("membership sessions must be a DatetimeIndex")
    if (sessions.tz is not None or sessions.hasnans or not sessions.is_unique
            or not sessions.is_monotonic_increasing or not sessions.equals(sessions.normalize())):
        raise DataContractError("membership sessions must be sorted unique calendar dates")

    # Several genuine notices may share a first session. Preserve all identities
    # without creating zero-length segments or discarding conflicting revisions.
    event_groups: dict[pd.Timestamp, dict[str, Any]] = {}
    identities: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    for row in events.to_dict("records"):
        day = _day(row["Date"], "event Date")
        announcement = _day(row["AnnouncementDate"], "AnnouncementDate")
        if announcement > day:
            raise DataContractError("announcement date is later than the effective session")
        if pd.isna(row["NoticeId"]) or not str(row["NoticeId"]).strip():
            raise DataContractError("membership event is missing NoticeId")
        notice_id = str(row["NoticeId"])
        identity = (day, announcement)
        if notice_id in identities and identities[notice_id] != identity:
            raise DataContractError("membership notice has conflicting effective dates", notice_id=notice_id)
        identities[notice_id] = identity
        observed = _observed(row["ObservedAt"])
        group = event_groups.setdefault(day, {"notice_ids": set(), "observed": observed})
        group["notice_ids"].add(notice_id)
        group["observed"] = max(group["observed"], observed)
    boundaries = sorted(event_groups)

    def segment(day: pd.Timestamp) -> int:
        return bisect_right(boundaries, day)

    def boundary_context(index: int) -> dict[str, Any]:
        lower = boundaries[index - 1] if index else None
        upper = boundaries[index] if index < len(boundaries) else None
        notices = sorted({notice for day in (lower, upper) if day is not None
                          for notice in event_groups[day]["notice_ids"]})
        return {
            "segment_start": None if lower is None else lower.date().isoformat(),
            "segment_end_exclusive": None if upper is None else upper.date().isoformat(),
            "notice_ids": notices,
        }

    def boundary_availability(index: int, available: pd.Timestamp) -> pd.Timestamp:
        days = boundaries[max(index - 1, 0):min(index + 1, len(boundaries))]
        return max([available, *(event_groups[day]["observed"] for day in days)])

    grouped: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    for row in snapshots.to_dict("records"):
        grouped.setdefault(_day(row["Date"], "snapshot Date"), []).append(row)
    states: dict[int, _State] = {}
    anchored: set[int] = set()
    all_anchors: dict[int, list[dict[str, str]]] = {}
    for day, rows in sorted(grouped.items()):
        members = _symbols((row["ConstituentSymbol"] for row in rows), expected_members)
        times = {_observed(row["ObservedAt"]) for row in rows}
        hashes = {row["SnapshotSha256"] for row in rows}
        if (len(times) != 1 or len(hashes) != 1
                or any(not isinstance(item, str) or re.fullmatch(r"[0-9a-f]{64}", item) is None
                       for item in hashes)):
            raise DataContractError("one snapshot has conflicting source identities")
        index = segment(day)
        if index in states and states[index].members != members:
            raise IncompleteDataError("constituents changed without an identified effective event",
                                      **boundary_context(index))
        snapshot_hash = next(iter(hashes))
        all_anchors.setdefault(index, []).append({"date": day.date().isoformat(), "sha256": snapshot_hash})
        if index not in states:  # Earliest snapshot is the deterministic anchor.
            states[index] = _State(members, day, snapshot_hash,
                                   boundary_availability(index, next(iter(times))))
            anchored.add(index)
        else:
            # All reconciled snapshots are evidence dependencies, including a
            # later observation of the same unchanged historical membership.
            states[index] = replace(states[index], available=max(states[index].available, next(iter(times))))

    edges: dict[int, list[tuple[_IndexChangePatch, frozenset[str], frozenset[str]]]] = {}
    patch_identities: set[str] = set()
    for patch in patches:
        if not isinstance(patch, _IndexChangePatch):
            raise DataContractError("membership supplements must be typed verified patches")
        if patch.patch_id in patch_identities:
            raise DataContractError("duplicate membership supplement identity")
        patch_identities.add(patch.patch_id)
        day = _day(patch.first_session, "patch first session")
        if day not in event_groups or str(patch.notice_id) not in event_groups[day]["notice_ids"]:
            raise DataContractError("membership supplement has no matching effective event",
                                    patch_id=patch.patch_id)
        payload = json.dumps({"added": patch.added, "removed": patch.removed},
                             ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if sha256(payload).hexdigest() != patch.records_sha256:
            raise DataContractError("membership supplement differs from its pinned records hash")
        added = _symbols(symbol for symbol, _ in patch.added)
        removed = _symbols(symbol for symbol, _ in patch.removed)
        if (type(patch.replacement_count) is not int or patch.replacement_count <= 0
                or not added or added & removed or len(added) != len(removed)
                or len(added) != patch.replacement_count):
            raise DataContractError("membership supplement has invalid replacement sets")
        edges.setdefault(boundaries.index(day) + 1, []).append((patch, added, removed))

    # A same-session patch can reconstruct the boundary only if it covers every
    # notice for that session. A partial delta must not stand in for other events.
    for edge, items in list(edges.items()):
        day = boundaries[edge - 1]
        if {str(item[0].notice_id) for item in items} != event_groups[day]["notice_ids"]:
            del edges[edge]
            continue
        touched: set[str] = set()
        for _, added, removed in items:
            if touched & (added | removed):
                raise DataContractError("same-session membership supplements overlap",
                                        **boundary_context(edge))
            touched.update(added | removed)
        items.sort(key=lambda item: item[0].patch_id)

    def cross(state: _State, edge: int, forward: bool) -> _State:
        members = set(state.members)
        available = state.available
        ids, hashes = list(state.patch_ids), list(state.patch_hashes)
        for patch, added, removed in edges[edge]:
            subtract, include = (removed, added) if forward else (added, removed)
            if not subtract.issubset(members) or members & include:
                raise IncompleteDataError("official supplement conflicts with a source membership anchor",
                                          patch_id=patch.patch_id, **boundary_context(edge))
            members.difference_update(subtract)
            members.update(include)
            if len(members) != expected_members:
                raise DataContractError("supplement reconstruction has an unexpected constituent count")
            available = max(available, _observed(patch.observed_at_utc))
            ids.append(patch.patch_id)
            hashes.append(patch.records_sha256)
        target = edge if forward else edge - 1
        available = boundary_availability(target, available)
        return _State(frozenset(members), state.snapshot_date, state.snapshot_hash,
                      available, tuple(ids), tuple(hashes))

    # Fill gaps from either direction, preserving the full dependency path. Never
    # replace an anchored Tushare segment with an official supplement result.
    progress = True
    while progress:
        progress = False
        for edge in sorted(edges):
            left, right = edge - 1, edge
            if left in states and right not in states:
                states[right] = cross(states[left], edge, True)
                progress = True
            elif right in states and left not in states:
                states[left] = cross(states[right], edge, False)
                progress = True

    # Reconcile every known anchor reached by a reconstructed chain. Direct
    # snapshot-to-snapshot intervals never require a patch for publication.
    for edge in sorted(edges):
        left, right = edge - 1, edge
        if left in states and right in states and (left not in anchored or right not in anchored):
            if cross(states[left], edge, True).members != states[right].members:
                raise IncompleteDataError("supplement chain disagrees with a known source anchor",
                                          **boundary_context(right))

    requested: dict[int, list[pd.Timestamp]] = {}
    for day in sessions:
        requested.setdefault(segment(day), []).append(day)
    for index, days in requested.items():
        if index not in states:
            raise IncompleteDataError(
                "membership segment has neither a snapshot nor a complete official supplement chain",
                missing_session_start=days[0].date().isoformat(),
                missing_session_end=days[-1].date().isoformat(), **boundary_context(index),
            )

    rows: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    patched_sessions = 0
    for index, days in sorted(requested.items()):
        state = states[index]
        is_patch = index not in anchored
        patched_sessions += len(days) if is_patch else 0
        segments.append({
            **boundary_context(index),
            "session_start": days[0].date().isoformat(),
            "session_end": days[-1].date().isoformat(),
            "session_count": len(days),
            "source": "OFFICIAL_CHANGE_PATCH" if is_patch else "TUSHARE_SNAPSHOT",
            "source_snapshot_date": state.snapshot_date.date().isoformat(),
            "source_snapshot_sha256": state.snapshot_hash,
            "verified_snapshots": all_anchors.get(index, []),
            "patch_ids": list(state.patch_ids),
            "patch_records_sha256": list(state.patch_hashes),
            "available_date": state.available.isoformat(),
        })
        for day in days:
            rows.extend({"Date": day, "ConstituentSymbol": symbol,
                         "AvailableDate": state.available,
                         "SourceSnapshotDate": state.snapshot_date}
                        for symbol in sorted(state.members))
    frame = pd.DataFrame(rows, columns=["Date", "ConstituentSymbol", "AvailableDate", "SourceSnapshotDate"])
    for column in ("Date", "AvailableDate", "SourceSnapshotDate"):
        frame[column] = pd.to_datetime(frame[column])
    frame = frame.sort_values(["Date", "ConstituentSymbol"]).reset_index(drop=True)
    used_patch_ids = {patch_id for item in segments for patch_id in item["patch_ids"]}
    return frame, {
        "reconstruction_segments": segments,
        "effective_event_sources": [
            {"first_session": day.date().isoformat(),
             "notice_ids": sorted(event_groups[day]["notice_ids"]),
             "observed_at_shanghai": event_groups[day]["observed"].isoformat()}
            for day in boundaries
        ],
        "official_patch_sources": [
            {"patch_id": patch.patch_id, "patch_version": patch.version,
             "notice_id": str(patch.notice_id), "first_session": patch.first_session,
             "records_sha256": patch.records_sha256,
             "notice_sha256": patch.notice_sha256,
             "attachment_sha256": patch.attachment_sha256,
             "boundary_kind": patch.boundary_kind,
             "effective_date_source_url": patch.effective_date_source_url,
             "effective_date_source_sha256": patch.effective_date_source_sha256,
             "observed_at_utc": patch.observed_at_utc}
            for patch in sorted(patches, key=lambda item: item.patch_id)
            if patch.patch_id in used_patch_ids
        ],
        "patched_session_count": patched_sessions,
        "verified_session_count": len(sessions),
        "expected_constituents": expected_members,
        "historical_publication_time_verified": False,
        "historical_revision_history_verified": False,
        "availability_rule": "maximum observation time of dependent snapshots, notices and official patches",
        "reconstruction_kind": "RETROSPECTIVE_MEMBERSHIP_FACTS",
    }
