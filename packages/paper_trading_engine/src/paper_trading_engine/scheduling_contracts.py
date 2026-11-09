"""Calendar-resolved scheduling facts owned by the PTE host."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from dataflows import TimeInterval

DAILY_CLOSE_DELAY = timedelta(hours=5)


@dataclass(frozen=True, slots=True)
class ScheduledDecision:
    """One calendar-resolved decision; its provider owns market/session selection."""

    task_id: str
    interval: TimeInterval
    decision_at: datetime
    next_decision_at: datetime | None = None

    def __post_init__(self) -> None:
        if type(self.task_id) is not str or not self.task_id.strip():
            raise ValueError("scheduled decision requires a non-empty task identity")
        if type(self.interval) is not TimeInterval:
            raise TypeError("scheduled decision requires a typed calendar interval")
        if type(self.decision_at) is not datetime or self.decision_at.utcoffset() is None:
            raise ValueError("scheduled decision requires a timezone-aware decision time")
        if self.decision_at > self.interval.start:
            raise ValueError("scheduled decision cannot follow its submission start")
        if self.next_decision_at is not None and (
            type(self.next_decision_at) is not datetime or self.next_decision_at.utcoffset() is None
            or self.next_decision_at < self.interval.end
        ):
            raise ValueError("next decision must follow the current submission window")

    @property
    def validity(self) -> TimeInterval:
        return TimeInterval(self.decision_at, self.next_decision_at or self.interval.end)

    def cycle_record(self) -> dict[str, object]:
        return {"cycle_id": self.task_id, "validity": {
            "start": self.validity.start.isoformat(), "end": self.validity.end.isoformat(),
        }}

    @property
    def submit_after(self) -> datetime:
        return self.interval.start

    @property
    def submit_before(self) -> datetime:
        return self.interval.end
