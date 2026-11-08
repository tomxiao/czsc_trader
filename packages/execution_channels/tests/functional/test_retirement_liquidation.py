"""Retirement uses confirmed broker fills and the ordinary durable account ledger."""
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
import json
import sqlite3
from types import SimpleNamespace

import pytest

from execution_channels.contracts import PositionCycle
from execution_channels.entry_cycle import EntryCyclePhase, EntryCycleState
from execution_channels.instruments import AssetClass, BarFrequency, InstrumentId, MarketId, TimeInterval
from execution_channels.policy import AccountPolicy, CashAvailabilityPolicy, CnEquitySpec, ResearchExecutionSpec, UsEquitySpec
from execution_channels.state import AccountStrategyState, CycleState, StateRecord
from execution_channels.futu.account_retirement import AccountRetirementRequest, AccountRetirementStatus, RetirementSession
from execution_channels.futu.broker import BrokerAccount, BrokerOrder, BrokerOrderRejectedError, BrokerPosition, BrokerSnapshot, BrokerSubmissionUncertainError
from execution_channels.futu.channel import ChannelAccountConfig, FUTU_SIMULATE_CN_CHANNEL_ID, FUTU_US_SIM_CHANNEL_ID
from execution_channels.futu.equity_account_state import position_to_dict, save_document
from execution_channels.futu.equity_contracts import EquityAccountRules
from execution_channels.futu.futu_execution import ChannelExecution, FeeReconciliationPolicy
from execution_channels.futu.store import PaperStore


FEE = Decimal('.001')
POLICY = FeeReconciliationPolicy(Decimal('.01'), Decimal('5'), Decimal('.01'))


class RetirementBroker:
    """Explicit external facts; fills are never inferred from an accepted order."""

    def __init__(self, config, symbol, quantity, price, clock):
        self.channel_id, self.channel_account_id = config.channel_id, config.channel_account_id
        self.market, self.currency = config.market, config.currency
        self.symbol, self.quantity, self.sellable = symbol, quantity, quantity
        self.initial_quantity, self.price, self.clock = quantity, price, clock
        self.cash = Decimal('800')
        self.orders, self.placed, self.cancelled = [], [], []
        self.lose_response = False
        self.reject = False
        self.defer_cash = False

    def account_snapshot(self):
        positions = (() if not self.quantity else
                     (BrokerPosition(self.symbol, self.quantity, self.sellable),))
        return BrokerSnapshot(BrokerAccount('SIMULATE', self.market, float(self.cash),
            float(self.cash + self.quantity * self.price), 0,
            currency=self.currency, channel_account_id=self.channel_account_id), positions, ())

    def order_snapshot(self):
        return tuple(self.orders)

    def historical_order_snapshot(self, start, end):
        return tuple(self.orders)

    def place_order(self, intent):
        self.placed.append(intent)
        if self.reject:
            raise BrokerOrderRejectedError('market order rejected by exchange')
        order = BrokerOrder(str(len(self.placed)), intent.symbol, intent.side, intent.quantity,
            intent.limit_price, 'SUBMITTED', 0, 0, intent.intent_id,
            updated_at=self.clock[0].isoformat(), channel_account_id=self.channel_account_id,
            session=intent.session, order_type=intent.order_type)
        self.orders.append(order)
        if self.lose_response:
            raise BrokerSubmissionUncertainError('accepted; response lost')
        return order

    def fill(self, cumulative_quantity, *, status='FILLED_ALL'):
        value = Decimal(cumulative_quantity) * self.price
        self.quantity = self.sellable = self.initial_quantity - cumulative_quantity
        if not self.defer_cash:
            self.cash = Decimal('800') + value * (1 - FEE)
        self.clock[0] += timedelta(seconds=1)
        self.orders[-1] = replace(self.orders[-1], status=status,
            cumulative_filled_quantity=cumulative_quantity, average_fill_price=float(self.price),
            cumulative_notional=value, updated_at=self.clock[0].isoformat())

    def cancel_order(self, identity):
        self.cancelled.append(identity)

    def close(self):
        pass


@pytest.fixture
def make_holding(tmp_path):
    roots = []

    def create(market, *, legacy=False, v4=False, settled_only=False):
        cn = market == 'CN'
        quantity, price = (200, Decimal('1')) if cn else (2, Decimal('100'))
        symbol = '510500.SH' if cn else 'MU'
        at = datetime.fromisoformat('2026-11-05T09:30:00' + ('+08:00' if cn else '-05:00'))
        clock = [at]
        interval = TimeInterval(at, at + timedelta(minutes=30))
        config = ChannelAccountConfig('retirement-' + market.lower(),
            FUTU_SIMULATE_CN_CHANNEL_ID if cn else FUTU_US_SIM_CHANNEL_ID, 77)
        database = tmp_path / f'{market}-{len(roots)}.db'
        root = PaperStore(database)
        roots.append(root)
        store = root.register_channel_account(config, capital=Decimal('1000'))
        rules = None if legacy else EquityAccountRules(
            InstrumentId(MarketId(market), AssetClass.ETF if cn else AssetClass.STOCK, symbol),
            ResearchExecutionSpec(CnEquitySpec() if cn else UsEquitySpec(), BarFrequency.M30,
                AccountPolicy(config.currency, CashAvailabilityPolicy.SETTLED_ONLY if settled_only
                              else CashAvailabilityPolicy.IMMEDIATE_RESEARCH),
                100 if cn else 1, .001 if cn else .01, .01, 0.))
        store.create_virtual_account('strategy', 'strategy', 'v1', 'a' * 64, '1000',
            symbol=symbol, asset_type='etf' if cn else 'stock', strategy_id='S999',
            strategy_version='v1', strategy_name_snapshot='Retirement fixture', release_hash='b' * 64,
            qualification_snapshot='PAPER_READY', selection_data_cutoff='2026-09-30', equity_rules=rules)
        store.create_channel_reconciliation_account()
        with store.atomic_decision_update():
            store._connection.execute('UPDATE virtual_accounts SET quantity=?,cash=?,average_cost=?,total_assets=? '
                'WHERE account_id=?', (quantity, '800', str(price), '1000', 'strategy'))
            store._equity_ledger('strategy', 'seed', 'FIXTURE_CONFIRMED_BUY', Decimal('-200'),
                quantity, Decimal('800'), quantity, at)
            if v4:
                cycle = PositionCycle('confirmed-cycle', interval, interval, quantity, 200., 0., 0., 1, 0)
                state = AccountStrategyState(cycle=CycleState('confirmed-cycle', at, StateRecord()))
                save_document(store, 'strategy', {'schema_version': 2, 'state': state.to_dict(),
                    'pending_cycle': None, 'active': position_to_dict(cycle), 'latest_closed': None,
                    'budget': None, 'locked_quantity': quantity, 'buy_locks': [],
                    'last_interval': None, 'last_inputs': None})
        broker = RetirementBroker(config, symbol, quantity, price, clock)
        engine = ChannelExecution(store, broker, config=config, fee_policy=POLICY, now=lambda: clock[0])
        engine.refresh_orders()
        store.set_paused(False)
        store.set_virtual_paused('strategy', False)
        assert store.account_invariant_violations() == []
        case = SimpleNamespace(root=root, database=database, store=store, broker=broker, engine=engine, clock=clock,
            config=config, quantity=quantity, price=price, interval=interval,
            request=AccountRetirementRequest('strategy', 'b' * 64, 'operator', 'retire strategy'))

        def restart():
            case.root.close()
            reopened = PaperStore(database)
            roots.append(reopened)
            case.root, case.store = reopened, reopened.scope(config.channel_account_id)
            case.engine = ChannelExecution(case.store, broker, config=config,
                fee_policy=POLICY, now=lambda: clock[0])
            return case.engine

        case.restart = restart
        return case

    yield create
    for root in roots:
        root.close()


def start_liquidation(case):
    result = case.engine.retire_account(case.request)
    assert result.status is AccountRetirementStatus.WAITING_MARKET
    assert result.released_cash == 0
    case.store.set_retirement_session('strategy', RetirementSession(case.interval, FEE))
    case.engine.refresh_orders()
    case.engine.submit_pending()
    assert len(case.broker.placed) == 1, case.store.retirement_status('strategy')
    intent = case.broker.placed[0]
    assert (intent.side, intent.order_type, intent.quantity) == ('SELL', 'MARKET', case.quantity)


def test_scoped_retirement_does_not_expire_or_submit_another_accounts_order(make_holding):
    from pte_support import adopt_test_decision
    case = make_holding('CN')
    case.store.set_setting('futu_capital_pool', '2000')
    case.broker.cash += Decimal('1000')
    case.store.create_virtual_account('other', 'other', 'S001-v1', 'a' * 64, 1000,
        strategy_id='S001', strategy_version='v1', release_hash='a' * 64,
        strategy_name_snapshot='other', qualification_snapshot='PAPER_READY', selection_data_cutoff='2026-01-01')
    case.engine.refresh_orders()
    case.store.set_virtual_paused('other', False)
    adopt_test_decision(case.store, account_id='other', decision_id='old-buy', valid_session='2026-11-04',
        orders=[{'side': 'BUY', 'quantity': 100, 'order_type': 'LIMIT', 'limit_price': 1.}])
    other = case.store.create_account_intent(account_id='other', decision_id='old-buy', order_sequence=0,
        symbol='588080.SH', side='BUY', quantity=100, limit_price=1., valid_session='2026-11-04')
    case.engine.retire_account(case.request)
    case.store.set_retirement_session('strategy', RetirementSession(case.interval, FEE))
    case.engine.retire_account(case.request)
    assert case.store.account_intent(other['intent_id']) == other
    assert len(case.broker.placed) == 1 and case.broker.placed[0].account_id == 'strategy'


@pytest.mark.parametrize('market', ['CN', 'US'])
def test_market_sale_retires_only_after_confirmed_fill_and_returns_cash(make_holding, market):
    case = make_holding(market)
    start_liquidation(case)
    assert case.store.virtual_account('strategy')['run_state'] == 'RETIRING'
    assert case.store.retirement_status('strategy').released_cash == 0
    case.broker.fill(case.quantity)
    case.engine.refresh_orders()
    result = case.store.retirement_status('strategy')
    assert result.status is AccountRetirementStatus.RETIRED
    assert result.released_cash == Decimal('999.8000')
    assert case.store.capital_pool_balance().unallocated_cash == result.released_cash
    assert len(case.store.account_fills('strategy')) == 1
    assert case.store.account_invariant_violations() == []
    # Retries before/after process boundaries cannot return capital twice.
    assert case.engine.retire_account(case.request) == result
    case.engine.refresh_orders()
    assert len(case.broker.placed) == 1
    assert len(case.store.query_audit_events(event_type='ACCOUNT_RETIRED')) == 1


@pytest.mark.parametrize('market', ['CN', 'US'])
def test_partial_fills_and_duplicate_requests_preserve_remaining_position(make_holding, market):
    case = make_holding(market)
    start_liquidation(case)
    case.broker.fill(case.quantity // 2, status='FILLED_PART')
    case.engine.refresh_orders()
    case.engine.refresh_orders()
    result = case.engine.retire_account(case.request)
    assert result.status is AccountRetirementStatus.LIQUIDATING
    assert result.remaining_quantity == case.quantity // 2 and result.released_cash == 0
    assert len(case.store.account_fills('strategy')) == len(case.broker.placed) == 1
    case.broker.fill(case.quantity)
    case.engine.refresh_orders()
    assert case.store.retirement_status('strategy').status is AccountRetirementStatus.RETIRED
    assert len(case.store.account_fills('strategy')) == 2


@pytest.mark.parametrize('market', ['CN', 'US'])
def test_unsellable_position_waits_without_false_success_or_order(make_holding, market):
    case = make_holding(market)
    case.broker.sellable = 0
    case.engine.retire_account(case.request)
    case.store.set_retirement_session('strategy', RetirementSession(case.interval, FEE))
    case.engine.refresh_orders()
    case.engine.submit_pending()
    result = case.store.retirement_status('strategy')
    assert result.status is AccountRetirementStatus.WAITING_SELLABLE
    assert result.remaining_quantity == case.quantity and result.released_cash == 0
    assert not case.broker.placed
    case.broker.sellable = case.quantity
    case.engine.refresh_orders()
    case.engine.submit_pending()
    assert len(case.broker.placed) == 1


@pytest.mark.parametrize('market', ['CN', 'US'])
def test_unknown_submit_is_recovered_after_restart_without_duplicate_sale(make_holding, market):
    case = make_holding(market)
    case.engine.retire_account(case.request)
    case.store.set_retirement_session('strategy', RetirementSession(case.interval, FEE))
    case.broker.lose_response = True
    case.engine.refresh_orders()
    assert len(case.broker.placed) == 1
    assert case.store.account_intents('strategy')[0]['status'] == 'SUBMISSION_UNCERTAIN'
    # Reopen the database as well as the execution instance: no in-memory request survives.
    restarted = case.restart()
    restarted.refresh_orders()
    restarted.submit_pending()
    assert len(case.broker.placed) == 1
    case.broker.fill(case.quantity)
    restarted.refresh_orders()
    assert case.store.retirement_status('strategy').status is AccountRetirementStatus.RETIRED


@pytest.mark.parametrize('market', ['CN', 'US'])
def test_v4_actual_sales_close_cycle_without_strategy_proposal(make_holding, market):
    case = make_holding(market, v4=True)
    start_liquidation(case)
    case.broker.fill(case.quantity // 2, status='FILLED_PART')
    case.engine.refresh_orders()
    document = json.loads(case.store.virtual_account('strategy')['account_v4_json'])
    assert document['active']['quantity'] == case.quantity // 2
    assert document['active']['sell_income'] == pytest.approx(99.9)
    case.broker.fill(case.quantity)
    case.engine.refresh_orders()
    document = json.loads(case.store.virtual_account('strategy')['account_v4_json'])
    assert document['active'] is document['state']['cycle'] is document['locked_quantity'] is None
    assert document['latest_closed']['sell_income'] == pytest.approx(199.8)
    assert document['latest_closed']['sell_fills'] == 2
    assert document['buy_locks'] == []


def test_legacy_account_entry_cycle_can_retire_without_v4_migration(make_holding):
    case = make_holding('CN', legacy=True)
    cycle = EntryCycleState('c' * 64, 'd' * 64, Decimal('1'), Decimal('1000'),
        case.quantity, Decimal('200'), EntryCyclePhase.ACTIVE)
    with case.store.atomic_decision_update():
        case.store._connection.execute('UPDATE virtual_accounts SET entry_cycle_json=? WHERE account_id=?',
            (json.dumps(cycle.to_dict()), 'strategy'))
    start_liquidation(case)
    case.broker.fill(case.quantity)
    case.engine.refresh_orders()
    account = case.store.virtual_account('strategy')
    assert account['run_state'] == 'RETIRED'
    assert account['entry_cycle_json'] is None and account.get('account_v4_json') is None
    assert case.store.retirement_status('strategy').released_cash == Decimal('999.8000')


@pytest.mark.parametrize('market', ['CN', 'US'])
def test_rejected_retirement_order_is_blocked_without_automatic_resubmit(make_holding, market):
    case = make_holding(market)
    case.engine.retire_account(case.request)
    case.store.set_retirement_session('strategy', RetirementSession(case.interval, FEE))
    case.broker.reject = True
    case.engine.refresh_orders()
    for _ in range(2):
        case.engine.refresh_orders()
        result = case.engine.retire_account(case.request)
    assert result.status is AccountRetirementStatus.BLOCKED
    assert result.remaining_quantity == case.quantity and result.released_cash == 0
    assert len(case.broker.placed) == 1 and not case.broker.orders


@pytest.mark.parametrize('market', ['CN', 'US'])
def test_reviewed_rejection_can_resume_retirement_with_channel_audit(make_holding, market):
    case = make_holding(market)
    case.engine.retire_account(case.request)
    case.store.set_retirement_session('strategy', RetirementSession(case.interval, FEE))
    case.broker.reject = True
    case.engine.refresh_orders()
    rejected = case.store.account_intents('strategy')[0]
    assert rejected['attention_required']
    case.broker.reject = False
    case.engine.acknowledge_execution_gap('strategy', rejected['intent_id'], 'checked broker restriction cleared')
    case.engine.refresh_orders()
    assert len(case.broker.placed) == 2 and len(case.broker.orders) == 1
    events = case.store.query_audit_events(event_type='EXECUTION_GAP_ACKNOWLEDGED')
    assert events[0]['channel'] == case.config.channel_id


@pytest.mark.parametrize('market', ['CN', 'US'])
def test_unconfirmed_sellability_is_blocked_and_expired_session_waits(make_holding, market):
    case = make_holding(market)
    case.broker.sellable = None
    case.engine.retire_account(case.request)
    case.store.set_retirement_session('strategy', RetirementSession(case.interval, FEE))
    case.engine.refresh_orders()
    assert case.store.retirement_status('strategy').status is AccountRetirementStatus.BLOCKED
    assert not case.broker.placed
    case.broker.sellable = case.quantity
    case.clock[0] = case.interval.end
    case.engine.refresh_orders()
    assert case.store.retirement_status('strategy').status is AccountRetirementStatus.WAITING_MARKET
    assert not case.broker.placed


def test_settled_only_sale_waits_for_cash_before_releasing_capital(make_holding):
    case = make_holding('US', settled_only=True)
    case.broker.defer_cash = True
    settlement = case.interval.start + timedelta(days=1)
    case.engine.retire_account(case.request)
    case.store.set_retirement_session('strategy', RetirementSession(case.interval, FEE, settlement))
    case.engine.refresh_orders()
    case.broker.fill(case.quantity)
    case.engine.refresh_orders()
    result = case.store.retirement_status('strategy')
    assert result.status is AccountRetirementStatus.WAITING_SETTLEMENT
    assert result.released_cash == 0 and result.remaining_quantity == 0
    assert Decimal(case.store.virtual_account('strategy')['receivable']) == Decimal('199.8000')
    case.clock[0] = settlement
    case.broker.cash = Decimal('999.8')
    case.engine.refresh_orders()
    assert case.store.retirement_status('strategy').status is AccountRetirementStatus.RETIRED
    assert case.store.retirement_status('strategy').released_cash == Decimal('999.8000')
    assert Decimal(case.store.virtual_account('strategy')['receivable']) == 0


@pytest.mark.parametrize('market', ['CN', 'US'])
def test_pending_strategy_order_is_cancelled_before_retirement_sale(make_holding, market):
    case = make_holding(market)
    day = case.interval.start.date().isoformat()
    payload = {'contract_version': 'advice.equity.v1', 'decision_id': 'old-sell',
        'strategy': {'strategy_id': 'S999', 'version': 'v1', 'release_hash': 'b' * 64},
        'symbol': case.broker.symbol, 'signal_date': day, 'valid_session': day,
        'actual_quantity': case.quantity, 'available_cash': 800., 'action': 'SELL',
        'target_quantity': 0, 'delta_quantity': -case.quantity, 'cycle_target_quantity': 0,
        'orders': [{'side': 'SELL', 'quantity': case.quantity, 'order_type': 'LIMIT',
                    'limit_price': float(case.price)}],
        'equity_execution_interval': {'start': case.interval.start.isoformat(), 'end': case.interval.end.isoformat()},
        'equity_observed_through': case.interval.start.isoformat()}
    case.store.save_account_decision('strategy', payload)
    case.store.create_account_intent(account_id='strategy', decision_id='old-sell', order_sequence=0,
        symbol=case.broker.symbol, side='SELL', quantity=case.quantity, limit_price=case.price,
        valid_session=day, fee_rate=FEE, order_type='LIMIT')
    case.engine.submit_pending()
    result = case.engine.retire_account(case.request)
    assert result.status is AccountRetirementStatus.DRAINING
    case.store.set_retirement_session('strategy', RetirementSession(case.interval, FEE))
    case.engine.refresh_orders()
    assert len(case.broker.cancelled) == 1 and len(case.broker.placed) == 1
    # Cancellation request is not cancellation confirmation.
    assert case.store.virtual_account('strategy')['quantity'] == case.quantity
    case.clock[0] += timedelta(seconds=1)
    case.broker.orders[0] = replace(case.broker.orders[0], status='CANCELLED_ALL',
        updated_at=case.clock[0].isoformat())
    case.engine.refresh_orders()
    assert len(case.broker.placed) == 2
    assert case.broker.placed[-1].order_type == 'MARKET'
    assert case.broker.placed[-1].quantity == case.quantity


def test_channel_read_failure_preserves_request_and_capital(make_holding, monkeypatch):
    case = make_holding('US')

    def disconnected():
        raise ConnectionError('broker unavailable')

    with monkeypatch.context() as patch:
        patch.setattr(case.broker, 'order_snapshot', disconnected)
        result = case.engine.retire_account(case.request)
    assert result.status is AccountRetirementStatus.BLOCKED
    assert 'broker unavailable' in result.reason
    assert result.released_cash == 0 and result.remaining_quantity == case.quantity
    assert case.store.virtual_account('strategy')['run_state'] == 'RETIRING'
    assert not case.broker.placed


def test_schema8_upgrade_preserves_rows_indexes_triggers_and_retirement_after_restart(make_holding):
    case = make_holding('CN', legacy=True)
    case.root.close()
    with sqlite3.connect(case.database) as connection:
        # Reconstruct the schema-8 CHECK constraint while retaining populated
        # account and ledger history; do not patch production migration behavior.
        ddl = connection.execute("SELECT sql FROM sqlite_master WHERE name='virtual_accounts'").fetchone()[0]
        objects = connection.execute("SELECT sql FROM sqlite_master WHERE tbl_name='virtual_accounts' "
            "AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
        ddl = ddl.replace('virtual_accounts', 'schema8_accounts', 1).replace("'RETIRING',", '')
        connection.execute(ddl)
        connection.execute('INSERT INTO schema8_accounts SELECT * FROM virtual_accounts')
        connection.execute('DROP TABLE virtual_accounts')
        connection.execute('ALTER TABLE schema8_accounts RENAME TO virtual_accounts')
        for row in objects:
            connection.execute(row[0])
        connection.execute('DROP TABLE account_retirement_requests')
        connection.execute("UPDATE settings SET value='8' WHERE key='runtime_database_schema_version'")
        connection.execute('CREATE TABLE fixture_run_state_history(account_id TEXT, state TEXT)')
        connection.execute('CREATE TRIGGER fixture_run_state AFTER UPDATE OF run_state ON virtual_accounts '
            'BEGIN INSERT INTO fixture_run_state_history VALUES(NEW.account_id,NEW.run_state); END')
        connection.execute('CREATE INDEX fixture_account_name ON virtual_accounts(name)')
        original_rows = connection.execute('SELECT * FROM virtual_accounts ORDER BY account_id').fetchall()
        original_ledger = connection.execute('SELECT * FROM account_ledger ORDER BY ledger_entry_id').fetchall()
    case.restart()
    connection = case.store._connection
    assert [tuple(row) for row in connection.execute('SELECT * FROM virtual_accounts ORDER BY account_id')] == original_rows
    assert [tuple(row) for row in connection.execute('SELECT * FROM account_ledger ORDER BY ledger_entry_id')] == original_ledger
    assert case.root.get_setting('runtime_database_schema_version') == '9'
    assert connection.execute("SELECT type FROM sqlite_master WHERE name='fixture_account_name'").fetchone()[0] == 'index'
    start_liquidation(case)
    request_identity = case.store.retirement_request('strategy')['request_id']
    case.restart()
    assert case.store.retirement_request('strategy')['request_id'] == request_identity
    case.engine.retire_account(case.request)
    assert len(case.broker.placed) == 1
    case.broker.fill(case.quantity)
    case.engine.refresh_orders()
    result = case.store.retirement_status('strategy')
    assert result.status is AccountRetirementStatus.RETIRED
    assert [row[0] for row in case.store._connection.execute(
        "SELECT state FROM fixture_run_state_history WHERE account_id='strategy'")] == ['RETIRING', 'RETIRED']
    case.restart()
    assert case.engine.retire_account(case.request) == result
    assert len(case.broker.placed) == 1
