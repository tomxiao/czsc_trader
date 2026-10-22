import pandas as pd
import pytest

from trading_execution_engine import execute_target_positions


def _prices():
    return pd.DataFrame({
        "dt": pd.to_datetime(["2026-09-14", "2026-09-15"]),
        "open": [10., 11.], "close": [10.5, 11.5],
    })


@pytest.mark.parametrize(
    ("value", "error", "message"),
    [
        pytest.param(True, TypeError, "lot_size must be an integer", id="True"),
        pytest.param(1.5, TypeError, "lot_size must be an integer", id="1.5"),
        pytest.param("100", TypeError, "lot_size must be an integer", id="100"),
        pytest.param(0, ValueError, "lot_size must be positive", id="0"),
        pytest.param(-1, ValueError, "lot_size must be positive", id="-1"),
    ],
)
def test_daily_execution_rejects_invalid_lot_size(value, error, message):
    prices = _prices()
    with pytest.raises(error, match=f"^{message}$"):
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


def test_daily_numeric_replay_does_not_copy_evidence_or_modify_inputs():
    class Evidence:
        def __deepcopy__(self, memo):
            raise AssertionError("source evidence must not be deep-copied")

    prices = _prices()
    target = pd.Series([.5, 0.], index=prices.dt)
    baseline = execute_target_positions(prices, target, fee_rate=.001, initial_cash=10000, lot_size=100)
    evidence = Evidence()
    prices.attrs["evidence"] = target.attrs["evidence"] = evidence
    result = execute_target_positions(prices, target, fee_rate=.001, initial_cash=10000, lot_size=100)
    for name in ("equity", "orders", "state", "attempts"):
        left, right = getattr(baseline, name), getattr(result, name)
        if isinstance(left, pd.Series):
            pd.testing.assert_series_equal(left, right, check_exact=True)
        else:
            pd.testing.assert_frame_equal(left, right, check_exact=True)
    assert prices.attrs["evidence"] is target.attrs["evidence"] is evidence
    assert pd.DataFrame(prices).open.tolist() == [10., 11.]
    assert pd.Series(target).tolist() == [.5, 0.]
