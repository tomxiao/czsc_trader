"""One bounded spawn pool shared by computation and evidence serialization."""
from collections import defaultdict
from concurrent.futures import CancelledError, ProcessPoolExecutor, wait, FIRST_COMPLETED
from concurrent.futures.process import BrokenProcessPool
from contextlib import contextmanager
from multiprocessing import get_context
import os
from time import perf_counter

from strategy_runtime.resources import ExecutionResources
from threadpoolctl import threadpool_limits

from ._cpu_affinity import bind_worker, replay_resources
from .execution import ExecutionProgress, ExecutionStats


_worker_binding_error = None


def _initialize_replay_worker(slots, pids, claim_lock):
    global _worker_binding_error
    with claim_lock:
        index = next(i for i, pid in enumerate(pids) if pid == 0)
        pids[index] = -1
    cpu = slots[index]
    try:
        bind_worker(cpu)
    except (OSError, RuntimeError) as exc:
        # Surface the actual setup failure via the normal task outcome channel.
        _worker_binding_error = f"cannot bind V4 replay worker to logical CPU {cpu}: {exc}"
    else:
        pids[index] = os.getpid()


def _timed_task(operation, args, native_threads):
    if _worker_binding_error is not None:
        raise RuntimeError(_worker_binding_error)
    start = perf_counter()
    with threadpool_limits(limits=native_threads):
        value = operation(*args)
    return value, perf_counter() - start


def implementation_identity():
    """Bind resumed computation to installed implementation bytes and versions."""
    import hashlib
    import importlib
    import platform
    from pathlib import Path
    from strategy_runtime import canonical_sha256
    packages = {}
    for name in ("czsc_trader", "strategy_runtime", "strategy_evaluator", "execution_channels", "dataflows",
                 "strategy_manager"):
        module = importlib.import_module(name)
        root = Path(module.__file__).parent
        packages[name] = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(root.rglob("*.py"))}
    import numpy
    import pandas
    return canonical_sha256({"python": platform.python_version(), "numpy": numpy.__version__,
                             "pandas": pandas.__version__, "sources": packages})


class ExecutionExecutor:
    def __init__(self, resources, *, on_progress=None):
        if resources is not None and type(resources) is not ExecutionResources:
            raise TypeError("execution requires ExecutionResources")
        self.resources = resources if resources is not None else ExecutionResources()
        self.requested_resources = resources
        self._replay_configured = False
        self._cpu_slots = ()
        self._worker_pids = ()
        self.peak_in_flight = 0
        self.on_progress = on_progress
        self.pool = None
        self.broken = False
        self.closed = False
        self.busy = False
        self.started = perf_counter()
        self.finished = None
        self.pool_starts = self.submitted = self.completed = self.failed = self.unknown = 0
        self.reused_results = self.reused_publications = 0
        self.wall = defaultdict(float)
        self.worker = defaultdict(float)
        self.account_inputs = None

    def __enter__(self):
        return self

    def configure_replay(self):
        """Resolve the replay budget once, only when a session has accounts to run."""
        if not self._replay_configured:
            self.resources, self._cpu_slots = replay_resources(self.requested_resources)
            self._replay_configured = True
        return bool(self._cpu_slots)

    def _start_pool(self):
        context = get_context("spawn")
        options = {}
        if self._cpu_slots:
            # Claiming requires a lock. Reading PID telemetry must remain safe
            # after cancellation, even if a worker died holding that lock.
            self._worker_pids = context.RawArray("q", len(self._cpu_slots))
            options = {"initializer": _initialize_replay_worker,
                       "initargs": (self._cpu_slots, self._worker_pids, context.Lock())}
        self.pool = ProcessPoolExecutor(max_workers=self.resources.max_workers, mp_context=context, **options)
        self.pool_starts += 1

    def __exit__(self, *exc):
        try:
            if exc and exc[0] is not None:
                self._abort_pool()
            if self.pool is not None:
                self.pool.shutdown(wait=True, cancel_futures=True)
        finally:
            if self.account_inputs is not None:
                self.account_inputs.close()
            self.closed = True
            self.finished = perf_counter()

    def _abort_pool(self):
        """Python 3.12 has no public terminate_workers; bound cancellation locally."""
        if self.pool is None:
            return
        self.broken = True
        processes = tuple((self.pool._processes or {}).values())
        for process in processes:
            if process.is_alive():
                process.terminate()
        for process in processes:
            process.join()

    @contextmanager
    def measure(self, phase):
        start = perf_counter()
        try:
            yield
        finally:
            self.wall[phase.value] += perf_counter() - start

    def notify(self, progress):
        if self.on_progress is not None:
            was_busy = self.busy
            self.busy = True
            try:
                self.on_progress(progress)
            finally:
                self.busy = was_busy

    @property
    def stats(self):
        bindings = tuple((pid, cpu) for pid, cpu in zip(self._worker_pids, self._cpu_slots) if pid > 0)
        return ExecutionStats(
            (self.finished or perf_counter()) - self.started, self.pool_starts,
            self.submitted, self.completed, self.failed, self.unknown,
            self.reused_results, self.reused_publications,
            tuple(sorted(self.wall.items())), tuple(sorted(self.worker.items())),
            self.resources.max_workers, self.resources.native_threads_per_worker, self.peak_in_flight, bindings,
        )

    def run(self, operation, tasks, *, phase, total):
        """Yield (key, result, error) as each task finishes; keep submission bounded."""
        if self.closed or self.busy:
            raise RuntimeError("executor is closed or already running an operation")
        if self.broken:
            raise BrokenProcessPool("execution session is broken; explicit new session required")
        self.busy = True
        started = perf_counter()
        completed = failed = unknown = 0
        fully_consumed = False
        pending = {}

        def outcome(key, value=None, error=None):
            nonlocal completed, failed, unknown
            completed += 1
            self.completed += 1
            if isinstance(error, BrokenProcessPool):
                self.broken = True
                unknown += 1
                self.unknown += 1
            elif error is not None:
                failed += 1
                self.failed += 1
            self.notify(ExecutionProgress(phase, completed, total, failed, unknown,
                                           perf_counter() - started))
            return key, value, error

        iterator = iter(tasks)
        try:
            if (not self._cpu_slots or total == 0) and min(total, self.resources.max_workers) <= 1 and self.pool is None:
                for key, args in iterator:
                    self.submitted += 1
                    self.peak_in_flight = max(self.peak_in_flight, 1)
                    try:
                        value, seconds = _timed_task(operation, args, self.resources.native_threads_per_worker)
                        self.worker[phase.value] += seconds
                    except BaseException as exc:
                        yield outcome(key, error=exc)
                    else:
                        yield outcome(key, value)
                fully_consumed = True
                return
            exhausted = False
            while pending or not exhausted:
                while not exhausted and not self.broken and len(pending) < self.resources.max_workers:
                    try:
                        key, args = next(iterator)
                    except StopIteration:
                        exhausted = True
                        break
                    try:
                        if self.pool is None:
                            self._start_pool()
                        future = self.pool.submit(_timed_task, operation, args,
                                                  self.resources.native_threads_per_worker)
                    except BaseException as exc:
                        if isinstance(exc, BrokenProcessPool):
                            self.broken = True
                        yield outcome(key, error=CancelledError(f"task was not submitted: {exc}"))
                    else:
                        self.submitted += 1
                        pending[future] = key
                        self.peak_in_flight = max(self.peak_in_flight, len(pending))
                if self.broken and not exhausted:
                    for key, _ in iterator:
                        yield outcome(key, error=CancelledError("task was not submitted: broken process pool"))
                    exhausted = True
                if not pending:
                    continue
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    key = pending.pop(future)
                    try:
                        value, seconds = future.result()
                        self.worker[phase.value] += seconds
                    except BaseException as exc:
                        yield outcome(key, error=exc)
                    else:
                        yield outcome(key, value)
            fully_consumed = True
        finally:
            if not fully_consumed:
                self.broken = True
                for future in pending:
                    future.cancel()
                self._abort_pool()
            self.wall[phase.value] += perf_counter() - started
            self.busy = False
