"""Frozen V2 execution retains row, economic and transaction boundaries."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import MappingProxyType

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
TABLES = ('decisions', 'orders', 'fills', 'account_entries',
          'account_points', 'account_daily', 'trades')


def account(actions=None, *, deferred=False):
    policy = CashAvailabilityPolicy.SETTLED_ONLY if deferred else CashAvailabilityPolicy.IMMEDIATE_RESEARCH
    spec = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
                                AccountPolicy('USD', policy), 1, .01, .01, 0.)
    if actions is None:
        actions = pd.DataFrame(columns=['Date', 'EventId', 'Kind'])
    return _FrozenEquityExecutor(specification=spec, initial_cash=1000., fee_rate=.001)


def transition(executor, side='BUY', quantity=10, **updates):
    start = START + timedelta(minutes=30 * executor.revision)
    interval = TimeInterval(start, start + timedelta(minutes=30))
    plan = EquityPlan(f'plan-{executor.revision}', DecisionPoint(start, start, interval),
        1. if side in {'BUY', 'HOLD'} else 0., quantity, side,
        10.1 if side == 'BUY' else None, executor.revision, 10., executor.spec.fingerprint)
    bar = dict(BarStart=start, Date=interval.end, Open=10., High=10.2, Low=9.8,
               Close=10., Volume=1000., Amount=10000., BarStatus='OBSERVED', ExecutionBlocked=False)
    bar.update(updates)
    constraint = dict(Date=start, AvailableDate=start, QuantityStep=1, PriceTick=.01,
                      Tradable=True, SettlementAt=interval.end)
    return plan, bar, constraint


def step(executor, side='BUY', quantity=10, **updates):
    plan, bar, constraint = transition(executor, side, quantity, **updates)
    return executor.execute(plan, MappingProxyType(bar), constraint=MappingProxyType(constraint))


def snapshot(executor):
    return deepcopy({key: value for key, value in vars(executor).items()
                     if key not in {'actions', '_action_events', 'spec', '_transactions'}})


# Independent risk: EC29; responsibility-level assertions.
@pytest.mark.parametrize('mapping', [True], ids=['EC29-C01'])
def test_replacing_executor_spec_rejects_old_plan_despite_cached_fingerprint(mapping):
    executor = account()
    plan, bar, constraint = transition(executor)
    original = executor.spec
    assert original.fingerprint == plan.specification_hash
    executor.spec = replace(original, buy_premium=.02)
    assert executor.spec.fingerprint != original.fingerprint
    before = snapshot(executor)
    row_type = MappingProxyType if mapping else pd.Series
    with pytest.raises(ValueError, match='MARKET_CONTRACT_MISMATCH: execution plan'):
        executor.execute(plan, row_type(bar), constraint=row_type(constraint))
    assert snapshot(executor) == before
    executor.spec = original
    executor.execute(plan, row_type(bar), constraint=row_type(constraint))
    assert len(executor.rows['decisions']) == 1


# Session-date boundaries and representation acceptance are orthogonal risks.
# Each timezone offset is exercised close enough to midnight to affect the output.


# Independent risk: EC12; responsibility-level assertions.


# Independent risk: EC11; responsibility-level assertions.
def test_nested_failed_savepoint_can_retry_and_outer_failure_preserves_prior_keys():
    executor = account()
    step(executor)
    original = snapshot(executor)
    with pytest.raises(RuntimeError, match='outer'):
        with executor.transaction():
            with pytest.raises(RuntimeError, match='inner'):
                with executor.transaction():
                    step(executor, 'SELL')
                    raise RuntimeError('inner')
            assert snapshot(executor) == original
            step(executor, 'SELL')
            assert len(executor.completed) == 2
            raise RuntimeError('outer')
    assert snapshot(executor) == original
    assert not executor._transactions


# Independent risk: EC11; responsibility-level assertions.
def test_EC11_C01_second_posting_failure_restores_only_current_interval():
    executor = account()
    step(executor,'BUY',10)
    before = snapshot(executor)
    failed_postings = []
    class RejectNewFill(list):
        def append(self,entry):
            failed_postings.append((executor.cash,executor.quantity,entry['quantity']))
            assert executor.cash == pytest.approx(999.8)
            assert executor.quantity == 0 and entry['quantity'] == 10
            raise RuntimeError('current interval fill journal failed')
    # This transaction owns the complete frozen-adapter interval. The already
    # confirmed previous interval must survive a failure after economic posting.
    executor.rows['fills'] = RejectNewFill(executor.rows['fills'])
    try:
        with pytest.raises(RuntimeError,match='current interval fill journal failed'):
            step(executor,'SELL',10)
    finally:
        executor.rows['fills'] = list(executor.rows['fills'])
    assert len(failed_postings) == 1
    assert failed_postings[0] == pytest.approx((999.8,0,10))
    assert snapshot(executor) == before
    assert executor.quantity == 10 and len(executor.rows['fills']) == 1
    assert len(executor.completed) == 1
