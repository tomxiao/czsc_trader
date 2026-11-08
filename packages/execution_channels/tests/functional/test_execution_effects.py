"""Planning is not execution: explicit confirmed effects and target deviations."""
from datetime import timedelta
from decimal import Decimal
from dataclasses import replace

import pytest

from execution_channels.execution_effects import (ExecutionEffectStatus, OrderExecutionEffect,
                                                 decision_execution_effect)
from execution_channels.contracts import AccountSnapshot, SellRemainderPolicy
from execution_channels.historical import PortfolioHistoricalExecutor
from execution_channels.historical.channel import HistoricalReplayChannel, HistoricalDecision
from execution_channels.instruments import MarketId
from execution_channels.planning import plan_account_decision
from execution_channels.planning.intent import TradeIntent, DecisionExplanation
from execution_channels.policy import ExecutionPolicy
from execution_channels.state import StateRecord
from test_historical_boundary import fixture


def project(orders=(), *, status='BLOCKED', cash='100', receivable='0', actual=0):
    _, _, point, _, _ = fixture(MarketId.US)
    return decision_execution_effect(decision_id='decision', at=point.decision_at, target_weight=1.,
        planning_result={'status':status, 'reasons':['INSUFFICIENT_CASH'] if status=='BLOCKED' else [],
                         'desired_quantity':10, 'planned_quantity':actual if not orders else 10},
        actual_quantity=actual, cash=cash, available_cash=cash, receivable=receivable,
        valuation_price=10., orders=orders)


def test_empty_blocked_effect_is_not_success_and_keeps_target():
    effect = project()
    assert effect.status is ExecutionEffectStatus.NOT_EXECUTED and effect.terminal
    assert (effect.target_weight,effect.actual_weight,effect.weight_deviation)==(1.,0.,-1.)
    assert effect.constraint_reasons == ('INSUFFICIENT_CASH',)
    assert project(status='NO_CHANGE').status is ExecutionEffectStatus.COMPLETED
    zero = project(cash='0')
    assert zero.actual_weight is None and zero.weight_deviation is None


@pytest.mark.parametrize('status,count,in_flight,unknown,expected',[
    ('SUBMITTED',0,True,False,'WAITING'), ('FILLED_PART',4,True,False,'PARTIAL'),
    ('FILLED_ALL',10,False,False,'COMPLETED'), ('CANCELLED_PART',4,False,False,'PARTIAL'),
    ('EXPIRED',0,False,False,'NOT_EXECUTED'), ('TIMEOUT',0,True,True,'UNKNOWN')])
def test_effect_separates_confirmed_fills_from_order_progress(status,count,in_flight,unknown,expected):
    order=OrderExecutionEffect('order','BUY',10,count,status,in_flight,unknown)
    effect=project((order,),status='READY',actual=count)
    assert effect.status.value == expected and effect.terminal is not in_flight
    assert effect.actual_quantity == count
    if count == 10:
        assert effect.actual_weight == .5  # completed orders do not mean target weight attained


def test_effect_rejects_fabricated_quantities_and_invalid_valuation():
    with pytest.raises(ValueError,match='within'):
        OrderExecutionEffect('order','BUY',1,2,'FILLED_ALL',False)
    with pytest.raises(ValueError,match='duplicate'):
        project((OrderExecutionEffect('same','BUY',1,0,'SUBMITTED',True),)*2,status='READY')
    with pytest.raises(ValueError,match='valuation'):
        replace(project(),valuation_price=Decimal(0))


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
@pytest.mark.parametrize('filled',[False,True])
def test_historical_effect_before_and_after_execution(market,filled):
    instrument,spec,point,bar,rule=fixture(market)
    if not filled:
        bar={**bar,'Open':10.5,'High':10.6,'Low':10.4,'Close':10.5}
    account=AccountSnapshot(instrument,instrument.currency,point.decision_at,0,10000.,10000.,0.,0,0)
    plan=plan_account_decision(TradeIntent(.5,DecisionExplanation({})),point,account,10.,spec,
        owner='account',implementation='a'*64,fee_rate=.001,
        sell_remainder_policy=SellRemainderPolicy.FULL_LIQUIDATION,
        execution_policy=ExecutionPolicy('TARGET_POSITION',{}))
    executor=PortfolioHistoricalExecutor(specification=spec,initial_cash=10000.,fee_rate=.001,price_basis='HFQ')
    channel=HistoricalReplayChannel.from_executor(executor,account_id='account',instrument=instrument,
        bars=[bar],constraints=[rule])
    channel.advance(point.decision_at)
    channel.adopt('account',HistoricalDecision(plan,0,StateRecord(),StateRecord(),0,'binding'))
    waiting=channel.decision_execution_effect(plan.plan_identity,valuation_price=10.,at=point.decision_at)
    assert waiting.status is ExecutionEffectStatus.WAITING and waiting.actual_quantity==0
    channel.advance(point.execution_end)
    effect=channel.decision_execution_effect(plan.plan_identity,valuation_price=10.5,at=point.execution_end)
    assert effect.status is (ExecutionEffectStatus.COMPLETED if filled else ExecutionEffectStatus.NOT_EXECUTED)
    assert effect.actual_quantity == (500 if filled else 0)
    assert effect.cash == Decimal(str(executor.cash)) and effect.terminal
    with pytest.raises(ValueError,match='clock'):
        channel.decision_execution_effect(plan.plan_identity,valuation_price=10.,at=point.execution_end-timedelta(seconds=1))
