"""Native dependency plans use confirmed inventory and durable dual-market intents."""
from datetime import timedelta
from decimal import Decimal

import pytest
from dataflows import MarketId
from paper_trading_engine.account_engine import AccountEngine
from paper_trading_engine.equity_advice import EquityAdviceClient
from paper_trading_engine.equity_contracts import EquityOrderReport
from paper_trading_engine.equity_execution import EquityExecution
from paper_trading_engine.store import PaperStore
from test_v4_pte import native_account, prepared_at, replace_strategy


STRATEGY = '''from datetime import timedelta
from strategy_runtime import AccountDecision, AccountStepResult, StateRecord, ReplayOrder, ReplayLeg
from strategy_runtime.contracts import OrderSide, OrderType
def step(ctx,state):
    quantity = 200
    if ctx.portfolio.quantity == 0:
        decision = AccountDecision.from_facts(1, 'core', facts={'core':quantity}, next_watch='rotation',
            orders=(ReplayOrder(OrderSide.BUY, quantity, OrderType.LIMIT, 10.10),))
    else:
        start = ctx.point.execution_interval.start
        legs = (ReplayLeg(0, ReplayOrder(OrderSide.BUY, quantity, OrderType.LIMIT, 10.10),
                    'OPEN', start, start+timedelta(minutes=5)),
                ReplayLeg(1, ReplayOrder(OrderSide.SELL, quantity, OrderType.MARKET),
                    'EXIT', start+timedelta(minutes=10), start+timedelta(minutes=15), 0, 'FILLED_ALL'))
        decision = AccountDecision.from_facts(1, 'rotation', facts={'core':quantity}, next_watch='next', legs=legs)
    return AccountStepResult(decision, cycle_values=StateRecord())
'''


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US])
@pytest.mark.parametrize('entry_outcome', ['complete', 'partial', 'unfilled'])
def test_native_rotation_waits_for_full_entry_and_survives_restart(tmp_path, market, entry_outcome):
    context, request, products, store, permit, channel = native_account(tmp_path, market)
    request = replace_strategy(request, STRATEGY)
    first = prepared_at(context, request, products)
    AccountEngine(store, EquityAdviceClient(store), now=lambda:first.interval.start).refresh_account('native', prepared=first)
    execution = EquityExecution(store, channel, now=lambda:first.interval.start)
    execution.reconcile(cash=Decimal(str(request.initial_cash)), quantity=0, account_id='native')
    core, = execution.submit_pending('native')
    execution.apply_report(EquityOrderReport(core, 200, Decimal('10'), first.interval.start+timedelta(minutes=1), 'FILLED_ALL'))
    next_day = prepared_at(context, request, products, 1)
    clock = next_day.interval.start
    AccountEngine(store, EquityAdviceClient(store), now=lambda:clock).refresh_account('native', prepared=next_day)
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
    else:
        execution.apply_report(EquityOrderReport(entry, 0, Decimal('0'), clock+timedelta(minutes=1), 'CANCELLED_ALL'))
    path = store.path
    store.close()
    store = PaperStore(path, inspection_permit=permit)
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
        assert status == ('WAITING_DEPENDENCY' if entry_outcome == 'partial' else 'EXPIRED')
        assert store.virtual_account('native')['quantity'] == (300 if entry_outcome == 'partial' else 200)
    assert not store.account_invariant_violations()
    store.close()


def test_aware_leg_windows_preserve_utc_and_exclude_deadline():
    from datetime import datetime
    from paper_trading_engine.order_windows import within_planned_window
    payload = {'submit_after':'2026-11-05T09:30:00-05:00', 'submit_before':'2026-11-05T09:35:00-05:00'}
    assert within_planned_window(payload, '2026-11-05', datetime.fromisoformat('2026-11-05T14:30:00+00:00'))
    assert not within_planned_window(payload, '2026-11-05', datetime.fromisoformat('2026-11-05T14:35:00+00:00'))
