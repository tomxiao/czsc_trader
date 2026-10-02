from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from strategy_runtime import StrategyObservation

from .models import StrategyIdentity


@dataclass(frozen=True)
class BacktestResult:
    identity: StrategyIdentity
    decisions: pd.DataFrame
    orders: pd.DataFrame
    fills: pd.DataFrame
    account_daily: pd.DataFrame
    trades: pd.DataFrame
    observations: tuple[StrategyObservation, ...] = ()

    @property
    def equity(self) -> pd.Series:
        return self.account_daily.set_index("date")["equity"].astype(float)
