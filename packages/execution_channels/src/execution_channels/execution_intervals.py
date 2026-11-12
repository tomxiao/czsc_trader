"""Calendar-ordered execution intervals shared by historical and online hosts."""
from dataclasses import dataclass
from typing import Iterable, Iterator

from .instruments import TimeInterval


@dataclass(frozen=True, slots=True)
class ExecutionInterval:
    """One decision through the end of its market submission window."""

    window: TimeInterval
    previous_window: TimeInterval | None

    def __post_init__(self):
        if type(self.window) is not TimeInterval:
            raise TypeError('execution interval requires a typed submission window')
        previous = self.previous_window
        if previous is not None:
            if type(previous) is not TimeInterval:
                raise TypeError('previous execution requires a typed submission window')
            if previous.end > self.window.start:
                raise ValueError('execution windows must be ordered and disjoint')

    @property
    def start(self):
        return self.window.start if self.previous_window is None else self.previous_window.end

    @property
    def end(self):
        return self.window.end


def execution_intervals(windows: Iterable[TimeInterval]) -> Iterator[ExecutionInterval]:
    """Project calendar windows before filtering them by data or account readiness."""
    previous = None
    for window in windows:
        yield ExecutionInterval(window, previous)
        previous = window
