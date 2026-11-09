"""Frozen V2 feedback follows confirmed fills without changing journal facts."""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from execution_channels.instruments import BarFrequency
from execution_channels.instruments import TimeInterval
from execution_channels.policy import AccountPolicy
from execution_channels.policy import CashAvailabilityPolicy
from execution_channels.contracts import DecisionPoint
from execution_channels.contracts import EquityPlan
from execution_channels.policy import ResearchExecutionSpec
from execution_channels.policy import UsEquitySpec
from execution_channels.historical.frozen_equity import _FrozenEquityExecutor


START = datetime(2026, 10, 1, 14, tzinfo=timezone.utc)


def executor(actions=None):
    spec = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
        AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.)
    if actions is None:
        actions = pd.DataFrame(columns=['Date', 'EventId', 'Kind'])
    return _FrozenEquityExecutor(specification=spec, initial_cash=1000., fee_rate=.001)


def transition(account, side, quantity, *, limit=10.1, blocked=False, price=10.):
    start = START + timedelta(minutes=30 * account.revision)
    interval = TimeInterval(start, start + timedelta(minutes=30))
    plan = EquityPlan(f'plan-{account.revision}', DecisionPoint(start, start, interval),
        1. if side in {'BUY', 'HOLD'} else 0., quantity, side,
        limit if side == 'BUY' else None, account.revision, price, account.spec.fingerprint)
    bar = pd.Series(dict(BarStart=start, Date=interval.end, Open=price, High=price + .2,
                         Low=price - .2, Close=price, Volume=1000, Amount=10000,
                         ExecutionBlocked=blocked))
    constraint = pd.Series(dict(Date=start, AvailableDate=start, QuantityStep=1, PriceTick=.01,
                                Tradable=True, SettlementAt=interval.end))
    return plan, bar, constraint


def execute(account, side, quantity, **kwargs):
    plan, bar, constraint = transition(account, side, quantity, **kwargs)
    return account.execute(plan, bar, constraint=constraint)


def test_EC29_C02_closed_cycle_requires_final_confirmed_exit():
    from execution_channels.instruments import MarketId
    from execution_channels.session_contracts import OrderSide
    from test_portfolio_parity import setup,facts,plan,order
    account,stamp,_ = setup(MarketId.US)
    bar,rule = facts(stamp)
    account.execute_account_plan(plan(account,stamp,(order(OrderSide.BUY,200),)),bar,constraint=rule)
    assert account.position_feedback.latest_closed is None
    partial_at = stamp+timedelta(minutes=30)
    bar,rule = facts(partial_at)
    account.execute_account_plan(plan(account,partial_at,(order(OrderSide.SELL,100),)),bar,constraint=rule)
    assert account.quantity == 100 and account.position_feedback.latest_closed is None
    final_at = stamp+timedelta(minutes=60)
    bar,rule = facts(final_at)
    account.execute_account_plan(plan(account,final_at,(order(OrderSide.SELL,100),)),bar,constraint=rule)
    closed = account.position_feedback.latest_closed
    assert account.quantity == 0 and closed.quantity == 0
    assert closed.buy_cost == pytest.approx(2002.)
    assert closed.sell_income == pytest.approx(1998.)
    assert closed.buy_fills == 1 and closed.sell_fills == 2
    assert account.cash == pytest.approx(9996.)


def test_EC29_C03_reentry_preserves_last_closed_cycle_and_starts_new_cost():
    account = executor()
    execute(account,'BUY',10)
    cycle = execute(account,'SELL',10).closed_cycle_feedback.latest
    reopened = execute(account,'BUY',5)
    assert reopened.quantity == 5 and reopened.closed_cycle_feedback.latest == cycle
    second = execute(account,'SELL',5).closed_cycle_feedback.latest
    assert second.cycle_id != cycle.cycle_id and second.entry_quantity == 5
    assert second.entry_cost == pytest.approx(50.05)
