"""Calendar-resolved scheduling facts owned by the PTE host."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from dataflows import TimeInterval
from execution_channels.execution_intervals import ExecutionInterval

DAILY_CLOSE_DELAY = timedelta(hours=5)


@dataclass(frozen=True, slots=True)
class ScheduledDecision:
    """One calendar-resolved decision; its provider owns market/session selection."""

    task_id: str
    interval: TimeInterval
    decision_at: datetime
    next_decision_at: datetime | None = None
    execution_interval: ExecutionInterval | None = None
    use_execution_interval: bool = False

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

        if self.execution_interval is not None and (
            type(self.execution_interval) is not ExecutionInterval
            or (self.execution_interval.window.start, self.execution_interval.window.end)
                != (self.interval.start, self.interval.end)
            or self.decision_at < self.execution_interval.start
        ):
            raise ValueError("scheduled decision differs from its execution interval")
        if type(self.use_execution_interval) is not bool:
            raise TypeError("execution interval scheduling requires a boolean")
        if self.use_execution_interval and self.execution_interval is None:
            raise ValueError("interval scheduling requires its calendar identity")

    @property
    def validity(self) -> TimeInterval:
        end = self.interval.end if self.use_execution_interval else (self.next_decision_at or self.interval.end)
        return TimeInterval(self.decision_at, end)

    def cycle_record(self) -> dict[str, object]:
        return {"cycle_id": self.task_id, "validity": {
            "start": (self.execution_interval.start if self.use_execution_interval else self.validity.start).isoformat(),
            "end": self.validity.end.isoformat(),
        }}

    @property
    def submit_after(self) -> datetime:
        return self.interval.start

    @property
    def submit_before(self) -> datetime:
        return self.interval.end
