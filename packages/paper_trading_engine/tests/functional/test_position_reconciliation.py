"""Broker differences update owned quantities without inventing fills or causes."""
from datetime import datetime, timedelta
from decimal import Decimal
import json

import pytest
from test_shared_channel_execution import live_us as live_us

from execution_channels.contracts import CycleBudget, PositionCycle
from execution_channels.entry_cycle import EntryCyclePhase
from execution_channels.instruments import AssetClass, BarFrequency, InstrumentId, MarketId, TimeInterval
from execution_channels.policy import AccountPolicy, CashAvailabilityPolicy, CnEquitySpec, UsEquitySpec, ResearchExecutionSpec
from execution_channels.state import AccountStrategyState, CycleState, StateRecord
from execution_channels.futu.channel import ChannelAccountConfig, FUTU_SIMULATE_CN_CHANNEL_ID, FUTU_US_SIM_CHANNEL_ID
from execution_channels.futu.equity_account_state import budget_to_dict, position_to_dict, recognized_events, save_document
from execution_channels.futu.store import PaperStore
from execution_channels.futu.equity_contracts import EquityAccountRules
from execution_channels.futu.equity_events import allocate_quantities


@pytest.fixture(params=list(MarketId))
def holdings(tmp_path, request):
    market = request.param
    cn = market is MarketId.CN
    instrument = InstrumentId(market, AssetClass.ETF if cn else AssetClass.STOCK, '588080.SH' if cn else 'MU')
    root = PaperStore(tmp_path / 'positions.db')
    config = ChannelAccountConfig('positions-' + market.value, FUTU_SIMULATE_CN_CHANNEL_ID if cn else FUTU_US_SIM_CHANNEL_ID, 77)
    store = root.register_channel_account(config, capital=Decimal('10000'))
    rules = EquityAccountRules(instrument, ResearchExecutionSpec(CnEquitySpec() if cn else UsEquitySpec(),
        BarFrequency.M30, AccountPolicy(instrument.currency, CashAvailabilityPolicy.IMMEDIATE_RESEARCH),
        100 if cn else 1, .001 if cn else .01, .01, 0.))
    at = datetime.fromisoformat('2026-11-05T09:30:00+08:00' if cn else '2026-11-05T09:30:00-05:00')
    interval = TimeInterval(at, at + timedelta(minutes=30))
    for account_id, quantity in (('a', 3), ('b', 1)):
        store.create_virtual_account(account_id, account_id, 'v1', 'a'*64, '1000', symbol=instrument.symbol,
            asset_type='etf' if cn else 'stock', strategy_id='S999', strategy_name_snapshot='Fixture',
            strategy_version='v1', release_hash='b'*64, qualification_snapshot='PAPER_READY',
            selection_data_cutoff='2026-09-30', equity_rules=rules)
        with store.atomic_decision_update():
            store._connection.execute('UPDATE virtual_accounts SET quantity=?,average_cost=? WHERE account_id=?',
                (quantity, '10', account_id))
            store._equity_ledger(account_id, 'seed', 'FIXTURE_CONFIRMED_HOLDING', Decimal(0), quantity, Decimal(1000), quantity, at)
            cycle = PositionCycle(account_id, interval, interval, quantity, quantity*10., 0., 0., 1, 0)
            state = AccountStrategyState(cycle=CycleState(account_id, at, StateRecord()))
            document = {'schema_version': 2, 'state': state.to_dict(), 'pending_cycle': None,
                'active': position_to_dict(cycle), 'latest_closed': None,
                'budget': budget_to_dict(CycleBudget(account_id, quantity, Decimal(1), Decimal(1000), Decimal(quantity*10), EntryCyclePhase.ACTIVE)),
                'locked_quantity': quantity, 'buy_locks': [{'at': (at+timedelta(days=1)).isoformat(), 'quantity': quantity}],
                'last_interval': None, 'last_inputs': None}
            save_document(store, account_id, document)
    try:
        yield store, instrument.symbol, at + timedelta(minutes=31)
    finally:
        root.close()


def test_unknown_quantity_change_updates_ledger_and_all_v4_locks_once(holdings):
    store, symbol, at = holdings
    results = store.reconcile_equity_positions(symbol, quantity=10, at=at)
    assert [r['quantity_after'] for r in results] == [8, 2]
    assert all(r['reason'] == 'UNKNOWN' for r in results)
    for key, expected in [('a', 8), ('b', 2)]:
        account = store.virtual_account(key)
        state = json.loads(account['account_v4_json'])
        assert account['quantity'] == state['active']['quantity'] == state['locked_quantity'] == expected
        assert state['budget']['target_quantity'] == expected
        assert sum(lock['quantity'] for lock in state['buy_locks']) == expected
        assert state['active']['buy_fills'] == 1 and state['active']['sell_fills'] == 0
        events, _ = recognized_events(store, key, 0, at)
        assert len(events) == 1 and events[0].kind.value == 'POSITION_ADJUSTMENT'
        assert events[0].reason == 'UNKNOWN' and events[0].cash_delta == 0
        assert Decimal(account['average_cost']) * expected == Decimal(30 if key == 'a' else 10)
    assert store.reconcile_equity_positions(symbol, quantity=10, at=at) == ()
    assert store.account_invariant_violations() == []
    assert store.account_fills('a') == store.account_fills('b') == []


def test_position_reconciliation_state_failure_rolls_back_every_account(holdings, monkeypatch):
    from execution_channels.futu import equity_account_state
    store, symbol, at = holdings
    before = {key: store.virtual_account(key) for key in ('a', 'b')}
    original = equity_account_state.record_v4_position_reconciliation
    def fail(store, key, **kwargs):
        if key == 'b':
            raise RuntimeError('state write failed')
        return original(store, key, **kwargs)
    monkeypatch.setattr(equity_account_state, 'record_v4_position_reconciliation', fail)
    with pytest.raises(RuntimeError, match='state write failed'):
        store.reconcile_equity_positions(symbol, quantity=8, at=at)
    assert {key: store.virtual_account(key) for key in before} == before
    assert store.account_invariant_violations() == []


def test_zero_broker_quantity_closes_cycle_without_sale_income(holdings):
    store, symbol, at = holdings
    store.reconcile_equity_positions(symbol, quantity=0, at=at)
    state = json.loads(store.virtual_account('a')['account_v4_json'])
    assert state['active'] is state['state']['cycle'] is state['locked_quantity'] is state['budget'] is None
    assert state['buy_locks'] == []
    assert state['latest_closed']['sell_income'] == 0
    assert store.account_invariant_violations() == []
    with pytest.raises(ValueError, match='no confirmed account owner'):
        store.reconcile_equity_positions(symbol, quantity=2, at=at)


def test_unknown_orders_block_quantity_attribution(holdings, monkeypatch):
    store, symbol, at = holdings
    monkeypatch.setattr(store, 'account_intents', lambda key: [{'status': 'TIMEOUT'}])
    with pytest.raises(ValueError, match='outstanding order'):
        store.reconcile_equity_positions(symbol, quantity=8, at=at)
    assert store.virtual_account('a')['quantity'] == 3


def test_stable_remainder_allocation_never_creates_fractional_units():
    assert allocate_quantities({'b': 1, 'a': 1}, 1) == {'b': 0, 'a': 1}
    assert allocate_quantities({'a': 3, 'b': 1}, 10) == {'a': 8, 'b': 2}


def test_broker_quantity_difference_is_reconciled_once_after_confirmed_orders(live_us):
    _, store, broker, engine, _ = live_us
    engine.submit_pending()
    broker.fill(2, '99')
    engine.refresh_orders()
    broker.quantity = broker.sellable = 10
    engine.now = lambda: datetime.fromisoformat('2026-11-05T10:01:00-05:00')
    engine.refresh_orders()
    engine.refresh_orders()
    assert store.virtual_account('strategy')['quantity'] == 10
    events = store.query_audit_events(event_type='CHANNEL_POSITION_RECONCILED')
    assert len(events) == 1 and events[0]['details']['reason'] == 'UNKNOWN'
    assert len(store.account_fills('strategy')) == 1
    assert store.get_setting('channel_reconciliation_status') == 'OK'


def test_broker_quantity_change_and_audit_rollback_together(live_us, monkeypatch):
    _, store, broker, engine, _ = live_us
    engine.submit_pending()
    broker.fill(2, '99')
    engine.refresh_orders()
    broker.quantity = broker.sellable = 10
    record = engine.audit.record
    def fail(event, **kwargs):
        if event == 'CHANNEL_POSITION_RECONCILED':
            raise RuntimeError('audit write failed')
        return record(event, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(engine.audit, 'record', fail)
        with pytest.raises(RuntimeError, match='audit write failed'):
            engine.refresh_orders()
    assert store.virtual_account('strategy')['quantity'] == 2
    assert store.account_invariant_violations() == []


def test_unowned_historical_fill_blocks_position_adjustment(live_us, monkeypatch):
    from execution_channels.futu.broker import BrokerOrder
    from execution_channels.futu.futu_execution import ChannelReconciliationError
    _, store, broker, engine, _ = live_us
    engine.submit_pending()
    broker.fill(2, '99')
    engine.refresh_orders()
    broker.quantity = broker.sellable = 3
    unknown = BrokerOrder('43', 'MU', 'BUY', 1, 100, 'FILLED_ALL', 1, 100, 'unknown',
        updated_at=engine.now().isoformat(), channel_account_id=broker.channel_account_id)
    monkeypatch.setattr(broker, 'historical_order_snapshot', lambda start, end: (*broker.orders, unknown))
    with pytest.raises(ChannelReconciliationError, match='完整订单记录'):
        engine.refresh_orders()
    assert store.virtual_account('strategy')['quantity'] == 2
    assert not store.query_audit_events(event_type='CHANNEL_POSITION_RECONCILED')


@pytest.mark.parametrize('late', [True, False])
def test_confirmed_broker_deadline_zero_fill_has_explicit_normal_disposition(live_us, late):
    from dataclasses import replace
    _, store, broker, engine, intent = live_us
    engine.submit_pending()
    stamp = '2026-11-05T10:00:01-05:00' if late else '2026-11-05T09:31:00-05:00'
    broker.orders = [replace(broker.orders[0], status='CANCELLED_ALL', updated_at=stamp)]
    engine.now = lambda: datetime.fromisoformat(stamp)
    engine.refresh_orders()
    result = store.account_intent(intent['intent_id'])
    assert bool(result['attention_required']) is not late
    assert (result['payload'].get('termination_reason') == 'NORMAL_UNFILLED') is late
    assert (store.virtual_account('strategy')['health'] == 'BLOCKED') is not late
