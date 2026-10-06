"""Benchmark accounting through the public backtest result and artifacts."""
import json
import numpy as np
import pandas as pd
import pytest
from czsc_trader.application import BacktestRequest, run_backtest
from public_backtest_support import request_for_prices, render_output


@pytest.mark.parametrize("initial_cash,lot_size,quantity", [(500, 100, 0), (1100, 100, 0), (1100, 1, 91)])
def test_benchmark_quantities_cash_signal_timing_and_independent_audit(candidate_payload, tmp_path, monkeypatch, initial_cash, lot_size, quantity):
    from czsc_trader.research_tools import EvaluationBenchmark, NextOpenBuyHold
    dates = pd.bdate_range("2026-01-05", periods=65)
    close = np.r_[np.linspace(10, 12, 25), np.linspace(12, 9, 20), np.linspace(9, 12, 20)]
    prices = pd.DataFrame({"dt": dates, "open": close, "close": close + .1})
    context, request, _ = request_for_prices(
        candidate_payload, tmp_path, monkeypatch, prices, start_index=25, initial_cash=initial_cash,
        benchmark=EvaluationBenchmark(NextOpenBuyHold(lot_size)),
    )
    # Lot-size 1 is researcher-owned buy-and-hold, independently of strategy lot 100.
    evaluated = context.evaluation.evaluate(request)
    buyhold = evaluated.runs[0].buyhold
    assert len(evaluated.runs) == 1
    assert (buyhold.account_daily.quantity % lot_size == 0).all()
    assert (buyhold.account_daily.cash >= 0).all()
    assert buyhold.account_daily.equity.tolist() == pytest.approx(
        (buyhold.account_daily.cash + buyhold.account_daily.quantity * buyhold.account_daily.close).tolist(),
    )
    assert len(buyhold.orders) == (1 if quantity else 0)
    assert buyhold.account_daily.iloc[0].quantity == quantity
    if not quantity:
        assert buyhold.account_daily.equity.eq(initial_cash).all()
    else:
        assert pd.Timestamp(buyhold.orders.iloc[0].signal_date) == dates[24]
        assert pd.Timestamp(buyhold.orders.iloc[0].execution_date) == dates[25]
    if lot_size == 100:
        result = run_backtest(context, request.strategy, BacktestRequest(
            "588080.SH", "etf", dates[25].date(), dates[-1].date(), initial_cash, 100,
        ))
        assert result.manifest["audit"]["status"] == "PASS"
        output = render_output(result, context.repository.root)
        audit = json.loads((output / "audit.json").read_text(encoding="utf-8"))
        assert audit["status"] == "PASS"
        assert {"buyhold", "ma5_ma20"} == set(audit["benchmarks"])
        assert all(item["status"] == "PASS" for item in audit["benchmarks"].values())
        for name in ("buyhold", "ma"):
            account = pd.read_csv(output / f"{name}_account_daily.csv")
            orders = pd.read_csv(output / ("ma_orders.csv" if name == "ma" else "buyhold_account_daily.csv"))
            assert not account.empty and len(account) == 40
            assert account.quantity.mod(100).eq(0).all()
            assert account.cash.ge(0).all()
            assert account.equity.tolist() == pytest.approx((account.cash + account.quantity * account.close).tolist())
            if name == "ma":
                assert bool(len(orders)) == (initial_cash != 500)
                for order in orders.itertuples():
                    day = pd.Timestamp(order.execution_date)
                    assert pd.Timestamp(order.signal_date) == dates[dates.get_loc(day) - 1]
                    assert order.size > 0 and order.size % 100 == 0
