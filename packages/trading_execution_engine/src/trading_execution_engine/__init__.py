"""Trading Execution Engine (TXE) public contracts."""

from .daily import DailyExecutionResult, execute_target_positions
from .fills import FillDecision, OrderSpec, resolve_fill
from .historical import HistoricalExecutor
from .market import MarketExecutionRules, SessionPriceLimits
from .result import ExecutionResult

EXECUTION_CONTRACT_VERSION = "TXE-v2-market-limits"

__all__ = [
    "DailyExecutionResult",
    "EXECUTION_CONTRACT_VERSION",
    "FillDecision",
    "HistoricalExecutor",
    "MarketExecutionRules",
    "SessionPriceLimits",
    "ExecutionResult",
    "OrderSpec",
    "execute_target_positions",
    "resolve_fill",
]
