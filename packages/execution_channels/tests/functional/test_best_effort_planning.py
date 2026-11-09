"""Executable constraints are outcomes; malformed contracts remain errors."""
from decimal import Decimal

import pytest

from execution_channels.contracts import AccountSnapshot, SellRemainderPolicy
from execution_channels.instruments import MarketId
from execution_channels.planning import plan_account_decision
from execution_channels.planning.intent import DecisionExplanation, TradeIntent
from execution_channels.planning.result import PlanningConstraint, PlanningResult, PlanningStatus
from execution_channels.policy import ExecutionPolicy
from ec_facts import fixture
from ec_facts import frozen


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


# Independent risk: EC04; responsibility-level assertions.
@pytest.mark.parametrize('market',[MarketId.US])
def test_existing_position_target_survives_fee_unaffordable_last_unit(market):
    _,spec,_,_,_=fixture(market)
    step=spec.quantity_step
    result=plan(market,cash=100.*step,held=10*step)
    assert result.orders==() and result.target_quantity==10*step
    assert result.evidence['target']==1.
    assert result.planning_result==PlanningResult(PlanningStatus.BLOCKED,
        (PlanningConstraint.INSUFFICIENT_CASH,),11*step,10*step)


# Independent risk: EC03; responsibility-level assertions.
@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US], ids=['EC03-C01','EC03-C02'])
def test_quote_premium_and_cash_lot_budget(market):
    _,spec,_,_,_=fixture(market)
    step=spec.quantity_step
    cash=Decimal('250')*step
    result=plan(market,cash=float(cash))
    assert len(result.orders)==1
    assert result.orders[0].quantity==2*step
    assert result.orders[0].limit_price==101.
    committed=Decimal(str(result.orders[0].limit_price))*result.orders[0].quantity*Decimal('1.001')
    assert committed < cash < committed + Decimal('101.101')*step
    assert result.evidence['target']==1.



# Independent risk: EC04; responsibility-level assertions.
@pytest.mark.parametrize('market',[MarketId.US])
def test_receivable_is_equity_but_not_spendable_cash(market):
    _,spec,_,_,_=fixture(market)
    step=spec.quantity_step
    result=plan(market,cash=0.,receivable=1000.*step,held=10*step)
    assert result.planning_result.status is PlanningStatus.BLOCKED
    assert result.planning_result.desired_quantity==20*step
    assert result.target_quantity==10*step and result.orders==()


# Independent risk: EC06; responsibility-level assertions.
@pytest.mark.parametrize('market,kind,sellable_lots', [
    pytest.param(MarketId.CN,'TARGET_POSITION',2,id='EC06-C01'),
    pytest.param(MarketId.US,'FROZEN_RULE',0,id='EC06-C02'),
])
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


# Independent risk: EC04; responsibility-level assertions.
@pytest.mark.parametrize('market',[MarketId.US])
def test_unaffordable_entry_does_not_create_a_cycle_budget_or_quantity_lock(market):
    _,spec,_,_,_=fixture(market)
    result=plan(market,cash=1.,policy=frozen(spec,'signal_cash_fraction'),target=.5)
    assert result.planning_result.status is PlanningStatus.BLOCKED
    assert result.cycle_before is None and result.cycle_after is None
    assert result.evidence['locked_quantity'] is None and result.evidence['target']==.5


# Independent risk: EC28; responsibility-level assertions.
@pytest.mark.parametrize('market',[MarketId.US])
def test_overlay_does_not_buy_without_required_sellable_exit_inventory(market):
    _,spec,_,_,_=fixture(market)
    step=spec.quantity_step
    policy=ExecutionPolicy('INTRADAY_OVERLAY',{'lot_size':step,'core_fraction':.5,'one_way_cost':.001})
    result=plan(market,cash=10000.*step,held=10*step,sellable=0,policy=policy,lock=10*step)
    assert result.planning_result.status is PlanningStatus.BLOCKED
    assert result.orders==() and result.legs==() and result.target_quantity==10*step
    assert result.planning_result.reasons==(PlanningConstraint.INSUFFICIENT_SELLABLE_QUANTITY,
                                           PlanningConstraint.DEPENDENCY_UNAVAILABLE)


# Independent risk: EC03; responsibility-level assertions.
def test_EC03_C04_positive_reference_below_price_tick_is_a_constraint_not_zero_price_order():
    market, kind = MarketId.US, 'TARGET_POSITION'
    _,spec,_,_,_=fixture(market)
    policy=ExecutionPolicy('TARGET_POSITION',{}) if kind=='TARGET_POSITION' else frozen(spec)
    result=plan(market,cash=100.,reference=.001,policy=policy)
    assert result.planning_result.status is PlanningStatus.BLOCKED
    assert PlanningConstraint.BELOW_PRICE_TICK in result.planning_result.reasons
    assert result.orders==() and result.legs==()


# Independent risk: EC01; responsibility-level assertions.


# Independent risk: EC04; responsibility-level assertions.
def test_no_change_and_suppressed_are_not_blocked_or_executed():
    unchanged=plan(MarketId.US,cash=0.,held=10)
    suppressed=plan(MarketId.US,cash=0.,held=10,target=0.,suppressed=True)
    assert unchanged.planning_result.status is PlanningStatus.NO_CHANGE
    assert suppressed.planning_result.status is PlanningStatus.SUPPRESSED
    assert unchanged.planning_result.reasons==suppressed.planning_result.reasons==()
    assert unchanged.orders==suppressed.orders==()




def test_EC03_C05_exact_fee_inclusive_cash_buys_one_unit():
    result = plan(MarketId.US, cash=101.101)
    assert len(result.orders) == 1
    assert result.orders[0].quantity == 1
    assert result.orders[0].limit_price == 101.
    assert Decimal(str(result.orders[0].limit_price)) * Decimal('1.001') == Decimal('101.101')


def test_EC03_C06_explanation_cannot_change_order_finances():
    instrument,spec,point,_,_=fixture(MarketId.US)
    account=AccountSnapshot(instrument,'USD',point.decision_at,0,1000.,1000.,0.,0,0)
    arguments=dict(owner='same-account',implementation='a'*64,fee_rate=.001,
        sell_remainder_policy=SellRemainderPolicy.FULL_LIQUIDATION,
        execution_policy=ExecutionPolicy('TARGET_POSITION',{}))
    first=plan_account_decision(TradeIntent(1.,DecisionExplanation({'reason':'first'})),point,account,100.,spec,**arguments)
    second=plan_account_decision(TradeIntent(1.,DecisionExplanation({'reason':'second','quantity':99999,'price':1.})),point,account,100.,spec,**arguments)
    assert first.orders==second.orders
    assert first.target_quantity==second.target_quantity==9
    assert first.planning_result==second.planning_result


def test_EC03_C03_nonfinite_reference_is_a_contract_error():
    with pytest.raises(ValueError,match='planning reference must be finite positive price'):
        plan(MarketId.US,reference=float('nan'))


def test_EC04_C02_affordable_portion_is_not_actual_execution():
    result=plan(MarketId.US,cash=1000.,available=250.)
    assert result.planning_result==PlanningResult(PlanningStatus.CONSTRAINED,
        (PlanningConstraint.INSUFFICIENT_CASH,),10,2)
    assert result.orders[0].quantity==2 and result.orders[0].limit_price==101.
