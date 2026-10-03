"""Internal calculation ranges derived by each strategy implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from types import MappingProxyType
from typing import Mapping

from dataflows import Dataset

from strategy_runtime import TradableWindow
from strategy_runtime import RuntimeContractError
from strategy_runtime import CutoffRule, StrategyDefinition


@dataclass(frozen=True, slots=True)
class CalendarWindow:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise RuntimeContractError("calendar window start must not follow end")


@dataclass(frozen=True, slots=True)
class InputRange:
    start: date
    end: date
    required_cutoff: date | None

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise RuntimeContractError("input range start must not follow end")
        if self.required_cutoff is not None and self.required_cutoff > self.end:
            raise RuntimeContractError("input cutoff must not follow input range end")


@dataclass(frozen=True, slots=True)
class CalculationScope:
    tradable_window: TradableWindow
    trading_dates: tuple[date, ...]
    signal_dates: Mapping[date, date]
    calculation_dates: tuple[date, ...]
    inputs: Mapping[str, InputRange]

    def __post_init__(self) -> None:
        trading_dates = tuple(self.trading_dates)
        calculation_dates = tuple(self.calculation_dates)
        signal_dates = MappingProxyType(dict(sorted(self.signal_dates.items())))
        inputs = MappingProxyType(dict(sorted(self.inputs.items())))
        if not trading_dates or tuple(sorted(set(trading_dates))) != trading_dates:
            raise RuntimeContractError("scope trading dates must be unique and ordered")
        if (
            trading_dates[0] != self.tradable_window.start
            or trading_dates[-1] != self.tradable_window.end
            or any(not self.tradable_window.contains(item) for item in trading_dates)
        ):
            raise RuntimeContractError("scope trading dates differ from tradable window")
        if set(signal_dates) != set(trading_dates):
            raise RuntimeContractError("scope must define one signal date per trading date")
        if any(signal_dates[item] >= item for item in trading_dates):
            raise RuntimeContractError("scope signal dates must precede trading dates")
        if (
            not calculation_dates
            or tuple(sorted(set(calculation_dates))) != calculation_dates
            or calculation_dates[-1] != signal_dates[trading_dates[-1]]
        ):
            raise RuntimeContractError("scope calculation dates are invalid")
        if not inputs:
            raise RuntimeContractError("scope must contain input ranges")
        object.__setattr__(self, "trading_dates", trading_dates)
        object.__setattr__(self, "signal_dates", signal_dates)
        object.__setattr__(self, "calculation_dates", calculation_dates)
        object.__setattr__(self, "inputs", inputs)

    @property
    def available_through(self) -> date:
        return self.calculation_dates[-1]


def next_session_calendar_window(
    definition: StrategyDefinition,
    tradable_window: TradableWindow,
) -> CalendarWindow:
    """Return the calendar range selected by a next-session strategy."""

    lookback = max(
        (
            item.lookback_sessions
            for item in definition.inputs.requirements
            if item.dataset != Dataset.TRADING_CALENDAR.value
        ),
        default=1,
    )
    policy_start = definition.history.preparation_start(tradable_window.start)
    estimated = tradable_window.start - timedelta(days=max(31, lookback * 2))
    return CalendarWindow(
        min(policy_start, estimated),
        tradable_window.end + timedelta(days=20),
    )


def next_session_calculation_scope(
    definition: StrategyDefinition,
    tradable_window: TradableWindow,
    calendar_dates: tuple[date, ...],
) -> CalculationScope:
    """Derive the exact current frozen next-session calculation semantics."""

    trading_dates = tuple(
        item for item in calendar_dates if tradable_window.contains(item)
    )
    if (
        not trading_dates
        or trading_dates[0] != tradable_window.start
        or trading_dates[-1] != tradable_window.end
    ):
        raise RuntimeContractError("tradable window endpoints must be open sessions")
    signal_dates: dict[date, date] = {}
    for trading_date in trading_dates:
        previous = [item for item in calendar_dates if item < trading_date]
        if not previous:
            raise RuntimeContractError(
                "trading calendar has no signal session before trading date"
            )
        signal_dates[trading_date] = previous[-1]
    first_signal = signal_dates[trading_dates[0]]
    last_signal = signal_dates[trading_dates[-1]]
    requirements = {item.name: item for item in definition.inputs.requirements}
    ranges: dict[str, InputRange] = {}
    for name, requirement in requirements.items():
        if requirement.dataset == Dataset.TRADING_CALENDAR.value:
            ranges[name] = InputRange(
                calendar_dates[0], calendar_dates[-1], calendar_dates[-1]
            )
            continue
        available = [item for item in calendar_dates if item <= first_signal]
        required = max(1, requirement.lookback_sessions)
        if len(available) < required:
            raise RuntimeContractError(
                f"trading calendar cannot satisfy input lookback: {requirement.name}"
            )
        start = min(
            definition.history.preparation_start(first_signal),
            available[-required],
        )
        if requirement.cutoff_rule is CutoffRule.LATEST_AVAILABLE:
            start -= timedelta(days=requirement.maximum_staleness_days)
        end = last_signal
        cutoff: date | None = None
        if requirement.cutoff_rule is CutoffRule.SIGNAL_SESSION:
            cutoff = last_signal
        elif requirement.cutoff_rule is CutoffRule.PREVIOUS_SESSION:
            previous = [item for item in calendar_dates if item < last_signal]
            if not previous:
                raise RuntimeContractError(
                    f"prepared data has no previous session for input {name}"
                )
            end = previous[-1]
            cutoff = end
        ranges[name] = InputRange(start, end, cutoff)
    calculation_start = (
        date.fromisoformat(definition.history.canonical_start)
        if definition.history.canonical_start is not None
        else first_signal
    )
    calculation_dates = tuple(
        item for item in calendar_dates if calculation_start <= item <= last_signal
    )
    return CalculationScope(
        tradable_window,
        trading_dates,
        signal_dates,
        calculation_dates,
        ranges,
    )
