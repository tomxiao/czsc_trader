"""Independent EC planning/account tests: no SRT or DFLS fixture dependency."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
from dataclasses import replace

import pandas as pd
import pytest

from execution_channels.contracts import AccountSnapshot, ExecutionPrecision, ReplayPoint, SellRemainderPolicy
from execution_channels.historical import PortfolioHistoricalExecutor
from execution_channels.instruments import AssetClass, BarFrequency, InstrumentId, MarketId
from execution_channels.planning import plan_account_decision
from execution_channels.planning.intent import DecisionExplanation, TradeIntent
from execution_channels.policy import ExecutionPolicy, AccountPolicy, CashAvailabilityPolicy, CnEquitySpec, ResearchExecutionSpec, UsEquitySpec
from execution_channels.serialization import from_record, to_record
from execution_channels.historical.channel import HistoricalReplayChannel, HistoricalDecision, AdoptionStatus
from execution_channels.state import StateRecord


def fixture(market):
    instrument = InstrumentId(market, AssetClass.STOCK, 'MU' if market is MarketId.US else '600000.SH')
    start = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc) if market is MarketId.US else datetime(2026, 1, 5, 1, 30, tzinfo=timezone.utc)
    end = start + timedelta(hours=6 if market is MarketId.US else 4)
    spec = ResearchExecutionSpec(UsEquitySpec() if market is MarketId.US else CnEquitySpec(), BarFrequency.DAILY,
        AccountPolicy(instrument.currency, CashAvailabilityPolicy.IMMEDIATE_RESEARCH),
        1 if market is MarketId.US else 100, .01, .01, 0.)
    point = ReplayPoint(start-timedelta(days=1), start, start, end, '2026-01-05', ExecutionPrecision.BAR_INTERVAL)
    row = {'BarStart': start, 'Date': end, 'Open': 10., 'High': 11., 'Low': 9., 'Close': 10.5, 'Volume': 10000.}
    constraint = {'Date': start, 'AvailableDate': start, 'QuantityStep': spec.quantity_step, 'PriceTick': .01,
        'Tradable': True, 'BuySellableAt': start, 'SettlementAt': end, 'SellRemainderPolicy': 'FULL_LIQUIDATION',
        'PriceLimitPolicy': 'EXPLICIT_UNBOUNDED' if market is MarketId.US else 'DATED_LIMITS',
        'PriceLimitLower': None if market is MarketId.US else 9., 'PriceLimitUpper': None if market is MarketId.US else 11.}
    return instrument, spec, point, row, constraint


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
def test_explicit_records_preserve_planning_and_confirmed_ledger(market):
    instrument, spec, point, row, constraint = fixture(market)
    account = AccountSnapshot(instrument, instrument.currency, point.decision_at, 0,
                              Decimal('10000'), Decimal('10000'), Decimal(0), 0, 0)
    intent = TradeIntent(1., DecisionExplanation({'reason': 'independent boundary'}))
    restored = from_record(ResearchExecutionSpec, to_record(spec))
    assert restored.fingerprint == spec.fingerprint
    plan = plan_account_decision(from_record(TradeIntent, to_record(intent)), point,
        from_record(AccountSnapshot, json.loads(json.dumps(to_record(account, json_safe=True)))),
        10., restored, owner='test', implementation='a'*64, fee_rate=.001,
        execution_policy=ExecutionPolicy("TARGET_POSITION", {}), sell_remainder_policy=SellRemainderPolicy.FULL_LIQUIDATION)
    assert plan.orders[0].quantity == (900 if market is MarketId.CN else 989)
    assert plan.orders[0].limit_price == 10.1
    executor = PortfolioHistoricalExecutor(specification=spec, initial_cash=10000., fee_rate=.001,
                                          price_basis='HFQ')
    assert executor.account_snapshot(point, instrument).quantity == 0
    after = executor.execute_account_plan(plan, row, constraint=constraint)
    quantity = plan.orders[0].quantity
    assert after.quantity == quantity
    assert after.cash == pytest.approx(10000.-quantity*10.*1.001)
    assert executor.position_feedback.active.quantity == quantity
    # Repeating identical facts cannot add another fill or subtract more cash.
    assert executor.execute_account_plan(plan, row, constraint=constraint) == after
    assert len(executor.rows['fills']) == 1


def test_records_reject_unknown_fields_and_boolean_quantity():
    instrument, _, point, _, _ = fixture(MarketId.US)
    account = AccountSnapshot(instrument, 'USD', point.decision_at, 0, 10., 10., 0., 0, 0)
    record = to_record(account)
    with pytest.raises(ValueError, match='unknown execution fields'):
        from_record(AccountSnapshot, {**record, 'silent_default': True})
    with pytest.raises(TypeError):
        from_record(AccountSnapshot, {**record, 'quantity': True})
    with pytest.raises(ValueError, match='available assets'):
        from_record(AccountSnapshot, {**record, 'available_cash': 11.})


def test_suppressed_input_creates_no_orders_and_keeps_quantity():
    instrument, spec, point, _, _ = fixture(MarketId.US)
    account = AccountSnapshot(instrument, 'USD', point.decision_at, 1, 10., 10., 0., 20, 20)
    plan = plan_account_decision(TradeIntent(0., DecisionExplanation({'reason': 'missing observation'})),
        point, account, 10., spec, owner='test', implementation='a'*64, fee_rate=.001,
        execution_policy=ExecutionPolicy("TARGET_POSITION", {}), sell_remainder_policy=SellRemainderPolicy.FULL_LIQUIDATION, suppressed=True)
    assert not plan.orders and not plan.legs
    assert plan.target_quantity == 20
    assert plan.evidence['signal_status'] == 'SUPPRESSED_UNOBSERVED_BAR'


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
def test_frozen_binary_intent_uses_channel_sizing_and_suppression(market):
    from execution_channels.contracts import DecisionPoint, EquityPortfolio
    from execution_channels.instruments import TimeInterval
    from execution_channels.planning.frozen_equity import FrozenEquityIntent, plan_frozen_equity
    _, spec, point, _, _ = fixture(market)
    intent = FrozenEquityIntent(DecisionPoint(point.observed_through, point.decision_at,
        TimeInterval(point.execution_start, point.execution_end)), 1, 10., {'reason':'frozen target'})
    portfolio = EquityPortfolio(10000., 0, 0., 0)
    arguments = dict(owner='test', implementation='a'*64, fee_rate=.001)
    plan = plan_frozen_equity(from_record(FrozenEquityIntent, to_record(intent)), portfolio, spec, **arguments)
    assert (plan.side, plan.quantity, plan.limit_price) == ('BUY', 900 if market is MarketId.CN else 989, 10.1)
    held = replace(portfolio, quantity=17)
    sell = plan_frozen_equity(replace(intent, target=0), held, spec, **arguments)
    assert (sell.side, sell.quantity, sell.limit_price) == ('SELL',17,None)
    suppressed = plan_frozen_equity(replace(intent, target=0, suppressed=True), held, spec, **arguments)
    assert (suppressed.side, suppressed.quantity, suppressed.target) == ('WAIT',0,1.)
    with pytest.raises(ValueError, match='fee rate'):
        plan_frozen_equity(intent, portfolio, spec, **{**arguments,'fee_rate':True})


@pytest.mark.parametrize('field,invalid', [
    pytest.param('Date', pd.NaT, id='missing-date'),
    pytest.param('AvailableDate', pd.NaT, id='missing-available-date'),
    pytest.param('BuySellableAt', pd.NaT, id='missing-sellable-at'),
    pytest.param('SettlementAt', pd.NaT, id='missing-settlement-at'),
    pytest.param('Date', datetime(2026,1,5), id='naive-datetime'),
    pytest.param('Date', '2026-01-05T09:30:00', id='naive-string'),
])
def test_constraint_normalization_rejects_incomplete_execution_clocks(field, invalid):
    from execution_channels.historical.input_facts import normalize_constraint_times
    _, _, _, _, rule = fixture(MarketId.US)
    with pytest.raises(ValueError, match=field + ' requires'):
        normalize_constraint_times({**rule, field:invalid})


@pytest.mark.parametrize('bound_executor', [False, True])
def test_channel_rejects_incomplete_execution_clocks_at_binding(bound_executor):
    # The shared normalizer owns the invalid-value matrix; both bindings must call it.
    instrument, spec, _, row, rule = fixture(MarketId.US)
    rule = {**rule, 'Date':pd.NaT}
    with pytest.raises(ValueError, match='Date requires'):
        if bound_executor:
            executor = PortfolioHistoricalExecutor(specification=spec,initial_cash=10000.,
                fee_rate=.001,price_basis='HFQ')
            HistoricalReplayChannel.from_executor(executor,account_id='account',instrument=instrument,
                bars=[row],constraints=[rule])
        else:
            HistoricalReplayChannel(account_id='account',instrument=instrument,specification=spec,
                initial_cash=10000.,fee_rate=.001,bars=pd.DataFrame([row]),
                constraints=pd.DataFrame([rule]))


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
@pytest.mark.parametrize('text_dates', [False, True])
def test_execution_constraint_clocks_normalize_without_mutating_input(market, text_dates):
    from execution_channels.historical.input_facts import normalize_constraint_times, CONSTRAINT_TIMES
    instrument, spec, _, row, rule = fixture(market)
    from zoneinfo import ZoneInfo
    for field in CONSTRAINT_TIMES:
        stamp = rule[field].astimezone(ZoneInfo(instrument.timezone))
        rule[field] = stamp.isoformat() if text_dates else stamp
    original = dict(rule)
    normalized = normalize_constraint_times(rule)
    assert rule == original
    assert all(type(normalized[key]) is datetime and normalized[key].tzinfo is timezone.utc
               for key in CONSTRAINT_TIMES)
    channel = HistoricalReplayChannel(account_id='account',instrument=instrument,specification=spec,
        initial_cash=10000.,fee_rate=.001,bars=pd.DataFrame([row]),constraints=pd.DataFrame([rule]),)
    assert channel._constraints[row['BarStart']] == normalized


@pytest.mark.parametrize('field', ['Date','AvailableDate','BuySellableAt','SettlementAt'])
def test_direct_executor_rejects_nat_constraints_even_for_buy(field):
    instrument, spec, point, row, rule = fixture(MarketId.US)
    executor = PortfolioHistoricalExecutor(specification=spec, initial_cash=10000., fee_rate=.001,price_basis='HFQ')
    account = executor.account_snapshot(point,instrument)
    plan = plan_account_decision(TradeIntent(1.,DecisionExplanation({})),point,account,10.,spec,
        owner='account',implementation='a'*64,fee_rate=.001,
        execution_policy=ExecutionPolicy("TARGET_POSITION", {}), sell_remainder_policy=SellRemainderPolicy.FULL_LIQUIDATION)
    with pytest.raises(ValueError, match=field + ' requires'):
        executor.execute_account_plan(plan,row,constraint={**rule,field:pd.NaT})
    assert executor.cash == 10000. and executor.quantity == executor.revision == 0
    assert not executor.rows['fills']


def test_historical_imports_do_not_load_strategy_data_or_application_packages():
    source = Path(__file__).resolve().parents[2] / 'src'
    program = '''
import sys, importlib.abc
class BlockHostImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'strategy_runtime','dataflows','paper_trading_engine','czsc_trader'}:
            raise AssertionError('EC imported a forbidden host or data dependency: ' + fullname)
sys.meta_path.insert(0, BlockHostImports())
sys.path.insert(0, sys.argv[1])
from execution_channels.historical import PortfolioHistoricalExecutor, HistoricalExecutor
from execution_channels.planning import plan_account_decision
from execution_channels.state import AccountStrategyState
'''
    completed = subprocess.run([sys.executable, '-I', '-c', program, str(source)],
                               capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
def test_historical_channel_adopts_before_execution_and_preserves_idempotency(market):
    instrument, spec, point, row, constraint = fixture(market)
    prior = {**row, 'BarStart': row['BarStart']-timedelta(days=1), 'Date': point.observed_through}
    prior_constraint = {**constraint, 'Date': prior['BarStart'], 'AvailableDate': prior['BarStart'],
                        'BuySellableAt': prior['BarStart'], 'SettlementAt': prior['Date']}
    channel = HistoricalReplayChannel(account_id='account', instrument=instrument, specification=spec,
        initial_cash=10000., fee_rate=.001, bars=pd.DataFrame([prior,row]),
        constraints=pd.DataFrame([prior_constraint,constraint]),)
    channel.advance(point.decision_at)
    before = channel.snapshot('account', at=point.decision_at)
    plan = plan_account_decision(TradeIntent(1., DecisionExplanation({'reason':'entry'})), point,
        before.account, 10., spec, owner='account', implementation='a'*64, fee_rate=.001,
        execution_policy=ExecutionPolicy("TARGET_POSITION", {}), sell_remainder_policy=SellRemainderPolicy.FULL_LIQUIDATION)
    decision = HistoricalDecision(plan, before.strategy.revision, StateRecord((('seen',1),)),
                                  StateRecord(), before.next_event_cursor, 'owner-binding')
    assert channel.adopt('account', replace(decision,expected_state_revision=3)) is AdoptionStatus.STALE_SNAPSHOT
    assert channel.adopt('account', decision) is AdoptionStatus.ADOPTED
    assert channel.executor.quantity == 0
    assert channel.state.account.get('seen') == 1
    assert channel.state.cycle is None
    assert channel.adopt('account', decision) is AdoptionStatus.ALREADY_ADOPTED
    with pytest.raises(RuntimeError, match='unresolved'):
        channel.finish()
    advanced = channel.advance(point.execution_end)
    assert advanced.completed_plan == plan.plan_identity
    after = channel.snapshot('account', at=point.execution_end)
    assert after.account.quantity == plan.target_quantity
    assert after.position.active.quantity == plan.target_quantity
    assert after.strategy.cycle is not None
    assert after.strategy.revision == 1
    assert channel.adopt('account', decision) is AdoptionStatus.ALREADY_ADOPTED
    assert channel.advance(point.execution_end).completed_plan is None
    with pytest.raises(ValueError,match='different content'):
        channel.adopt('account', replace(decision,account_values=StateRecord((('seen',2),))))
