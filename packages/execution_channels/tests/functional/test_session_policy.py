"""EC33/34: financial policy inputs go directly to the channel planner."""
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
import pytest
from execution_channels.planning.session import build_execution_plan, SessionProposal, plan_session_decision
from execution_channels.session_contracts import (StrategyIdentity, TradingPoint, PriceReference,
    PortfolioSnapshot, ExecutionState, signal_identity_for)
from execution_channels.policy import ExecutionPolicy
from execution_channels.errors import RuntimeContractError


SETTINGS = {
    'capital': {'fee_rate': .001, 'mode': 'target_equity_fraction',
                'target_scope': 'decision', 'allocation_fraction': 1.},
    'entry': {'limit_parameter': .01, 'order_type': 'LIMIT'},
    'exit': {'limit_ratio': .1, 'order_type': 'MARKET'},
    'instrument': {'lot_size': 100, 'maximum_order_quantity': 1000,
                   'price_limit_ratio': .1, 'price_tick': .001},
}


def plan(target, cash=10000., held=1000, reference=10., *, policy=None, locked=99900):
    return build_execution_plan(deployment_settings={'cycle_target_quantity': locked},
        available_cash=cash, position_quantity=held, target_position=target,
        policy=policy or ExecutionPolicy('FROZEN_RULE', SETTINGS),
        signal_reference_price=reference, execution_reference_price=reference)


@pytest.mark.parametrize('target,quantity,side', [
    pytest.param(.25, 500, 'SELL', id='EC33-C01'),
    pytest.param(.5, 1000, None, id='EC33-C02'),
    pytest.param(.75, 1500, 'BUY', id='EC33-C03'),
    pytest.param(1., 1900, 'BUY', id='EC33-C04'),
])
def test_equity_targets(target, quantity, side):
    result = plan(target)
    assert result['target_position'] == target
    assert result['target_quantity'] == quantity
    assert result['delta_quantity'] == quantity - 1000
    assert [o['side'] for o in result['orders']] == ([] if side is None else [side])
    assert result['capital_rule']['target_scope'] == 'decision'
    assert result['unallocated_cash'] >= 0
    if side == 'BUY':
        assert result['orders'][0]['limit_price'] == 10.1
    elif side == 'SELL':
        assert result['orders'][0]['order_type'] == 'MARKET'


def test_EC33_C05_order_cap_splits_without_exceeding_cash():
    result = plan(.75, cash=60000., held=0)
    assert result['target_quantity'] == 4500
    assert [o['quantity'] for o in result['orders']] == [1000,1000,1000,1000,500]
    assert sum(o['quantity'] * o['limit_price'] * 1.001 for o in result['orders']) <= 60000


@pytest.mark.parametrize('reference,action,quantity', [
    pytest.param(20., 'SELL', 700, id='EC33-C06'),
    pytest.param(5., 'BUY', 1500, id='EC33-C07'),
])
def test_price_drift_rebalances_real_equity(reference, action, quantity):
    result = plan(.5, reference=reference)
    assert (result['action'], result['target_quantity']) == (action, quantity)


@pytest.mark.parametrize('field,value', [
    pytest.param('target_scope','entry_cycle',id='EC33-C08'),
    pytest.param('allocation_fraction',.5,id='EC33-C09'),
])
def test_equity_capital_has_one_unambiguous_source(field,value):
    settings=deepcopy(SETTINGS)
    settings['capital'][field]=value
    with pytest.raises(RuntimeContractError,match='decision scope and allocation fraction one'):
        ExecutionPolicy('FROZEN_RULE',settings)


def frozen(*, marketable=False):
    settings=deepcopy(SETTINGS)
    settings['capital'].update(mode='full_available_cash',target_scope='entry_cycle')
    settings['exit'].update(order_type='LIMIT')
    if marketable:
        settings['virtual_fill']={'sell':'marketable_limit_at_open'}
    return ExecutionPolicy('FROZEN_RULE',settings)


def test_EC34_C01_held_frozen_position_does_not_restart_cycle():
    result=plan(1.,cash=50000.,held=5900,reference=5.,policy=frozen(),locked=5900)
    assert result['action']=='HOLD'
    assert result['target_quantity']==result['cycle_target_quantity']==5900
    assert result['orders']==[]


@pytest.mark.parametrize('marketable,kind,price', [
    # Frozen LIMIT exits stay one tick inside the dated lower price boundary.
    pytest.param(False,'LIMIT',1.351,id='EC34-C02'),
    pytest.param(True,'MARKET',1.5,id='EC34-C03'),
])
def test_frozen_exit_semantics(marketable,kind,price):
    result=plan(0.,cash=100.,reference=1.5,policy=frozen(marketable=marketable),locked=1000)
    assert result['action']=='SELL'
    assert result['orders'][0]['order_type']==kind
    assert result['orders'][0]['limit_price']==pytest.approx(price)


def test_EC34_C04_binary_policy_rejects_fractional_target():
    with pytest.raises(RuntimeContractError,match='binary target position'):
        plan(.5,policy=frozen())


@pytest.mark.parametrize('held,target,mode,capital,fraction,sides', [
    pytest.param(0,1.,'CORE_SETUP','available_cash_fraction',.5,['BUY'],id='EC34-C05'),
    pytest.param(5900,1.,'CORE_EVENT_INTRADAY_ROTATION','full_available_cash',1.,['BUY','SELL'],id='EC34-C06'),
    pytest.param(5900,0.,'NONE','full_available_cash',1.,[],id='EC34-C07'),
])
def test_overlay_preserves_core_and_explicit_capital(held,target,mode,capital,fraction,sides):
    policy=ExecutionPolicy('INTRADAY_OVERLAY',{'lot_size':100,'one_way_cost':.001,'core_fraction':.5,'event_fraction':.5})
    at=datetime(2026,9,1,20,tzinfo=timezone.utc)
    signal_date=date(2026,9,1)
    identity=StrategyIdentity('S999','S999-v1','a'*64,'b'*64,'588080.SH')
    facts={'prices':'c'*64}
    signal=signal_identity_for(strategy=identity,signal_date=signal_date,target_position=target,
        input_identities=facts,price_identities=facts)
    proposal=SessionProposal(identity,TradingPoint(date(2026,9,2),at),signal_date,signal,target,None,{},
        PriceReference(Decimal(5),Decimal(5),'ADJUSTED_CLOSE','UNADJUSTED_CLOSE'),facts,facts,policy)
    portfolio=PortfolioSnapshot('account','588080.SH',Decimal(50000),Decimal(50000+held*5),held,0,at)
    result=plan_session_decision(proposal,portfolio,ExecutionState(0,at,held or None))
    assert (result.plan_mode,result.capital_mode)==(mode,capital)
    assert result.allocation_fraction==Decimal(str(fraction))
    orders=result.orders or tuple(leg.order for leg in result.legs)
    assert [order.side.value for order in orders]==sides
    if held:
        assert result.target_quantity==held
