"""Explicit, bounded research execution and resumable local computation."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
import re
from typing import Callable
from .context import ResearchContext, ExperimentRef


class CheckpointMode(StrEnum):
    CREATE = "CREATE"
    RESUME = "RESUME"


@dataclass(frozen=True, slots=True)
class ExecutionCheckpointRequest:
    run_id: str
    mode: CheckpointMode = CheckpointMode.CREATE

    def __post_init__(self):
        if type(self.run_id) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", self.run_id) is None:
            raise ValueError("checkpoint run_id must be a safe identifier")
        if type(self.mode) is not CheckpointMode:
            raise TypeError("checkpoint mode requires CheckpointMode")


class ExecutionPhase(StrEnum):
    PREPARE = "PREPARE"
    COMPUTE = "COMPUTE"
    SERIALIZE = "SERIALIZE"
    PUBLISH = "PUBLISH"
    AUTHENTICATE = "AUTHENTICATE"
    RECOMPUTE = "RECOMPUTE"
    VERIFY = "VERIFY"


@dataclass(frozen=True, slots=True)
class ExecutionProgress:
    phase: ExecutionPhase
    completed: int
    total: int
    failed: int
    unknown: int
    elapsed_seconds: float

    def __post_init__(self):
        if type(self.phase) is not ExecutionPhase:
            raise TypeError("execution phase requires ExecutionPhase")
        if any(type(x) is not int or x < 0 for x in (self.completed, self.total, self.failed, self.unknown)):
            raise ValueError("progress counters must be nonnegative integers")
        if self.completed > self.total or self.failed + self.unknown > self.completed:
            raise ValueError("progress counters are inconsistent")
        if type(self.elapsed_seconds) not in (int, float) or not isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise ValueError("elapsed seconds must be nonnegative and finite")


@dataclass(frozen=True, slots=True)
class ExecutionStats:
    elapsed_seconds: float
    pool_starts: int
    submitted: int
    completed: int
    failed: int
    unknown: int
    reused_results: int
    reused_publications: int
    phase_wall_seconds: tuple[tuple[str, float], ...]
    worker_seconds: tuple[tuple[str, float], ...]

    def __post_init__(self):
        for name in ("pool_starts", "submitted", "completed", "failed", "unknown",
                     "reused_results", "reused_publications"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError("execution counters must be nonnegative integers")
        if self.failed + self.unknown > self.completed:
            raise ValueError("execution outcome counters are inconsistent")
        if type(self.elapsed_seconds) not in (float, int) or not isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise ValueError("execution elapsed seconds must be finite and nonnegative")
        for items in (self.phase_wall_seconds, self.worker_seconds):
            if type(items) is not tuple:
                raise TypeError("phase timings must be immutable tuples")
            seen = set()
            for item in items:
                if type(item) is not tuple or len(item) != 2:
                    raise TypeError("phase timing requires a name and seconds")
                name, seconds = item
                if type(name) is not str or name not in ExecutionPhase.__members__ or name in seen:
                    raise ValueError("phase timing identity is invalid or duplicated")
                if type(seconds) not in (float, int) or not isfinite(seconds) or seconds < 0:
                    raise ValueError("phase seconds must be finite and nonnegative")
                seen.add(name)


class ResearchExecutionSession:
    """A caller-owned context manager; it never implicitly retries failed work."""

    def __init__(self, context: ResearchContext, *, experiment: ExperimentRef,
                 checkpoint: ExecutionCheckpointRequest | None = None,
                 on_progress: Callable[[ExecutionProgress], None] | None = None):
        from ._execution_session import ExecutionExecutor

        if type(context) is not ResearchContext or type(experiment) is not ExperimentRef:
            raise TypeError("execution requires ResearchContext and ExperimentRef")
        if experiment.strategy_id != context.strategy_id:
            raise ValueError("execution experiment belongs to another batch")
        if checkpoint is not None and type(checkpoint) is not ExecutionCheckpointRequest:
            raise TypeError("checkpoint requires ExecutionCheckpointRequest")
        if on_progress is not None and not callable(on_progress):
            raise TypeError("on_progress must be callable")
        self.context = context
        self.experiment = experiment
        self.checkpoint_request = checkpoint
        self.executor = ExecutionExecutor(context.evaluation.resources, on_progress=on_progress)
        self.checkpoint = None
        self._active = False
        self._entered = False
        self._owns_lock = False

    def __enter__(self):
        import json
        if self._entered:
            raise RuntimeError("execution session cannot be reopened")
        path = self.experiment.resolve(self.context.repository.root) / "experiment.json"
        from .context import ExperimentRef
        if ExperimentRef.from_dict(json.loads(path.read_bytes())) != self.experiment:
            raise ValueError("execution requires the allocated experiment identity")
        access = self.context.evaluation
        if not access._session_lock.acquire(blocking=False):
            raise RuntimeError("research context already has an active execution session")
        self._owns_lock = True
        try:
            if self.checkpoint_request is not None:
                from ._execution_checkpoint import CheckpointStore
                from ._execution_session import implementation_identity
                self.checkpoint = CheckpointStore(
                    self.context.repository.root, self.experiment,
                    self.checkpoint_request.run_id, self.checkpoint_request.mode.value,
                    implementation_identity(),
                )
        except BaseException:
            access._session_lock.release()
            self._owns_lock = False
            raise
        self._entered = self._active = True
        access._active_execution = self
        self.executor.__enter__()
        return self

    def __exit__(self, *exc):
        try:
            return self.executor.__exit__(*exc)
        finally:
            self._active = False
            try:
                if self.checkpoint is not None:
                    self.checkpoint.close()
            finally:
                if self._owns_lock:
                    self.context.evaluation._active_execution = None
                    self.context.evaluation._session_lock.release()
                    self._owns_lock = False

    def require(self, access, experiment_id=None):
        if not self._active:
            raise RuntimeError("execution session must be used inside its context manager")
        if self.executor.broken:
            from concurrent.futures.process import BrokenProcessPool
            raise BrokenProcessPool("execution session is broken; explicit new session required")
        if self.executor.busy:
            raise RuntimeError("execution session already has an active operation")
        if self.context.evaluation is not access:
            raise ValueError("execution session belongs to another research context")
        if access.resources != self.executor.resources:
            raise ValueError("execution resources changed during the session")
        if experiment_id is not None and experiment_id != self.experiment.experiment_id:
            raise ValueError("execution request belongs to another experiment")

    @property
    def stats(self) -> ExecutionStats:
        return self.executor.stats


ProgressCallback = Callable[[ExecutionProgress], None]
