"""CN and US PTE expose confirmed effects through the same EC query."""
from datetime import timedelta
from decimal import Decimal

import pytest

from dataflows import MarketId
from execution_channels.execution_effects import ExecutionEffectStatus
from execution_channels.futu.equity_execution import EquityExecution
from execution_channels.futu.equity_contracts import EquityOrderReport
from execution_channels.futu.broker import BrokerSubmissionUncertainError
from execution_channels.futu.store import PaperStore
from paper_trading_engine.account_engine import AccountEngine
from paper_trading_engine.equity_advice import EquityAdviceClient
from paper_trading_engine.ec_boundary import execution_permit
from test_v4_pte import native_account, prepared_at


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_confirmed_effect_pending_partial_complete_and_restart(tmp_path,market):
    context,request,products,store,permit,channel=native_account(tmp_path,market)
    try:
        prepared=prepared_at(context,request,products)
        at=prepared.interval.start
        AccountEngine(store,EquityAdviceClient(store),now=lambda:at).refresh_account('native',prepared=prepared)
        decision_id=store.virtual_account('native')['last_decision_id']
        def effect(when=at):
            return store.decision_execution_effect('native',decision_id,valuation_price=Decimal('10'),at=when)
        pending=effect()
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
