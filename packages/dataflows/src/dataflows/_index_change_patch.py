"""Typed source identity for one independently verified official event."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _IndexChangePatch:
    patch_id: str
    version: int
    symbol: str
    notice_id: int
    notice_url: str
    notice_sha256: str
    attachment_url: str
    attachment_sha256: str
    calendar_url: str | None
    calendar_sha256: str | None
    observed_at_utc: str
    announcement_date: str
    effective_after_close: str | None
    first_session: str
    added: tuple[tuple[str, str], ...]
    removed: tuple[tuple[str, str], ...]
    records_sha256: str
    replacement_count: int = 50
    boundary_kind: str = "AFTER_CLOSE_STATED"
