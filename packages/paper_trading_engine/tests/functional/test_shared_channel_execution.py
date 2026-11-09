"""US broker facts traverse the same durable execution core as CN/inspection."""
from dataclasses import replace
from datetime import datetime
from decimal import Decimal

import pytest

from execution_channels.instruments import AssetClass, BarFrequency, InstrumentId, MarketId
from execution_channels.policy import AccountPolicy, CashAvailabilityPolicy, ResearchExecutionSpec, UsEquitySpec
from execution_channels.futu.broker import (BrokerAccount, BrokerOrder, BrokerPosition,
    BrokerSnapshot, BrokerSubmissionUncertainError, BrokerOrderRejectedError)
from execution_channels.futu.channel import ChannelAccountConfig, FUTU_US_SIM_CHANNEL_ID
from execution_channels.futu.equity_contracts import EquityAccountRules
from execution_channels.futu.futu_execution import ChannelExecution, ChannelReconciliationError, FeeReconciliationPolicy
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


# Independent risk: EC19; responsibility-level assertions.
def test_EC19_C01_cumulative_notional_uses_delta_not_latest_average(durable_us):
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


# Independent risk: EC18; responsibility-level assertions.
def test_us_unknown_submission_recovers_without_resubmit(live_us):
    _, store, broker, engine, intent = live_us
    broker.lose_response = True
    with pytest.raises(BrokerSubmissionUncertainError):
        engine.submit_pending()
    assert store.account_intent(intent['intent_id'])['status'] == 'SUBMISSION_UNCERTAIN'
    engine.refresh_orders()
    assert len(store.account_orders('strategy')) == 1 and broker.submissions == 1


# Independent risk: EC19; responsibility-level assertions.
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


# Independent risk: EC21; responsibility-level assertions.
@pytest.mark.parametrize('fault',[False,True],ids=['EC21-C02','EC21-C04'])
def test_us_cash_adjustment_atomicity_and_idempotency(durable_us,monkeypatch,fault):
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

    if fault:
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


# Independent risk: EC21; responsibility-level assertions.
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


def test_EC19_C02_duplicate_partial_report_posts_once(live_us):
    _, store, broker, engine, _ = live_us
    engine.submit_pending()
    broker.fill(1,'99.1234',status='FILLED_PART')
    engine.refresh_orders()
    first_account = store.virtual_account('strategy')
    first_fills = store.account_fills('strategy')
    engine.refresh_orders()
    assert len(first_fills) == 1
    assert store.account_fills('strategy') == first_fills
    assert store.virtual_account('strategy') == first_account
    assert first_account['quantity'] == 1


def test_EC19_C04_terminal_partial_releases_only_unfilled_reservation(live_us):
    _, store, broker, engine, intent = live_us
    engine.submit_pending()
    broker.fill(1,'99.1234',status='FILLED_PART')
    engine.refresh_orders()
    assert Decimal(store.virtual_account('strategy')['frozen_cash']) > 0
    broker.fill(1,'99.1234',status='CANCELLED_PART')
    engine.refresh_orders()
    account = store.virtual_account('strategy')
    assert account['quantity'] == 1
    assert Decimal(account['frozen_cash']) == 0
    assert Decimal(account['cash']) == Decimal('900.8270')
    assert len(store.account_fills('strategy')) == 1
    assert Decimal(store.account_fills('strategy')[0]['fee']) == Decimal('.0496')
    assert store.account_intent(intent['intent_id'])['attention_required']


def test_EC19_C05_incremental_fees_sum_to_rounded_cumulative_fee(live_us):
    _, store, broker, engine, _ = live_us
    engine.submit_pending()
    broker.fill(1,'99.1234',status='FILLED_PART')
    engine.refresh_orders()
    assert Decimal(store.account_fills('strategy')[0]['fee']) == Decimal('.0496')
    broker.fill(2,'99.2234')
    engine.refresh_orders()
    fills = store.account_fills('strategy')
    assert len(fills) == 2
    assert [Decimal(item['fee']) for item in fills] == [Decimal('.0496'),Decimal('.0496')]
    assert sum(Decimal(item['fee']) for item in fills) == Decimal('.0992')
    before = store.virtual_account('strategy')
    engine.refresh_orders()
    assert store.account_fills('strategy') == fills
    assert store.virtual_account('strategy') == before
    assert Decimal(before['cash']) == Decimal('801.4540')
