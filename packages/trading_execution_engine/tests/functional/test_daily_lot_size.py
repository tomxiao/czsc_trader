import pandas as pd
import pytest

from trading_execution_engine import execute_target_positions


def _prices():
    return pd.DataFrame({
        "dt": pd.to_datetime(["2026-09-14", "2026-09-15"]),
        "open": [10., 11.], "close": [10.5, 11.5],
    })


@pytest.mark.parametrize("value", [True, False, 1.5, "100", 0, -1])
def test_daily_execution_rejects_invalid_lot_size(value):
    prices = _prices()
    with pytest.raises((TypeError, ValueError), match="lot_size"):
        execute_target_positions(
            prices, pd.Series([1., 0.], index=prices.dt),
            fee_rate=.01, initial_cash=1100, lot_size=value,
        )


def test_daily_lot_rounding_preserves_residual_cash_and_liquidation():
    prices = _prices()
    result = execute_target_positions(
        prices, pd.Series([1., 0.], index=prices.dt),
        fee_rate=.01, initial_cash=1100, lot_size=100,
    )
    assert result.orders.quantity.tolist() == [100, 100]
    assert result.state.cash.tolist() == pytest.approx([90, 1179])
    assert result.state.quantity.tolist() == [100, 0]
    assert result.equity.tolist() == pytest.approx([1140, 1179])


def test_daily_insufficient_cash_emits_no_zero_order():
    prices = _prices()
    result = execute_target_positions(
        prices, pd.Series([1., 0.], index=prices.dt),
        fee_rate=.01, initial_cash=1000, lot_size=100,
    )
    assert result.orders.empty
    assert result.equity.tolist() == [1000, 1000]
    assert result.state.quantity.tolist() == [0, 0]
