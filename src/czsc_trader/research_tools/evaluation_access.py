"""Batch-owned account computation; persistence is an explicit evidence operation."""
from __future__ import annotations

from concurrent.futures import CancelledError, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from enum import Enum
from multiprocessing import get_context
from pathlib import Path
import pickle
import re

from dataflows import Dataflows
from threadpoolctl import threadpool_limits
from strategy_runtime import canonical_sha256

from .evaluation import (
    EvaluationRequest, EvaluationResult, _bind_evaluation_inputs,
    _evaluate_strategy, _evaluation_result_hash, _request_contract,
)
from ._evaluation_workers import PlatformEvaluator, compute, pack


@dataclass(frozen=True, slots=True)
class EvaluationResources:
    max_workers: int = 1
    native_threads_per_worker: int = 1
    random_seed: int = 0

    def __post_init__(self):
        for name in ("max_workers", "native_threads_per_worker"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.random_seed) is not int or self.random_seed < 0:
            raise ValueError("random_seed must be a nonnegative integer")


class EvaluationStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class EvaluationError:
    code: str
    message: str

    def __post_init__(self):
        if not isinstance(self.code, str) or not self.code.strip():
            raise ValueError("evaluation error requires a code")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("evaluation error requires a message")


@dataclass(frozen=True, slots=True)
class EvaluationOutcome:
    status: EvaluationStatus
    request_hash: str
    result: EvaluationResult | None = None
    error: EvaluationError | None = None

    def __post_init__(self):
        if not isinstance(self.status, EvaluationStatus):
            raise TypeError("outcome status must be EvaluationStatus")
        if not isinstance(self.request_hash, str) or re.fullmatch(r"[0-9a-f]{64}", self.request_hash) is None:
            raise ValueError("outcome requires a request identity")
        if self.status is EvaluationStatus.SUCCEEDED:
            if not isinstance(self.result, EvaluationResult) or self.error is not None:
                raise ValueError("successful outcome requires only a result")
            if self.result.request_hash != self.request_hash:
                raise ValueError("outcome and result request identities differ")
        elif self.result is not None or not isinstance(self.error, EvaluationError):
            raise ValueError("unsuccessful outcome requires only an error")


class EvaluationAccess:
    """Use one injected DFLS space for preparation and all account calculations."""

    def __init__(self, *, dataflows: Dataflows, resources: EvaluationResources | None = None,
                 strategy_id: str | None = None):
        if not isinstance(dataflows, Dataflows):
            raise TypeError("evaluation requires Dataflows")
        self.data = dataflows
        self.resources = resources if resources is not None else EvaluationResources()
        if not isinstance(self.resources, EvaluationResources):
            raise TypeError("evaluation requires EvaluationResources")
        self.strategy_id = strategy_id
        self._base_dir = dataflows.binding.base_dir
        self._batch_evaluator = PlatformEvaluator(
            self._base_dir, dataflows.binding.space,
        )

    def prepare(self, request: EvaluationRequest) -> EvaluationRequest:
        if not isinstance(request, EvaluationRequest):
            raise TypeError("evaluation requires EvaluationRequest")
        if Path(request.repository_root).resolve() != self._base_dir:
            raise ValueError("evaluation request repository differs from its context")
        if self.strategy_id is not None and request.strategy.strategy_family_id != self.strategy_id:
            raise ValueError("evaluation candidate belongs to another batch")
        if request.workers > self.resources.max_workers:
            raise ValueError("evaluation workers exceed EvaluationResources.max_workers")
        if request.execution_data is not None:
            prepared = request.execution_data.prepared
            if prepared is None or prepared.space_id != self.data.binding.space_id:
                raise ValueError("execution data belongs to another data space")
        if any(binding.prepared.space_id != self.data.binding.space_id
               for binding in request.input_bindings.values()):
            raise ValueError("input binding belongs to another data space")
        return _bind_evaluation_inputs(request, dataflows=self.data)

    def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        prepared = self.prepare(request)
        with threadpool_limits(limits=self.resources.native_threads_per_worker):
            return _evaluate_strategy(prepared, dataflows=self.data)

    @staticmethod
    def _outcome(request, calculate):
        contract, binding_hash = _request_contract(request)
        request_hash = canonical_sha256(contract)
        try:
            result = calculate()
            if not isinstance(result, EvaluationResult) or result.request_hash != request_hash:
                raise ValueError("evaluation result identity differs from request")
            if (result.strategy_identity, result.runtime_binding_hash, result.data_identity, result.execution_mode) != (
                request.strategy.runtime_identity_sha256, binding_hash,
                request.execution_data.fingerprint, request.execution_mode,
            ):
                raise ValueError("evaluation result metadata differs from request")
            expected = {(w.window_id, c.scenario_id) for w in request.windows for c in request.costs}
            coordinates = [(run.window_id, run.scenario_id) for run in result.runs]
            if len(coordinates) != len(expected) or set(coordinates) != expected or any(
                run.identity is None or run.identity.content_sha256 != contract["content_sha256"]
                or run.identity.candidate.strategy_id != request.strategy.strategy_family_id
                or run.identity.candidate.candidate_id != request.strategy.candidate_id
                or run.candidate_id != request.strategy.candidate_id
                for run in result.runs
            ):
                raise ValueError("evaluation coordinates or candidate identity differ")
            if _evaluation_result_hash(request_hash, result.runs) != result.result_hash:
                raise ValueError("evaluation result hash differs")
            return EvaluationOutcome(EvaluationStatus.SUCCEEDED, request_hash, result)
        except BaseException as exc:
            status = (EvaluationStatus.CANCELLED if isinstance(exc, (CancelledError, KeyboardInterrupt, SystemExit))
                      else EvaluationStatus.UNKNOWN if isinstance(exc, BrokenProcessPool)
                      else EvaluationStatus.FAILED)
            return EvaluationOutcome(status, request_hash, error=EvaluationError(
                type(exc).__name__, str(exc) or type(exc).__name__,
            ))

    def evaluate_many(self, requests: tuple[EvaluationRequest, ...]) -> tuple[EvaluationOutcome, ...]:
        if not isinstance(requests, tuple) or not requests:
            raise ValueError("evaluate_many requires a nonempty tuple")
        if not all(isinstance(item, EvaluationRequest) for item in requests):
            raise TypeError("evaluate_many requires EvaluationRequest values")
        if any(item.workers != 1 for item in requests):
            raise ValueError("batch requests require workers=1; configure EvaluationResources")
        # Contract errors reject the call. Data/preparation failures belong to their item.
        contracts = tuple(_request_contract(item, require_execution=False)[0] for item in requests)
        outcomes = [None] * len(requests)
        prepared = []
        def fail(error):
            raise error
        for index, (item, contract) in enumerate(zip(requests, contracts, strict=True)):
            try:
                prepared.append((index, self.prepare(item)))
            except Exception as exc:
                outcomes[index] = EvaluationOutcome(EvaluationStatus.FAILED,
                    canonical_sha256(contract), error=EvaluationError(type(exc).__name__, str(exc) or type(exc).__name__))
        if self.resources.max_workers == 1:
            with threadpool_limits(limits=self.resources.native_threads_per_worker):
                for index, item in prepared:
                    outcomes[index] = self._outcome(item, lambda item=item: self._batch_evaluator(item))
        elif prepared:
            # Validate private transport before starting workers; it is never loaded from evidence.
            payloads = tuple(pack((self._batch_evaluator, item, self.resources.native_threads_per_worker))
                             for _, item in prepared)
            with ProcessPoolExecutor(max_workers=min(len(prepared), self.resources.max_workers),
                                     mp_context=get_context("spawn")) as pool:
                pending = []
                for (index, item), payload in zip(prepared, payloads, strict=True):
                    try:
                        pending.append((index, item, pool.submit(compute, payload)))
                    except Exception as exc:
                        # Submission failed before this request could begin computation.
                        outcomes[index] = self._outcome(item, lambda exc=exc: fail(
                            CancelledError(f"evaluation not submitted: {exc}")))
                for index, item, future in pending:
                    outcomes[index] = self._outcome(item, lambda future=future: pickle.loads(future.result()))
        return tuple(outcomes)
