"""US broker facts traverse the same durable execution core as CN/inspection."""
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from execution_channels.instruments import AssetClass, BarFrequency, InstrumentId, MarketId
from execution_channels.policy import AccountPolicy, CashAvailabilityPolicy, CnEquitySpec, ResearchExecutionSpec, UsEquitySpec
from execution_channels.futu.broker import (BrokerAccount, BrokerOrder, BrokerPosition,
    BrokerSnapshot, BrokerSubmissionUncertainError, BrokerOrderRejectedError, PaperTradingSafetyError)
from execution_channels.futu.channel import ChannelAccountConfig, FUTU_US_SIM_CHANNEL_ID, FUTU_SIMULATE_CN_CHANNEL_ID
from execution_channels.futu.equity_contracts import EquityAccountRules
from execution_channels.futu.futu_execution import ChannelExecution, ChannelReconciliationError, FeeReconciliationPolicy, OrderSubmissionBatchError
from pte_support import decision


START = datetime.fromisoformat('2026-11-05T09:30:00-05:00')
FILL_TIME = '2026-11-05T09:31:00-05:00'
POLICY = FeeReconciliationPolicy(Decimal('.01'), Decimal('5'), Decimal('.01'))


class Broker:
    channel_id = FUTU_US_SIM_CHANNEL_ID
    channel_account_id = 'us-test'

    def __init__(self):
        self.orders = []
        self.submissions = 0
        self.cancelled = []
        self.cash = Decimal('1000')
        self.quantity = self.sellable = 0
        self.lose_response = False
        self.reject = False
        self.market, self.currency, self.symbol = 'US', 'USD', 'MU'
        self.frozen_cash = 0
        self.start, self.fill_time = START, FILL_TIME

    def account_snapshot(self):
        positions = () if not self.quantity else (BrokerPosition(self.symbol, self.quantity, self.sellable),)
        return BrokerSnapshot(BrokerAccount('SIMULATE', self.market, float(self.cash), 1000, self.frozen_cash,
            currency=self.currency, channel_account_id=self.channel_account_id), positions, ())

    def order_snapshot(self):
        return tuple(self.orders)

    def historical_order_snapshot(self, start, end):
        return tuple(self.orders)

    def place_order(self, intent):
        self.submissions += 1
        if self.reject:
            raise BrokerOrderRejectedError('confirmed broker price restriction')
        order = BrokerOrder(str(41 + self.submissions), intent.symbol, intent.side, intent.quantity, intent.limit_price,
            'SUBMITTED', 0, 0, intent.intent_id, updated_at=self.start.isoformat(),
            channel_account_id=self.channel_account_id, session=intent.session)
        self.orders.append(order)
        if self.lose_response:
            raise BrokerSubmissionUncertainError('response lost after acceptance')
        return order

    def fill(self, quantity, average, *, fee=None, status='FILLED_ALL'):
        value = Decimal(str(average)) * quantity
        fee = value * Decimal('.0005') if fee is None else Decimal(str(fee))
        self.cash = Decimal('1000') - value - fee
        self.quantity = self.sellable = quantity
        self.orders = [replace(self.orders[0], status=status, cumulative_filled_quantity=quantity,
            average_fill_price=float(average), cumulative_notional=value, updated_at=self.fill_time)]

    def cancel_order(self, identity):
        self.cancelled.append(identity)

    def close(self):
        pass


def _live_us(root):
    config = ChannelAccountConfig('us-test', FUTU_US_SIM_CHANNEL_ID, 77)
    store = root.register_channel_account(config, capital=Decimal('1000'))
    execution_spec = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
        AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.)
    rules = EquityAccountRules(InstrumentId(MarketId.US, AssetClass.STOCK, 'MU'), execution_spec)
    store.create_virtual_account('strategy', 'strategy', 'v1', 'a'*64, '1000', symbol='MU',
        asset_type='stock', strategy_id='S999', strategy_name_snapshot='Fixture', strategy_version='v1',
        release_hash='b'*64, qualification_snapshot='PAPER_READY', selection_data_cutoff='2026-09-30',
        equity_rules=rules)
    store.create_channel_reconciliation_account()
    broker = Broker()
    engine = ChannelExecution(store, broker, config=config, fee_policy=POLICY, now=lambda: START)
    engine.refresh_orders()
    store.set_paused(False)
    store.set_virtual_paused('strategy', False)
    payload = decision().to_store_payload()
    payload.update(contract_version='advice.equity.v1', decision_id='buy', symbol='MU',
        strategy={'strategy_id':'S999','version':'v1','release_hash':'b'*64},
        signal_date='2026-11-05', valid_session='2026-11-05', available_cash=1000,
        target_quantity=2, delta_quantity=2, cycle_target_quantity=2, action='BUY',
        orders=[{'side':'BUY','quantity':2,'order_type':'LIMIT','limit_price':100}],
        equity_execution_interval={'start':START.isoformat(),'end':'2026-11-05T10:00:00-05:00'},
        equity_observed_through=START.isoformat())
    store.save_account_decision('strategy', payload)
    intent = store.create_account_intent(account_id='strategy', decision_id='buy', order_sequence=0,
        symbol='MU', side='BUY', quantity=2, limit_price=100, valid_session='2026-11-05')
    return root, store, broker, engine, intent


@pytest.fixture
def live_us(memory_store):
    # Single-connection business outcomes use the real SQL execution paths.
    return _live_us(memory_store())


@pytest.fixture
def durable_us(new_store, tmp_path):
    # Recovery and atomic persistence failures retain a normal file-backed DB.
    root = new_store(tmp_path / 'db')
    try:
        yield _live_us(root)
    finally:
        root.close()


def test_us_partial_repeat_and_restart_preserve_cumulative_notional(durable_us):
    _, store, broker, engine, _ = durable_us
    # The same US session is supplied in Beijing time, without a Shanghai gate.
    engine.now = lambda: datetime.fromisoformat('2026-11-05T22:30:00+08:00')
    engine.submit_pending()
    broker.fill(1, '99.1234', status='FILLED_PART')
    engine.refresh_orders()
    engine.refresh_orders()
    assert len(store.account_fills('strategy')) == 1
    engine = ChannelExecution(store, broker, config=engine.config, fee_policy=POLICY, now=lambda: START)
    broker.fill(2, '99.2234')
    engine.refresh_orders()
    engine.refresh_orders()
    fills = store.account_fills('strategy')
    assert len(fills) == 2 and broker.submissions == 1
    assert [Decimal(str(x['price'])) for x in fills] == [Decimal('99.1234'), Decimal('99.3234')]
    account = store.virtual_account('strategy')
    assert account['quantity'] == 2 and Decimal(account['frozen_cash']) == 0
    assert Decimal(account['cash']) == Decimal('801.4540')
    order = store.account_orders('strategy')[0]
    assert order['channel_order_id'] == 'us-test:42' and order['broker_order_id'] == '42'
    assert engine.status()['currency'] == 'USD'


def test_us_unknown_submission_recovers_without_resubmit(live_us):
    _, store, broker, engine, intent = live_us
    broker.lose_response = True
    with pytest.raises(BrokerSubmissionUncertainError):
        engine.submit_pending()
    assert store.account_intent(intent['intent_id'])['status'] == 'SUBMISSION_UNCERTAIN'
    engine.refresh_orders()
    assert len(store.account_orders('strategy')) == 1 and broker.submissions == 1


def test_fill_report_and_release_rollback_together(durable_us, monkeypatch):
    _, store, broker, engine, _ = durable_us
    engine.submit_pending()
    original = store.virtual_account('strategy')
    broker.fill(2, '99.1234')
    def fail(*args, **kwargs):
        raise RuntimeError('report persistence failure')
    with monkeypatch.context() as patch:
        patch.setattr(store, 'update_channel_order_report', fail)
        with pytest.raises(RuntimeError, match='persistence failure'):
            engine.refresh_orders()
    assert store.virtual_account('strategy') == original
    assert store.account_fills('strategy') == []
    engine.refresh_orders()
    assert store.virtual_account('strategy')['quantity'] == 2


def test_us_fee_variance_separate_from_strategy_model_and_idempotent(live_us):
    _, store, broker, engine, _ = live_us
    engine.submit_pending()
    broker.fill(2, '99', fee='1.99')
    engine.refresh_orders()
    engine.refresh_orders()
    assert Decimal(store.virtual_account('strategy')['cash']) == Decimal('801.9010')
    assert Decimal(store.channel_reconciliation_account()['cash']) == Decimal('-1.8910')
    events = store.query_audit_events(event_type='CHANNEL_FEE_VARIANCE_RECONCILED')
    assert len(events) == 1 and events[0]['details']['fee_source'] == 'INFERRED_CASH'


def test_us_cash_difference_without_policy_remains_blocked(live_us):
    _, store, broker, engine, _ = live_us
    engine.fee_policy = None
    engine.submit_pending()
    broker.fill(2, '99', fee='1.99')
    with pytest.raises(ChannelReconciliationError):
        engine.refresh_orders()
    assert store.get_setting('futu_cash_reconciliation_status') == 'UNATTRIBUTED'


def test_us_cash_adjustment_after_fill_is_atomic_and_idempotent(durable_us, monkeypatch):
    _, store, broker, engine, _ = durable_us
    engine.submit_pending()
    broker.fill(2, '99', fee='1.99')
    broker.cash += Decimal('5.00')
    checkpoint = store.get_setting('futu_cash_reconciliation_checkpoint')
    set_setting = store.set_setting

    def fail_checkpoint(key, value):
        if key == 'futu_cash_reconciliation_checkpoint':
            raise RuntimeError('checkpoint write failed')
        set_setting(key, value)

    with monkeypatch.context() as patch:
        patch.setattr(store, 'set_setting', fail_checkpoint)
        with pytest.raises(RuntimeError, match='checkpoint write failed'):
            engine.refresh_orders()
    assert store.get_setting('futu_cash_reconciliation_checkpoint') == checkpoint
    assert Decimal(store.channel_reconciliation_account()['cash']) == 0
    assert not store.query_audit_events(event_type='CHANNEL_CASH_ADJUSTMENT_RECONCILED')

    engine.refresh_orders()
    engine.refresh_orders()
    assert Decimal(store.virtual_account('strategy')['cash']) == Decimal('801.9010')
    assert Decimal(store.channel_reconciliation_account()['cash']) == Decimal('3.1090')
    event, = store.query_audit_events(event_type='CHANNEL_CASH_ADJUSTMENT_RECONCILED')
    assert event['details']['origin'] == 'UNCLASSIFIED'
    assert not store.query_audit_events(event_type='CHANNEL_FEE_VARIANCE_RECONCILED')
    assert store.account_invariant_violations() == []
    assert store.get_setting('futu_cash_reconciliation_status') == 'OK'


def test_us_cash_adjustment_checks_terminal_fills_missing_from_current_orders(live_us, monkeypatch):
    _, store, broker, engine, _ = live_us
    engine.submit_pending()
    broker.fill(2, '99')
    engine.now = lambda: datetime.fromisoformat(FILL_TIME).replace(microsecond=500000)
    engine.refresh_orders()
    unknown = BrokerOrder('43', 'MU', 'SELL', 1, 100, 'FILLED_ALL', 1, 100, 'unknown',
        updated_at=FILL_TIME, channel_account_id=broker.channel_account_id)
    monkeypatch.setattr(broker, 'historical_order_snapshot', lambda start, end: (*broker.orders, unknown))
    broker.cash += Decimal('100')
    with pytest.raises(ChannelReconciliationError, match='UNATTRIBUTED'):
        engine.refresh_orders()
    assert Decimal(store.channel_reconciliation_account()['cash']) == 0
    assert store.get_setting('channel_reconciliation_status') == 'BLOCKED'


def test_us_missing_interval_blocks_before_submission(live_us, monkeypatch):
    _, store, broker, engine, _ = live_us
    original = store.account_decision
    def decision_without_interval(*args, **kwargs):
        value = original(*args, **kwargs)
        value['payload'].pop('equity_execution_interval', None)
        return value
    monkeypatch.setattr(store, 'account_decision', decision_without_interval)
    with pytest.raises(Exception, match='requires a prepared trading interval'):
        engine.submit_pending()
    assert broker.submissions == 0


@pytest.fixture(params=['CN', 'US'])
def live_market(request, memory_store):
    """Both production channel profiles use real stores, reservations and reconciliation."""
    market = request.param
    broker = Broker()
    broker.market = market
    broker.currency = 'CNY' if market == 'CN' else 'USD'
    broker.symbol = '588080.SH' if market == 'CN' else 'MU'
    broker.channel_id = FUTU_SIMULATE_CN_CHANNEL_ID if market == 'CN' else FUTU_US_SIM_CHANNEL_ID
    broker.channel_account_id = f'{market.lower()}-test'
    broker.start = datetime.fromisoformat('2026-11-05T09:30:00' + ('+08:00' if market == 'CN' else '-05:00'))
    broker.fill_time = (broker.start + timedelta(minutes=1)).isoformat()
    step, price = (100, 1) if market == 'CN' else (1, 100)
    root = memory_store()
    config = ChannelAccountConfig(broker.channel_account_id, broker.channel_id, 77)
    store = root.register_channel_account(config, capital=Decimal('1000'))
    rules = EquityAccountRules(InstrumentId(MarketId(market), AssetClass.ETF if market == 'CN' else AssetClass.STOCK, broker.symbol),
        ResearchExecutionSpec(CnEquitySpec() if market == 'CN' else UsEquitySpec(), BarFrequency.M30,
            AccountPolicy(broker.currency, CashAvailabilityPolicy.IMMEDIATE_RESEARCH), step, .001 if market == 'CN' else .01, .01, 0.))
    store.create_virtual_account('strategy', 'strategy', 'v1', 'a'*64, '1000', symbol=broker.symbol,
        asset_type='etf' if market == 'CN' else 'stock', strategy_id='S999', strategy_name_snapshot='Fixture', strategy_version='v1',
        release_hash='b'*64, qualification_snapshot='PAPER_READY', selection_data_cutoff='2026-09-30', equity_rules=rules)
    store.create_channel_reconciliation_account()
    clock = [broker.start]
    engine = ChannelExecution(store, broker, config=config, fee_policy=POLICY, now=lambda: clock[0])
    engine.refresh_orders()
    store.set_paused(False)
    store.set_virtual_paused('strategy', False)

    def adopt(identity, side='BUY'):
        account = store.virtual_account('strategy')
        quantity = 2 * step
        target = account['quantity'] + quantity if side == 'BUY' else 0
        payload = decision().to_store_payload()
        payload.update(contract_version='advice.equity.v1', decision_id=identity, symbol=broker.symbol,
            strategy={'strategy_id':'S999','version':'v1','release_hash':'b'*64},
            signal_date=clock[0].date().isoformat(), valid_session=clock[0].date().isoformat(),
            actual_quantity=account['quantity'], available_cash=account['cash'],
            target_quantity=target, delta_quantity=quantity if side == 'BUY' else -quantity,
            cycle_target_quantity=target, action=side,
            orders=[{'side':side,'quantity':quantity,'order_type':'LIMIT','limit_price':price}],
            equity_execution_interval={'start':clock[0].isoformat(),'end':(clock[0] + timedelta(minutes=30)).isoformat()},
            equity_observed_through=clock[0].isoformat(),
            strategy_output={'execution_plan':{'target':.2 if side == 'BUY' else 0,
                'planning_result':{'status':'READY','reasons':[],'desired_quantity':target,'planned_quantity':target}}})
        store.save_account_decision('strategy', payload)
        return store.create_account_intent(account_id='strategy', decision_id=identity, order_sequence=0,
            symbol=broker.symbol, side=side, quantity=quantity, limit_price=price, order_type='LIMIT', valid_session=clock[0].date().isoformat())
    try:
        yield store, broker, engine, clock, adopt, step, price
    finally:
        root.close()


@pytest.mark.parametrize('outcome', ['rejected', 'cash', 'expired', 'partial'])
def test_known_business_outcome_preserves_target_and_next_cycle_progress(live_market, outcome):
    store, broker, engine, clock, adopt, step, price = live_market
    intent = adopt('first')
    original = store.account_decision('strategy', 'first')['payload']
    if outcome == 'rejected':
        broker.reject = True
    elif outcome == 'cash':
        broker.frozen_cash = 1000
    elif outcome == 'expired':
        clock[0] += timedelta(minutes=31)
    engine.submit_pending()
    if outcome == 'partial':
        broker.fill(step, price, status='FILLED_PART')
        clock[0] += timedelta(minutes=31)
        engine.refresh_orders()
        assert len(broker.cancelled) == 1
        broker.fill(step, price, status='CANCELLED_PART')
        engine.refresh_orders()
    expected = {'rejected':'ORDER_REJECTED','cash':'EXECUTION_CONSTRAINED','expired':'EXECUTION_EXPIRED','partial':'NORMAL_PARTIAL'}[outcome]
    terminal = store.account_intent(intent['intent_id'])
    assert terminal['payload']['termination_reason'] == expected
    assert terminal['attention_required'] is False
    account = store.virtual_account('strategy')
    assert account['health'] == 'OK'
    assert account['quantity'] == (step if outcome == 'partial' else 0)
    assert Decimal(account['frozen_cash']) == 0
    assert store.account_decision('strategy', 'first')['payload'] == original
    assert store.account_decision('strategy', 'first')['status'] == 'INCOMPLETE'
    assert store.account_decision('strategy', 'first')['state_reason'] == expected
    assert len(store.account_fills('strategy')) == (1 if outcome == 'partial' else 0)
    effect = store.decision_execution_effect('strategy', 'first', valuation_price=price, at=clock[0] + timedelta(minutes=1))
    assert effect.status == ('PARTIAL' if outcome == 'partial' else 'NOT_EXECUTED')
    assert effect.target_weight == .2 and effect.actual_quantity == account['quantity']
    submitted = broker.submissions
    broker.reject, broker.frozen_cash = False, 0
    engine.submit_pending()
    engine.refresh_orders()
    assert broker.submissions == submitted
    assert len(store.account_fills('strategy')) == (1 if outcome == 'partial' else 0)
    clock[0] = broker.start + timedelta(days=1)
    adopt('next-cycle')
    engine.submit_pending()
    assert broker.submissions == submitted + 1
    assert store.account_decision('strategy', 'first')['status'] == 'INCOMPLETE'
    assert store.virtual_account('strategy')['health'] == 'OK'
    assert store.account_invariant_violations() == []


def test_sellable_shortage_is_terminal_but_ledger_corruption_remains_blocking(live_market):
    store, broker, engine, clock, adopt, step, price = live_market
    adopt('buy')
    engine.submit_pending()
    broker.fill(2 * step, price)
    clock[0] += timedelta(minutes=1)
    engine.refresh_orders()
    clock[0] = broker.start + timedelta(days=1)
    intent = adopt('sell', 'SELL')
    broker.sellable = 0
    engine.submit_pending()
    result = store.account_intent(intent['intent_id'])
    assert result['payload']['termination_reason'] == 'EXECUTION_CONSTRAINED'
    assert result['attention_required'] is False
    assert store.virtual_account('strategy')['health'] == 'OK'
    assert store.virtual_account('strategy')['quantity'] == 2 * step
    broker.sellable = 2 * step
    engine.submit_pending()
    assert broker.submissions == 1
    assert store.account_decision('strategy', 'sell')['payload']['target_quantity'] == 0
    # Deliberately corrupt the materialized balance without a ledger event.
    # A legitimate broker share adjustment is separately supported and is not corruption.
    broker.quantity += step
    store._connection.execute('UPDATE virtual_accounts SET quantity=quantity+? WHERE account_id=?', (step, 'strategy'))
    store._connection.commit()
    with pytest.raises(ChannelReconciliationError):
        engine.refresh_orders()
    assert store.get_setting('channel_reconciliation_status') == 'BLOCKED'


def test_illegal_submission_and_unknown_outcome_still_block(live_market):
    store, broker, engine, clock, adopt, step, price = live_market
    intent = adopt('buy')
    broker.lose_response = True
    with pytest.raises(BrokerSubmissionUncertainError):
        engine.submit_pending()
    assert store.account_intent(intent['intent_id'])['status'] == 'SUBMISSION_UNCERTAIN'
    assert store.virtual_account('strategy')['health'] == 'BLOCKED'
    assert broker.submissions == 1
    broker.channel_account_id = 'wrong-channel'
    with pytest.raises(PaperTradingSafetyError):
        engine.submit_pending()
    assert broker.submissions == 1


def test_real_submission_safety_error_keeps_batch_failure_and_account_block(live_market, monkeypatch):
    store, broker, engine, clock, adopt, step, price = live_market
    intent = adopt('unsafe')

    def unsafe_order(_intent):
        raise PaperTradingSafetyError('broker environment no longer SIMULATE')

    monkeypatch.setattr(broker, 'place_order', unsafe_order)
    with pytest.raises(OrderSubmissionBatchError, match='PaperTradingSafetyError'):
        engine.submit_pending()
    failed = store.account_intent(intent['intent_id'])
    assert failed['status'] == 'SUBMISSION_FAILED'
    assert failed['attention_required'] is True
    assert not failed['payload'].get('termination_reason')
    assert store.virtual_account('strategy')['health'] == 'BLOCKED'
    assert store.account_fills('strategy') == []
    assert broker.orders == []
