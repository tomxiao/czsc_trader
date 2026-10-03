"""Required implementation surface for every strategy algorithm."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Mapping, Self

import pandas as pd

from .calculation import CalculationScope, CalendarWindow
from .contracts import TradableWindow
from .models import ParameterSet, StrategyDefinition
from .errors import RuntimeCompatibilityError


class StrategyImplementation(ABC):
    """Base class that makes every strategy-owned responsibility explicit."""

    @classmethod
    @abstractmethod
    def from_parameters(cls, parameters: ParameterSet) -> Self:
        """Construct identical business behavior for candidate and release execution."""
        raise NotImplementedError

    @classmethod
    def from_parameters_for_symbol(cls, parameters: ParameterSet, symbol: str) -> Self:
        """Explicit opt-in for deployment on an instrument different from the declaration."""
        raise RuntimeCompatibilityError("strategy does not support deployment symbol rebinding")

    @property
    @abstractmethod
    def definition(self) -> StrategyDefinition:
        """Return immutable strategy-owned business contracts."""

        raise NotImplementedError

    @abstractmethod
    def calendar_window(self, tradable_window: TradableWindow) -> CalendarWindow:
        """Return the calendar range needed to resolve the tradable window."""

        raise NotImplementedError

    @abstractmethod
    def derive_calculation_scope(
        self,
        tradable_window: TradableWindow,
        calendar_dates: tuple[date, ...],
    ) -> CalculationScope:
        """Derive signal dates and the exact range of every strategy input."""

        raise NotImplementedError

    @abstractmethod
    def calculate_history(
        self,
        inputs: Mapping[str, pd.DataFrame],
        sessions: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        """Calculate the channel-neutral strategy history for prepared inputs."""

        raise NotImplementedError

    def calculate_window_history(
        self,
        inputs: Mapping[str, pd.DataFrame],
        sessions: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        """Calculate an evaluation window with strategy state reset at its left edge."""

        return self.calculate_history(inputs, sessions)
