"""Internal data preparation owned by one StrategyInstance."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date

import pandas as pd
from dataflows import (
    DataRequest,
    EvidenceParameters,
    PreparePolicy,
    DataResult,
    DataStatus,
    Dataflows,
    Dataset,
    canonical_frame_sha256,
)

from .algorithm import StrategyImplementation
from .contracts import StrategyIdentity, TradableWindow
from .errors import RuntimeContractError, RuntimeExecutionError
from .models import canonical_sha256
from .calculation import CalculationScope
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
                key.isoformat(): value.isoformat() for key, value in signal_dates.items()
            },
            "inputs": identities,
        }
    )


def calendar_request(
    *, algorithm: StrategyImplementation, tradable_window: TradableWindow
) -> DataRequest:
    calendars = [
        item
        for item in algorithm.definition.inputs.requirements
        if item.dataset == Dataset.TRADING_CALENDAR.value
    ]
    if len(calendars) != 1:
        raise RuntimeContractError("strategy requires exactly one trading calendar")
    requirement = calendars[0]
    request = algorithm.calendar_request(tradable_window)
    if not isinstance(request, DataRequest):
        raise RuntimeContractError("strategy calendar request must be DataRequest")
    if (
        request.dataset.value != requirement.dataset
        or request.symbol != requirement.subject
        or request.frequency != requirement.frequency
    ):
        raise RuntimeContractError("strategy calendar request differs from input contract")
    return request


def plan_inputs(
    *,
    strategy: StrategyIdentity,
    algorithm: StrategyImplementation,
    tradable_window: TradableWindow,
    calendar: DataResult,
) -> StrategyInputPlan:
    definition = algorithm.definition
    if definition.tradable_symbol != strategy.symbol:
        raise RuntimeContractError("prepared-data symbol differs from strategy")
    request = calendar_request(algorithm=algorithm, tradable_window=tradable_window)
    requirements = {item.name: item for item in definition.inputs.requirements}
    calendar_name = next(
        name
        for name, item in requirements.items()
        if item.dataset == Dataset.TRADING_CALENDAR.value
    )
    result = _ready(calendar, calendar_name)
    if (
        result.prepared is None
        or result.identity.dataset != request.dataset
        or result.identity.symbol != request.symbol
    ):
        raise RuntimeContractError("calendar must be fetched from an explicit DFLS preparation")
    actual_dates = pd.DatetimeIndex(pd.to_datetime(result.dataframe["Date"]))
    expected_dates = pd.date_range(request.start, request.end)
    if not actual_dates.equals(expected_dates):
        raise RuntimeContractError("calendar result differs from strategy calendar request")
    dates = _open_dates(result.dataframe)
    scope = algorithm.derive_calculation_scope(tradable_window, dates)
    if not isinstance(scope, CalculationScope) or scope.tradable_window != tradable_window:
        raise RuntimeContractError("strategy calculation scope differs from requested window")
    if calendar_name in scope.inputs or not set(scope.inputs) <= set(requirements):
        raise RuntimeContractError("strategy calculation scope differs from input contract")
    for name, declared in scope.inputs.items():
        requirement = requirements[name]
        if (
            declared.dataset.value != requirement.dataset
            or declared.symbol != requirement.subject
            or declared.frequency != requirement.frequency
        ):
            raise RuntimeContractError(
                f"strategy input request differs from input contract: {name}"
            )
    requests = {calendar_name: request, **scope.inputs}
    return StrategyInputPlan(
        strategy,
        tradable_window,
        calendar_name,
        result.identity.content_sha256,
        requests,
        dates,
        scope.signal_dates,
        scope.calculation_dates,
    )


def acquire_binding(
    *,
    strategy: StrategyIdentity,
    algorithm: StrategyImplementation,
    tradable_window: TradableWindow,
    dataflows: Dataflows,
    policy: PreparePolicy,
) -> StrategyInputBinding:
    request = calendar_request(algorithm=algorithm, tradable_window=tradable_window)
    prepared = dataflows.prepare((request,), policy=policy)
    if not prepared.ready:
        raise RuntimeExecutionError(
            "calendar preparation failed: "
            + "; ".join(item.error.message for item in prepared.items if item.error is not None)
        )
    calendar = _ready(dataflows.fetch(request, prepared=prepared.reference), "calendar")
    plan = plan_inputs(
        strategy=strategy, algorithm=algorithm, tradable_window=tradable_window, calendar=calendar
    )
    prepared = dataflows.prepare(tuple(plan.requests.values()), policy=policy)
    if not prepared.ready:
        raise RuntimeExecutionError(
            "input preparation failed: "
            + "; ".join(item.error.message for item in prepared.items if item.error is not None)
        )
    return StrategyInputBinding(plan, prepared.reference)


def prepare_inputs(
    *,
    strategy: StrategyIdentity,
    algorithm: StrategyImplementation,
    tradable_window: TradableWindow,
    dataflows: Dataflows,
    binding: StrategyInputBinding,
) -> PreparedInputs:
    """Read only the explicitly bound assets; authenticate the calculation plan."""
    if binding.plan.strategy != strategy or binding.plan.tradable_window != tradable_window:
        raise RuntimeContractError("input binding belongs to another strategy or window")
    plan = binding.plan
    calendar = _ready(
        dataflows.fetch(plan.requests[plan.calendar_name], prepared=binding.prepared),
        plan.calendar_name,
    )
    actual_plan = plan_inputs(
        strategy=strategy, algorithm=algorithm, tradable_window=tradable_window, calendar=calendar
    )
    comparable_requests = dict(actual_plan.requests)
    for name, derived in actual_plan.requests.items():
        bound = plan.requests.get(name)
        if (
            derived.dataset is Dataset.STRATEGY_FEATURE_EVIDENCE
            and bound is not None
            and isinstance(derived.parameters, EvidenceParameters)
            and isinstance(bound.parameters, EvidenceParameters)
        ):
            # Materializing the same hash-pinned evidence inside a release changes
            # only its physical repository root. Read the already authenticated
            # bound asset; all logical selection fields and source hashes must
            # still match. Never reopen or fetch the relocated source here.
            comparable_requests[name] = replace(
                derived,
                parameters=replace(
                    derived.parameters, repository_root=bound.parameters.repository_root
                ),
            )
    if replace(actual_plan, requests=comparable_requests) != plan:
        raise RuntimeContractError(
            "bound calendar or calculation plan differs from its derived inputs"
        )
    results = {plan.calendar_name: calendar}
    for name, request in plan.requests.items():
        if name == plan.calendar_name:
            continue
        result = _ready(dataflows.fetch(request, prepared=binding.prepared), name)
        results[name] = result
    identity = prepared_inputs_identity(
        strategy=strategy,
        tradable_window=tradable_window,
        available_through=plan.available_through,
        signal_dates=plan.signal_dates,
        results=results,
    )
    return PreparedInputs(
        strategy,
        tradable_window,
        plan.available_through,
        identity,
        plan.requests,
        results,
        plan.calendar_dates,
        plan.signal_dates,
        plan.calculation_dates,
    )
