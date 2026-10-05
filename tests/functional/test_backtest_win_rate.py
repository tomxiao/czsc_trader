"""Closed-trade metric semantics through public, actual SRT/TXE evaluation."""
import pandas as pd
import pytest
from pathlib import Path
from strategy_runtime import implementation_sha256
from czsc_trader.application import BacktestRequest, run_backtest
from public_backtest_support import request_for_prices


@pytest.mark.parametrize("returns,expected", [
    ([], None), ([.1], 1.), ([-.1], 0.), ([0.], 0.), ([.1, -.1, 0.], 1 / 3),
])
def test_win_rate_counts_only_profitable_closed_trades(candidate_payload, tmp_path, monkeypatch, returns, expected):
    payload, source = candidate_payload
    path = source / "strategies/candidate_fixture.py"
    path.write_text(path.read_text(encoding="utf-8").replace('"fee_rate": 0.001', '"fee_rate": 0.0'), encoding="utf-8", newline="\n")
    payload["runtime"]["source_sha256"] = implementation_sha256(payload["runtime"]["source_files"], source_root=source)
    payload["parameters"]["entry_order_type"] = "MARKET"
    days = pd.bdate_range("2026-01-05", periods=2 * len(returns) + 21)
    opens = [10.] * len(days)
    for index, trade_return in enumerate(returns):
        opens[2 * index + 21] = 10. * (1 + trade_return)
    prices = pd.DataFrame({"dt": days, "open": opens, "close": 10.})
    flow = [.1] * 19 + [.8, .1] * (len(returns) + 1)
    context, request, _ = request_for_prices(candidate_payload, tmp_path, monkeypatch, prices, start_index=20, flow=flow, cost=0.)
    result = run_backtest(context, request.strategy, BacktestRequest("588080.SH", "etf", days[20].date(), days[-1].date(), 100000, 100))
    assert result.status == "PASS"
    trades = pd.read_csv(Path(result.artifacts["output_dir"]) / "trades.csv")
    closed = trades.loc[trades.status.eq("CLOSED")]
    assert len(closed) == len(returns)
    assert len(trades.loc[trades.status.eq("OPEN")]) == 1
    assert closed.net_return.tolist() == pytest.approx(returns)
    assert result.result["metrics"]["strategy"]["metrics"]["win_rate"] == expected


def test_benchmark_win_rate_uses_net_costs_and_ignores_open_tail(candidate_payload, tmp_path, monkeypatch):
    import numpy as np
    payload, source = candidate_payload
    path = source / "strategies/candidate_fixture.py"
    path.write_text(path.read_text(encoding="utf-8").replace('"fee_rate": 0.001', '"fee_rate": 0.1'), encoding="utf-8", newline="\n")
    payload["runtime"]["source_sha256"] = implementation_sha256(payload["runtime"]["source_files"], source_root=source)
    close = np.r_[np.full(20, 10.), np.tile(np.r_[np.linspace(10, 13, 20), np.linspace(13, 10, 20)], 3), np.linspace(10, 13, 20)]
    days = pd.bdate_range("2026-01-05", periods=len(close))
    prices = pd.DataFrame({"dt": days, "open": close, "close": close})
    context, request, _ = request_for_prices(candidate_payload, tmp_path, monkeypatch, prices, start_index=20)
    result = run_backtest(context, request.strategy, BacktestRequest("588080.SH", "etf", days[20].date(), days[-1].date(), 100000, 100))
    assert result.status == "PASS"
    output = Path(result.artifacts["output_dir"])
    orders = pd.read_csv(output / "ma_orders.csv")
    trades = pd.read_csv(output / "ma_trades.csv")
    assert len(trades) == 3 and len(orders) == 7
    assert orders.iloc[-1].side == "BUY"
    buys, sells = orders.iloc[:-1:2].reset_index(drop=True), orders.iloc[1::2].reset_index(drop=True)
    assert sells.price.gt(buys.price).all()
    net = (sells["size"] * sells.price - sells.fees) / (buys["size"] * buys.price + buys.fees) - 1
    assert net.lt(0).all()
    assert trades.net_return.tolist() == pytest.approx(net.tolist())
    assert result.result["metrics"]["benchmarks"]["ma5_ma20"]["metrics"]["closed_trades"] == 3
    assert result.result["metrics"]["benchmarks"]["ma5_ma20"]["metrics"]["win_rate"] == 0.
