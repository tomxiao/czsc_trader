"""Strongly typed calculation declarations supplied by strategy implementations."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Mapping
from dataflows import DataRequest
from .contracts import SignalHistoryMode, TradableWindow
from .errors import RuntimeContractError


@dataclass(frozen=True, slots=True)
class HistoryCalculationContext:
    """Immutable boundary between feature warm-up and decision-state replay.

    WINDOW begins fresh account-dependent trade/feedback state at its first
    signal. CONTINUOUS reconstructs it from declared calculation history.
    Canonical market indicators and market intent may use full warm-up history
    under HistoryPolicy in both modes. Both use the same implementation and
    complete authenticated inputs. Account cash/positions belong to execution.
    """

    mode: SignalHistoryMode
    tradable_window: TradableWindow
    signal_dates: tuple[date, ...]
    calculation_dates: tuple[date, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.mode, SignalHistoryMode):
            raise RuntimeContractError("history context requires SignalHistoryMode")
        if not isinstance(self.tradable_window, TradableWindow):
            raise RuntimeContractError("history context requires TradableWindow")
        for name in ("signal_dates", "calculation_dates"):
            values = getattr(self, name)
            if (type(values) is not tuple or not values
                    or any(type(day) is not date for day in values)
                    or tuple(sorted(set(values))) != values):
                raise RuntimeContractError(f"history context {name} requires ordered unique dates")
        if not set(self.signal_dates) <= set(self.calculation_dates):
            raise RuntimeContractError("calculation history omits window signal dates")
        if self.signal_dates[0] >= self.tradable_window.start:
            raise RuntimeContractError("first signal must precede the first execution session")
        if self.signal_dates[-1] >= self.tradable_window.end:
            raise RuntimeContractError("last signal must precede the last execution session")
        if self.calculation_dates[-1] != self.signal_dates[-1]:
            raise RuntimeContractError("calculation history must end at the last signal session")

    @property
    def sessions(self):
        """A detached index; feature inputs are never sliced by the framework."""
        import pandas as pd

        dates = self.signal_dates if self.mode is SignalHistoryMode.WINDOW else self.calculation_dates
        return pd.DatetimeIndex(dates, name="dt")

    @property
    def state_start(self) -> date:
        """Replay start for account-dependent state, not market-feature warm-up."""
        return self.signal_dates[0] if self.mode is SignalHistoryMode.WINDOW else self.calculation_dates[0]


@dataclass(frozen=True, slots=True)
class CalculationScope:
    tradable_window: TradableWindow
    trading_dates: tuple[date, ...]
    signal_dates: Mapping[date, date]
    calculation_dates: tuple[date, ...]
    inputs: Mapping[str, DataRequest]

    def __post_init__(self) -> None:
        if not isinstance(self.tradable_window, TradableWindow):
            raise RuntimeContractError("scope requires a TradableWindow")
        if not isinstance(self.inputs, Mapping) or not isinstance(self.signal_dates, Mapping):
            raise RuntimeContractError("scope inputs and signal dates must be mappings")
        for values in (
            self.trading_dates,
            self.calculation_dates,
            self.signal_dates.keys(),
            self.signal_dates.values(),
        ):
            if any(type(value) is not date for value in values):
                raise RuntimeContractError("scope dates must be date values")
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
        if not calculation_dates or tuple(sorted(set(calculation_dates))) != calculation_dates:
            raise RuntimeContractError("scope calculation dates are invalid")
        if any(
            not isinstance(name, str) or not name or not isinstance(request, DataRequest)
            for name, request in inputs.items()
        ):
            raise RuntimeContractError("scope inputs must be named DataRequest instances")
        object.__setattr__(self, "trading_dates", trading_dates)
        object.__setattr__(self, "signal_dates", signal_dates)
        object.__setattr__(self, "calculation_dates", calculation_dates)
        object.__setattr__(self, "inputs", inputs)

    @property
    def available_through(self) -> date:
        return self.calculation_dates[-1]
