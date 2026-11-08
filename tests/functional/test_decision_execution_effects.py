"""CN and US PTE expose confirmed effects through the same EC query."""
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from dataflows import MarketId
from execution_channels.execution_effects import ExecutionEffectStatus
from execution_channels.futu.equity_execution import EquityExecution
from execution_channels.futu.equity_contracts import EquityOrderReport
from execution_channels.futu.broker import BrokerSubmissionUncertainError, IntentTerminationReason
from execution_channels.futu.store import PaperStore
from paper_trading_engine.account_engine import AccountEngine
from paper_trading_engine.equity_advice import EquityAdviceClient
from paper_trading_engine.ec_boundary import execution_permit
from test_v4_pte import native_account, prepared_at, replace_strategy
from paper_store_support import new_paper_store


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_confirmed_effect_pending_partial_complete_and_restart(tmp_path,market):
    context,request,products,store,permit,channel=native_account(tmp_path,market)
    try:
        prepared=prepared_at(context,request,products)
        at=prepared.interval.start
        AccountEngine(store,EquityAdviceClient(store),now=lambda:at-timedelta(minutes=1)).refresh_account(
            'native',prepared=prepared)
        decision_id=store.virtual_account('native')['last_decision_id']
        def effect(when=at):
            return store.decision_execution_effect('native',decision_id,valuation_price=Decimal('10'),at=when)
        pending=effect()
        # Explicitly prepared plans may be adopted before their execution window.
        # Querying their pending state does not claim the formal scheduler prepares early.
        assert effect(at-timedelta(minutes=1)).status is ExecutionEffectStatus.WAITING
        assert pending.status is ExecutionEffectStatus.WAITING
        assert pending.actual_quantity==0 and pending.actual_weight==0
        assert pending.cash==Decimal(str(request.initial_cash))
        assert pending.available_cash < pending.cash  # reservations are not an expense
        execution=EquityExecution(store,channel,now=lambda:at)
        execution.reconcile(cash=Decimal(str(request.initial_cash)),quantity=0,account_id='native')
        order_id,=execution.submit_pending('native')
        quantity=store.account_order(order_id)['quantity']
        assert effect().status is ExecutionEffectStatus.WAITING
        count=context.execution_spec.quantity_step
        when=at+timedelta(minutes=1)
        execution.apply_report(EquityOrderReport(order_id,count,Decimal('10'),when,'FILLED_PART'))
        partial=effect(when)
        assert partial.status is ExecutionEffectStatus.PARTIAL and not partial.terminal
        assert partial.actual_quantity==count and partial.orders[0].filled_quantity==count
        execution.apply_report(EquityOrderReport(order_id,count,Decimal('10'),when,'FILLED_PART'))
        assert effect(when)==partial
        with pytest.raises(ValueError,match='later'):
            effect(at)
        later=at+timedelta(minutes=2)
        execution.apply_report(EquityOrderReport(order_id,quantity,Decimal('10'),later,'FILLED_ALL'))
        done=effect(later)
        assert done.status is ExecutionEffectStatus.COMPLETED and done.terminal
        assert done.actual_quantity==quantity and done.actual_weight < done.target_weight
        path=store.path
        store.close()
        store=PaperStore(path,inspection_permit=execution_permit(permit))
        assert effect(later)==done
    finally:
        store.close()


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_no_affordable_entry_is_retained_as_unexecuted_decision(tmp_path,market):
    context,request,products,store,_,_=native_account(tmp_path,market)
    try:
        store.migrate_pristine_virtual_account_capital('native',
            expected_initial_cash=str(request.initial_cash),new_initial_cash='1')
        prepared=prepared_at(context,request,products)
        at=prepared.interval.start
        AccountEngine(store,EquityAdviceClient(store),now=lambda:at).refresh_account('native',prepared=prepared)
        decision_id=store.virtual_account('native')['last_decision_id']
        effect=store.decision_execution_effect('native',decision_id,valuation_price=10.,at=at)
        assert effect.status is ExecutionEffectStatus.NOT_EXECUTED and effect.terminal
        assert effect.planning_status=='BLOCKED' and effect.constraint_reasons
        assert effect.orders==() and effect.actual_quantity==0 and effect.target_weight==1.
        assert effect.cash==Decimal(1) and store.account_intents('native')==[]
        # An unexecutable decision does not prevent the next normal account cycle.
        following=prepared_at(context,request,products,index=1)
        AccountEngine(store,EquityAdviceClient(store),now=lambda:following.interval.start).refresh_account(
            'native',prepared=following)
        assert store.virtual_account('native')['last_decision_id'] != decision_id
    finally:
        store.close()


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_submission_unknown_remains_visible_in_effect(tmp_path,market):
    context,request,products,store,_,channel=native_account(tmp_path,market)
    try:
        prepared=prepared_at(context,request,products)
        at=prepared.interval.start
        AccountEngine(store,EquityAdviceClient(store),now=lambda:at).refresh_account('native',prepared=prepared)
        decision_id=store.virtual_account('native')['last_decision_id']
        def unknown(_):
            raise RuntimeError('response lost after possible submission')
        channel.place_order=unknown
        execution=EquityExecution(store,channel,now=lambda:at)
        execution.reconcile(cash=Decimal(str(request.initial_cash)),quantity=0,account_id='native')
        with pytest.raises(BrokerSubmissionUncertainError):
            execution.submit_pending('native')
        effect=store.decision_execution_effect('native',decision_id,valuation_price=10.,at=at)
        assert effect.status is ExecutionEffectStatus.UNKNOWN and not effect.terminal
        assert effect.actual_quantity==0 and effect.orders[0].outcome_unknown
    finally:
        store.close()


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
def test_no_change_remains_completed_without_orders(tmp_path, market):
    context, request, products, store, _, _ = native_account(tmp_path, market)
    try:
        request = replace_strategy(request,
            "from strategy_runtime import AccountStepResult,AccountDecision,StateRecord\n"
            "def step(ctx,state):\n"
            "    return AccountStepResult(AccountDecision.from_facts(0,'remain flat',"
            "facts={'fixture':True},next_watch='next'),cycle_values=StateRecord())\n")
        prepared = prepared_at(context, request, products)
        AccountEngine(store, EquityAdviceClient(store), now=lambda: prepared.interval.start).refresh_account(
            'native', prepared=prepared)
        decision_id = store.virtual_account('native')['last_decision_id']
        decision = store.account_decision('native', decision_id)
        assert decision['status'] == 'COMPLETED' and decision['state_reason'] == 'NO_ORDER'
        effect = store.decision_execution_effect('native', decision_id,
            valuation_price=10., at=prepared.interval.start).to_dict()
        assert effect['status'] == 'COMPLETED' and effect['planning_status'] == 'NO_CHANGE'
        assert effect['orders'] == [] and effect['actual_weight'] == effect['target_weight'] == 0
    finally:
        store.close()


@pytest.mark.parametrize('bound,status,reason,error', [
    (False, 'SUBMISSION_FAILED', 'EXECUTION_CONSTRAINED', TypeError),
    (False, 'SUBMISSION_FAILED', IntentTerminationReason.EXECUTION_EXPIRED, ValueError),
    (True, 'SUBMISSION_FAILED', IntentTerminationReason.EXECUTION_CONSTRAINED, ValueError),
    (True, 'REJECTED', IntentTerminationReason.ORDER_REJECTED, ValueError),
])
def test_local_termination_requires_typed_unsubmitted_evidence(tmp_path, bound, status, reason, error):
    # This boundary owns intent termination, not data preparation or strategy
    # computation. The dual-market cases above retain that real integration.
    store = new_paper_store(tmp_path / 'termination.db')
    try:
        store.set_setting('futu_capital_pool', '1000')
        store.create_virtual_account('native', 'termination', 'S999-v1', 'a' * 64, 1000,
            strategy_id='S999', strategy_version='v1', release_hash='a' * 64,
            strategy_name_snapshot='termination', qualification_snapshot='PAPER_READY',
            selection_data_cutoff='2026-01-01')
        store.set_virtual_paused('native', False)
        store.save_account_decision('native', {
            'contract_version': 'advice.v4', 'decision_id': 'buy', 'symbol': '588080.SH',
            'strategy': {'strategy_id': 'S999', 'version': 'v1', 'release_hash': 'a' * 64},
            'signal_date': '2026-11-03', 'valid_session': '2026-11-04',
            'actual_quantity': 0, 'available_cash': 1000., 'action': 'BUY',
            'target_quantity': 100, 'delta_quantity': 100, 'cycle_target_quantity': 100,
            'orders': [{'side': 'BUY', 'quantity': 100, 'order_type': 'LIMIT', 'limit_price': 1.}],
        })
        intent = store.create_account_intent(account_id='native', decision_id='buy',
            order_sequence=0, symbol='588080.SH', side='BUY', quantity=100,
            limit_price=1., valid_session='2026-11-04')
        if bound:
            store.set_setting('channel_reconciliation_status', 'OK')
            store.set_setting('futu_cash_reconciliation_status', 'OK')
            assert store.claim_account_intent(intent['intent_id'],
                moment=datetime(2026, 11, 4, 9, 30, tzinfo=ZoneInfo('Asia/Shanghai')))
            store.bind_channel_order(intent['intent_id'], 'broker-order', {
                'symbol': '588080.SH', 'side': 'BUY', 'quantity': 100,
                'remark': intent['intent_id'], 'status': 'SUBMITTED',
            })
        intent, = store.account_intents('native')
        before = store.virtual_account('native')
        with pytest.raises(error):
            store.release_account_intent(intent['intent_id'], status,
                termination_reason=reason, attention_reason='synthetic local rejection')
        assert store.virtual_account('native') == before
        assert store.account_intent(intent['intent_id']) == intent
    finally:
        store.close()
