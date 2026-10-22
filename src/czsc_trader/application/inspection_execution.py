"""Bounded worker orchestration and optional baseline comparison."""
from dataclasses import asdict, dataclass
import json
import multiprocessing
import time
from strategy_manager import canonical_sha256
from strategy_manager import freeze_contracts as f
from strategy_runtime.inspection import InspectionProgress, InspectionStage
from ..research_tools._evaluation_workers import pack


class Interrupted(Exception):
    def __init__(self, reason, message, *, quiescent=True):
        self.reason = reason
        self.quiescent = quiescent
        super().__init__(message)


@dataclass(frozen=True)
class EquivalenceOutcome:
    completed: tuple
    interruption: Interrupted | None


class Controller:
    def __init__(self, run_id, control, workspace):
        self.run_id, self.control, self.workspace = run_id, control, workspace
        self.started = time.monotonic()
        self.stage = InspectionStage.PREPARE
        self.last_progress = 0

    def tick(self, completed=0, total=None, message="inspection running", force=False):
        elapsed = time.monotonic() - self.started
        if self.control.cancelled:
            try:
                cancelled = self.control.cancelled()
                if type(cancelled) is not bool:
                    raise TypeError("cancelled callback must return bool")
            except Exception as exc:
                raise Interrupted(f.InspectionReason.EXECUTION_ERROR, f"cancelled callback failed: {exc}") from exc
            if cancelled:
                raise Interrupted(f.InspectionReason.CANCELLED, "inspection cancelled")
        if self.control.timeout_seconds is not None and elapsed >= self.control.timeout_seconds:
            raise Interrupted(f.InspectionReason.RESOURCE_LIMIT, "inspection total deadline exceeded")
        self.progress(completed, total, message, force)

    def progress(self, completed=0, total=None, message="inspection running", force=False):
        elapsed = time.monotonic() - self.started
        if force or elapsed - self.last_progress >= 10:
            progress = InspectionProgress(self.run_id, self.stage, completed, total, elapsed, message)
            with (self.workspace / "progress.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(asdict(progress), ensure_ascii=False) + "\n")
            self.last_progress = elapsed
            if self.control.on_progress:
                try:
                    self.control.on_progress(progress)
                except Exception as exc:
                    raise Interrupted(f.InspectionReason.EXECUTION_ERROR, f"progress callback failed: {exc}") from exc

    def remaining(self):
        self.tick()
        return None if self.control.timeout_seconds is None else max(.001, self.control.timeout_seconds - (time.monotonic() - self.started))


def equivalence_jobs(request, candidate, verified, workspace, controller):
    from .inspection_replay import compute
    ctx = multiprocessing.get_context("spawn")
    pending = list(enumerate(request.replays))
    active, results = {}, {}
    interruption = None
    try:
        while pending or active:
            controller.tick(len(results), len(request.replays), "candidate/frozen replay")
            while pending and len(active) < controller.control.max_workers:
                index, replay = pending.pop(0)
                receive, send = ctx.Pipe(duplex=False)
                binding = request.research.data.binding
                payload = pack((binding.base_dir, binding.space, candidate, verified, replay,
                                workspace / "candidate" / str(index), request.protocol.float_tolerance))
                process = ctx.Process(target=compute, args=(send, payload))
                process.start()
                send.close()
                active[index] = process, receive
            for index, (process, receive) in tuple(active.items()):
                if receive.poll(.05):
                    try:
                        results[index] = receive.recv()
                    except EOFError:
                        results[index] = (False, {"type": "WorkerExited", "message": str(process.exitcode)})
                    process.join(5)
                    if process.is_alive():
                        _stop_worker(process)
                    receive.close()
                    del active[index]
                elif not process.is_alive():
                    results[index] = (False, {"type": "WorkerExited", "message": str(process.exitcode)})
                    process.join()
                    receive.close()
                    del active[index]
    except Exception as exc:
        interruption = exc if isinstance(exc, Interrupted) else Interrupted(f.InspectionReason.EXECUTION_ERROR, str(exc))
    finally:
        for index, (process, receive) in active.items():
            try:
                _stop_worker(process)
            except Interrupted as exc:
                interruption = exc
            else:
                # A result can become ready between the last poll and cancellation.
                # Read only after all writers on this pipe have stopped.
                try:
                    if index not in results and receive.poll():
                        results[index] = receive.recv()
                except (EOFError, OSError):
                    pass  # Interrupted writes are not completed calculation facts.
            receive.close()
    return EquivalenceOutcome(tuple((index, *results[index]) for index in sorted(results)), interruption)


def _stop_worker(process):
    if process.is_alive():
        process.terminate()
    process.join(5)
    if process.is_alive():
        process.kill()
        process.join(5)
    if process.is_alive():
        raise Interrupted(f.InspectionReason.RESOURCE_LIMIT, "worker could not be stopped", quiescent=False)


def compare_baseline(context, replay, candidate_evidence, registration, tolerance, store):
    from .inspection_replay import technical_ledger_differences
    from .inspection_inputs import portable_value, portable_binding_dict
    from strategy_evaluator import ReplayEvidence, compare_ledgers, LedgerComparisonRequest, LedgerComparisonMode, LedgerComparisonStatus
    from ..research_tools.evaluation import validate_evaluation_evidence
    if replay.baseline is None:
        return {"status": "NOT_REQUESTED"}, ()
    value = json.loads(replay.baseline.evidence.resolve(context.root).read_text(encoding="utf-8"))
    validate_evaluation_evidence(value)
    matches = [x for x in value["runs"] if (x["window_id"], x["scenario_id"]) ==
               (replay.coordinate.window_id, replay.coordinate.scenario_id)
               and (not replay.baseline.evaluation_ids or canonical_sha256(x["identity"]) in replay.baseline.evaluation_ids)]
    if len(matches) != 1:
        raise ValueError("baseline must identify exactly one matching coordinate")
    run = matches[0]
    if (run["identity"]["candidate"] != registration.key.to_dict()
            or run["identity"]["content_sha256"] != registration.content_sha256
            or portable_value(value["input_bindings"][replay.coordinate.window_id]) != portable_binding_dict(replay.input_binding)):
        raise ValueError("baseline candidate or input binding differs")
    left = ReplayEvidence.from_dict(run["replay_evidence"])
    right = ReplayEvidence.from_dict(candidate_evidence)
    for name in ("initial_cash", "execution_spec", "data_hash", "evaluation_sessions"):
        if getattr(left, name) != getattr(right, name):
            raise ValueError(f"baseline {name} differs from technical replay")
    compared = compare_ledgers(LedgerComparisonRequest(left, right, LedgerComparisonMode.ECONOMIC, tolerance))
    source = store.put_json(value)
    differences = technical_ledger_differences(left.to_dict(), right.to_dict(), tolerance)
    return {"status": "PASS" if compared.status is LedgerComparisonStatus.EQUIVALENT and not differences else "FAIL",
            "comparison": compared.to_dict(), "differences": differences}, (source,)


def goal(cases):
    if not cases:
        return f.InspectionGoalResult(f.InspectionStatus.NOT_RUN, (), ())
    status = (f.InspectionStatus.FAIL if any(x.status is f.InspectionStatus.FAIL for x in cases)
              else f.InspectionStatus.PASS if cases and all(x.status is f.InspectionStatus.PASS for x in cases)
              else f.InspectionStatus.INCOMPLETE)
    return f.InspectionGoalResult(status, tuple(cases), tuple(dict.fromkeys(ref for case in cases for ref in case.evidence)))
