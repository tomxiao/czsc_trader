"""Channel-owned sizing, frozen budgets and HFQ account-unit boundaries."""
from datetime import timedelta

import pytest
from execution_channels.historical import PortfolioHistoricalExecutor
from execution_channels.instruments import MarketId
from execution_channels.policy import CashAvailabilityPolicy
from ec_facts import fixture
from test_portfolio_parity import setup, facts, plan, order
from execution_channels.session_contracts import OrderSide






# Independent risk: EC01; responsibility-level assertions.


# Independent risk: EC04; responsibility-level assertions.


# Independent risk: EC09; responsibility-level assertions.
def test_EC09_C02_hfq_account_settles_only_sale_proceeds_and_reports_simulated_unit_model():
    market = MarketId.US
    executor,stamp,instrument=setup(market,cash_policy=CashAvailabilityPolicy.SETTLED_ONLY)
    bar,rule=facts(stamp)
    executor.execute_account_plan(plan(executor,stamp,(order(OrderSide.BUY,100,10.1),)),bar,constraint=rule)
    sell_at=stamp+timedelta(minutes=30)
    bar,rule=facts(sell_at)
    executor.execute_account_plan(plan(executor,sell_at,(order(OrderSide.SELL,100),)),bar,constraint=rule)
    assert executor.cash==pytest.approx(8999.) and executor.receivable==pytest.approx(999.)
    paid_at=rule['SettlementAt']
    executor.snapshot_at(sell_at,paid_at)
    assert executor.cash==pytest.approx(9998.) and executor.receivable==0
    events,cursor=executor.recognized_events_since(0,paid_at)
    assert cursor==1 and events[0].kind.value=='SALE_SETTLEMENT' and events[0].reason=='TRADE_SETTLEMENT'
    assert executor.recognized_events_since(cursor,paid_at)==((),cursor)
    result=executor.finish()
    assert result.price_basis=='HFQ' and result.quantity_basis=='SIMULATED_INTEGER_UNITS'
    assert set(result.account_entries.kind)=={'SALE_SETTLEMENT'}
    assert not hasattr(result,'corporate_action_entries')


def test_EC09_C03_hfq_executor_refuses_company_action_event_input():
    _,spec,_,_,_=fixture(MarketId.US)
    with pytest.raises(TypeError, match="actions"):
        PortfolioHistoricalExecutor(specification=spec, initial_cash=10000., fee_rate=.001,
                                    price_basis='HFQ', actions=[])


def test_EC09_C01_hfq_buy_posts_confirmed_cost_fee_quantity_and_valuation():
    executor, stamp, _ = setup(MarketId.US)
    bar, rule = facts(stamp)
    executor.execute_account_plan(
        plan(executor, stamp, (order(OrderSide.BUY, 100, 10.1),)), bar, constraint=rule,
    )
    assert executor.cash == pytest.approx(8999.)
    assert executor.quantity == 100 and executor.receivable == 0.
    assert len(executor.rows['fills']) == 1
    result = executor.finish()
    assert result.price_basis == 'HFQ'
    assert result.account_points.equity.iloc[-1] == pytest.approx(9999.)
