"""Frozen V2 feedback follows confirmed fills without changing journal facts."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import pickle

import pandas as pd
import pytest
from dataflows import BarFrequency, TimeInterval
from strategy_runtime import (AccountPolicy, CashAvailabilityPolicy, DecisionPoint, EquityPlan,
                              ResearchExecutionSpec, UsEquitySpec)
from trading_execution_engine.frozen_equity import _FrozenEquityExecutor


START = datetime(2026, 10, 1, 14, tzinfo=timezone.utc)


def executor(actions=None):
    spec = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
        AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.)
    if actions is None:
        actions = pd.DataFrame(columns=['Date', 'EventId', 'Kind'])
    return _FrozenEquityExecutor(specification=spec, initial_cash=1000., fee_rate=.001, actions=actions)


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


@pytest.mark.parametrize('failed_quantity, failed_limit, reason', [
    (10, 9., 'LIMIT_NOT_CROSSED'), (1000, 10.1, 'INSUFFICIENT_CASH')])
def test_closed_cycle_only_after_confirmed_exit_and_survives_reentry_and_restore(
        failed_quantity, failed_limit, reason):
    account = executor()
    assert account.snapshot().closed_cycle_feedback.latest is None
    failed = execute(account, 'BUY', failed_quantity, limit=failed_limit)
    assert failed.quantity == 0 and failed.closed_cycle_feedback.latest is None
    assert account.rows['orders'][-1]['reason'] == reason
    entry_plan, bar, constraint = transition(account, 'BUY', 10)
    opened = account.execute(entry_plan, bar, constraint=constraint)
    assert opened.quantity == 10 and opened.closed_cycle_feedback.latest is None
    blocked = execute(account, 'SELL', 10, blocked=True)
    assert blocked.quantity == 10 and blocked.closed_cycle_feedback.latest is None
    exit_plan, bar, constraint = transition(account, 'SELL', 10, price=12.)
    closed = account.execute(exit_plan, bar, constraint=constraint)
    cycle = closed.closed_cycle_feedback.latest
    assert closed.quantity == 0
    assert cycle.cycle_id == entry_plan.plan_id
    assert cycle.entry_interval == entry_plan.point.execution_interval
    assert cycle.exit_interval == exit_plan.point.execution_interval
    assert cycle.exit_observed_through == exit_plan.point.observed_through
    assert cycle.entry_quantity == 10 and cycle.entry_cost == pytest.approx(100.1)
    assert closed.cash == pytest.approx(1019.78)
    lengths = {key: len(rows) for key, rows in account.rows.items()}
    assert account.execute(exit_plan, bar, constraint=constraint) == closed
    assert {key: len(rows) for key, rows in account.rows.items()} == lengths

    account = pickle.loads(pickle.dumps(account))
    assert account.snapshot() == closed
    assert execute(account, 'BUY', 5).closed_cycle_feedback.latest == cycle
    assert execute(account, 'SELL', 5, blocked=True).closed_cycle_feedback.latest == cycle
    second = execute(account, 'SELL', 5).closed_cycle_feedback.latest
    assert second.cycle_id != cycle.cycle_id and second.entry_quantity == 5
    assert second.entry_cost == pytest.approx(50.05)
    # Existing evidence remains a trade journal, not a new feedback serialization.
    assert set(account.finish().trades.columns) == {
        'cycle_id', 'entry_at', 'exit_at', 'cost', 'income', 'net_pnl', 'net_return', 'status'}


@pytest.mark.parametrize('complexity', ['additional_buy', 'partial_sell', 'split'])
def test_unrepresentable_cycles_keep_old_execution_and_recover_only_after_new_close(complexity):
    actions = None
    if complexity == 'split':
        actions = pd.DataFrame([dict(Date=START + timedelta(minutes=30), EventId='split', Kind='SPLIT',
                                     Ratio=2., CashPerShare=0., PayAt=pd.NaT)])
    account = executor(actions)
    execute(account, 'BUY', 10)
    if complexity == 'additional_buy':
        unsupported = execute(account, 'BUY', 5)
        assert unsupported.quantity == 15
    elif complexity == 'partial_sell':
        unsupported = execute(account, 'SELL', 5)
        assert unsupported.quantity == 5
    else:
        unsupported = account.snapshot_at(START + timedelta(minutes=30), START + timedelta(minutes=30))
        assert unsupported.quantity == 20
    assert unsupported.closed_cycle_feedback is None
    assert execute(account, 'SELL', account.quantity).closed_cycle_feedback is None
    assert execute(account, 'BUY', 5).closed_cycle_feedback is None
    recovered = execute(account, 'SELL', 5).closed_cycle_feedback.latest
    assert recovered.entry_quantity == 5 and recovered.entry_cost == pytest.approx(50.05)
    assert len(account.finish().trades) == 2


def test_split_invalidates_old_raw_closed_feedback_even_while_flat():
    stamp = START + timedelta(minutes=60)
    actions = pd.DataFrame([dict(Date=stamp, EventId='split', Kind='SPLIT', Ratio=2.,
                                 CashPerShare=0., PayAt=pd.NaT)])
    account = executor(actions)
    execute(account, 'BUY', 10)
    assert execute(account, 'SELL', 10).closed_cycle_feedback.latest is not None
    assert account.snapshot_at(stamp, stamp).closed_cycle_feedback is None
    assert execute(account, 'BUY', 5).closed_cycle_feedback is None
    assert execute(account, 'SELL', 5).closed_cycle_feedback.latest.entry_quantity == 5


def test_rejected_transition_rolls_back_feedback_and_journal():
    account = executor()
    execute(account, 'BUY', 10)
    before = account.snapshot()
    lengths = {key: len(rows) for key, rows in account.rows.items()}
    plan, bar, constraint = transition(account, 'SELL', 11)
    with pytest.raises(ValueError, match='sell quantity exceeds'):
        account.execute(plan, bar, constraint=constraint)
    assert account.snapshot() == before
    assert {key: len(rows) for key, rows in account.rows.items()} == lengths
    # The old plan API permits an earlier observation boundary; execution remains
    # valid, but it cannot supply the stronger closed-cycle observation contract.
    plan = replace(plan, quantity=10, point=replace(plan.point, observed_through=START))
    assert account.execute(plan, bar, constraint=constraint).closed_cycle_feedback is None
    assert account.quantity == 0 and len(account.finish().trades) == 1


def test_failed_split_restores_feedback_capability_and_account():
    stamp = START + timedelta(minutes=30)
    actions = pd.DataFrame([dict(Date=stamp, EventId='split', Kind='SPLIT', Ratio=1.5,
                                 CashPerShare=0., PayAt=pd.NaT)])
    account = executor(actions)
    execute(account, 'BUY', 1)
    before = account.snapshot()
    with pytest.raises(ValueError, match='fractional split entitlement'):
        account.snapshot_at(stamp, stamp)
    assert account.snapshot() == before
    assert account.applied == set() and account.rows['actions'] == []
    # execute's separate transaction wrapper must preserve the same state.
    with pytest.raises(ValueError, match='fractional split entitlement'):
        execute(account, 'SELL', 1)
    assert account.snapshot() == before
    assert len(account.rows['decisions']) == 1 and len(account.rows['fills']) == 1
