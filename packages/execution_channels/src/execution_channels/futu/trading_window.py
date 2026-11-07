"""Explicit scheduled intervals and the existing CN automatic-order window."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo



SHANGHAI = ZoneInfo("Asia/Shanghai")


def shanghai_now() -> datetime:
    return datetime.now(SHANGHAI)


def is_submission_window(moment: datetime) -> bool:
    if moment.tzinfo is None:
        raise ValueError("submission clock must be timezone-aware")
    clock = moment.astimezone(SHANGHAI).time().replace(tzinfo=None)
    morning = time(9, 30) <= clock <= time(11, 30)
    afternoon = time(13, 0) <= clock < time(14, 57)
    return morning or afternoon
