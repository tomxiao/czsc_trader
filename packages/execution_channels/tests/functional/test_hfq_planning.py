"""Channel-owned sizing, frozen budgets and HFQ account-unit boundaries."""
from dataclasses import fields, replace
from datetime import timedelta
from decimal import Decimal

import pytest
from execution_channels.contracts import AccountSnapshot, SellRemainderPolicy
from execution_channels.entry_cycle import EntryCyclePhase
from execution_channels.historical import PortfolioHistoricalExecutor
from execution_channels.instruments import MarketId
from execution_channels.planning import plan_account_decision
from execution_channels.planning.intent import TradeIntent, DecisionExplanation
from execution_channels.planning.result import PlanningStatus, PlanningConstraint
from execution_channels.policy import ExecutionPolicy, CashAvailabilityPolicy
from test_historical_boundary import fixture
from test_portfolio_parity import setup, facts, plan, order
from execution_channels.session_contracts import OrderSide


def frozen(spec, mode='available_cash_fraction'):
    capital = {'fee_rate':.001,'mode':mode,'target_scope':'entry_cycle'}
    if mode != 'signal_cash_fraction':
        capital['allocation_fraction'] = 1.
    return ExecutionPolicy('FROZEN_RULE', {'capital':capital,
        'entry':{'limit_parameter':.01,'order_type':'LIMIT'},
        'exit':{'limit_ratio':.1,'order_type':'MARKET'},
        'instrument':{'lot_size':spec.quantity_step,'price_tick':spec.price_tick,
            'price_limit_ratio':.1,'maximum_order_quantity':100000}})


def planned(market, *, reference=10., cash=10000., target=1., policy=None, budget=None, held=0):
    instrument,spec,point,_,_=fixture(market)
    account=AccountSnapshot(instrument,instrument.currency,point.decision_at,0,cash,cash,0.,held,held)
    return plan_account_decision(TradeIntent(target,DecisionExplanation({'quantity':999999,'price':.001})),
        point,account,reference,spec,owner='fixture',implementation='a'*64,fee_rate=.001,
        sell_remainder_policy=SellRemainderPolicy.FULL_LIQUIDATION,
        execution_policy=policy or ExecutionPolicy('TARGET_POSITION',{}),cycle_budget=budget)


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_intent_cannot_supply_orders_and_cannot_change_execution_with_explanation(market):
    assert [field.name for field in fields(TradeIntent)] == ['target','explanation']
    result=planned(market)
    assert result.orders[0].limit_price==10.1
    assert result.orders[0].quantity==(900 if market is MarketId.CN else 989)
    with pytest.raises(TypeError):
        TradeIntent(1.,DecisionExplanation({}),orders=())


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
@pytest.mark.parametrize('kind',['TARGET_POSITION','FROZEN_RULE'])
def test_unaffordable_hfq_units_block_without_rescaling_or_relaxing_lots(market,kind):
    _,spec,_,_,_=fixture(market)
    policy=ExecutionPolicy('TARGET_POSITION',{}) if kind=='TARGET_POSITION' else frozen(spec)
    result=planned(market,reference=100000.,policy=policy)
    assert result.orders==() and result.legs==() and result.target_quantity==0
    assert result.evidence['target']==1.
    assert result.planning_result.status is PlanningStatus.BLOCKED
    assert PlanningConstraint.BELOW_MINIMUM_UNIT in result.planning_result.reasons
    with pytest.raises(ValueError,match='HFQ'):
        PortfolioHistoricalExecutor(specification=spec,initial_cash=10000.,fee_rate=.001,price_basis='RAW')
    with pytest.raises(TypeError):
        PortfolioHistoricalExecutor(specification=spec,initial_cash=10000.,fee_rate=.001,price_basis='HFQ',actions=[])


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_signal_fraction_opens_once_and_budget_survives_changed_target(market):
    _,spec,_,_,_=fixture(market)
    policy=frozen(spec,'signal_cash_fraction')
    first=planned(market,target=.5,policy=policy)
    assert first.capital_mode=='signal_cash_fraction'
    assert first.cycle_after.cash_budget==Decimal('5000.0')
    assert first.cycle_after.allocation_fraction==Decimal('.5')
    second=planned(market,target=.8,policy=policy,budget=first.cycle_after)
    assert second.cycle_before==second.cycle_after==first.cycle_after
    assert second.orders==first.orders
    exit_plan=planned(market,target=0.,policy=policy,budget=first.cycle_after,held=first.target_quantity)
    assert exit_plan.cycle_after.phase is EntryCyclePhase.EXITING
    assert exit_plan.target_quantity==0


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_hfq_account_settles_only_sale_proceeds_and_reports_simulated_unit_model(market):
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
