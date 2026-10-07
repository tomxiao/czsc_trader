"""Closed-trade numerical classes owned by SE's public replay audit."""
from dataclasses import replace
from math import sqrt

import pandas as pd
import pytest
from strategy_evaluator import AuditStatus, ReplayEvidence, audit_replay, hash_replay_evidence


def _trade_evidence(gross_returns, fee_rate, expected_win_rate):
    """Small causal MARKET ledger; every case also ends with one open trade."""
    days = tuple(str(day.date()) for day in pd.bdate_range("2026-01-05", periods=2 * len(gross_returns) + 2))
    previous = ("2026-01-02", *days[:-1])
    cash, quantity = 10_000., 0
    decisions, orders, fills, account, trades, daily = [], [], [], [], [], []
    daily.append(dict(date=previous[0], open=10., close=10., unadjusted_close=10., price_scale=1.))
    for index, day in enumerate(days):
        before_cash, before_quantity = cash, quantity
        # Leave an initial HOLD row and a final BUY that never closes.
        side = "HOLD" if index == 0 else "BUY" if index % 2 else "SELL"
        cycle = f"cycle-{(index - 1) // 2}"
        price = 10. if side != "SELL" else 10. * (1. + gross_returns[index // 2 - 1])
        daily.append(dict(date=day, open=price, close=10., unadjusted_close=10., price_scale=1.))
        decisions.append(dict(decision_id=f"d{index}", signal_date=previous[index],
                              valid_session=day, target_position=0. if side in {"HOLD", "SELL"} else 1.,
                              action=side, plan_mode="NONE"))
        if side != "HOLD":
            fee = 100 * price * fee_rate
            order = dict(order_id=f"o{index}", decision_id=f"d{index}", cycle_id=cycle,
                         signal_date=previous[index], execution_date=day, side=side,
                         quantity=100, order_type="MARKET", limit_price=10., status="FILLED")
            orders.append(order)
            fills.append(dict(fill_id=f"f{index}", order_id=order["order_id"],
                              decision_id=order["decision_id"], cycle_id=cycle,
                              signal_date=previous[index], fill_time=day, side=side,
                              quantity=100, price=price, fees=fee, trigger="OPEN_MARKET"))
            if side == "BUY":
                cash -= 100 * price + fee
                quantity += 100
                trades.append(dict(cycle_id=cycle, status="OPEN", quantity=100,
                                   entry_price=10., exit_price=None, net_return=None))
            else:
                cash += 100 * price - fee
                quantity -= 100
                trades[-1].update(status="CLOSED", exit_price=price,
                                 net_return=(100 * price - fee) / (1000 * (1 + fee_rate)) - 1.)
        account.append(dict(date=day, cash_before=before_cash, quantity_before=before_quantity,
                            cash=cash, quantity=quantity, close=10., equity=cash + quantity * 10.))
    equity = [row["equity"] for row in account]
    peak, drawdown = 10_000., 0.
    returns = []
    previous_equity = 10_000.
    for value in equity:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1.)
        returns.append(value / previous_equity - 1.)
        previous_equity = value
    mean = sum(returns) / len(returns)
    volatility = sqrt(sum((value - mean) ** 2 for value in returns) / (len(returns) - 1))
    closed = [row["net_return"] for row in trades if row["status"] == "CLOSED"]
    wins, losses = [value for value in closed if value > 0], [value for value in closed if value < 0]
    ratio = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else None
    ratio_status = "NO_CLOSED_TRADES" if not closed else "NO_WINS" if not wins else "NO_LOSSES" if not losses else "VALID"
    metrics = dict(return_=equity[-1] / 10_000. - 1.)
    metrics = {"return": metrics["return_"], "max_drawdown": drawdown,
               "calmar": ((equity[-1] / 10_000.) ** (252 / len(equity)) - 1.) / abs(drawdown) if abs(drawdown) > 1e-12 else None,
               "sharpe": sqrt(252.) * mean / volatility if volatility > 0 else None,
               "closed_trades": len(closed), "win_rate": expected_win_rate,
               "win_loss_ratio": ratio, "win_loss_ratio_status": ratio_status}
    evidence = ReplayEvidence(
        "a" * 64, "b" * 64, 10_000., days,
        {"decision_coverage": "COMPLETE", "entry_order_type": "MARKET", "exit_order_type": "MARKET",
         "entry_limit_parameter": 0., "exit_limit_ratio": .1, "fee_rate": fee_rate,
         "instrument": {"lot_size": 100, "price_tick": .001, "price_limit_ratio": .1}},
        tuple(decisions), tuple(orders), tuple(fills), tuple(account), tuple(trades), metrics,
        tuple(daily), (),
    )
    return replace(evidence, content_hash=hash_replay_evidence(evidence))


@pytest.mark.parametrize("gross_returns,fee_rate,expected", [
    pytest.param((), 0., None, id="no-closed-trades"),
    pytest.param((.1,), 0., 1., id="profitable"),
    pytest.param((-.1,), 0., 0., id="losing"),
    pytest.param((0.,), 0., 0., id="break-even"),
    pytest.param((.1, -.1, 0.), 0., 1 / 3, id="mixed"),
    pytest.param((.1,), .1, 0., id="gross-profit-net-loss"),
])
def test_public_replay_audit_authenticates_closed_trade_win_rate(gross_returns, fee_rate, expected):
    evidence = _trade_evidence(gross_returns, fee_rate, expected)
    baseline = audit_replay(evidence)
    assert baseline.status is AuditStatus.PASS, baseline.reason_codes
    assert baseline.evidence_hash == evidence.content_hash
    assert len([row for row in evidence.trades if row["status"] == "OPEN"]) == 1
    assert evidence.metrics["closed_trades"] == len(gross_returns)
    if fee_rate:
        assert gross_returns[0] > 0 and evidence.trades[0]["net_return"] < 0
    wrong = 0. if expected is None or expected > 0 else 1.
    result = audit_replay(replace(evidence, metrics={**evidence.metrics, "win_rate": wrong}))
    assert result.status is AuditStatus.FAIL
    assert result.reason_codes == ("METRIC_MISMATCH",)
