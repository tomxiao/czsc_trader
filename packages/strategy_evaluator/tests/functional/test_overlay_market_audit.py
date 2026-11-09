"""Independent market-rule proof for real checkpoint fills and rejected buys."""

from dataclasses import replace
from math import sqrt

import pytest

from strategy_evaluator import AuditStatus, audit_replay
from test_intraday_replay_audit import _evidence


def _metrics(first, final, *, closed=1):
    returns = [first / 10000 - 1, final / first - 1]
    mean = sum(returns) / 2
    std = sqrt(sum((r - mean) ** 2 for r in returns))
    dd = min(first / 10000 - 1, final / max(first, 10000) - 1)
    return {"return": final / 10000 - 1, "max_drawdown": dd,
            "calmar": ((final / 10000) ** 126 - 1) / abs(dd),
            "sharpe": sqrt(252) * mean / std, "closed_trades": closed,
            "win_rate": 0. if closed else None, "win_loss_ratio": None,
            "win_loss_ratio_status": "NO_WINS" if closed else "NO_CLOSED_TRADES"}


def market_evidence(*, rejected_buy=False):
    value = _evidence()
    spec = {**value.execution_spec, "market_rules": {
        "contract_version": "DAILY_RANGE_V3", "symbol": "510500.SH", "suspended_sessions": [],
        "suspension_information": "NOT_PROVIDED", "sessions": [
            {"session": "2026-09-17", "down_limit": 8., "up_limit": 12., "price_tick": .001},
            {"session": "2026-09-18", "down_limit": 8.,
             "up_limit": 10.5 if rejected_buy else 12., "price_tick": .001},
        ]}}
    bars = [dict(row) for row in value.execution_intraday]
    bars.insert(1, {"time": "2026-09-17T11:30", "open": 10., "close": 10.})
    bars = tuple({**row, "high": max(row["open"], row["close"]),
                 "low": min(row["open"], row["close"])} for row in bars)
    orders = [dict(row) for row in value.orders]
    orders[1]["quantity"] = orders[2]["quantity"] = 400
    fills = [dict(row) for row in value.fills]
    fills[0]["fill_time"] = "2026-09-17T09:30"
    fills[1].update(quantity=400, fees=40., fill_time="2026-09-18T09:30")
    fills[2].update(quantity=400, fees=36.)
    trades = ({**value.trades[0], "quantity": 400},)
    final_cash = 5484.
    if rejected_buy:
        orders = [orders[0], {**orders[1], "status": "UNFILLED", "reason": "ORDER_PRICE_OUTSIDE_LIMITS"}]
        fills, trades, final_cash = fills[:1], (), 5960.
    final_equity = final_cash + 3600
    account = (value.account_daily[0], {**value.account_daily[1], "cash": final_cash, "equity": final_equity})
    daily = tuple({**row, "high": max(row["open"], row["close"]),
                   "low": min(row["open"], row["close"])} for row in value.execution_daily)
    return replace(value, execution_spec=spec, orders=tuple(orders), fills=tuple(fills),
                   trades=trades, account_daily=account, execution_intraday=bars,
                   execution_daily=daily, metrics=_metrics(9960., final_equity, closed=0 if rejected_buy else 1))


@pytest.mark.risk_cases('SE-36-C04')
def test_market_audit_rejects_unproven_rejections_or_missing_dependent_sell():
    rejected = market_evidence(rejected_buy=True)
    assert audit_replay(rejected).status is AuditStatus.PASS
    completed_sell = market_evidence()
    invalid = replace(rejected, orders=(*rejected.orders, completed_sell.orders[-1]),
                      fills=(*rejected.fills, completed_sell.fills[-1]))
    result = audit_replay(invalid)
    assert result.status is AuditStatus.FAIL
    assert 'INVALID_INTRADAY_ORDER_PAIR' in result.reason_codes
