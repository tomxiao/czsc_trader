"""Explicit equity computation on the shared bounded execution/session machinery."""
from concurrent.futures import CancelledError
from concurrent.futures.process import BrokenProcessPool
from contextlib import closing, nullcontext
import json
from types import SimpleNamespace

from dataflows import Dataflows, ProviderConfig
from strategy_runtime.equity import equity_hash

from ._execution_session import ExecutionExecutor
from .execution import ExecutionPhase, ResearchExecutionSession
from .equity_evaluation import EquityEvaluationResult, evaluate_equity, validate_equity_result


def compute_equity(binding, specification, request):
    """Workers can only read parent-pinned assets, never acquire or publish."""
    flows = Dataflows(base_dir=binding.base_dir, space=binding.space, providers=ProviderConfig(bindings={}))
    access = SimpleNamespace(data=flows, execution_spec=specification, strategy_id=request.experiment.strategy_id)
    request.candidate.verify()
    return evaluate_equity(access, request)


def evaluate_many_equity(access, requests, *, execution):
    from .evaluation_access import EvaluationOutcome, EvaluationStatus, EvaluationError
    if execution is None and access._active_execution is not None:
        raise RuntimeError("pass the active execution session explicitly")
    if execution is not None:
        if type(execution) is not ResearchExecutionSession:
            raise TypeError("execution requires ResearchExecutionSession")
        for request in requests:
            execution.require(access, request.experiment.experiment_id)
    executor = ExecutionExecutor(access.resources) if execution is None else execution.executor
    checkpoint = None if execution is None else execution.checkpoint
    outcomes, prepared_requests = [None] * len(requests), {}

    def outcome(request, result=None, error=None):
        identity = equity_hash(request.identity(access.execution_spec))
        if error is None:
            try:
                validate_equity_result(access, request, result)
                return EvaluationOutcome(EvaluationStatus.SUCCEEDED, identity, result)
            except Exception as exc:
                error = exc
        status = (EvaluationStatus.CANCELLED if isinstance(error, (CancelledError, KeyboardInterrupt, SystemExit))
                  else EvaluationStatus.UNKNOWN if isinstance(error, BrokenProcessPool) else EvaluationStatus.FAILED)
        return EvaluationOutcome(status, identity, error=EvaluationError(type(error).__name__, str(error) or type(error).__name__))

    def tasks():
        for index, request in enumerate(requests):
            try:
                with executor.measure(ExecutionPhase.PREPARE):
                    prepared = access.prepare(request)
            except Exception as exc:
                outcomes[index] = outcome(request, error=exc)
                continue
            request_hash = equity_hash(prepared.identity(access.execution_spec))
            if checkpoint is not None:
                cached = checkpoint.load_equity_result(prepared, request_hash)
                if cached is not None:
                    restored = outcome(prepared, cached)
                    if restored.status is not EvaluationStatus.SUCCEEDED:
                        raise ValueError("restored equity checkpoint failed authentication")
                    outcomes[index] = restored
                    executor.reused_results += 1
                    continue
            prepared_requests[index] = prepared
            yield index, (access.data.binding, access.execution_spec, prepared)

    with (nullcontext(executor) if execution is not None else executor):
        with closing(executor.run(compute_equity, tasks(), phase=ExecutionPhase.COMPUTE, total=len(requests))) as completed:
            for index, result, error in completed:
                prepared = prepared_requests.pop(index)
                value = outcome(prepared, result, error)
                if checkpoint is not None and value.status is EvaluationStatus.SUCCEEDED:
                    checkpoint.save_equity_result(value.request_hash, value.result)
                outcomes[index] = value
    return tuple(outcomes)


def encode_result(result):
    if type(result) is not EquityEvaluationResult or result.payload.get("schema") != "equity-research/v2":
        raise TypeError("equity checkpoint requires formal v2 result")
    return {"kind": "equity-research/v2", "request_hash": result.request_hash,
            "result_hash": result.result_hash, "content": result.content.decode("utf-8")}


def decode_result(payload, request_hash):
    if type(payload) is not dict or set(payload) != {"kind", "request_hash", "result_hash", "content"}:
        raise ValueError("equity checkpoint fields differ")
    if payload["kind"] != "equity-research/v2" or payload["request_hash"] != request_hash:
        raise ValueError("equity checkpoint identity differs")
    result = EquityEvaluationResult(request_hash, payload["content"].encode("utf-8"))
    if result.result_hash != payload["result_hash"]:
        raise ValueError("equity checkpoint bytes differ")
    json.loads(result.content)
    return result
