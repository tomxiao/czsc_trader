"""Historical execution input refusal belongs to the public TXE constructor."""

import pandas as pd
import pytest
from strategy_runtime import ExecutionPolicy, RuntimeContractError
from trading_execution_engine import HistoricalExecutor


def test_historical_execution_rejects_invalid_cash_prices_sessions_and_fee_override():
    daily = pd.DataFrame({"dt": pd.to_datetime(["2026-09-17"]), "open": [1.], "close": [1.]})
    execution = dict(strategy_reference="S900-C0001", symbol="588080.SH", execution_daily=daily,
        execution_intraday=pd.DataFrame(columns=["dt", "high", "low"]),
        evaluation_start=pd.Timestamp("2026-09-17"), evaluation_end=pd.Timestamp("2026-09-17"),
        initial_cash=100_000, execution_policy=ExecutionPolicy("FROZEN_RULE", {
            "capital": {"fee_rate": .001, "mode": "full_available_cash"},
            "entry": {"limit_parameter": 0., "order_type": "LIMIT"},
            "exit": {"limit_ratio": .1, "order_type": "MARKET"},
            "instrument": {"lot_size": 100, "maximum_order_quantity": 1_000_000, "price_limit_ratio": .1, "price_tick": .001},
        }), order_types=("LIMIT", "MARKET"))
    HistoricalExecutor(**execution)
    for changes, reason in (
        ({"initial_cash": float("nan")}, "positive and finite"),
        ({"execution_daily": pd.concat([daily, daily])}, "unique"),
        ({"execution_daily": daily.assign(close=float("nan"))}, "positive and finite"),
        ({"evaluation_end": pd.Timestamp("2026-09-18")}, "do not cover"),
    ):
        with pytest.raises(RuntimeContractError, match=reason):
            HistoricalExecutor(**{**execution, **changes})
    with pytest.raises(TypeError, match="fee_rate_override"):
        HistoricalExecutor(**execution, fee_rate_override=.003)
