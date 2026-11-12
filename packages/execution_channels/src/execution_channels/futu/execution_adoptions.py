"""Stable storage coordinates for equity execution windows."""
from datetime import datetime

from ..instruments import TimeInterval


def adoption_window(payload):
    raw = payload.get('equity_execution_interval')
    if raw is None:
        return '', ''
    interval = TimeInterval(datetime.fromisoformat(raw['start']), datetime.fromisoformat(raw['end']))
    return interval.start.isoformat(timespec='microseconds'), interval.end.isoformat(timespec='microseconds')
