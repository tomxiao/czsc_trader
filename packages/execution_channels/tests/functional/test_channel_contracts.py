"""EC01: monetary and quantity contracts refuse fabricated account facts."""
from dataclasses import replace
from decimal import Decimal
import pytest
from execution_channels.contracts import AccountSnapshot, ReplayOrder, SellRemainderPolicy
from execution_channels.instruments import MarketId
from execution_channels.planning import plan_account_decision
from execution_channels.planning.intent import TradeIntent, DecisionExplanation
from execution_channels.policy import ExecutionPolicy
from execution_channels.serialization import to_record, from_record
from execution_channels.session_contracts import OrderSide, OrderType
from ec_facts import fixture


@pytest.mark.parametrize('quantity,error,reason',[(True,TypeError,'incorrect type'),(1.5,TypeError,'incorrect type'),(0,ValueError,'positive integer')],ids=['EC01-C02','EC01-C03','EC01-C06'])
def test_order_units_are_positive_integers(quantity,error,reason):
    with pytest.raises(error,match=reason):
        from_record(ReplayOrder,{'side':'BUY','quantity':quantity,'order_type':'LIMIT','limit_price':'10'})


@pytest.mark.parametrize('changes',[{'available_cash':Decimal('11')},{'sellable_quantity':2}],ids=['EC01-C07','EC01-C08'])
def test_account_available_facts_cannot_exceed_confirmed_assets(changes):
    instrument,_,point,_,_=fixture(MarketId.US)
    account=AccountSnapshot(instrument,'USD',point.decision_at,1,Decimal('10'),Decimal('10'),Decimal(0),1,1)
    assert from_record(AccountSnapshot,to_record(account))==account
    with pytest.raises(ValueError,match='available assets'):
        replace(account,**changes)


def test_EC01_C05_foreign_homonymous_contract_is_rejected_before_planning():
    _,spec,point,_,_=fixture(MarketId.US)
    from strategy_runtime.replay_contracts import AccountSnapshot as SrtAccountSnapshot
    from dataflows import InstrumentId as SrtInstrumentId, MarketId as SrtMarketId, AssetClass as SrtAssetClass
    foreign=SrtAccountSnapshot(SrtInstrumentId(SrtMarketId.US,SrtAssetClass.STOCK,'MU'),
        'USD',point.decision_at,0,100.,100.,0.,0,0)
    with pytest.raises(TypeError,match='typed point, account and execution contract'):
        plan_account_decision(TradeIntent(1.,DecisionExplanation({})),point,foreign,10.,spec,
            owner='account',implementation='a'*64,fee_rate=.001,
            sell_remainder_policy=SellRemainderPolicy.FULL_LIQUIDATION,
            execution_policy=ExecutionPolicy('TARGET_POSITION',{}))


def test_EC01_C04_order_enum_decimal_roundtrip():
    order=ReplayOrder(OrderSide.BUY,2,OrderType.LIMIT,Decimal('101.01'))
    assert from_record(ReplayOrder,to_record(order))==order
    instrument,_,point,_,_=fixture(MarketId.US)
    account=AccountSnapshot(instrument,'USD',point.decision_at,1,Decimal('10.25'),Decimal('9.25'),Decimal('1'),2,1)
    assert from_record(AccountSnapshot,to_record(account))==account


def test_EC01_C01_strategy_intent_cannot_carry_orders():
    with pytest.raises(TypeError, match="orders"):
        TradeIntent(1., DecisionExplanation({}), orders=())
