"""PTE01: transport SRT facts into EC without recomputing strategy decisions."""
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from decimal import Decimal
import pytest
from dataflows import InstrumentId,MarketId,AssetClass,BarFrequency,TimeInterval
from strategy_runtime import (ResearchExecutionSpec,UsEquitySpec,AccountPolicy,CashAvailabilityPolicy,
    ExecutionPolicy,ReplayPoint,AccountSnapshot)
from strategy_runtime.replay_contracts import ExecutionPrecision
from strategy_runtime.account_strategy import AccountDecision,AccountStepResult
from strategy_runtime.account_planning import AccountDecisionProposal
from strategy_runtime.equity_replay import StateRecord
from execution_channels.state import StateRecord as ExecutionState
from execution_channels.futu.equity_account_state import load_document
from paper_trading_engine.ec_boundary import execution_plan,execution_admission,execution_rules
from paper_trading_engine.account_engine import AccountEngine
from pte_support import decision,preparation


@pytest.fixture
def projected():
    start=datetime(2026,11,5,14,30,tzinfo=timezone.utc)
    end=start+timedelta(minutes=30)
    instrument=InstrumentId(MarketId.US,AssetClass.STOCK,'MU')
    spec=ResearchExecutionSpec(UsEquitySpec(),BarFrequency.M30,
        AccountPolicy('USD',CashAvailabilityPolicy.IMMEDIATE_RESEARCH),1,.01,.01,0.)
    intent=AccountDecision.from_facts(1.,'fixture',facts={'ready':True},next_watch='next close')
    state=AccountStepResult(intent,StateRecord((('seen',7),)),StateRecord((('entry',1),)))
    point=ReplayPoint(start-timedelta(days=1),start,start,end,'2026-11-05',ExecutionPrecision.BAR_INTERVAL)
    proposal=AccountDecisionProposal(state,point,3)
    snapshot=AccountSnapshot(instrument,'USD',start,0,Decimal('1000'),Decimal('1000'),Decimal(0),0,0)
    plan=execution_plan(proposal,snapshot,spec,reference=100.,execution_policy=ExecutionPolicy('TARGET_POSITION',{}),
        cycle_budget=None,locked_quantity=None,owner='strategy-account',implementation='a'*64,
        fee_rate=.001,sell_remainder_policy='FULL_LIQUIDATION')
    prepared=SimpleNamespace(interval=TimeInterval(start,end),as_of=start,
        buy_sellable_at=start,data_identity='b'*64,fee_rate=.001,v4_constraint={
            'SellRemainderPolicy':'FULL_LIQUIDATION','PriceLimitPolicy':'EXPLICIT_UNBOUNDED',
            'PriceLimitLower':None,'PriceLimitUpper':None})
    document=load_document({'account_v4_json':None,'quantity':0},ExecutionState())
    return plan,snapshot,document,state,prepared,execution_rules(instrument,spec)


def admit(case):
    plan,snapshot,document,state,prepared,rules=case
    return execution_admission(plan,snapshot,document,state,state_binding='release-binding',
        next_event_cursor=3,prepared=prepared,rules=rules)


def test_PTE01_C01_target_state_market_fee_and_observation_time_survive_projection(projected,monkeypatch):
    from execution_channels.futu import v4_admission
    real=v4_admission.prepare_v4_adoption
    observed=[]
    def capture(plan,snapshot,document,proposal,prepared,rules):
        observed.append((plan,snapshot,proposal,prepared,rules))
        return real(plan,snapshot,document,proposal,prepared,rules)
    monkeypatch.setattr(v4_admission,'prepare_v4_adoption',capture)
    result=admit(projected)
    plan,snapshot,proposal,context,rules=observed[0]
    assert len(observed)==1
    assert plan.evidence['target']==1. and plan.evidence['fee_rate']==.001
    assert plan.owner=='strategy-account' and plan.evidence['implementation']=='a'*64
    assert snapshot.instrument.symbol=='MU' and rules.instrument.market.value=='US'
    assert context.as_of==projected[4].as_of and context.as_of.utcoffset()==timedelta(0)
    assert context.fee_rate==.001
    assert proposal.account.to_dict()=={'values':[['seen',7]]} and proposal.next_event_cursor==3
    assert result.after['state']['account']=={'values':[['seen',7]]}
    assert result.after['state']['binding']=='release-binding'
    assert result.after['state']['event_cursor']==3
    assert result.orders[0].quantity==9 and result.orders[0].limit_price==101.


@pytest.mark.parametrize('fault,error,reason',[
    ('missing',TypeError,'explicit temporal record'),
    ('future',ValueError,'must not follow execution start'),
],ids=['PTE01-C02','PTE01-C03'])
def test_invalid_observation_cutoff_never_reaches_execution_adoption(projected,monkeypatch,fault,error,reason):
    from execution_channels.futu import v4_admission
    calls=[]
    monkeypatch.setattr(v4_admission,'prepare_v4_adoption',lambda *args:calls.append(args))
    prepared=projected[4]
    prepared.as_of=None if fault=='missing' else prepared.interval.start+timedelta(seconds=1)
    with pytest.raises(error,match=reason):
        admit(projected)
    assert calls==[]


def test_PTE01_C04_strategy_order_injection_propagates_without_account_mutation(memory_store):
    store=memory_store()
    store.create_virtual_account('strategy','strategy','v1','a'*64,100000,
        strategy_id='S001',strategy_name_snapshot='Fixture',strategy_version='v1',
        release_hash='b'*64,qualification_snapshot='PAPER_READY',selection_data_cutoff='2026-09-01')
    store.set_virtual_paused('strategy',False)
    explanation=AccountDecision.from_facts(1.,'fixture',facts={'ready':True},next_watch='next close').explanation
    class InvalidStrategy:
        calls=0
        def get_decision(self,*args,**kwargs):
            self.calls+=1
            return AccountDecision(1.,explanation,orders=())
    source=InvalidStrategy()
    engine=AccountEngine(store,source)
    before=tuple(store._connection.iterdump())
    with pytest.raises(TypeError,match='orders'):
        engine.refresh_account('strategy',prepared=preparation(decision()))
    assert source.calls==1
    assert tuple(store._connection.iterdump())==before
    assert store.account_decisions('strategy')==store.account_intents('strategy')==[]
