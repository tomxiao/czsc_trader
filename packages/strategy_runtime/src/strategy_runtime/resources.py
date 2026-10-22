"""Host execution budgets shared by research and isolated technical inspection."""
from dataclasses import dataclass, field
import os


def default_worker_count() -> int:
    """Use seventy percent of local logical CPUs, rounded down, with a minimum of one."""
    count = os.cpu_count()
    if type(count) is not int or count < 1:
        raise RuntimeError("cannot determine local logical CPU count; specify max_workers explicitly")
    return max(1, count * 70 // 100)


@dataclass(frozen=True, slots=True)
class ExecutionResources:
    """An execution-session budget, never an economic strategy parameter."""

    max_workers: int = field(default_factory=default_worker_count)
    native_threads_per_worker: int = 1
    random_seed: int = 0

    def __post_init__(self):
        for name in ("max_workers", "native_threads_per_worker"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.random_seed) is not int or self.random_seed < 0:
            raise ValueError("random_seed must be a nonnegative integer")
