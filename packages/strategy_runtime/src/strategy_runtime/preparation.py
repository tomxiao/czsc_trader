"""Internal data preparation owned by one StrategyInstance."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from importlib.resources import files
from pathlib import Path
import sys

import pandas as pd
from dataflows import (
    DataRequest,
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


def _request_options(
    definition: RuntimeDefinition,
    requirement,
    base: Mapping[str, object],
) -> dict[str, object]:
    options = dict(base)
    if requirement.dataset != Dataset.STRATEGY_FEATURE_EVIDENCE.value:
        return options
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
    options.update(
        {
            "repository_root": str(root),
            "source_path": str(data_source["path"]),
            "source_sha256": str(data_source["sha256"]),
        }
    )
    return options


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


def prepare_inputs(
    *,
    strategy: StrategyIdentity,
    algorithm: StrategyImplementation,
    tradable_window: TradableWindow,
    data_dir: Path,
    dataflows: Dataflows | None = None,
) -> PreparedInputs:
    """Derive, fetch and validate every dataset required by one instance."""

    definition = algorithm.definition
    root = Path(data_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    symbol = definition.tradable_symbol
    if symbol != strategy.symbol:
        raise RuntimeContractError("prepared-data symbol differs from strategy")
    requirements = {item.name: item for item in definition.inputs.requirements}
    calendars = [
        item
        for item in definition.inputs.requirements
        if item.dataset == Dataset.TRADING_CALENDAR.value
    ]
    if len(calendars) != 1:
        raise RuntimeContractError("strategy requires exactly one trading calendar")
    calendar_requirement = calendars[0]
    flows = dataflows or Dataflows()
    calendar_window = algorithm.calendar_window(tradable_window)
    base_options = _request_options(
        definition, calendar_requirement, {}
    )
    calendar_request = DataRequest(
        calendar_requirement.dataset,
        calendar_requirement.subject,
        calendar_window.start.isoformat(),
        calendar_window.end.isoformat(),
        calendar_window.end.isoformat(),
        calendar_requirement.frequency,
        base_options,
    )
    calendar_result = _ready(
        flows.fetch(calendar_request), calendar_requirement.name
    )
    calendar_dates = _open_dates(calendar_result.dataframe)
    scope = algorithm.derive_calculation_scope(tradable_window, calendar_dates)
    if set(scope.inputs) != set(requirements):
        raise RuntimeContractError("strategy calculation scope differs from input contract")
    requests: dict[str, DataRequest] = {
        calendar_requirement.name: calendar_request
    }
    results: dict[str, DataResult] = {
        calendar_requirement.name: calendar_result
    }
    for name, requirement in requirements.items():
        if name == calendar_requirement.name:
            continue
        input_range = scope.inputs[name]
        if input_range is None:
            continue
        options = _request_options(definition, requirement, {})
        if (
            requirement.dataset == Dataset.STOCK_MONEYFLOW.value
            and requirement.subject is None
        ):
            options["trading_dates"] = [
                item.isoformat()
                for item in calendar_dates
                if input_range.start <= item <= input_range.end
            ]
        request = DataRequest(
            requirement.dataset,
            requirement.subject,
            input_range.start.isoformat(),
            input_range.end.isoformat(),
            None
            if input_range.required_cutoff is None
            else input_range.required_cutoff.isoformat(),
            requirement.frequency,
            options,
        )
        result = _ready(flows.fetch(request), name)
        validate_history_depth(name, requirement.lookback_sessions, result.dataframe)
        if (
            requirement.cutoff_rule is CutoffRule.LATEST_AVAILABLE
            and requirement.maximum_staleness_days
            and pd.Timestamp(result.identity.data_cutoff)
            < pd.Timestamp(scope.available_through)
            - pd.Timedelta(days=requirement.maximum_staleness_days)
        ):
            raise RuntimeContractError(
                f"prepared input exceeds maximum staleness: {name}"
            )
        requests[name] = request
        results[name] = result

    data_identity = prepared_inputs_identity(
        strategy=strategy,
        tradable_window=tradable_window,
        available_through=scope.available_through,
        signal_dates=scope.signal_dates,
        results=results,
    )
    return PreparedInputs(
        strategy,
        tradable_window,
        scope.available_through,
        data_identity,
        requests,
        results,
        calendar_dates,
        scope.signal_dates,
        scope.calculation_dates,
    )
