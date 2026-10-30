"""Explicit, bounded research execution and resumable local computation."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
import re
from typing import Callable, Literal
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


@dataclass(frozen=True, slots=True)
class EquityAccountTiming:
    """Cumulative successful replay work for one full account owner identity.

    replay_seconds includes feature_seconds. Both are worker elapsed seconds,
    not end-to-end wall time, and exclude subsequent independent certification.
    Repeated executions of the same owner are added rather than overwritten.
    """
    kind: Literal["CANDIDATE", "BENCHMARK"]
    owner: str
    feature_seconds: float
    replay_seconds: float
    rows: int
    decisions: int

    def __post_init__(self):
        if type(self.kind) is not str or self.kind not in {"CANDIDATE", "BENCHMARK"}:
            raise ValueError("equity account timing requires a candidate or benchmark kind")
        if type(self.owner) is not str or not self.owner.startswith(self.kind.lower() + ":") or not self.owner.split(":", 1)[1]:
            raise ValueError("equity account timing owner differs from its kind")
        if any(type(value) not in (int, float) or not isfinite(value) or value < 0
               for value in (self.feature_seconds, self.replay_seconds)):
            raise ValueError("equity replay timings must be finite nonnegative seconds")
        if self.feature_seconds > self.replay_seconds:
            raise ValueError("feature time cannot exceed the inclusive replay time")
        if any(type(value) is not int or value < 0 for value in (self.rows, self.decisions)) or self.decisions > self.rows:
            raise ValueError("equity replay counters must be nonnegative and consistent")


@dataclass(frozen=True, slots=True)
class EquityExecutionStatistics:
    """Detached V3 session statistics, including completed but rejected accounts.

    Run counts include only replays that returned successfully, even when their
    subsequent certification failed. Restored results do not count as replays.
    Authentication counters describe exact ledger audits and their reuse within
    this session; they are not a serialized certification authority.
    """
    input_snapshots: int
    candidate_runs: int
    benchmark_runs: int
    authenticated_accounts: int
    reused_authentications: int
    account_timings: tuple[EquityAccountTiming, ...]

    def __post_init__(self):
        counts = (self.input_snapshots, self.candidate_runs, self.benchmark_runs,
                  self.authenticated_accounts, self.reused_authentications)
        if any(type(value) is not int or value < 0 for value in counts):
            raise ValueError("equity execution counters must be nonnegative integers")
        if type(self.account_timings) is not tuple or any(type(item) is not EquityAccountTiming for item in self.account_timings):
            raise TypeError("equity execution timings require an immutable typed tuple")
        owners = [(item.kind, item.owner) for item in self.account_timings]
        if len(set(owners)) != len(owners):
            raise ValueError("equity execution timing owners must be unique")
        for kind, count in (("CANDIDATE", self.candidate_runs), ("BENCHMARK", self.benchmark_runs)):
            if sum(item.kind == kind for item in self.account_timings) > count:
                raise ValueError("equity timing owners exceed completed replay count")


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

    @property
    def equity_statistics(self) -> EquityExecutionStatistics | None:
        """A frozen statistics snapshot; None means this session has no V3 work."""
        state = getattr(self, "_equity_v3", None)
        if state is None:
            return None
        timings = tuple(EquityAccountTiming(kind, owner, item.feature_seconds, item.replay_seconds,
                                           item.rows, item.decisions)
                        for (kind, owner), item in sorted(state.replay_statistics.items()))
        return EquityExecutionStatistics(len(state.products), state.candidate_runs, state.benchmark_runs,
            state.certification.audit_count, state.certification.reused_count, timings)


ProgressCallback = Callable[[ExecutionProgress], None]
