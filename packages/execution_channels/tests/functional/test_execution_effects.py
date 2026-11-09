"""Planning is not execution: explicit confirmed effects and target deviations."""
from decimal import Decimal
from dataclasses import replace

import pytest

from execution_channels.execution_effects import (ExecutionEffectStatus, OrderExecutionEffect,
                                                 decision_execution_effect)
from execution_channels.instruments import MarketId
from ec_facts import fixture


def project(orders=(), *, status='BLOCKED', cash='100', receivable='0', actual=0):
    _, _, point, _, _ = fixture(MarketId.US)
    return decision_execution_effect(decision_id='decision', at=point.decision_at, target_weight=1.,
        planning_result={'status':status, 'reasons':['INSUFFICIENT_CASH'] if status=='BLOCKED' else [],
                         'desired_quantity':10, 'planned_quantity':actual if not orders else 10},
        actual_quantity=actual, cash=cash, available_cash=cash, receivable=receivable,
        valuation_price=10., orders=orders)


# Independent risk: EC13; responsibility-level assertions.
def test_EC13_C04_empty_blocked_effect_is_not_success_and_keeps_target():
    effect = project()
    assert effect.status is ExecutionEffectStatus.NOT_EXECUTED and effect.terminal
    assert (effect.target_weight,effect.actual_weight,effect.weight_deviation)==(1.,0.,-1.)
    assert effect.constraint_reasons == ('INSUFFICIENT_CASH',)


# Independent risk: EC13; responsibility-level assertions.
@pytest.mark.parametrize('status,count,in_flight,unknown,expected',[
    ('SUBMITTED',0,True,False,'WAITING'), ('FILLED_PART',4,True,False,'PARTIAL'),
    ('TIMEOUT',0,True,True,'UNKNOWN')], ids=['EC13-C01','EC13-C02','EC13-C03'])
def test_effect_separates_confirmed_fills_from_order_progress(status,count,in_flight,unknown,expected):
    order=OrderExecutionEffect('order','BUY',10,count,status,in_flight,unknown)
    effect=project((order,),status='READY',actual=count)
    assert effect.status.value == expected and effect.terminal is not in_flight
    assert effect.actual_quantity == count


# Independent risk: EC13; responsibility-level assertions.
def test_EC13_C06_effect_rejects_fabricated_quantities():
    with pytest.raises(ValueError,match='within'):
        OrderExecutionEffect('order','BUY',1,2,'FILLED_ALL',False)


def test_EC13_C05_effect_rejects_invalid_valuation():
    with pytest.raises(ValueError,match='valuation'):
        replace(project(),valuation_price=Decimal(0))
