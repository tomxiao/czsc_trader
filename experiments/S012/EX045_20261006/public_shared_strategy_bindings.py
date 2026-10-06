"""Batch caller-owned SRT input bindings through public REX/SRT/DFLS APIs.

Call only after a successful FULL outcome has returned real execution_data.
Every candidate/window gets its own newly derived plan. Two REUSE preparations
cover all calendars, then the union of strategy inputs and existing execution
market requests. One new immutable PreparedDataRef contains the whole union;
existing and new preparation identities are never spliced. No private API,
evaluation, fallback, source edit or governance action is invoked here.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from dataflows import DataRequest, PreparePolicy, PreparedDataRef
from research_experiment import ExperimentContext
from strategy_runtime import StrategyInit, StrategyInputBinding, TradableWindow

from czsc_trader.backtesting import BacktestExecutionData
from czsc_trader.research_tools import EvaluationRequest


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _unique(requests: tuple[DataRequest, ...]) -> tuple[DataRequest, ...]:
    """Deduplicate exact requests only; preserve distinct acceptance requirements."""
    values: list[DataRequest] = []
    for request in requests:
        if not isinstance(request, DataRequest):
            raise TypeError("Input lists must contain public DataRequest objects")
        if request not in values:
            values.append(request)
    return tuple(values)


def prepare_bindings(
    context: ExperimentContext,
    requests: tuple[EvaluationRequest, ...],
    shared_execution_data: BacktestExecutionData,
    *,
    root: Path,
    workspace: Path | None = None,
) -> tuple[EvaluationRequest, ...]:
    """Return the same requests with shared execution data and complete bindings.

    This is an explicit parent-process operation. Pass original unbound requests,
    a genuine successful evaluation's execution_data and repository root.
    workspace defaults to context.workspace.root, and must remain below .tmp.
    Preparation/fetch failures propagate; no refresh, retry or automatic prepare
    fallback occurs. Public evaluation later authenticates each plan and table.
    """
    if not isinstance(requests, tuple) or not requests or any(
        not isinstance(request, EvaluationRequest) for request in requests
    ):
        raise TypeError("requests must be a nonempty tuple of EvaluationRequest")
    if not isinstance(shared_execution_data, BacktestExecutionData):
        raise TypeError("shared_execution_data must be BacktestExecutionData")
    root = Path(root).resolve()
    workspace = context.workspace.root if workspace is None else Path(workspace)
    workspace = workspace.resolve()
    _require(workspace.is_relative_to(root / ".tmp"), "Input binding workspace must be repository-local .tmp")
    shared = shared_execution_data
    _require(isinstance(shared.prepared, PreparedDataRef) and bool(shared.requests)
             and set(shared.requests) == set(shared.input_identities),
             "Shared market data must retain its original authenticated preparation and input list")

    pending = []
    seen = set()
    for request_index, request in enumerate(requests):
        _require(Path(request.repository_root).resolve() == root, "Request repository differs")
        _require(request.experiment_id == context.definition.experiment_id,
                 "Request belongs to another experiment context")
        _require(request.strategy.strategy_family_id == context.definition.strategy_id,
                 "Request belongs to another research family")
        _require(not request.input_bindings, "Pass original unbound requests; do not replace existing input bindings")
        _require(request.execution_data is None or request.execution_data is shared,
                 "Request already carries different execution data")
        _require((request.symbol, request.asset_type, request.data_cutoff) ==
                 (shared.symbol, shared.asset_type, shared.cutoff), "Shared market instrument/cutoff differs")
        _require(request.execution_mode == "FULL" and request.workers == 1,
                 "Managed batch requests must retain FULL and workers=1")
        _require(bool(request.windows), "Evaluation windows must be nonempty")
        _require(len({window.window_id for window in request.windows}) == len(request.windows),
                 "Evaluation window IDs must be unique within a request")
        for window in request.windows:
            coordinate = (request.strategy.reference_id, window.window_id, window.start, window.end)
            _require(coordinate not in seen, "Duplicate candidate/window coordinate")
            seen.add(coordinate)
            _require(shared.evaluation_start.date() <= window.start <= window.end <= shared.cutoff,
                     "Evaluation window is outside shared market sessions")
            data_dir = (workspace / "shared-strategy-bindings" /
                        request.strategy.runtime_identity_sha256 / window.window_id).resolve()
            _require(data_dir.is_relative_to(workspace), "Window identifier escapes binding workspace")
            instance = context.runtime.create(StrategyInit(
                request.strategy, TradableWindow(window.start, window.end), data_dir))
            _require(instance.identity.reference_id == request.strategy.reference_id
                     and instance.identity.symbol == request.symbol
                     and instance.tradable_window == TradableWindow(window.start, window.end),
                     "Runtime instance does not represent the actual candidate/window")
            pending.append((request_index, window, instance, instance.calendar_request()))

    calendars = _unique(tuple(item[3] for item in pending))
    calendar_batch = context.data.prepare(calendars, policy=PreparePolicy.REUSE)
    _require(calendar_batch.ready, f"Calendar batch preparation failed: {calendar_batch.items}")
    calendar_results = {}
    for calendar in calendars:
        result = context.data.fetch(calendar, prepared=calendar_batch.reference)
        _require(result.ready and result.prepared == calendar_batch.reference,
                 f"Calendar is not ready in its explicit preparation: {calendar}")
        calendar_results[calendar] = result

    planned = []
    for request_index, window, instance, calendar in pending:
        plan = instance.plan_inputs(calendar_results[calendar])
        _require(plan.strategy == instance.identity and plan.tradable_window == instance.tradable_window
                 and plan.requests[plan.calendar_name] == calendar
                 and plan.calendar_sha256 == calendar_results[calendar].identity.content_sha256,
                 "Derived plan differs from actual strategy/window/calendar")
        planned.append((request_index, window.window_id, plan))

    union = _unique(tuple(request for _, _, plan in planned for request in plan.requests.values())
                    + tuple(shared.requests.values()))
    input_batch = context.data.prepare(union, policy=PreparePolicy.REUSE)
    _require(input_batch.ready, f"Strategy/market union preparation failed: {input_batch.items}")
    # One read per unique calendar authenticates that planning and the union
    # use exactly the same calendar version. No instance.prepare_data() is needed.
    final_calendar_hashes = {}
    for calendar in calendars:
        result = context.data.fetch(calendar, prepared=input_batch.reference)
        _require(result.ready and result.prepared == input_batch.reference,
                 "Calendar absent from new union preparation")
        final_calendar_hashes[calendar] = result.identity.content_sha256
    for _, _, plan in planned:
        _require(final_calendar_hashes[plan.requests[plan.calendar_name]] == plan.calendar_sha256,
                 "Calendar changed between planning and union preparation")
    # New features may create a new preparation, while all execution assets must
    # remain byte-identical to the successful shared market preparation.
    for name, request in shared.requests.items():
        result = context.data.fetch(request, prepared=input_batch.reference)
        _require(result.ready and result.prepared == input_batch.reference
                 and result.identity.content_sha256 == shared.input_identities[name],
                 f"Shared market identity changed in union: {name}")

    bindings = [{} for _ in requests]
    for request_index, window_id, plan in planned:
        bindings[request_index][window_id] = StrategyInputBinding(plan, input_batch.reference)
    return tuple(replace(request, execution_data=shared, input_bindings=bindings[index])
                 for index, request in enumerate(requests))
