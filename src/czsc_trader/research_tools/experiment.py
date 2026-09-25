"""TDR adapters for executing REX contracts through public platform APIs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any

from dataflows import DataRequest, DataResult, Dataflows
import pandas as pd
from research_experiment import (
    ExperimentCapability,
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
from strategy_runtime import StrategyInit, StrategyRuntime
from threadpoolctl import threadpool_limits

from ..temp_workspace import create_temporary_directory
from .evaluation import EvaluationRequest, EvaluationResult, evaluate_strategy
from .preflight import preflight_experiment


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
    def __init__(self) -> None:
        self.capabilities: list[ExperimentCapability] = []
        self.operations: list[str] = []
        self.data_requests: list[Mapping[str, Any]] = []
        self.evaluations: list[Mapping[str, Any]] = []

    def record_capability(self, capability: ExperimentCapability) -> None:
        if capability not in self.capabilities:
            self.capabilities.append(capability)

    def record_operation(self, operation: str) -> None:
        self.operations.append(operation)

    def record_data_request(self, request: Mapping[str, Any]) -> None:
        self.data_requests.append(_freeze_trace_json(request, "data request trace"))

    def record_evaluation(self, evidence: Mapping[str, Any]) -> None:
        self.evaluations.append(_freeze_trace_json(evidence, "evaluation trace"))

    def snapshot(self) -> ExperimentTrace:
        return ExperimentTrace(
            capabilities=tuple(self.capabilities),
            operations=tuple(self.operations),
            data_requests=tuple(self.data_requests),
            evaluations=tuple(self.evaluations),
        )


class _ExperimentDataAccess:
    """Capability- and cutoff-aware DFLS adapter."""

    def __init__(
        self,
        definition: ExperimentDefinition,
        dataflows: Dataflows,
        recorder: _TraceRecorder,
        *,
        real_returns: bool,
        sealed_validation: bool,
    ) -> None:
        self._definition = definition
        self._dataflows = dataflows
        self._recorder = recorder
        self._real_returns = real_returns
        self._sealed_validation = sealed_validation

    def fetch(self, request: DataRequest) -> DataResult:
        if not isinstance(request, DataRequest):
            raise TypeError("data fetch requires a DataRequest")
        if request.dataset not in self._definition.allowed_datasets:
            raise PermissionError(f"dataset was not declared: {request.dataset}")
        governed_cutoff = (
            self._definition.validation_cutoff
            if self._sealed_validation
            else self._definition.development_cutoff
        )
        cutoff = pd.Timestamp(governed_cutoff)
        if pd.Timestamp(request.end).normalize() > cutoff:
            raise PermissionError("data request exceeds the development cutoff")
        if request.required_cutoff is not None and (
            pd.Timestamp(request.required_cutoff).normalize() > cutoff
        ):
            raise PermissionError("required cutoff exceeds the development cutoff")
        if self._real_returns:
            _require_capability(
                self._definition, self._recorder, ExperimentCapability.READ_REAL_RETURNS
            )
        if self._sealed_validation:
            _require_capability(
                self._definition,
                self._recorder,
                ExperimentCapability.READ_SEALED_VALIDATION,
            )
        result = self._dataflows.fetch(request)
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
        self._recorder.record_operation("data.fetch")
        self._recorder.record_data_request(
            {
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
                    "minimum_rows": request.coverage.minimum_rows,
                },
                "status": result.status.value,
                "identity": identity,
            }
        )
        return result


class _ExperimentRuntimeAccess:
    """Tracked adapter over the public SRT runtime surface."""

    def __init__(self, runtime: StrategyRuntime, recorder: _TraceRecorder) -> None:
        self._runtime = runtime
        self._recorder = recorder

    def describe(
        self,
        source: Any,
        *,
        symbol: str | None = None,
        source_root: Path | None = None,
        runtime_binding: Mapping[str, object] | None = None,
    ) -> Any:
        result = self._runtime.describe(
            source,
            symbol=symbol,
            source_root=source_root,
            runtime_binding=runtime_binding,
        )
        self._recorder.record_operation("runtime.describe")
        return result

    def create(self, request: StrategyInit) -> Any:
        if not isinstance(request, StrategyInit):
            raise TypeError("runtime create requires a StrategyInit")
        result = self._runtime.create(request)
        self._recorder.record_operation("runtime.create")
        return result


class _ExperimentEvaluationAccess:
    """Tracked adapter over the researcher-facing evaluation Harness."""

    def __init__(
        self,
        definition: ExperimentDefinition,
        evaluator: Callable[[EvaluationRequest], EvaluationResult],
        recorder: _TraceRecorder,
        resources: ExperimentResources,
        budget: _EvaluationBudget,
        *,
        real_returns: bool,
        sealed_validation: bool,
    ) -> None:
        self._definition = definition
        self._evaluator = evaluator
        self._recorder = recorder
        self._resources = resources
        self._budget = budget
        self._real_returns = real_returns
        self._sealed_validation = sealed_validation

    def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        if not isinstance(request, EvaluationRequest):
            raise TypeError("evaluation requires an EvaluationRequest")
        if request.experiment_id != self._definition.experiment_id:
            raise ValueError("evaluation request belongs to another experiment")
        governed_cutoff = (
            self._definition.validation_cutoff
            if self._sealed_validation
            else self._definition.development_cutoff
        )
        if request.development_cutoff != governed_cutoff:
            raise ValueError("evaluation request development cutoff differs")
        if request.workers > self._resources.max_workers:
            raise PermissionError("evaluation workers exceed the experiment resource budget")
        self._budget.claim(len(request.windows) * len(request.costs))
        if self._real_returns:
            _require_capability(
                self._definition, self._recorder, ExperimentCapability.READ_REAL_RETURNS
            )
        if self._sealed_validation:
            _require_capability(
                self._definition,
                self._recorder,
                ExperimentCapability.READ_SEALED_VALIDATION,
            )
        result = self._evaluator(request)
        if not isinstance(result, EvaluationResult):
            raise TypeError("evaluation Harness returned an invalid result")
        self._recorder.record_operation("evaluation.evaluate")
        self._recorder.record_evaluation(
            {
                "experiment_id": request.experiment_id,
                "request_hash": result.request_hash,
                "strategy_identity": result.strategy_identity,
                "runtime_binding_hash": result.runtime_binding_hash,
                "data_identity": result.data_identity,
                "result_hash": result.result_hash,
                "execution_mode": result.execution_mode,
            }
        )
        return result


class _EvaluationBudget:
    def __init__(self, maximum: int | None) -> None:
        self._maximum = maximum
        self._used = 0

    def claim(self, count: int) -> None:
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError("evaluation claim must be a positive integer")
        if self._maximum is not None and self._used + count > self._maximum:
            raise PermissionError("evaluation count exceeds the experiment resource budget")
        self._used += count


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

    @property
    def trace(self) -> ExperimentTrace:
        return self._recorder.snapshot()

    def require_capability(self, capability: ExperimentCapability) -> None:
        """Declare an imminent third-party action and fail before unauthorized work."""

        _require_capability(self.definition, self._recorder, capability)


def _require_capability(
    definition: ExperimentDefinition,
    recorder: _TraceRecorder,
    capability: ExperimentCapability,
) -> None:
    capability = ExperimentCapability(capability)
    if not definition.capabilities.allows(capability):
        raise PermissionError(f"experiment did not declare capability: {capability.value}")
    recorder.record_capability(capability)


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
) -> ExperimentContext:
    """Wire discovery adapters into one capability- and resource-tracked context."""

    if definition.mode is ExperimentMode.FORMAL:
        raise ValueError("FORMAL experiments require create_formal_experiment_context")
    return _create_experiment_context(
        definition,
        repository_root=repository_root,
        dataflows=dataflows,
        resources=resources,
        runtime=runtime or StrategyRuntime(),
        evaluator=evaluator,
        workspace=workspace,
        real_returns=real_returns,
        sealed_validation=sealed_validation,
        predecessors=predecessors,
        formal=False,
    )


def create_formal_experiment_context(
    definition: ExperimentDefinition,
    *,
    repository_root: Path,
    resources: ExperimentResources,
    workspace: ExperimentWorkspace | None = None,
    predecessors: tuple[ExperimentInput, ...] = (),
) -> ExperimentContext:
    """Create a formal context using only platform-owned production adapters."""

    if definition.mode is not ExperimentMode.FORMAL:
        raise ValueError("formal context requires a FORMAL experiment definition")
    return _create_experiment_context(
        definition,
        repository_root=repository_root,
        dataflows=Dataflows(),
        resources=resources,
        runtime=StrategyRuntime(),
        evaluator=evaluate_strategy,
        workspace=workspace,
        real_returns=True,
        sealed_validation=True,
        predecessors=predecessors,
        formal=True,
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
) -> ExperimentContext:
    if not isinstance(definition, ExperimentDefinition):
        raise TypeError("experiment definition must be ExperimentDefinition")
    if not isinstance(resources, ExperimentResources):
        raise TypeError("experiment resources must be ExperimentResources")
    if definition.capabilities.searches_parameters and resources.max_evaluations is None:
        raise ValueError("parameter-search experiments require max_evaluations")
    inputs = tuple(predecessors)
    if not all(isinstance(item, ExperimentInput) for item in inputs):
        raise TypeError("predecessors must contain ExperimentInput values")
    by_id = {item.experiment_id: item for item in inputs}
    if len(by_id) != len(inputs):
        raise ValueError("predecessor experiment inputs must be unique")
    expected = set(definition.protocol.predecessor_experiment_ids)
    if set(by_id) != expected:
        raise ValueError("predecessor inputs differ from the experiment protocol")

    recorder = _TraceRecorder()
    budget = _EvaluationBudget(resources.max_evaluations)
    if workspace is None:
        root = create_temporary_directory(
            repository_root,
            "research-experiments",
            prefix=f"{definition.experiment_id.lower()}-",
            repository_root=repository_root,
        )
        workspace = ExperimentWorkspace(root, repository_root)
    return _PlatformExperimentContext(
        definition,
        data=_ExperimentDataAccess(
            definition,
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
            budget,
            real_returns=real_returns,
            sealed_validation=sealed_validation,
        ),
        workspace=workspace,
        resources=resources,
        recorder=recorder,
        predecessors=by_id,
        formal=formal,
    )


def execute_experiment(
    experiment: LoadedExperiment, context: ExperimentContext
) -> ExperimentResult:
    """Execute one source-bound REX experiment and validate its result boundary."""

    if not isinstance(experiment, LoadedExperiment):
        raise TypeError("experiment must be loaded by load_experiment")
    if not isinstance(context, _PlatformExperimentContext):
        raise TypeError("context must be created by a platform experiment context factory")
    actual_hash = experiment_source_sha256(experiment.root, experiment.binding.source_files)
    if actual_hash != experiment.binding.source_sha256:
        raise ValueError("experiment source SHA-256 differs from binding")
    if experiment.implementation.definition.sha256 != experiment.definition.sha256:
        raise ValueError("experiment definition changed after loading")
    if experiment.definition.sha256 != context.definition.sha256:
        raise ValueError("experiment and context definitions differ")
    if context._formal != (experiment.definition.mode is ExperimentMode.FORMAL):
        raise ValueError("experiment mode and context assurance differ")
    if experiment.binding.schema_version >= 3:
        preflight_experiment(
            experiment,
            resources=context.resources,
            predecessors=tuple(context.predecessors.values()),
        ).require_pass()
    with threadpool_limits(limits=context.resources.native_threads_per_worker):
        result = experiment.implementation.execute(context)
    if not isinstance(result, ExperimentResult):
        raise TypeError("experiment returned an invalid result")
    if result.candidate is not None:
        context.require_capability(ExperimentCapability.CREATE_CANDIDATE)
    for artifact in result.artifacts:
        context.workspace.validate_artifact(artifact)
    if result.receipt is not None:
        raise ValueError("experiment implementation cannot supply a platform receipt")
    receipt = ExperimentReceipt._from_execution(
        schema_version=1,
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
    receipt_path = context.workspace.path("execution_receipt.json")
    envelope_path = context.workspace.path("execution_envelope.json")
    if receipt_path.exists() or envelope_path.exists():
        raise FileExistsError("platform execution evidence already exists")
    envelope_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "receipt": receipt.to_dict(),
                "receipt_sha256": receipt.sha256,
                "result": result.to_dict(),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    receipt_path.write_text(
        json.dumps(
            {**receipt.to_dict(), "receipt_sha256": receipt.sha256},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return replace(result, receipt=receipt)


__all__ = [
    "create_experiment_context",
    "create_formal_experiment_context",
    "execute_experiment",
    "preflight_experiment",
]
