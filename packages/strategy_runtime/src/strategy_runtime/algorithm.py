"""Required implementation surface for every strategy algorithm."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Mapping, Self

import pandas as pd
from dataflows import DataRequest

from .calculation import CalculationScope, HistoryCalculationContext
from .contracts import TradableWindow
from .models import ParameterSet, StrategyDefinition
from .errors import RuntimeCompatibilityError, RuntimeContractError


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
    def calendar_request(self, tradable_window: TradableWindow) -> DataRequest:
        """Declare the complete prerequisite calendar request."""

        raise NotImplementedError

    @abstractmethod
    def derive_calculation_scope(
        self,
        tradable_window: TradableWindow,
        calendar_dates: tuple[date, ...],
    ) -> CalculationScope:
        """Declare calculation dates and complete requests for active non-calendar inputs."""

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


class StrategyImplementationV2(StrategyImplementation):
    """One decision kernel with an explicit history initialization boundary.

    Implementations calculate market features and canonical market-intent
    history from all prepared inputs under their declared HistoryPolicy.
    Account-dependent trade/feedback state advances over context.sessions:
    WINDOW starts fresh at its first signal; CONTINUOUS reconstructs it over
    the declared calculation range. Market intent is not an account position.
    """

    @abstractmethod
    def calculate_context_history(
        self,
        inputs: Mapping[str, pd.DataFrame],
        context: HistoryCalculationContext,
    ) -> pd.DataFrame:
        raise NotImplementedError

    def calculate_history(self, inputs, sessions):
        raise RuntimeContractError("contract 2 requires an explicit HistoryCalculationContext")

    def calculate_window_history(self, inputs, sessions):
        raise RuntimeContractError("contract 2 requires an explicit HistoryCalculationContext")
