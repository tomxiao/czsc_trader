"""EC dependency plans use confirmed inventory and durable dual-market intents.

Orders belong to EC; the strategy contract is deliberately not used to inject legs.
"""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest
from dataflows import MarketId
from paper_trading_engine.account_engine import AccountEngine
from paper_trading_engine.equity_advice import EquityAdviceClient
from paper_trading_engine.ec_boundary import execution_permit
from paper_trading_engine.contracts import AdviceDecision, OrderSpec, PlanLegSpec
from execution_channels.contracts import AccountExecutionPlan, ExecutionPrecision, ReplayPoint, ReplayOrder, ReplayLeg
from execution_channels.instruments import TimeInterval
from execution_channels.session_contracts import OrderSide, OrderType
from execution_channels.state import StateRecord
from execution_channels.identity import equity_hash
from execution_channels.futu.adoption import AccountAdoption, DecisionAdoption
from execution_channels.futu.audit import AuditRecorder
from execution_channels.futu.equity_account_state import load_document, validate_document
from execution_channels.futu.v4_admission import (V4AccountProposal, V4ExecutionContext,
    decision_snapshot, prepare_v4_adoption)
from execution_channels.futu.equity_contracts import EquityOrderReport
from execution_channels.futu.equity_execution import EquityExecution
from execution_channels.futu.store import PaperStore
from test_v4_pte import native_account, prepared_at


def adopt_execution_plan(store, prepared, *, rotation=False):
    """Admit an explicit EC plan through real V4 validation and atomic adoption."""
    account = store.virtual_account('native')
    rules = store.equity_account_rules('native')
    document = load_document(account, StateRecord())
    state = validate_document(document)
    start, end = prepared.interval.start, prepared.interval.end
    point = ReplayPoint(prepared.execution_reference.observed_through, start, start, end,
        start.astimezone(rules.timezone).date().isoformat(), ExecutionPrecision.BAR_INTERVAL)
    buy = ReplayOrder(OrderSide.BUY, 200, OrderType.LIMIT, 10.10)
    legs = (ReplayLeg(0, buy, 'OPEN', start, start+timedelta(minutes=5)),
        ReplayLeg(1, ReplayOrder(OrderSide.SELL, 200, OrderType.MARKET), 'EXIT',
            start+timedelta(minutes=10), start+timedelta(minutes=15), 0, 'FILLED_ALL')) if rotation else ()
    owner = account['account_id'] + ':' + account['release_hash']
    identity = equity_hash({'owner': owner, 'interval': start.isoformat(), 'rotation': rotation})
    plan = AccountExecutionPlan(identity, owner, point, state.revision, 200,
        orders=() if rotation else (buy,), legs=legs,
        evidence={'reference_price': 10., 'locked_quantity': None})
    snapshot = decision_snapshot(account, document, rules, start, Decimal(account['cash']))
    binding = equity_hash({'owner': owner, 'implementation': prepared.candidate.implementation_hash,
        'specification': rules.execution.fingerprint, 'fee_rate': prepared.fee_rate})
    proposal = V4AccountProposal(state.account, StateRecord(), binding, state.event_cursor)
    context = V4ExecutionContext(TimeInterval(start, end), prepared.as_of, prepared.buy_sellable_at,
        prepared.v4_constraint, prepared.data_identity, prepared.fee_rate)
    effects = prepare_v4_adoption(plan, snapshot, document, proposal, context, rules)
    orders = tuple(OrderSpec(**asdict(order)) for order in effects.orders)
    adopted_legs = tuple(PlanLegSpec(**{**asdict(leg), 'order': OrderSpec(**asdict(leg.order))})
                         for leg in effects.legs)
    decision = AdviceDecision('advice.equity.v4', identity, account['symbol'], prepared.available_through,
        start.astimezone(rules.timezone).date(), snapshot.quantity, 200, 200, 200-snapshot.quantity,
        effects.action, {'strategy_id': account['strategy_id'], 'version': account['strategy_version'],
                         'release_hash': account['release_hash']},
        float(prepared.history.Close.iloc[-1]), effects.reference, prepared.available_through,
        orders[0] if orders else None, identity, identity, 0, 0,
        orders=orders, available_cash=float(snapshot.available_cash), fee_rate=prepared.fee_rate,
        estimated_order_cost=effects.estimated_order_cost, unallocated_cash=effects.unallocated_cash,
        plan_mode='V4' if rotation else 'NONE', plan_legs=adopted_legs,
        runtime_sha256=prepared.candidate.implementation_hash,
        equity_execution_interval={'start': start.isoformat(), 'end': end.isoformat()},
        equity_observed_through=point.observed_through.isoformat(),
        v4_state_transition={'before': account.get('account_v4_json'), 'after': effects.after,
            'buy_sellable_at': prepared.buy_sellable_at.isoformat(),
            'sell_remainder_policy': prepared.v4_constraint['SellRemainderPolicy']})
    payload = decision.to_store_payload()
    payload['prepared_data_identity'] = prepared.data_identity
    AccountAdoption(store, AuditRecorder(store)).adopt(DecisionAdoption('native',
        json.dumps(payload, default=str).encode()))


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
@pytest.mark.parametrize('entry_outcome', ['complete', 'partial', 'unfilled', 'cancelled_part', 'failed', 'unknown'])
def test_native_rotation_waits_for_full_entry_and_survives_restart(tmp_path, market, entry_outcome):
    context, request, products, store, permit, channel = native_account(tmp_path, market)
    first = prepared_at(context, request, products)
    adopt_execution_plan(store, first)
    execution = EquityExecution(store, channel, now=lambda:first.interval.start)
    execution.reconcile(cash=Decimal(str(request.initial_cash)), quantity=0, account_id='native')
    core, = execution.submit_pending('native')
    execution.apply_report(EquityOrderReport(core, 200, Decimal('10'), first.interval.start+timedelta(minutes=1), 'FILLED_ALL'))
    next_day = prepared_at(context, request, products, 1)
    clock = next_day.interval.start
    adopt_execution_plan(store, next_day, rotation=True)
    assert store.account_decisions('native')[0]['payload']['action'] == 'ROTATE'
    legs = store.account_intents('native')[-2:]
    assert [row['status'] for row in legs] == ['PENDING_SUBMIT', 'WAITING_DEPENDENCY']
    assert not store.activate_dependency_intent(legs[1]['intent_id'])
    execution = EquityExecution(store, channel, now=lambda:clock)
    entry, = execution.submit_pending('native')
    assert execution.submit_pending('native') == ()
    if entry_outcome == 'complete':
        execution.apply_report(EquityOrderReport(entry, 200, Decimal('10'), clock+timedelta(minutes=1), 'FILLED_ALL'))
        early = EquityExecution(store, channel, now=lambda:clock+timedelta(minutes=2))
        assert early.submit_pending('native') == ()
        assert store.account_intent(legs[1]['intent_id'])['status'] == 'PENDING_SUBMIT'
    elif entry_outcome == 'partial':
        execution.apply_report(EquityOrderReport(entry, 100, Decimal('10'), clock+timedelta(minutes=1), 'FILLED_PART'))
    elif entry_outcome == 'unfilled':
        execution.apply_report(EquityOrderReport(entry, 0, Decimal('0'), clock+timedelta(minutes=1), 'CANCELLED_ALL'))
    elif entry_outcome == 'cancelled_part':
        execution.apply_report(EquityOrderReport(entry, 100, Decimal('10'), clock+timedelta(minutes=1), 'CANCELLED_PART'))
    elif entry_outcome == 'failed':
        execution.apply_report(EquityOrderReport(entry, 0, Decimal('0'), clock+timedelta(minutes=1), 'FAILED'))
    # Unknown means the submitted order has no conclusive channel report.
    path = store.path
    store.close()
    store = PaperStore(path, inspection_permit=execution_permit(permit))
    before_intents = store.account_intents('native')
    AccountEngine(store, EquityAdviceClient(store), now=lambda:clock+timedelta(minutes=10)).refresh_account('native', prepared=next_day)
    assert store.account_intents('native') == before_intents
    assert len(store.account_decisions('native')) == 2
    execution = EquityExecution(store, channel, now=lambda:clock+timedelta(minutes=10))
    orders = execution.submit_pending('native')
    if entry_outcome == 'complete':
        assert len(orders) == 1
        assert store.account_order(orders[0])['side'] == 'SELL'
        execution.apply_report(EquityOrderReport(orders[0], 200, Decimal('10'), clock+timedelta(minutes=11), 'FILLED_ALL'))
        assert store.virtual_account('native')['quantity'] == 200
    else:
        assert orders == ()
        status = store.account_intent(legs[1]['intent_id'])['status']
        assert status == ('WAITING_DEPENDENCY' if entry_outcome in ('partial', 'unknown') else 'EXPIRED')
        assert store.virtual_account('native')['quantity'] == (300 if entry_outcome in ('partial', 'cancelled_part') else 200)
    assert not store.account_invariant_violations()
    store.close()


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
def test_unsubmitted_entry_expiry_cannot_activate_dependent_exit(tmp_path, market):
    context, request, products, store, _, channel = native_account(tmp_path, market)
    first = prepared_at(context, request, products)
    adopt_execution_plan(store, first)
    execution = EquityExecution(store, channel, now=lambda:first.interval.start)
    execution.reconcile(cash=Decimal(str(request.initial_cash)), quantity=0, account_id='native')
    core, = execution.submit_pending('native')
    execution.apply_report(EquityOrderReport(core, 200, Decimal('10'), first.interval.start+timedelta(minutes=1), 'FILLED_ALL'))
    second = prepared_at(context, request, products, 1)
    adopt_execution_plan(store, second, rotation=True)
    clock = second.interval.start+timedelta(minutes=10)
    execution = EquityExecution(store, channel, now=lambda:clock)
    assert execution.submit_pending('native') == ()
    assert execution.submit_pending('native') == ()
    legs = store.account_intents('native')[-2:]
    assert [row['status'] for row in legs] == ['EXPIRED', 'EXPIRED']
    assert not store.activate_dependency_intent(legs[1]['intent_id'])
    assert store.virtual_account('native')['quantity'] == 200
    assert not store.account_invariant_violations()
    store.close()


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
def test_overnight_adoption_preserves_locks_until_actual_unlock_time(tmp_path, market):
    context, request, products, store, _, channel = native_account(tmp_path, market)
    try:
        first = prepared_at(context, request, products)
        adopt_execution_plan(store, first)
        execution = EquityExecution(store, channel, now=lambda: first.interval.start)
        execution.reconcile(cash=Decimal(str(request.initial_cash)), quantity=0, account_id='native')
        order, = execution.submit_pending('native')
        execution.apply_report(EquityOrderReport(order, 200, Decimal('10'),
            first.interval.start + timedelta(minutes=1), 'FILLED_ALL'))
        gate = first.interval.end + timedelta(hours=5)
        following = replace(prepared_at(context, request, products, 1), as_of=gate)
        before = load_document(store.virtual_account('native'))
        expected_locks = [lock for lock in before['buy_locks'] if datetime.fromisoformat(lock['at']) > gate]
        # Next-session planning may use tomorrow's sellability, but must not
        # advance the durable account's lock state when adopted tonight.
        adopt_execution_plan(store, following, rotation=True)
        account = store.virtual_account('native')
        after = load_document(account)
        assert after['buy_locks'] == expected_locks
        assert bool(expected_locks) is (market is MarketId.CN)
        rules = store.equity_account_rules('native')
        current = decision_snapshot(account, after, rules, gate, Decimal(account['cash']))
        tomorrow = decision_snapshot(account, after, rules, following.interval.start, Decimal(account['cash']))
        assert current.sellable_quantity == (0 if market is MarketId.CN else 200)
        assert tomorrow.sellable_quantity == 200
        execution = EquityExecution(store, channel, now=lambda: gate)
        assert execution.submit_pending('native') == ()
        assert store.virtual_account('native')['quantity'] == 200
    finally:
        store.close()


def test_v4_adoption_requires_explicit_nonfuture_observation_time():
    start = datetime(2026, 11, 5, 14, 30, tzinfo=timezone.utc)
    interval = TimeInterval(start, start + timedelta(hours=6))
    for invalid in (None, start.replace(tzinfo=None)):
        with pytest.raises(TypeError, match='aware observation time'):
            V4ExecutionContext(interval, invalid, start, {}, 'a' * 64, .001)
    with pytest.raises(ValueError, match='must not follow execution start'):
        V4ExecutionContext(interval, start + timedelta(seconds=1), start, {}, 'a' * 64, .001)


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
def test_paused_account_cannot_adopt_previously_prepared_decision(tmp_path, market):
    context, request, products, store, _, _ = native_account(tmp_path, market)
    try:
        prepared = prepared_at(context, request, products)
        store.set_virtual_paused('native', True)
        before = store.virtual_account('native')
        with pytest.raises(RuntimeError, match='adoption requires a RUNNING account'):
            adopt_execution_plan(store, prepared)
        assert store.virtual_account('native') == before
        assert not store.account_decisions('native')
        assert not store.account_intents('native')
        assert not store.account_snapshots('native')
        assert not store.query_audit_events(event_type='DECISION_GENERATED', account_id='native')
    finally:
        store.close()


def test_aware_leg_windows_preserve_utc_and_exclude_deadline():
    from execution_channels.futu.order_windows import within_planned_window
    payload = {'submit_after':'2026-11-05T09:30:00-05:00', 'submit_before':'2026-11-05T09:35:00-05:00'}
    assert within_planned_window(payload, '2026-11-05', datetime.fromisoformat('2026-11-05T14:30:00+00:00'))
    assert not within_planned_window(payload, '2026-11-05', datetime.fromisoformat('2026-11-05T14:35:00+00:00'))
