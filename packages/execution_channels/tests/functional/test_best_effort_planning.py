"""Executable constraints are outcomes; malformed contracts remain errors."""
from dataclasses import replace
from decimal import Decimal

import pytest

from execution_channels.contracts import AccountSnapshot, SellRemainderPolicy
from execution_channels.instruments import MarketId
from execution_channels.planning import plan_account_decision
from execution_channels.planning.intent import DecisionExplanation, TradeIntent
from execution_channels.planning.result import PlanningConstraint, PlanningResult, PlanningStatus
from execution_channels.policy import ExecutionPolicy
from test_historical_boundary import fixture
from test_hfq_planning import frozen


def plan(market, *, cash=10000., available=None, receivable=0., held=0,
         sellable=None, target=1., reference=100., policy=None, lock=None,
         suppressed=False):
    instrument,spec,point,_,_=fixture(market)
    account=AccountSnapshot(instrument,instrument.currency,point.decision_at,0,
        cash,cash if available is None else available,receivable,held,held if sellable is None else sellable)
    return plan_account_decision(TradeIntent(target,DecisionExplanation({'reason':'test'})),
        point,account,reference,spec,owner='best-effort',implementation='a'*64,fee_rate=.001,
        sell_remainder_policy=SellRemainderPolicy.FULL_LIQUIDATION,
        execution_policy=policy or ExecutionPolicy('TARGET_POSITION',{}),
        locked_quantity=lock,suppressed=suppressed)


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_existing_position_target_survives_fee_unaffordable_last_unit(market):
    _,spec,_,_,_=fixture(market)
    step=spec.quantity_step
    result=plan(market,cash=100.*step,held=10*step)
    assert result.orders==() and result.target_quantity==10*step
    assert result.evidence['target']==1.
    assert result.planning_result==PlanningResult(PlanningStatus.BLOCKED,
        (PlanningConstraint.INSUFFICIENT_CASH,),11*step,10*step)


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_affordable_portion_is_planned_but_never_claimed_as_execution(market):
    _,spec,_,_,_=fixture(market)
    step=spec.quantity_step
    result=plan(market,cash=1000.*step,available=250.*step)
    assert result.planning_result.status is PlanningStatus.CONSTRAINED
    assert result.planning_result.desired_quantity==10*step
    assert result.planning_result.planned_quantity==2*step
    assert result.orders[0].quantity==2*step
    assert result.orders[0].limit_price==101.
    assert result.planning_result.reasons==(PlanningConstraint.INSUFFICIENT_CASH,)


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_receivable_is_equity_but_not_spendable_cash(market):
    _,spec,_,_,_=fixture(market)
    step=spec.quantity_step
    result=plan(market,cash=0.,receivable=1000.*step,held=10*step)
    assert result.planning_result.status is PlanningStatus.BLOCKED
    assert result.planning_result.desired_quantity==20*step
    assert result.target_quantity==10*step and result.orders==()


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
@pytest.mark.parametrize('kind',['TARGET_POSITION','FROZEN_RULE'])
@pytest.mark.parametrize('sellable_lots',[0,2])
def test_only_confirmed_sellable_inventory_is_offered(market,kind,sellable_lots):
    _,spec,_,_,_=fixture(market)
    step=spec.quantity_step
    policy=ExecutionPolicy('TARGET_POSITION',{}) if kind=='TARGET_POSITION' else frozen(spec)
    result=plan(market,cash=0.,held=10*step,sellable=sellable_lots*step,target=0.,policy=policy)
    assert result.evidence['target']==0.
    assert result.target_quantity==(10-sellable_lots)*step
    assert sum(o.quantity for o in result.orders)==sellable_lots*step
    assert result.planning_result.status is (PlanningStatus.CONSTRAINED if sellable_lots else PlanningStatus.BLOCKED)
    assert PlanningConstraint.INSUFFICIENT_SELLABLE_QUANTITY in result.planning_result.reasons


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_unaffordable_entry_does_not_create_a_cycle_budget_or_quantity_lock(market):
    _,spec,_,_,_=fixture(market)
    result=plan(market,cash=1.,policy=frozen(spec,'signal_cash_fraction'),target=.5)
    assert result.planning_result.status is PlanningStatus.BLOCKED
    assert result.cycle_before is None and result.cycle_after is None
    assert result.evidence['locked_quantity'] is None and result.evidence['target']==.5


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_overlay_does_not_buy_without_required_sellable_exit_inventory(market):
    _,spec,_,_,_=fixture(market)
    step=spec.quantity_step
    policy=ExecutionPolicy('INTRADAY_OVERLAY',{'lot_size':step,'core_fraction':.5,'one_way_cost':.001})
    result=plan(market,cash=10000.*step,held=10*step,sellable=0,policy=policy,lock=10*step)
    assert result.planning_result.status is PlanningStatus.BLOCKED
    assert result.orders==() and result.legs==() and result.target_quantity==10*step
    assert result.planning_result.reasons==(PlanningConstraint.INSUFFICIENT_SELLABLE_QUANTITY,
                                           PlanningConstraint.DEPENDENCY_UNAVAILABLE)


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
@pytest.mark.parametrize('held',[0,100])
def test_overlay_insufficient_cash_preserves_account_without_orders(market,held):
    _,spec,_,_,_=fixture(market)
    policy=ExecutionPolicy('INTRADAY_OVERLAY',{'lot_size':spec.quantity_step,'core_fraction':.5,'one_way_cost':.001})
    result=plan(market,cash=1.,held=held,policy=policy,lock=held or None)
    assert result.planning_result.status is PlanningStatus.BLOCKED
    assert PlanningConstraint.INSUFFICIENT_CASH in result.planning_result.reasons
    assert result.orders==() and result.legs==() and result.target_quantity==held


@pytest.mark.parametrize('reference',[0.,-1.,float('nan'),float('inf')])
def test_invalid_reference_remains_contract_error(reference):
    with pytest.raises(ValueError,match='finite positive'):
        plan(MarketId.US,reference=reference)


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
@pytest.mark.parametrize('kind',['TARGET_POSITION','FROZEN_RULE'])
def test_positive_reference_below_price_tick_is_a_constraint_not_zero_price_order(market,kind):
    _,spec,_,_,_=fixture(market)
    policy=ExecutionPolicy('TARGET_POSITION',{}) if kind=='TARGET_POSITION' else frozen(spec)
    result=plan(market,cash=100.,reference=.001,policy=policy)
    assert result.planning_result.status is PlanningStatus.BLOCKED
    assert PlanningConstraint.BELOW_PRICE_TICK in result.planning_result.reasons
    assert result.orders==() and result.legs==()


def test_wrong_execution_units_remain_contract_error():
    _,spec,_,_,_=fixture(MarketId.CN)
    original=frozen(spec)
    settings={**dict(original.settings),'instrument':{**dict(original.settings['instrument']),'lot_size':1}}
    with pytest.raises(ValueError,match='units differ'):
        plan(MarketId.CN,policy=ExecutionPolicy('FROZEN_RULE',settings))


def test_no_change_and_suppressed_are_not_blocked_or_executed():
    unchanged=plan(MarketId.US,cash=0.,held=10)
    suppressed=plan(MarketId.US,cash=0.,held=10,target=0.,suppressed=True)
    assert unchanged.planning_result.status is PlanningStatus.NO_CHANGE
    assert suppressed.planning_result.status is PlanningStatus.SUPPRESSED
    assert unchanged.planning_result.reasons==suppressed.planning_result.reasons==()
    assert unchanged.orders==suppressed.orders==()


def test_planning_result_roundtrip_and_invalid_state_rejection():
    original=plan(MarketId.US,cash=100.,held=10).planning_result
    assert PlanningResult.from_dict(original.to_dict())==original
    with pytest.raises(ValueError,match='explicit reasons'):
        replace(original,reasons=())
    with pytest.raises(ValueError,match='distinct typed'):
        replace(original,reasons=(PlanningConstraint.INSUFFICIENT_CASH,)*2)
    with pytest.raises(ValueError,match='nonnegative integers'):
        replace(original,desired_quantity=Decimal(1))
