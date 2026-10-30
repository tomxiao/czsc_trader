"""One row kernel and atomic decision boundaries preserve equity evidence."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from types import MappingProxyType

import pandas as pd
import pytest
from dataflows import BarFrequency, TimeInterval
from strategy_runtime import (AccountPolicy, CashAvailabilityPolicy, DecisionPoint,
                              CnEquitySpec, EquityPlan, ResearchExecutionSpec, UsEquitySpec)
import strategy_runtime.equity as equity_contracts
from trading_execution_engine.equity import EquityHistoricalExecutor


START = datetime(2026, 10, 1, 14, tzinfo=timezone.utc)
TABLES = ('decisions', 'orders', 'fills', 'corporate_action_entries',
          'account_points', 'account_daily', 'trades')


def account(actions=None, *, deferred=False):
    policy = CashAvailabilityPolicy.SETTLED_ONLY if deferred else CashAvailabilityPolicy.IMMEDIATE_RESEARCH
    spec = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
                                AccountPolicy('USD', policy), 1, .01, .01, 0.)
    if actions is None:
        actions = pd.DataFrame(columns=['Date', 'EventId', 'Kind'])
    return EquityHistoricalExecutor(specification=spec, initial_cash=1000., fee_rate=.001, actions=actions)


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


def test_cached_spec_fingerprint_preserves_all_numeric_spellings_and_nested_contracts(monkeypatch):
    base = account().spec
    variants = [base, replace(base), replace(base, price_tick=1), replace(base, price_tick=1.),
        replace(base, buy_premium=0), replace(base, buy_premium=0.), replace(base, buy_premium=-0.),
        replace(base, slippage_bp=0), replace(base, slippage_bp=0.), replace(base, slippage_bp=-0.),
        replace(base, account=AccountPolicy('USD', CashAvailabilityPolicy.SETTLED_ONLY)),
        replace(base, market=CnEquitySpec(), account=AccountPolicy('CNY', CashAvailabilityPolicy.IMMEDIATE_RESEARCH)),
        replace(base, decision_clock=BarFrequency.DAILY), replace(base, inclusive_touch=True),
        replace(base, data_latency_seconds=1), replace(base, quantity_step=2)]
    expected = [equity_contracts.equity_hash(asdict(spec)) for spec in variants]
    original_asdict = equity_contracts.asdict
    calls = []

    def counted(value):
        calls.append(value)
        return original_asdict(value)

    equity_contracts._execution_spec_fingerprint.cache_clear()
    monkeypatch.setattr(equity_contracts, 'asdict', counted)
    assert [spec.fingerprint for spec in variants] == expected
    first_calls = len(calls)
    assert first_calls == len(set(expected))
    assert [replace(spec).fingerprint for spec in reversed(variants)] == list(reversed(expected))
    assert len(calls) == first_calls


@pytest.mark.parametrize('mapping', [False, True])
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


@pytest.mark.parametrize('case,reason', [
    ('observed', 'FILLED'), ('touch', 'LIMIT_NOT_CROSSED'),
    ('blocked', 'KNOWN_INTERRUPTION'), ('zero', 'ZERO_VOLUME'),
    ('missing', 'MISSING_BAR'), ('volume', 'INSUFFICIENT_BAR_VOLUME'),
    ('not_tradable', 'NOT_TRADABLE'),
])
def test_series_and_immutable_mapping_have_identical_seven_tables_and_idempotency(case, reason):
    old, new = account(), account()
    plan, bar, constraint = transition(old)
    if case == 'touch':
        bar.update(Open=10.2, High=10.3, Low=10.1, Close=10.2)
    elif case == 'blocked':
        bar['ExecutionBlocked'] = True
    elif case == 'zero':
        bar.update(BarStatus='ZERO_VOLUME', Volume=0., Amount=0.)
    elif case == 'missing':
        bar.update({name: float('nan') for name in ('Open', 'High', 'Low', 'Close', 'Volume', 'Amount')})
        bar['BarStatus'] = 'MISSING'
    elif case == 'volume':
        bar['Volume'] = 9.
    elif case == 'not_tradable':
        constraint['Tradable'] = False
    first = old.execute(plan, pd.Series(bar), constraint=pd.Series(constraint))
    second = new.execute(plan, MappingProxyType(bar), constraint=MappingProxyType(constraint))
    assert first == second
    assert old.completed == new.completed
    assert new.rows['orders'][0]['reason'] == reason
    assert new.execute(plan, MappingProxyType(bar), constraint=MappingProxyType(constraint)) == second
    for name in TABLES:
        pd.testing.assert_frame_equal(getattr(old.finish(), name), getattr(new.finish(), name))
    changed = {**bar, 'ExecutionBlocked': not bar['ExecutionBlocked']}
    with pytest.raises(ValueError, match='different execution facts'):
        new.execute(plan, MappingProxyType(changed), constraint=MappingProxyType(constraint))
    assert len(new.rows['decisions']) == 1


def test_outer_failure_restores_snapshot_actions_successful_execution_and_idempotency():
    stamp = START + timedelta(minutes=30)
    actions = pd.DataFrame([
        dict(Date=stamp, EventId='split', Kind='SPLIT', Ratio=2., CashPerShare=0., PayAt=pd.NaT),
        dict(Date=stamp, EventId='dividend', Kind='CASH_DIVIDEND', Ratio=1., CashPerShare=.25, PayAt=stamp),
    ])
    executor = account(actions)
    step(executor)
    before = snapshot(executor)
    with pytest.raises(RuntimeError, match='strategy state commit'):
        with executor.transaction():
            portfolio = executor.snapshot_at(stamp, stamp)
            assert portfolio.quantity == 20 and portfolio.cash == pytest.approx(904.9)
            plan, bar, constraint = transition(executor, 'SELL', 20, Open=5., High=5.2, Low=4.8, Close=5.)
            executor.execute(plan, MappingProxyType(bar), constraint=MappingProxyType(constraint))
            assert 'plan-1' in executor.completed and executor.quantity == 0
            raise RuntimeError('strategy state commit')
    assert snapshot(executor) == before
    with executor.transaction():
        executor.snapshot_at(stamp, stamp)
        executor.execute(plan, MappingProxyType(bar), constraint=MappingProxyType(constraint))
    assert executor.quantity == 0 and len(executor.rows['trades']) == 1
    assert len(executor.rows['actions']) == 3
    assert executor.applied == {'split', 'dividend'}
    assert set(executor.completed) == {'plan-0', 'plan-1'}


def test_snapshot_only_failure_and_pending_dividend_payment_are_rolled_back():
    stamp = START + timedelta(minutes=30)
    pay = stamp + timedelta(minutes=30)
    actions = pd.DataFrame([dict(Date=stamp, EventId='dividend', Kind='CASH_DIVIDEND',
                                 Ratio=1., CashPerShare=.5, PayAt=pay)])
    executor = account(actions)
    step(executor)
    before = snapshot(executor)
    with pytest.raises(ValueError, match='strategy evaluation'):
        with executor.transaction():
            executor.snapshot_at(stamp, stamp)
            assert executor.receivable == 5.
            raise ValueError('strategy evaluation')
    assert snapshot(executor) == before
    executor.snapshot_at(stamp, stamp)
    before_payment = snapshot(executor)
    with pytest.raises(ValueError, match='state validation'):
        with executor.transaction():
            executor.snapshot_at(pay, pay)
            assert executor.receivable == 0 and not executor.pending
            raise ValueError('state validation')
    assert snapshot(executor) == before_payment


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


def test_transaction_never_copies_or_enumerates_existing_completed_journal():
    class ExistingCompleted(dict):
        def __iter__(self):
            raise AssertionError('must not enumerate old keys')

        def keys(self):
            raise AssertionError('must not copy old keys')

        def items(self):
            raise AssertionError('must not enumerate old values')

        def __deepcopy__(self, memo):
            raise AssertionError('must not deepcopy old keys')

    class ExistingRow(dict):
        def __deepcopy__(self, memo):
            raise AssertionError('must not copy existing ledger rows')

    executor = account()
    executor.completed = ExistingCompleted({'earlier': 'identity'})
    executor.rows['decisions'].append(ExistingRow(marker=True))
    with pytest.raises(KeyboardInterrupt):
        with executor.transaction():
            step(executor)
            raise KeyboardInterrupt()
    assert len(executor.completed) == 1 and executor.completed['earlier'] == 'identity'
    assert len(executor.rows['decisions']) == 1
    assert executor.rows['decisions'][0]['marker']
    assert executor.revision == 0 and executor.quantity == 0


def test_action_rows_are_materialized_once_and_source_is_isolated(monkeypatch):
    stamp = START + timedelta(minutes=30)
    actions = pd.DataFrame([dict(Date=stamp, EventId='split', Kind='SPLIT',
                                 Ratio=2., CashPerShare=0., PayAt=pd.NaT)])
    executor = account(actions)
    actions.loc[0, 'Ratio'] = 3.
    assert isinstance(executor._action_events, tuple)
    def forbidden(*args, **kwargs):
        raise AssertionError('per-bar DataFrame tuple creation is forbidden')
    monkeypatch.setattr(pd.DataFrame, 'itertuples', forbidden)
    step(executor)
    assert executor.snapshot_at(stamp, stamp).quantity == 20
    step(executor, 'SELL', 20, Open=5., High=5.2, Low=4.8, Close=5.)
    assert len(executor.rows['actions']) == 1


def test_invalid_mapping_transition_rejects_and_restores_prior_account():
    executor = account()
    step(executor)
    before = snapshot(executor)
    plan, bar, constraint = transition(executor, 'SELL', 11)
    with pytest.raises(ValueError, match='sell quantity exceeds'):
        executor.execute(plan, MappingProxyType(bar), constraint=MappingProxyType(constraint))
    assert snapshot(executor) == before
    with pytest.raises(ValueError, match='CAUSAL_TIME_VIOLATION'):
        executor.execute(replace(plan, quantity=10), MappingProxyType(bar),
            constraint=MappingProxyType({**constraint, 'AvailableDate': constraint['Date']+timedelta(seconds=1)}))
    assert snapshot(executor) == before
    with pytest.raises(TypeError, match='Series or Mapping'):
        executor.execute(plan, [], constraint=MappingProxyType(constraint))
    assert snapshot(executor) == before


def test_mapping_settlement_and_event_ledger_matches_series():
    stamp = START + timedelta(minutes=30)
    actions = pd.DataFrame([
        dict(Date=stamp, EventId='dividend', Kind='CASH_DIVIDEND', Ratio=1., CashPerShare=.25,
             PayAt=stamp+timedelta(minutes=30)),
        dict(Date=stamp, EventId='split', Kind='SPLIT', Ratio=2., CashPerShare=0., PayAt=pd.NaT),
    ])
    executors = [account(actions, deferred=True), account(actions, deferred=True)]
    for executor, row in zip(executors, (pd.Series, MappingProxyType), strict=True):
        plan, bar, constraint = transition(executor)
        executor.execute(plan, row(bar), constraint=row(constraint))
        with executor.transaction():
            executor.snapshot_at(stamp, stamp)
            plan, bar, constraint = transition(executor, 'SELL', 20, Open=5., High=5.2, Low=4.8, Close=5.)
            constraint['SettlementAt'] = stamp+timedelta(hours=2)
            executor.execute(plan, row(bar), constraint=row(constraint))
        assert executor.quantity == 0 and executor.receivable == pytest.approx(99.9)
        assert executor.cash == pytest.approx(904.9)
        before = snapshot(executor)
        with pytest.raises(RuntimeError, match='commit'):
            with executor.transaction():
                executor.snapshot_at(constraint['SettlementAt'], constraint['SettlementAt'])
                assert executor.receivable == 0 and executor.cash == pytest.approx(1004.8)
                raise RuntimeError('commit')
        assert snapshot(executor) == before
        executor.snapshot_at(constraint['SettlementAt'], constraint['SettlementAt'])
        assert executor.receivable == 0 and executor.cash == pytest.approx(1004.8)
    for name in TABLES:
        pd.testing.assert_frame_equal(getattr(executors[0].finish(), name), getattr(executors[1].finish(), name))
