"""V4 BuyHold preserves market lot, available cash and causal execution semantics."""
from dataclasses import replace
import pandas as pd
import pytest
from dataflows import BarFrequency, MarketId
from czsc_trader.research_tools import ResearchExecutionSession
from czsc_trader.research_tools.equity_replay import materialize_equity
from account_parity_support import setup_account


@pytest.mark.parametrize("market,cash,quantity", [
    (MarketId.CN, 500., 0), (MarketId.CN, 1100., 100),
    (MarketId.US, 500., 49), (MarketId.US, 1100., 108),
])
def test_benchmark_lot_cash_valuation_and_execution_timing(tmp_path, market, cash, quantity):
    context, request = setup_account(tmp_path, market, BarFrequency.DAILY)
    request = replace(request, initial_cash=cash)
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        prepared = context.evaluation.prepare(request, execution=execution)
        outcome, = context.evaluation.evaluate_many((prepared,), execution=execution)
        assert outcome.result is not None, outcome.error
        payload = materialize_equity(outcome.result).payload
    run = payload["runs"]["buy_hold"]
    points = run["account_points"]
    step = context.execution_spec.quantity_step
    assert points and all(row["quantity"] % step == 0 for row in points)
    assert all(row["cash"] >= 0 for row in points)
    for row in points:
        assert row["equity"] == pytest.approx(row["cash"] + row["receivable"] + row["quantity"] * row["close"])
    assert points[0]["quantity"] == quantity
    assert len(run["fills"]) == (1 if quantity else 0)
    if quantity:
        # The declared 1% buy limit reserves cash at 10.10, although the fill is at 10.
        assert run["orders"][0]["limit_price"] == pytest.approx(10.10)
        fill = run["fills"][0]
        assert fill["quantity"] == quantity
        assert fill["fees"] == pytest.approx(quantity * 10. * request.fee_rate)
        assert pd.Timestamp(fill["interval_start"]) == request.window.start
        assert pd.Timestamp(fill["executed_at"]) >= pd.Timestamp(fill["interval_start"])
        assert points[0]["cash"] == pytest.approx(cash - quantity * 10. * (1 + request.fee_rate))
    else:
        assert all(row["equity"] == cash for row in points)
