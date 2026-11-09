"""EC09: full buy/sell cash flows at zero and nonzero fee rates."""
import pandas as pd
import pytest
from execution_channels.historical import execute_target_positions


@pytest.mark.parametrize('fee_rate,buy_cash,final_cash,equity', [
    (0., 100., 1200., 1150.),
    (.01, 90., 1179., 1140.),
], ids=['EC09-C04', 'EC09-C05'])
def test_daily_roundtrip_preserves_both_confirmed_cash_flows(fee_rate,buy_cash,final_cash,equity):
    prices = pd.DataFrame({
        'dt': pd.to_datetime(['2026-09-14', '2026-09-15']),
        'open': [10., 11.], 'close': [10.5, 11.5],
    })
    result = execute_target_positions(
        prices, pd.Series([1., 0.], index=prices.dt),
        fee_rate=fee_rate, initial_cash=1100, lot_size=100,
    )
    assert result.orders.side.tolist() == ['BUY', 'SELL']
    assert result.orders.quantity.tolist() == [100, 100]
    assert result.state.cash.tolist() == pytest.approx([buy_cash, final_cash])
    assert result.state.quantity.tolist() == [100, 0]
    assert result.equity.tolist() == pytest.approx([equity, final_cash])
