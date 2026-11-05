"""Interpret declared legacy local clocks and native aware leg intervals."""
from datetime import datetime, time
from zoneinfo import ZoneInfo


def planned_bounds(payload, valid_session, *, zone="Asia/Shanghai"):
    after, before = payload.get("submit_after"), payload.get("submit_before")
    if after is None and before is None:
        return None
    if after is None or before is None:
        raise ValueError("plan requires both submission bounds")
    dated = "-" in str(after)[:10]
    if dated != ("-" in str(before)[:10]):
        raise ValueError("plan bounds must use the same clock contract")
    if dated:
        start, end = (datetime.fromisoformat(str(value)) for value in (after, before))
        if start.utcoffset() is None or end.utcoffset() is None:
            raise ValueError("native plan bounds must be timezone aware")
    else:
        timezone = ZoneInfo(str(zone))
        day = datetime.fromisoformat(valid_session).date()
        start, end = (datetime.combine(day, time.fromisoformat(str(value)), timezone)
                      for value in (after, before))
    if start >= end:
        raise ValueError("plan submission window is empty")
    return start, end, dated


def within_planned_window(payload, valid_session, moment, *, zone="Asia/Shanghai"):
    bounds = planned_bounds(payload, valid_session, zone=zone)
    if bounds is None:
        return True
    start, end, dated = bounds
    return start <= moment < end if dated else start <= moment <= end
