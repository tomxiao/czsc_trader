"""US broker facts traverse the same durable execution core as CN/inspection."""
from dataclasses import replace
from datetime import datetime
from decimal import Decimal

import pytest

from dataflows import AssetClass, BarFrequency, InstrumentId, MarketId
from strategy_runtime import AccountPolicy, CashAvailabilityPolicy, ResearchExecutionSpec, UsEquitySpec
from paper_trading_engine.broker import (BrokerAccount, BrokerOrder, BrokerPosition,
    BrokerSnapshot, BrokerSubmissionUncertainError)
from paper_trading_engine.channel import ChannelAccountConfig, FUTU_US_SIM_CHANNEL_ID
from paper_trading_engine.equity_contracts import EquityAccountRules
from paper_trading_engine.futu_execution import ChannelExecution, ChannelReconciliationError, FeeReconciliationPolicy
from paper_trading_engine.store import PaperStore
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

    def account_snapshot(self):
        positions = () if not self.quantity else (BrokerPosition('MU', self.quantity, self.sellable),)
        return BrokerSnapshot(BrokerAccount('SIMULATE', 'US', float(self.cash), 1000, 0,
            currency='USD', channel_account_id=self.channel_account_id), positions, ())

    def order_snapshot(self):
        return tuple(self.orders)

    def historical_order_snapshot(self, start, end):
        return tuple(self.orders)

    def place_order(self, intent):
        self.submissions += 1
        order = BrokerOrder('42', intent.symbol, intent.side, intent.quantity, intent.limit_price,
            'SUBMITTED', 0, 0, intent.intent_id, updated_at=START.isoformat(),
            channel_account_id=self.channel_account_id, session=intent.session)
        self.orders = [order]
        if self.lose_response:
            raise BrokerSubmissionUncertainError('response lost after acceptance')
        return order

    def fill(self, quantity, average, *, fee=None, status='FILLED_ALL'):
        value = Decimal(str(average)) * quantity
        fee = value * Decimal('.0005') if fee is None else Decimal(str(fee))
        self.cash = Decimal('1000') - value - fee
        self.quantity = self.sellable = quantity
        self.orders = [replace(self.orders[0], status=status, cumulative_filled_quantity=quantity,
            average_fill_price=float(average), cumulative_notional=value, updated_at=FILL_TIME)]

    def cancel_order(self, identity):
        self.cancelled.append(identity)

    def close(self):
        pass


@pytest.fixture
def live_us(tmp_path):
    root = PaperStore(tmp_path / 'db')
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
    try:
        yield root, store, broker, engine, intent
    finally:
        root.close()


def test_us_partial_repeat_and_restart_preserve_cumulative_notional(live_us):
    _, store, broker, engine, _ = live_us
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


def test_fill_report_and_release_rollback_together(live_us, monkeypatch):
    _, store, broker, engine, _ = live_us
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


def test_us_execution_does_not_use_shanghai_clock(live_us):
    _, _, broker, engine, _ = live_us
    # Beijing 22:30 corresponds to the prepared US 09:30 execution interval.
    engine.now = lambda: datetime.fromisoformat('2026-11-05T22:30:00+08:00')
    engine.submit_pending()
    assert broker.submissions == 1


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
