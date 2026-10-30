"""Batch-owned account computation; persistence is an explicit evidence operation."""
from __future__ import annotations

from concurrent.futures import CancelledError
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, replace
from enum import Enum
from contextlib import closing
from pathlib import Path
import pickle
import re
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .equity_replay import PreparedAccountEvaluation

from dataflows import Dataflows
from strategy_runtime import canonical_sha256
from strategy_runtime.resources import ExecutionResources
from strategy_runtime.equity import ResearchExecutionSpec
from .equity_evaluation import (EquityEvaluationRequest, EquityEvaluationResult)

from .evaluation import (
    EvaluationRequest, EvaluationResult, _bind_evaluation_inputs,
    _evaluation_result_hash, _request_contract,
)
from ._evaluation_workers import PlatformEvaluator, compute, pack
from .execution import ResearchExecutionSession, ExecutionPhase, ExecutionProgress


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
    result: EvaluationResult | EquityEvaluationResult | None = None
    error: EvaluationError | None = None

    def __post_init__(self):
        if not isinstance(self.status, EvaluationStatus):
            raise TypeError("outcome status must be EvaluationStatus")
        if not isinstance(self.request_hash, str) or re.fullmatch(r"[0-9a-f]{64}", self.request_hash) is None:
            raise ValueError("outcome requires a request identity")
        if self.status is EvaluationStatus.SUCCEEDED:
            if not isinstance(self.result, (EvaluationResult, EquityEvaluationResult)) or self.error is not None:
                raise ValueError("successful outcome requires only a result")
            if self.result.request_hash != self.request_hash:
                raise ValueError("outcome and result request identities differ")
        elif self.result is not None or not isinstance(self.error, EvaluationError):
            raise ValueError("unsuccessful outcome requires only an error")


class EvaluationAccess:
    """Use one injected DFLS space for preparation and all account calculations."""

    def __init__(self, *, dataflows: Dataflows, resources: ExecutionResources | None = None,
                 strategy_id: str | None = None, execution_spec: ResearchExecutionSpec | None = None):
        if not isinstance(dataflows, Dataflows):
            raise TypeError("evaluation requires Dataflows")
        self.data = dataflows
        self.resources = resources if resources is not None else ExecutionResources()
        if type(self.resources) is not ExecutionResources:
            raise TypeError("evaluation requires ExecutionResources")
        self._context = None
        self.strategy_id = strategy_id
        if execution_spec is not None and type(execution_spec) is not ResearchExecutionSpec:
            raise TypeError("execution_spec requires ResearchExecutionSpec")
        self.execution_spec = execution_spec
        self._session_lock = Lock()
        self._active_execution = None
        self._base_dir = dataflows.binding.base_dir
        self._batch_evaluator = PlatformEvaluator(
            self._base_dir, dataflows.binding.space,
        )

    def prepare(self, request: EvaluationRequest | EquityEvaluationRequest, *,
                execution: ResearchExecutionSession | None = None) -> PreparedAccountEvaluation:
        if type(request) is EquityEvaluationRequest:
            if request.candidate.definition.contract_version == 4:
                from .equity_replay import prepare_equity
                return prepare_equity(self, request, execution=execution)
            raise TypeError("new equity replay requires contract_version=4 and an explicit ResearchExecutionSession")
        from .account_preparation import prepare_account
        return prepare_account(self, request, execution)

    def _bind_inputs(self, request):
        if self.execution_spec is not None:
            raise ValueError("explicit equity context requires EquityEvaluationRequest")
        if not isinstance(request, EvaluationRequest):
            raise TypeError("evaluation requires EvaluationRequest")
        if Path(request.repository_root).resolve() != self._base_dir:
            raise ValueError("evaluation request repository differs from its context")
        if self.strategy_id is not None and request.strategy.strategy_family_id != self.strategy_id:
            raise ValueError("evaluation candidate belongs to another batch")
        if request.execution_data is not None:
            prepared = request.execution_data.prepared
            if prepared is None or prepared.space_id != self.data.binding.space_id:
                raise ValueError("execution data belongs to another data space")
        if any(binding.prepared.space_id != self.data.binding.space_id
               for binding in request.input_bindings.values()):
            raise ValueError("input binding belongs to another data space")
        prepared = _bind_evaluation_inputs(request, dataflows=self.data)
        return prepared

    def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        if type(request) is EquityEvaluationRequest:
            raise TypeError("equity replay requires prepare(..., execution=session) and evaluate_many with session-owned V4 handles")
        from .context import ExperimentRef
        from .execution import ResearchExecutionSession
        if self._active_execution is not None:
            raise RuntimeError("use evaluate_many with the active execution session")
        context = self._context
        if context is None:
            raise TypeError("single evaluation requires a batch ResearchContext")
        with ResearchExecutionSession(context, experiment=ExperimentRef(self.strategy_id, request.experiment_id)) as execution:
            prepared = self.prepare(request, execution=execution)
            outcome, = self.evaluate_many((prepared,), execution=execution)
            if outcome.result is None:
                raise RuntimeError(outcome.error.message)
            return outcome.result

    @staticmethod
    def _outcome(request, calculate, *, contract=None):
        if contract is None:
            contract, binding_hash = _request_contract(request)
        else:
            binding_hash = contract["runtime_binding_hash"]
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

    def evaluate_many(self, requests: tuple[PreparedAccountEvaluation, ...], *,
                      execution: ResearchExecutionSession | None = None) -> tuple[EvaluationOutcome, ...]:
        if not isinstance(requests, tuple) or not requests:
            raise ValueError("evaluate_many requires a nonempty tuple")
        from .equity_replay import PreparedAccountEvaluation, evaluate_many_equity
        from .account_preparation import require_account
        if not all(type(item) is PreparedAccountEvaluation for item in requests):
            raise TypeError('evaluate_many requires explicitly prepared session-owned account handles')
        originals = tuple(require_account(self, item, execution) for item in requests)
        account_handles = requests
        if all(type(item) is EquityEvaluationRequest for item in originals):
            return evaluate_many_equity(self, requests, execution=execution)
        if not all(type(item) is EvaluationRequest for item in originals):
            raise TypeError('one account batch cannot mix execution contracts')
        contracts = tuple(item.identity(self.execution_spec) for item in account_handles)
        requests = originals
        outcomes = [None] * len(requests)
        def fail(error):
            raise error

        executor = execution.executor
        checkpoint = execution.checkpoint
        prepared_by_index = {}

        def tasks():
            for index, (item, contract) in enumerate(zip(requests, contracts, strict=True)):
                prepared = item
                request_hash = canonical_sha256(contract)
                if checkpoint is not None:
                    restored = checkpoint.load_result(prepared, request_hash, contract=contract)
                    if restored is not None:
                        outcomes[index] = self._outcome(prepared, lambda: restored, contract=contract)
                        if outcomes[index].status is not EvaluationStatus.SUCCEEDED:
                            raise ValueError("restored checkpoint does not match the prepared request")
                        executor.reused_results += 1
                        continue
                try:
                    evaluator = self._batch_evaluator
                    if type(evaluator) is PlatformEvaluator:
                        from .account_preparation import account_benchmark_seeds
                        evaluator = replace(evaluator, benchmark_seeds=account_benchmark_seeds(
                            execution, account_handles[index], request=prepared),
                                            contract_content=account_handles[index].contract_content)
                    payload = pack((evaluator, prepared, self.resources.native_threads_per_worker))
                except Exception as exc:
                    outcomes[index] = self._outcome(prepared, lambda exc=exc: fail(exc), contract=contract)
                    continue
                prepared_by_index[index] = prepared
                yield index, (payload,)

        if execution is not None:
            with closing(executor.run(compute, tasks(), phase=ExecutionPhase.COMPUTE,
                                      total=len(requests))) as completed:
                for index, value, error in completed:
                    item = prepared_by_index.pop(index)
                    outcome = self._outcome(item, lambda: fail(error) if error is not None else pickle.loads(value), contract=contracts[index])
                    if checkpoint is not None and outcome.status is EvaluationStatus.SUCCEEDED:
                        checkpoint.save_result(outcome.request_hash, outcome.result)
                    outcomes[index] = outcome
            if executor.on_progress is not None:
                executor.notify(ExecutionProgress(
                    ExecutionPhase.COMPUTE, len(outcomes), len(outcomes),
                    sum(x.status in (EvaluationStatus.FAILED, EvaluationStatus.CANCELLED) for x in outcomes),
                    sum(x.status is EvaluationStatus.UNKNOWN for x in outcomes), executor.stats.elapsed_seconds))
        return tuple(outcomes)
