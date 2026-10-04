"""Internal data preparation owned by one StrategyInstance."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, timedelta
from importlib.resources import files
from pathlib import Path
import sys

import pandas as pd
from dataflows import (
    DataRequest,
    DataCoverageRequirement,
    EvidenceParameters, MoneyflowParameters, NoParameters, PreparePolicy,
    DataResult,
    DataStatus,
    Dataflows,
    Dataset,
    canonical_frame_sha256,
)

from .algorithm import StrategyImplementation
from .contracts import StrategyIdentity, TradableWindow
from .errors import RuntimeContractError, RuntimeExecutionError
from .models import CutoffRule, RuntimeDefinition, canonical_sha256
from .validation import validate_history_depth
from .input_binding import StrategyInputPlan, StrategyInputBinding


@dataclass(frozen=True, slots=True)
class PreparedInputs:
    strategy: StrategyIdentity
    tradable_window: TradableWindow
    available_through: date
    data_identity: str
    requests: Mapping[str, DataRequest]
    results: Mapping[str, DataResult]
    calendar_dates: tuple[date, ...]
    signal_dates: Mapping[date, date]
    calculation_dates: tuple[date, ...]

    @property
    def input_identities(self) -> dict[str, str]:
        return {
            name: result.identity.content_sha256
            for name, result in self.results.items()
            if result.identity is not None
        }


def _request_parameters(
    definition: RuntimeDefinition,
    requirement,
):
    if requirement.dataset != Dataset.STRATEGY_FEATURE_EVIDENCE.value:
        return NoParameters()
    rule = definition.parameters.values.get("rule")
    data_source = rule.get("data_source") if isinstance(rule, Mapping) else None
    if (
        not isinstance(data_source, Mapping)
        or not isinstance(data_source.get("path"), str)
        or not isinstance(data_source.get("sha256"), str)
    ):
        raise RuntimeContractError("strategy evidence data source is incomplete")
    package = data_source.get("package")
    if package is None:
        root = Path.cwd().resolve()
    elif package == "strategy_runtime":
        module = sys.modules.get(definition.implementation.module)
        module_file = getattr(module, "__file__", None)
        if module_file is None:
            raise RuntimeContractError("strategy implementation source is unavailable")
        root = Path(module_file).resolve().parent.parent
    elif isinstance(package, str) and package:
        root = Path(str(files(package))).resolve()
    else:
        raise RuntimeContractError("strategy evidence package is invalid")
    return EvidenceParameters(root, str(data_source["path"]), str(data_source["sha256"]))



def _open_dates(frame: pd.DataFrame) -> tuple[date, ...]:
    if not {"Date", "IsOpen"} <= set(frame.columns):
        raise RuntimeContractError("trading calendar is structurally incomplete")
    dates = pd.to_datetime(frame["Date"], errors="raise").dt.date
    mask = pd.to_numeric(frame["IsOpen"], errors="raise").eq(1)
    result = tuple(dict.fromkeys(dates.loc[mask]))
    if tuple(sorted(result)) != result:
        raise RuntimeContractError("trading calendar dates are not ordered")
    return result


def _ready(result: DataResult, name: str) -> DataResult:
    if result.status is DataStatus.READY and result.identity is not None:
        if canonical_frame_sha256(result.dataframe) != result.identity.content_sha256:
            raise RuntimeContractError(
                f"prepared input identity differs from dataframe content: {name}"
            )
        return result
    detail = result.error.message if result.error else result.status.value
    raise RuntimeExecutionError(f"data preparation failed for {name}: {detail}")


def prepared_inputs_identity(
    *,
    strategy: StrategyIdentity,
    tradable_window: TradableWindow,
    available_through: date,
    signal_dates: Mapping[date, date],
    results: Mapping[str, DataResult],
) -> str:
    identities = {
        name: result.identity.content_sha256
        for name, result in sorted(results.items())
        if result.identity is not None
    }
    if len(identities) != len(results):
        raise RuntimeContractError("prepared inputs contain an unauthenticated result")
    return canonical_sha256(
        {
            "strategy": strategy.reference_id,
            "release_hash": strategy.release_hash,
            "runtime_sha256": strategy.runtime_sha256,
            "tradable_window": {
                "start": tradable_window.start.isoformat(),
                "end": tradable_window.end.isoformat(),
            },
            "available_through": available_through.isoformat(),
            "signal_dates": {
                key.isoformat(): value.isoformat()
                for key, value in signal_dates.items()
            },
            "inputs": identities,
        }
    )


def calendar_request(*, algorithm: StrategyImplementation, tradable_window: TradableWindow) -> DataRequest:
    calendars = [item for item in algorithm.definition.inputs.requirements
                 if item.dataset == Dataset.TRADING_CALENDAR.value]
    if len(calendars) != 1:
        raise RuntimeContractError("strategy requires exactly one trading calendar")
    requirement = calendars[0]
    window = algorithm.calendar_window(tradable_window)
    return DataRequest(requirement.dataset, requirement.subject, window.start.isoformat(),
                       window.end.isoformat(), window.end.isoformat(), requirement.frequency)


def plan_inputs(*, strategy: StrategyIdentity, algorithm: StrategyImplementation,
                tradable_window: TradableWindow, calendar: DataResult) -> StrategyInputPlan:
    definition = algorithm.definition
    if definition.tradable_symbol != strategy.symbol:
        raise RuntimeContractError("prepared-data symbol differs from strategy")
    request = calendar_request(algorithm=algorithm, tradable_window=tradable_window)
    requirements = {item.name: item for item in definition.inputs.requirements}
    calendar_name = next(name for name, item in requirements.items()
                         if item.dataset == Dataset.TRADING_CALENDAR.value)
    result = _ready(calendar, calendar_name)
    if result.prepared is None or result.identity.dataset != request.dataset or result.identity.symbol != request.symbol:
        raise RuntimeContractError("calendar must be fetched from an explicit DFLS preparation")
    actual_dates = pd.DatetimeIndex(pd.to_datetime(result.dataframe["Date"]))
    expected_dates = pd.date_range(request.start, request.end)
    if not actual_dates.equals(expected_dates):
        raise RuntimeContractError("calendar result differs from strategy calendar request")
    dates = _open_dates(result.dataframe)
    scope = algorithm.derive_calculation_scope(tradable_window, dates)
    if set(scope.inputs) != set(requirements):
        raise RuntimeContractError("strategy calculation scope differs from input contract")
    requests = {calendar_name: request}
    first_signal = min(scope.signal_dates.values())
    for name, requirement in requirements.items():
        if name == calendar_name or scope.inputs[name] is None:
            continue
        input_range = scope.inputs[name]
        parameters = _request_parameters(definition, requirement)
        if requirement.dataset == Dataset.STOCK_MONEYFLOW.value and requirement.subject is None:
            parameters = MoneyflowParameters(tuple(item.isoformat() for item in dates
                                                   if input_range.start <= item <= input_range.end))
        required_cutoff = input_range.required_cutoff
        if (requirement.cutoff_rule is CutoffRule.LATEST_AVAILABLE
                and requirement.maximum_staleness_days):
            freshness_cutoff = scope.available_through - timedelta(
                days=requirement.maximum_staleness_days,
            )
            required_cutoff = max(
                input_range.start, freshness_cutoff,
                required_cutoff or input_range.start,
            )
            if required_cutoff > input_range.end:
                raise RuntimeContractError(f"input range cannot satisfy maximum staleness: {name}")
        coverage = None
        if requirement.lookback_sessions > 0:
            coverage = DataCoverageRequirement(
                maximum_start_lag_days=None,
                minimum_observations=requirement.lookback_sessions,
                minimum_sessions=requirement.lookback_sessions,
                observations_through=min(first_signal, input_range.end).isoformat(),
            )
        requests[name] = DataRequest(
            requirement.dataset, requirement.subject, input_range.start.isoformat(),
            input_range.end.isoformat(),
            None if required_cutoff is None else required_cutoff.isoformat(),
            requirement.frequency, parameters, coverage=coverage,
        )
    return StrategyInputPlan(strategy, tradable_window, calendar_name,
                             result.identity.content_sha256, requests, dates,
                             scope.signal_dates, scope.calculation_dates)


def acquire_binding(*, strategy: StrategyIdentity, algorithm: StrategyImplementation,
                    tradable_window: TradableWindow, dataflows: Dataflows,
                    policy: PreparePolicy) -> StrategyInputBinding:
    request = calendar_request(algorithm=algorithm, tradable_window=tradable_window)
    prepared = dataflows.prepare((request,), policy=policy)
    if not prepared.ready:
        raise RuntimeExecutionError("calendar preparation failed: " + "; ".join(
            item.error.message for item in prepared.items if item.error is not None))
    calendar = _ready(dataflows.fetch(request, prepared=prepared.reference), "calendar")
    plan = plan_inputs(strategy=strategy, algorithm=algorithm, tradable_window=tradable_window,
                       calendar=calendar)
    prepared = dataflows.prepare(tuple(plan.requests.values()), policy=policy)
    if not prepared.ready:
        raise RuntimeExecutionError("input preparation failed: " + "; ".join(
            item.error.message for item in prepared.items if item.error is not None))
    return StrategyInputBinding(plan, prepared.reference)


def prepare_inputs(*, strategy: StrategyIdentity, algorithm: StrategyImplementation,
                   tradable_window: TradableWindow, dataflows: Dataflows,
                   binding: StrategyInputBinding) -> PreparedInputs:
    """Read only the explicitly bound assets; authenticate the calculation plan."""
    if binding.plan.strategy != strategy or binding.plan.tradable_window != tradable_window:
        raise RuntimeContractError("input binding belongs to another strategy or window")
    plan = binding.plan
    calendar = _ready(dataflows.fetch(plan.requests[plan.calendar_name], prepared=binding.prepared),
                      plan.calendar_name)
    actual_plan = plan_inputs(strategy=strategy, algorithm=algorithm,
                              tradable_window=tradable_window, calendar=calendar)
    comparable_requests = dict(actual_plan.requests)
    for name, derived in actual_plan.requests.items():
        bound = plan.requests.get(name)
        if (derived.dataset is Dataset.STRATEGY_FEATURE_EVIDENCE and bound is not None
                and isinstance(derived.parameters, EvidenceParameters)
                and isinstance(bound.parameters, EvidenceParameters)):
            # Materializing the same hash-pinned evidence inside a release changes
            # only its physical repository root. Read the already authenticated
            # bound asset; all logical selection fields and source hashes must
            # still match. Never reopen or fetch the relocated source here.
            comparable_requests[name] = replace(
                derived,
                parameters=replace(derived.parameters, repository_root=bound.parameters.repository_root),
            )
    if replace(actual_plan, requests=comparable_requests) != plan:
        raise RuntimeContractError("bound calendar or calculation plan differs from its derived inputs")
    results = {plan.calendar_name: calendar}
    first_signal = min(plan.signal_dates.values())
    requirements = {item.name: item for item in algorithm.definition.inputs.requirements}
    for name, request in plan.requests.items():
        if name == plan.calendar_name:
            continue
        result = _ready(dataflows.fetch(request, prepared=binding.prepared), name)
        requirement = requirements[name]
        history = result.dataframe.loc[pd.to_datetime(result.dataframe["Date"]).dt.date <= first_signal]
        validate_history_depth(name, requirement.lookback_sessions, history)
        if (requirement.cutoff_rule is CutoffRule.LATEST_AVAILABLE
                and requirement.maximum_staleness_days
                and pd.Timestamp(result.identity.data_cutoff) < pd.Timestamp(plan.available_through)
                    - pd.Timedelta(days=requirement.maximum_staleness_days)):
            raise RuntimeContractError(f"prepared input exceeds maximum staleness: {name}")
        results[name] = result
    identity = prepared_inputs_identity(strategy=strategy, tradable_window=tradable_window,
                                        available_through=plan.available_through,
                                        signal_dates=plan.signal_dates, results=results)
    return PreparedInputs(strategy, tradable_window, plan.available_through, identity,
                          plan.requests, results, plan.calendar_dates, plan.signal_dates,
                          plan.calculation_dates)
