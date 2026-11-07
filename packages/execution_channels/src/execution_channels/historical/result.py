"""Ledger facts produced by TXE, independent of research and report objects."""

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ExecutionResult:
    decisions: pd.DataFrame
    orders: pd.DataFrame
    fills: pd.DataFrame
    account_daily: pd.DataFrame
    trades: pd.DataFrame

    @property
    def equity(self) -> pd.Series:
        return self.account_daily.set_index("date")["equity"].astype(float)
