"""TDR adapters for executing REX contracts through public platform APIs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ProcessPoolExecutor, CancelledError
from concurrent.futures.process import BrokenProcessPool
from contextlib import contextmanager
from multiprocessing import get_context
import os
import pickle
from threading import Lock
from dataclasses import replace
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ..backtesting import _dataflows

from dataflows import (
    DataRequest, DataResult, Dataflows, DataSpace, PreparePolicy, PrepareResult,
    PreparedDataRef, ProviderConfig,
)
from research_experiment import (
    ExperimentCapability,
    ExperimentDataScope,
    EvaluationRecord,
    EvaluationOutcome,
    EvaluationAttemptStatus,
    ExperimentContext,
    ExperimentDefinition,
    ExperimentInput,
    ExperimentMode,
    ExperimentReceipt,
    ExperimentResources,
    ExperimentResult,
    ExperimentTrace,
    ExperimentWorkspace,
    LoadedExperiment,
    experiment_result_sha256,
    experiment_source_sha256,
)
from strategy_runtime import (
    StrategyInit,
    StrategyRuntime,
    StrategyCandidate,
    StrategyRelease,
    RuntimeDefinition,
    StrategyInstance,
    ImplementationDependency,
    canonical_sha256,
)
from threadpoolctl import threadpool_limits

from ..temp_workspace import create_temporary_directory
from .evaluation import (
    EvaluationRequest,
    EvaluationResult,
    evaluate_strategy,
    _prepare_evaluation_inputs,
    _bind_evaluation_inputs,
    _request_contract,
    _evaluation_result_hash,
)
from ._evaluation_records import _CallEvidence, EvaluationExecutionError
from .preflight import preflight_experiment
from ._evaluation_workers import pack, compute, PlatformEvaluator


class _UnobservedEvaluation(RuntimeError):
    """A batch stopped before the parent could authenticate this computation."""


def _freeze_trace_json(value: Any, field_name: str) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                _trace_key(key, field_name): _freeze_trace_json(item, field_name)
                for key, item in value.items()
            }
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_trace_json(item, field_name) for item in value)
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError(f"{field_name} must contain only finite JSON values")


def _trace_key(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} keys must be non-empty strings")
    return value.strip()


class _TraceRecorder:
    def __init__(self, scope: ExperimentDataScope) -> None:
        self.scope = scope
        self.capabilities: list[ExperimentCapability] = []
        self.operations: list[str] = []
        self.data_requests: list[Mapping[str, Any]] = []
        self.evaluations: list[EvaluationRecord] = []

    def record_capability(self, capability: ExperimentCapability) -> None:
        if capability not in self.capabilities:
            self.capabilities.append(capability)

    def record_operation(self, operation: str) -> None:
        self.operations.append(operation)

    def record_data_request(self, request: Mapping[str, Any]) -> None:
        self.data_requests.append(_freeze_trace_json(request, "data request trace"))

    def record_evaluation(self, evidence: EvaluationRecord) -> None:
        for index, item in enumerate(self.evaluations):
            if item.attempt_id == evidence.attempt_id:
                if item.status is not EvaluationAttemptStatus.STARTED:
                    raise ValueError("terminal attempt cannot be replaced")
                self.evaluations[index] = evidence
                return
        self.evaluations.append(evidence)

    def snapshot(self) -> ExperimentTrace:
        return ExperimentTrace(
            capabilities=tuple(self.capabilities),
            operations=tuple(self.operations),
            data_requests=tuple(self.data_requests),
            evaluations=tuple(self.evaluations),
            data_scope=self.scope,
        )


class _ExperimentDataAccess:
    """Record DFLS operations without interpreting research authorization."""

    def __init__(
        self,
        dataflows: Dataflows,
        recorder: _TraceRecorder,
        *,
        real_returns: bool,
        sealed_validation: bool,
    ) -> None:
        self._dataflows = dataflows
        self._recorder = recorder
        self._real_returns = real_returns
        self._sealed_validation = sealed_validation

    def _record_access(self, request: DataRequest) -> None:
        if not isinstance(request, DataRequest):
            raise TypeError("data access requires a DataRequest")
        for enabled, capability in (
            (self._real_returns, ExperimentCapability.READ_REAL_RETURNS),
            (self._sealed_validation, ExperimentCapability.READ_SEALED_VALIDATION),
        ):
            if enabled:
                self._recorder.record_capability(capability)

    def prepare(self, requests: tuple[DataRequest, ...], *, policy: PreparePolicy) -> PrepareResult:
        if not isinstance(requests, tuple) or not requests:
            raise TypeError("data prepare requires a non-empty tuple of DataRequest")
        for request in requests:
            self._record_access(request)
        result = self._dataflows.prepare(requests, policy=policy)
        self._recorder.record_operation("data.prepare")
        for item in result.items:
            self._record(item.request, item, result.reference, "prepare")
        return result

    def fetch(self, request: DataRequest, *, prepared: PreparedDataRef) -> DataResult:
        self._record_access(request)
        result = self._dataflows.fetch(request, prepared=prepared)
        self._recorder.record_operation("data.fetch")
        self._record(request, result, prepared, "fetch")
        return result

    def _record(self, request, result, prepared, operation):
        identity = None
        if result.identity is not None:
            temporal = result.identity.temporal_contract
            identity = {
                "dataset": result.identity.dataset,
                "source": result.identity.source,
                "symbol": result.identity.symbol,
                "data_start": result.identity.data_start,
                "data_cutoff": result.identity.data_cutoff,
                "content_sha256": result.identity.content_sha256,
                "temporal_contract": {
                    "source_time_field": temporal.source_time_field,
                    "availability_time_field": temporal.availability_time_field,
                    "source_calendar": temporal.source_calendar,
                    "available_at": temporal.available_at,
                    "request_range_policy": temporal.request_range_policy.value,
                },
            }
        self._recorder.record_data_request(
            {
                "operation": operation,
                "dataset": request.dataset,
                "symbol": request.symbol,
                "start": request.start,
                "end": request.end,
                "required_cutoff": request.required_cutoff,
                "frequency": request.frequency,
                "coverage": None
                if request.coverage is None
                else {
                    "maximum_start_lag_days": request.coverage.maximum_start_lag_days,
                    "minimum_observations": request.coverage.minimum_observations,
                    "minimum_sessions": request.coverage.minimum_sessions,
                },
                "prepared": None if prepared is None else {
                    "space_id": str(prepared.space_id),
                    "preparation_id": str(prepared.preparation_id),
                    "manifest_sha256": prepared.manifest_sha256,
                },
                "status": result.status.value,
                "identity": identity,
            }
        )


class _ExperimentRuntimeAccess:
    """Tracked adapter over the public SRT runtime surface."""

    def __init__(
        self, runtime: StrategyRuntime, recorder: _TraceRecorder
    ) -> None:
        self._runtime = runtime
        self._recorder = recorder

    def describe(
        self,
        source: StrategyRelease | StrategyCandidate,
        *,
        symbol: str | None = None,
        source_root: Path | None = None,
        runtime_binding: Mapping[str, object] | None = None,
    ) -> RuntimeDefinition:
        result = self._runtime.describe(
            source,
            symbol=symbol,
            source_root=source_root,
            runtime_binding=runtime_binding,
        )
        self._recorder.record_operation("runtime.describe")
        return result

    def create(self, request: StrategyInit) -> StrategyInstance:
        if not isinstance(request, StrategyInit):
            raise TypeError("runtime create requires a StrategyInit")
        result = self._runtime.create(request)
        self._recorder.record_operation("runtime.create")
        return result


class _ExperimentEvaluationAccess:
    """One-call contract validation and evidence; research owns search control."""

    def __init__(
        self,
        definition,
        evaluator,
        recorder,
        resources,
        workspace,
        *,
        repository_root,
        real_returns,
        sealed_validation,
        batch_evaluator=None,
        input_preparer=None,
    ):
        self._definition = definition
        self._repository_root = Path(repository_root).resolve()
        self._evaluator = evaluator
        self._batch_evaluator = batch_evaluator if batch_evaluator is not None else evaluator
        self._input_preparer = input_preparer
        self._recorder = recorder
        self._resources = resources
        self._workspace = workspace
        self._real_returns = real_returns
        self._sealed_validation = sealed_validation
        self._artifacts = []
        self._candidates = {}
        self._owner_pid = os.getpid()
        self._call_lock = Lock()

    @contextmanager
    def _call(self):
        if os.getpid() != self._owner_pid:
            raise RuntimeError("experiment evaluation context belongs to another process")
        if not self._call_lock.acquire(blocking=False):
            raise RuntimeError("experiment evaluation call is already active")
        try:
            if any(self._workspace.path(name).exists() for name in (
                "execution_receipt.json", "execution_envelope.json", "execution_failure.json",
            )):
                raise RuntimeError("experiment execution is already complete")
            yield
        finally:
            self._call_lock.release()

    def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        with self._call():
            prepared = self._prepare(request)
            return self._complete(prepared, self._start(prepared), lambda: self._evaluator(prepared[0]))

    def evaluate_many(
        self, requests: tuple[EvaluationRequest, ...]
    ) -> tuple[EvaluationOutcome[EvaluationResult], ...]:
        """Compute a caller-selected batch; record each attempt in the owning process."""
        with self._call():
            if not isinstance(requests, tuple) or not requests:
                raise ValueError("evaluate_many requires a non-empty tuple of requests")
            if not all(isinstance(item, EvaluationRequest) for item in requests):
                raise TypeError("evaluate_many requires EvaluationRequest values")
            if any(item.workers != 1 for item in requests):
                raise ValueError("batch requests require workers=1; use ExperimentResources.max_workers")
            previous = dict(self._candidates)
            try:
                prepared = tuple(self._prepare(item) for item in requests)
                # Validate transport before publishing STARTED or running any computation.
                payloads = tuple(pack((self._batch_evaluator, item[0], self._resources.native_threads_per_worker))
                                 for item in prepared)
            except BaseException:
                self._candidates = previous
                raise
            attempts = []
            outcomes = []
            def failed(error):
                raise error
            with ProcessPoolExecutor(
                max_workers=min(len(requests), self._resources.max_workers),
                mp_context=get_context("spawn"),
            ) as pool:
                futures = []
                try:
                    for item, payload in zip(prepared, payloads):
                        attempts.append(self._start(item))
                        futures.append(pool.submit(compute, payload))
                    for item, attempt, future in zip(prepared, attempts, futures):
                        try:
                            result = self._complete(item, attempt, lambda: pickle.loads(future.result()))
                        except EvaluationExecutionError as exc:
                            if exc.error_code == "EVIDENCE_WRITE_FAILED":
                                raise
                            result = None
                        record = next(x for x in self._recorder.evaluations if x.attempt_id == attempt[1].attempt_id)
                        outcomes.append(EvaluationOutcome(record, result))
                except BaseException:
                    for future in futures:
                        future.cancel()
                    # Every published STARTED record must have a terminal state even if
                    # submission, transport, cancellation or evidence publication fails.
                    for index, (item, attempt) in enumerate(zip(prepared, attempts)):
                        current = next(x for x in self._recorder.evaluations if x.attempt_id == attempt[1].attempt_id)
                        if current.status is EvaluationAttemptStatus.STARTED:
                            interrupted = (
                                CancelledError("batch item cancelled before computation")
                                if index < len(futures) and futures[index].cancelled()
                                else _UnobservedEvaluation("batch stopped before result authentication")
                            )
                            try:
                                self._complete(item, attempt, lambda error=interrupted: failed(error))
                            except (EvaluationExecutionError, KeyboardInterrupt, SystemExit):
                                pass
                    raise
            return tuple(outcomes)

    def _prepare(self, request):
        if not isinstance(request, EvaluationRequest):
            raise TypeError("evaluation requires an EvaluationRequest")
        if Path(request.repository_root).resolve() != self._repository_root:
            raise ValueError("evaluation request repository differs from its context")
        if request.experiment_id != self._definition.experiment_id:
            raise ValueError("evaluation request belongs to another experiment")
        if request.strategy.strategy_family_id != self._definition.strategy_id:
            raise ValueError("evaluation candidate belongs to another strategy family")
        if request.workers > self._resources.max_workers:
            raise PermissionError("evaluation workers exceed the per-call execution configuration")
        for enabled, capability in (
            (self._real_returns, ExperimentCapability.READ_REAL_RETURNS),
            (self._sealed_validation, ExperimentCapability.READ_SEALED_VALIDATION),
        ):
            if enabled:
                self._recorder.record_capability(capability)
        dependencies = tuple(
            ImplementationDependency(item.name, item.version)
            for item in self._definition.dependencies
        )
        if request.dependencies and tuple(sorted(request.dependencies)) != tuple(
            sorted(dependencies)
        ):
            raise ValueError("evaluation dependencies differ from experiment declaration")
        request = replace(request, dependencies=dependencies)
        contract, binding_hash = _request_contract(request, require_execution=False)
        key = request.strategy.reference_id
        content = contract["content_sha256"]
        if key in self._candidates and self._candidates[key] != content:
            raise ValueError("candidate key already binds different content in this experiment")
        self._candidates[key] = content
        if request.lineage:
            relation = request.lineage.derivation
            if (
                relation.child.strategy_id,
                relation.child.candidate_id,
                relation.child_content_sha256,
            ) != (request.strategy.strategy_family_id, request.strategy.candidate_id, content):
                raise ValueError("evaluation lineage child differs from actual candidate")
            parent = EvaluationRecord.from_dict(
                json.loads(
                    relation.evidence.resolve(request.repository_root).read_text(encoding="utf-8")
                )
            )
            if (
                parent.status is not EvaluationAttemptStatus.SUCCEEDED
                or parent.candidate_id
                != f"{relation.parent.strategy_id}-{relation.parent.candidate_id}"
                or parent.content_sha256 != relation.parent_content_sha256
            ):
                raise ValueError("lineage evidence does not identify the successful parent")
        if self._input_preparer is not None:
            request = self._input_preparer(request)
            contract, binding_hash = _request_contract(request)
        return request, contract, binding_hash

    def _start(self, prepared):
        request, contract, binding_hash = prepared
        request_hash = canonical_sha256(contract)
        key = request.strategy.reference_id
        content = contract["content_sha256"]
        attempt = uuid4().hex
        evidence = _CallEvidence(self._workspace, attempt)
        started = datetime.now(timezone.utc).isoformat()
        clock = perf_counter()
        record = EvaluationRecord(
            attempt,
            request.experiment_id,
            key,
            content,
            request_hash,
            EvaluationAttemptStatus.STARTED,
            started,
            len(request.windows) * len(request.costs),
        )
        try:
            self._artifacts.append(evidence.record(record))
        except OSError as exc:
            raise EvaluationExecutionError(
                str(exc), attempt_id=attempt, error_code="EVIDENCE_WRITE_FAILED"
            ) from exc
        self._recorder.record_evaluation(record)
        self._recorder.record_operation("evaluation.evaluate")
        return evidence, record, clock

    def _complete(self, prepared, attempt, calculate):
        request, contract, binding_hash = prepared
        dependencies = request.dependencies
        content = contract["content_sha256"]
        evidence, record, clock = attempt
        request_hash = record.request_hash
        attempt = record.attempt_id
        completed_count = None
        evaluation_ids = ()
        writing_evidence = False
        try:
            with threadpool_limits(limits=self._resources.native_threads_per_worker):
                result = calculate()
            if not isinstance(result, EvaluationResult):
                raise TypeError("evaluation returned an invalid result")
            expected = {
                (window.window_id, cost.scenario_id)
                for window in request.windows
                for cost in request.costs
            }
            actual = [(run.window_id, run.scenario_id) for run in result.runs]
            if len(actual) != len(expected) or set(actual) != expected:
                raise ValueError("evaluation result coordinates are incomplete or duplicated")
            if (
                result.request_hash,
                result.strategy_identity,
                result.runtime_binding_hash,
                result.data_identity,
                result.execution_mode,
            ) != (
                request_hash,
                request.strategy.runtime_identity_sha256,
                binding_hash,
                request.execution_data.fingerprint,
                request.execution_mode,
            ):
                raise ValueError("evaluation result identity differs from request")
            if any(
                run.identity is None
                or run.identity.content_sha256 != content
                or run.identity.candidate.strategy_id != request.strategy.strategy_family_id
                or run.identity.candidate.candidate_id != request.strategy.candidate_id
                or run.candidate_id != request.strategy.candidate_id
                for run in result.runs
            ):
                raise ValueError("evaluation run candidate identity differs")
            if result.result_hash != _evaluation_result_hash(request_hash, result.runs):
                raise ValueError("evaluation result hash differs")
            if (
                StrategyRuntime()
                .identify(request.strategy, dependencies=dependencies)
                .content_sha256
                != content
            ):
                raise ValueError("candidate content changed during evaluation")
            completed_count = len(result.runs)
            evaluation_ids = tuple(run.identity.evaluation_id for run in result.runs)
            writing_evidence = True
            artifact = evidence.result(result, request)
            self._artifacts.append(artifact)
            terminal = replace(
                record,
                status=EvaluationAttemptStatus.SUCCEEDED,
                finished_at=datetime.now(timezone.utc).isoformat(),
                elapsed_seconds=perf_counter() - clock,
                completed_count=len(result.runs),
                evaluation_ids=tuple(run.identity.evaluation_id for run in result.runs),
                result_hash=result.result_hash,
                result_artifact=artifact,
            )
            reference = evidence.record(terminal)
            self._artifacts.append(reference)
            self._recorder.record_evaluation(terminal)
            return replace(result, attempt_id=attempt, record=reference)
        except BaseException as exc:
            cancelled = isinstance(exc, (KeyboardInterrupt, SystemExit, CancelledError))
            terminal = replace(
                record,
                status=EvaluationAttemptStatus.CANCELLED
                if cancelled
                else EvaluationAttemptStatus.UNKNOWN if isinstance(exc, (BrokenProcessPool, _UnobservedEvaluation))
                else EvaluationAttemptStatus.FAILED,
                finished_at=datetime.now(timezone.utc).isoformat(),
                elapsed_seconds=perf_counter() - clock,
                completed_count=completed_count,
                evaluation_ids=evaluation_ids,
                error_code="EVIDENCE_WRITE_FAILED" if writing_evidence else type(exc).__name__,
                error_message=str(exc) or type(exc).__name__,
            )
            self._recorder.record_evaluation(terminal)
            try:
                self._artifacts.append(evidence.record(terminal))
            except OSError as write_error:
                raise EvaluationExecutionError(
                    f"execution evidence could not be finalized: {write_error}",
                    attempt_id=attempt,
                    error_code="EVIDENCE_WRITE_FAILED",
                ) from exc
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise EvaluationExecutionError(
                str(exc), attempt_id=attempt, error_code=terminal.error_code
            ) from exc


class _PlatformExperimentContext:
    """Concrete TDR implementation of the REX context protocol."""

    def __init__(
        self,
        definition: ExperimentDefinition,
        *,
        data: _ExperimentDataAccess,
        runtime: _ExperimentRuntimeAccess,
        evaluation: _ExperimentEvaluationAccess,
        workspace: ExperimentWorkspace,
        resources: ExperimentResources,
        recorder: _TraceRecorder,
        predecessors: Mapping[str, ExperimentInput],
        formal: bool,
        backtest_data: _ExperimentDataAccess,
        backtest_runtime: _ExperimentRuntimeAccess,
    ) -> None:
        if resources.random_seed != definition.random_seed:
            raise ValueError("resource random_seed must match the experiment definition")
        self.definition = definition
        self.data = data
        self.runtime = runtime
        self.evaluation = evaluation
        self.workspace = workspace
        self.resources = resources
        self.predecessors = MappingProxyType(dict(predecessors))
        self._recorder = recorder
        self._formal = formal
        self._artifacts = []
        self._backtest_data = backtest_data
        self._backtest_runtime = backtest_runtime

    def _prepare_evaluation(self, request: EvaluationRequest) -> EvaluationRequest:
        with self.evaluation._call():
            return self.evaluation._prepare(request)[0]

    @property
    def trace(self) -> ExperimentTrace:
        return self._recorder.snapshot()

    def record_capability(self, capability: ExperimentCapability) -> None:
        """Record a research operation; authorization belongs to the researcher."""
        self._recorder.record_capability(ExperimentCapability(capability))


def create_experiment_context(
    definition: ExperimentDefinition,
    *,
    repository_root: Path,
    dataflows: Dataflows,
    resources: ExperimentResources,
    runtime: StrategyRuntime | None = None,
    evaluator: Callable[[EvaluationRequest], EvaluationResult] = evaluate_strategy,
    workspace: ExperimentWorkspace | None = None,
    real_returns: bool = False,
    sealed_validation: bool = False,
    predecessors: tuple[ExperimentInput, ...] = (),
) -> ExperimentContext[EvaluationRequest, EvaluationResult]:
    """Wire discovery adapters into an operation- and resource-tracked context.

    ``real_returns`` and ``sealed_validation`` label trace observations only.
    Researchers own authorization and the meaning of their declared data scope.
    """

    if definition.mode is ExperimentMode.FORMAL:
        raise ValueError("FORMAL experiments require create_formal_experiment_context")
    return _create_experiment_context(
        definition,
        repository_root=repository_root,
        dataflows=dataflows,
        resources=resources,
        runtime=runtime or StrategyRuntime(dataflows=dataflows),
        evaluator=evaluator,
        workspace=workspace,
        real_returns=real_returns,
        sealed_validation=sealed_validation,
        predecessors=predecessors,
        formal=False,
        input_preparer=(_prepare_evaluation_inputs
                        if evaluator is evaluate_strategy else None),
    )


def create_formal_experiment_context(
    definition: ExperimentDefinition,
    *,
    repository_root: Path,
    resources: ExperimentResources,
    workspace: ExperimentWorkspace | None = None,
    predecessors: tuple[ExperimentInput, ...] = (),
    data_space: DataSpace,
) -> ExperimentContext[EvaluationRequest, EvaluationResult]:
    """Create a formal context using only platform-owned production adapters."""

    if definition.mode is not ExperimentMode.FORMAL:
        raise ValueError("formal context requires a FORMAL experiment definition")
    flows = Dataflows(base_dir=Path(repository_root), space=data_space,
                      providers=ProviderConfig(env_file=Path(repository_root) / ".env"))
    return _create_experiment_context(
        definition,
        repository_root=repository_root,
        dataflows=flows,
        resources=resources,
        runtime=StrategyRuntime(dataflows=flows),
        evaluator=evaluate_strategy,
        workspace=workspace,
        real_returns=True,
        sealed_validation=definition.data_scope is ExperimentDataScope.SEALED_VALIDATION,
        predecessors=predecessors,
        formal=True,
        batch_evaluator=PlatformEvaluator(Path(repository_root)),
        input_preparer=_prepare_evaluation_inputs,
    )


def _create_experiment_context(
    definition: ExperimentDefinition,
    *,
    repository_root: Path,
    dataflows: Dataflows,
    resources: ExperimentResources,
    runtime: StrategyRuntime,
    evaluator: Callable[[EvaluationRequest], EvaluationResult],
    workspace: ExperimentWorkspace | None,
    real_returns: bool,
    sealed_validation: bool,
    predecessors: tuple[ExperimentInput, ...],
    formal: bool,
    batch_evaluator=None,
    input_preparer=None,
) -> ExperimentContext[EvaluationRequest, EvaluationResult]:
    if not isinstance(definition, ExperimentDefinition):
        raise TypeError("experiment definition must be ExperimentDefinition")
    if not isinstance(resources, ExperimentResources):
        raise TypeError("experiment resources must be ExperimentResources")
    if definition.schema_version != 2:
        raise ValueError("new execution contexts require experiment definition schema 2")
    inputs = tuple(predecessors)
    if not all(isinstance(item, ExperimentInput) for item in inputs):
        raise TypeError("predecessors must contain ExperimentInput values")
    by_id = {item.experiment_id: item for item in inputs}
    if len(by_id) != len(inputs):
        raise ValueError("predecessor experiment inputs must be unique")
    expected = set(definition.protocol.predecessor_experiment_ids)
    if set(by_id) != expected:
        raise ValueError("predecessor inputs differ from the experiment protocol")

    recorder = _TraceRecorder(definition.data_scope)
    if workspace is None:
        root = create_temporary_directory(
            repository_root,
            "research-experiments",
            prefix=f"{definition.experiment_id.lower()}-",
            repository_root=repository_root,
        )
        workspace = ExperimentWorkspace(root, repository_root)
    backtest_flows = _dataflows.create_backtest_dataflows(Path(repository_root), read_only=True)
    if input_preparer is _prepare_evaluation_inputs:
        def prepare_managed_inputs(request):
            flows = _dataflows.create_backtest_dataflows(Path(repository_root))
            tracked = _ExperimentDataAccess(
                flows, recorder, real_returns=real_returns,
                sealed_validation=sealed_validation,
            )
            return _bind_evaluation_inputs(request, dataflows=tracked)
        input_preparer = prepare_managed_inputs
    return _PlatformExperimentContext(
        definition,
        data=_ExperimentDataAccess(
            dataflows,
            recorder,
            real_returns=real_returns,
            sealed_validation=sealed_validation,
        ),
        runtime=_ExperimentRuntimeAccess(runtime or StrategyRuntime(), recorder),
        evaluation=_ExperimentEvaluationAccess(
            definition,
            evaluator,
            recorder,
            resources,
            workspace,
            repository_root=repository_root,
            real_returns=real_returns,
            sealed_validation=sealed_validation,
            batch_evaluator=batch_evaluator,
            input_preparer=input_preparer,
        ),
        workspace=workspace,
        resources=resources,
        recorder=recorder,
        predecessors=by_id,
        formal=formal,
        backtest_data=_ExperimentDataAccess(
            backtest_flows, recorder,
            real_returns=real_returns, sealed_validation=sealed_validation,
        ),
        backtest_runtime=_ExperimentRuntimeAccess(
            StrategyRuntime(dataflows=backtest_flows), recorder,
        ),
    )


def execute_experiment(
    experiment: LoadedExperiment, context: ExperimentContext
) -> ExperimentResult:
    """Execute one source-bound REX experiment and validate its result boundary."""

    if not isinstance(experiment, LoadedExperiment):
        raise TypeError("experiment must be loaded by load_experiment")
    if not isinstance(context, _PlatformExperimentContext):
        raise TypeError("context must be created by a platform experiment context factory")
    _require_open_execution(context.workspace)
    _validate_execution_identity(experiment, context)
    if context._formal != (experiment.definition.mode is ExperimentMode.FORMAL):
        raise ValueError("experiment mode and context assurance differ")
    preflight_experiment(
        experiment,
        resources=context.resources,
        predecessors=tuple(context.predecessors.values()),
    ).require_pass()
    try:
        with threadpool_limits(limits=context.resources.native_threads_per_worker):
            result = experiment.implementation.execute(context)
        _validate_execution_identity(experiment, context)
        if not isinstance(result, ExperimentResult):
            raise TypeError("experiment returned an invalid result")
        artifacts = {item.path: item for item in result.artifacts}
        for item in (*context.evaluation._artifacts, *context._artifacts):
            if item.path in artifacts and artifacts[item.path] != item:
                raise ValueError("experiment artifact conflicts with platform evidence")
            artifacts[item.path] = item
        result = replace(result, artifacts=tuple(artifacts.values()))
        if result.candidate is not None:
            context.record_capability(ExperimentCapability.CREATE_CANDIDATE)
        for artifact in result.artifacts:
            context.workspace.validate_artifact(artifact)
        if result.receipt is not None:
            raise ValueError("experiment implementation cannot supply a platform receipt")
        receipt = ExperimentReceipt._from_execution(
            schema_version=2,
            experiment_id=experiment.definition.experiment_id,
            definition_sha256=experiment.definition.sha256,
            source_sha256=experiment.binding.source_sha256,
            resources_sha256=context.resources.sha256,
            predecessor_receipts={
                key: item.receipt_sha256 for key, item in context.predecessors.items()
            },
            result_sha256=experiment_result_sha256(result),
            artifact_sha256={item.path: item.sha256 for item in result.artifacts},
            trace=context.trace,
        )
        _require_open_execution(context.workspace)
        _atomic_execution_document(
            context.workspace,
            "execution_envelope.json",
            {
                "schema_version": 1,
                "receipt": receipt.to_dict(),
                "receipt_sha256": receipt.sha256,
                "result": result.to_dict(),
            },
        )
        _atomic_execution_document(
            context.workspace,
            "execution_receipt.json",
            {**receipt.to_dict(), "receipt_sha256": receipt.sha256},
        )
    except BaseException as exc:
        _atomic_execution_document(
            context.workspace,
            "execution_failure.json",
            {
                "experiment_id": experiment.definition.experiment_id,
                "definition_sha256": experiment.definition.sha256,
                "source_sha256": experiment.binding.source_sha256,
                "error_code": type(exc).__name__,
                "error_message": str(exc),
                "trace": context.trace.to_dict(),
            },
        )
        raise
    return replace(result, receipt=receipt)


def _require_open_execution(workspace):
    if any(workspace.path(name).exists() for name in (
        "execution_receipt.json", "execution_envelope.json", "execution_failure.json",
    )):
        raise FileExistsError("platform execution evidence already exists")


def _validate_execution_identity(experiment, context):
    actual_hash = experiment_source_sha256(experiment.root, experiment.binding.source_files)
    if actual_hash != experiment.binding.source_sha256:
        raise ValueError("experiment source SHA-256 differs from binding")
    if experiment.implementation.definition.sha256 != experiment.definition.sha256:
        raise ValueError("experiment definition changed after loading")
    if experiment.definition.sha256 != context.definition.sha256:
        raise ValueError("experiment and context definitions differ")


def _atomic_execution_document(workspace, name, payload):
    temporary = workspace.path(f".tmp/execution/{uuid4().hex}.json")
    temporary.write_text(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ),
        encoding="utf-8", newline="\n",
    )
    try:
        # Publish complete bytes without replacing any previously recorded terminal.
        os.link(temporary, workspace.path(name))
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "create_experiment_context",
    "create_formal_experiment_context",
    "execute_experiment",
    "preflight_experiment",
]
