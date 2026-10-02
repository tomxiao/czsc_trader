from types import SimpleNamespace

import pandas as pd
import pytest

from czsc_trader.backtesting.metrics import calculate_metrics
from czsc_trader.strategy_metrics import strategy_comparison_metrics


@pytest.mark.parametrize('returns,expected', [
    ([], None), ([.1], 1.), ([-.1], 0.), ([0.], 0.), ([.1, -.1, 0.], 1 / 3),
])
def test_win_rate_counts_only_profitable_closed_trades(returns, expected):
    trades = pd.DataFrame([{'status': 'CLOSED', 'net_return': r} for r in returns]
                          + [{'status': 'OPEN', 'net_return': .5}])
    result = SimpleNamespace(account_daily=pd.DataFrame({'equity': [100., 100.]}), trades=trades)
    assert calculate_metrics(result, 100.)['win_rate'] == expected


def test_benchmark_win_rate_uses_net_costs_and_ignores_open_tail():
    orders = []
    # One profitable, one gross profitable but net losing, and one breakeven trade.
    for exit_price in (13., 11., 12.):
        for side, price in [('Buy', 10.), ('Sell', exit_price)]:
            orders.append(dict(signal_date='2026-01-05', execution_date='2026-01-06',
                               side=side, size=1, price=price, fees=1.))
    orders.append(dict(orders[0]))
    metrics = strategy_comparison_metrics(pd.Series([100., 100.]), pd.DataFrame(orders), 100.)
    assert metrics['win_rate'] == pytest.approx(1 / 3)
