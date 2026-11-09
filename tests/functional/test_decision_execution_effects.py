# Risk ownership: E2E-05
"""CN and US PTE expose confirmed effects through the same EC query."""
from decimal import Decimal

import pytest

from dataflows import MarketId
from execution_channels.execution_effects import ExecutionEffectStatus
from execution_channels.futu.equity_execution import EquityExecution
from execution_channels.futu.broker import BrokerSubmissionUncertainError
from paper_trading_engine.account_engine import AccountEngine
from paper_trading_engine.equity_advice import EquityAdviceClient
from test_v4_pte import native_account, prepared_at


@pytest.mark.parametrize('market',[MarketId.US])
def test_submission_unknown_remains_visible_in_effect(tmp_path,market):
    context,request,products,store,permit,channel=native_account(tmp_path,market)
    submissions = []
    try:
        prepared=prepared_at(context,request,products)
        at=prepared.interval.start
        AccountEngine(store,EquityAdviceClient(store),now=lambda:at).refresh_account('native',prepared=prepared)
        decision_id=store.virtual_account('native')['last_decision_id']
        def unknown(intent):
            submissions.append(intent.intent_id)
            raise RuntimeError('response lost after possible submission')
        channel.place_order=unknown
        execution=EquityExecution(store,channel,now=lambda:at)
        execution.reconcile(cash=Decimal(str(request.initial_cash)),quantity=0,account_id='native')
        with pytest.raises(BrokerSubmissionUncertainError):
            execution.submit_pending('native')
        effect=store.decision_execution_effect('native',decision_id,valuation_price=10.,at=at)
        assert effect.status is ExecutionEffectStatus.UNKNOWN and not effect.terminal
        assert effect.actual_quantity==0 and effect.orders[0].outcome_unknown
        before = store.virtual_account('native')
        intents = store.account_intents('native')
        path = store.path
        store.close()
        from execution_channels.futu.store import PaperStore
        from paper_trading_engine.ec_boundary import execution_permit
        from paper_trading_engine.account_engine import ActiveOrderPendingError
        store = PaperStore(path, inspection_permit=execution_permit(permit))
        assert store.virtual_account('native') == before
        execution = EquityExecution(store, channel, now=lambda: at)
        assert execution.submit_pending('native') == ()
        following = prepared_at(context, request, products, 1)
        with pytest.raises(ActiveOrderPendingError):
            AccountEngine(store, EquityAdviceClient(store), now=lambda: following.interval.start).refresh_account(
                'native', prepared=following)
        assert store.account_intents('native') == intents
        assert len(submissions) == 1
        assert store.virtual_account('native')['quantity'] == 0
        effect = store.decision_execution_effect('native', decision_id, valuation_price=10., at=at)
        assert effect.status is ExecutionEffectStatus.UNKNOWN and not effect.terminal
    finally:
        store.close()
