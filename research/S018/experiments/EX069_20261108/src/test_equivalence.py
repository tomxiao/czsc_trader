"""Focused synthetic contract checks; these are not financial performance evidence."""
from dataclasses import replace
from datetime import datetime, time
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from dataflows import BarFrequency, TimeInterval, TradingSession
from strategy_runtime import (AccountDecision, AccountDecisionEngine, AccountStepContext,
    AccountStrategyState, CycleState, EquityPortfolio, PositionCycle, PositionFeedback,
    PreparedObservations, StateRecord)
from strategy_runtime.replay_contracts import AccountSnapshot
from execution_channels.historical import PortfolioHistoricalExecutor
from execution_channels.historical.channel import HistoricalReplayChannel, HistoricalDecision, AdoptionStatus
from execution_channels.state import StateRecord as ECStateRecord
from execution_channels.planning.result import PlanningStatus, PlanningConstraint
from czsc_trader.application.account_replay import run_replay
from czsc_trader.application.ec_boundary import (execution_spec, execution_instrument,
    execution_plan as research_plan, strategy_portfolio, strategy_snapshot, strategy_feedback)
from paper_trading_engine.ec_boundary import execution_plan as paper_plan

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = _load('s018_target_candidate_tests', HERE/'candidate.py')
implementation = _load('s018_target_strategy_tests', HERE/'strategy.py')


def fixture(*, price=102., sector_price=205., descending=False):
    candidate = builder.build_candidate()
    days = pd.bdate_range('2026-01-05', periods=80)
    zone = ZoneInfo('America/New_York')
    sessions = tuple(TradingSession(day.date(), str(zone), (TimeInterval(
        datetime.combine(day.date(), time(9, 30), zone),
        datetime.combine(day.date(), time(16), zone)),)) for day in days)
    starts = pd.DatetimeIndex([s.segments[0].start for s in sessions]).tz_convert('UTC')
    ends = pd.DatetimeIndex([s.segments[0].end for s in sessions]).tz_convert('UTC')
    x = np.arange(len(days))
    mu = 100 * np.exp(.001*x + .012*np.sin(x*.7))
    soxx = 200 * np.exp(.001*x + .012*np.sin(x*.7))
    mu[67:76] = [102.,101.,100.,100.2,100.4,102.,104.,105.,106.]
    soxx[67:76] = [200.,201.,202.,203.,204.,205.,206.,207.,208.]
    if not descending:
        mu[69], soxx[69] = price, sector_price
    def bars(close):
        return pd.DataFrame({'BarStart':starts, 'Date':ends, 'AvailableDate':ends,
            'Open':close, 'High':close*1.02, 'Low':close*.98, 'Close':close,
            'Volume':1000000., 'Amount':close*1000000.})
    frame, auxiliary = bars(mu), bars(soxx)
    calendar = pd.DataFrame({'Date':starts, 'AvailableDate':starts,
        'SessionDate':[s.session_date.isoformat() for s in sessions]})
    prepared = PreparedObservations.from_frames(frame,candidate.definition.feature_graph,
        auxiliary_histories={'soxx_hfq':auxiliary},sessions=calendar,trading_sessions=sessions,
        frequency=BarFrequency.DAILY,timezone=str(zone))
    constraints = pd.DataFrame({'Date':starts,'AvailableDate':starts,'QuantityStep':1,
        'PriceTick':.01,'Tradable':True,'SellRemainderPolicy':'FULL_LIQUIDATION',
        'PriceLimitPolicy':'EXPLICIT_UNBOUNDED','PriceLimitLower':None,'PriceLimitUpper':None,
        'BuySellableAt':starts,'SettlementAt':ends})
    return candidate, prepared, frame, constraints


def context(candidate, prepared, *, held=0, allocation=.375, promoted=False,
            exiting=False, buy_fills=1, quantity=100):
    engine = AccountDecisionEngine(candidate,prepared)
    start,end = prepared._data.starts[70],prepared._data.ends[70]
    point, features, history, views, _, _, _ = engine.observation(TimeInterval(start,end))
    active = None
    state = AccountStrategyState()
    if held:
        entry = TimeInterval(prepared._data.starts[70-held],prepared._data.ends[70-held])
        active = PositionCycle('confirmed-cycle',entry,entry,quantity,10000.,0.,10.,buy_fills,0)
        values = StateRecord((('anchor',100.),('sector_anchor',202.),('allocation',allocation),
            ('promoted',promoted),('exiting',exiting)))
        state = AccountStrategyState(cycle=CycleState(active.cycle_id,entry.start,values))
    else:
        quantity=0
    account = AccountSnapshot(candidate.instrument,'USD',start,0,90000.,90000.,0.,quantity,quantity)
    portfolio = EquityPortfolio(90000.,quantity,0.,0,active.entry_interval.start if active else None)
    ctx = AccountStepContext(point,portfolio,account,PositionFeedback(active),candidate.definition.parameters,
        features,history,auxiliary_histories=views)
    return engine,ctx,state


class LegacyCapture:
    """Test-only capture of removed execution kwargs; never a production adapter."""
    captured = None

    @classmethod
    def from_facts(cls,target,reason,*,facts,next_watch,**execution):
        cls.captured={'target':target,'reason':reason,'facts':facts,'execution':execution}
        return AccountDecision.from_facts(target,reason,facts=facts,next_watch=next_watch)


def legacy_step(ctx,state):
    namespace = {'__name__':'s018_frozen_formula_test'}
    path = ROOT/'strategies/S018/releases/v1/src/strategy_runtime/strategy.py'
    exec(compile(path.read_text(encoding='utf-8'),str(path),'exec'),namespace)
    namespace['AccountDecision']=LegacyCapture
    oldctx=SimpleNamespace(parameters=ctx.parameters, history=ctx.history,
        auxiliary_histories={'mu_hfq':ctx.history,**ctx.auxiliary_histories},point=ctx.point,
        position=ctx.position,account=ctx.account,portfolio=SimpleNamespace(reference_price_scale=1.))
    if state.cycle:
        values=StateRecord((('anchor',state.cycle.values.get('anchor')),
            ('sector_anchor',state.cycle.values.get('sector_anchor')),('entry_budget',90000.*.375)))
        state=replace(state,cycle=replace(state.cycle,values=values))
    result=namespace['step'](oldctx,state)
    return result,LegacyCapture.captured


def financial_predicate_comparison(mu,soxx,*,start=None,end=None):
    """Compare frozen/new flat-state predicates over supplied visible prefixes.

    Caller obtains real frames through DFLS and owns evidence publication. This
    helper never reads research assets or requests suppliers. Same HFQ inputs
    intentionally isolate formula equivalence from price/acquisition differences.
    """
    c=builder.build_candidate()
    if mu.Date.tolist()!=soxx.Date.tolist():
        raise ValueError('predicate comparison requires aligned MU/SOXX dates')
    required=max(63,int(c.definition.parameters['beta_window'])+
                 int(c.definition.parameters['entry_days'])+1)
    rows=[]
    groups={True:0,False:0}
    for count in range(required,len(mu)+1):
        observed=pd.Timestamp(mu.Date.iloc[count-1])
        if start is not None and observed.date()<pd.Timestamp(start).date():
            continue
        if end is not None and observed.date()>pd.Timestamp(end).date():
            continue
        left,right=mu.iloc[:count],soxx.iloc[:count]
        decision_at=max(left.AvailableDate.max(),right.AvailableDate.max())
        history=SimpleNamespace(to_frame=lambda tail=None,f=left: f.copy() if tail is None else f.tail(tail).copy())
        auxiliary=SimpleNamespace(to_frame=lambda tail=None,f=right: f.copy() if tail is None else f.tail(tail).copy())
        ctx=SimpleNamespace(parameters=c.definition.parameters,history=history,
            auxiliary_histories={'soxx_hfq':auxiliary},point=SimpleNamespace(decision_at=decision_at),
            position=PositionFeedback(),account=SimpleNamespace(available_cash=100000.),
            portfolio=SimpleNamespace(reference_price_scale=1.))
        new=implementation.step(ctx,AccountStrategyState())
        old_result,old=legacy_step(ctx,AccountStrategyState())
        newfacts={v['key']:v['text'] for v in new.decision.explanation.to_dict()['basis']}
        oldfacts={v['key']:v['text'] for v in old_result.decision.explanation.to_dict()['basis']}
        same=all(newfacts[key]==oldfacts[key] for key in
            ('anchor','sector_anchor','observed_signal','common_group','entry_allocation'))
        allocation=float(old['facts']['entry_allocation'])
        expected=allocation*float(c.definition.parameters['initial_fraction']) if old['facts']['observed_signal'] else 0.
        same=bool(same and new.decision.target==expected)
        group=bool(old['facts']['common_group'])
        groups[group]+=1
        rows.append({'observed_through':observed.isoformat(),'matched':same,'group':group,
            'entry_signal':bool(old['facts']['observed_signal']),
            'expected_target':expected,'actual_target':new.decision.target})
    return {'scope':'IDENTICAL_HFQ_PREFIX_FLAT_FINANCIAL_PREDICATES',
        'checked_points':len(rows),'differing_points':sum(not row['matched'] for row in rows),
        'group_counts':{'common':groups[True],'other':groups[False]},'points':rows}


@pytest.mark.parametrize('price,sector,held',[(100.,202.,0),(102.,205.,0),
    (101.,202.,2),(101.,202.,3),(101.0001,202.0001,3),(100.5,205.,3),
    (100.5001,205.,3),(103.,205.,4),(103.,205.,5)])
def test_original_financial_predicates_on_identical_hfq_inputs(price,sector,held):
    c,p,_,_=fixture(price=price,sector_price=sector)
    _,ctx,state=context(c,p,held=held)
    new=implementation.step(ctx,state)
    _,old=legacy_step(ctx,state)
    # Inspect structured numerical facts independently of presentation formatting.
    values=dict(new.cycle_values.values) if new.cycle_values is not None else {}
    assert values.get('anchor',price)==old['facts']['anchor']
    assert values.get('sector_anchor',sector)==old['facts']['sector_anchor']
    m=np.diff(np.log(ctx.history.to_frame(tail=63).Close.to_numpy()))
    s=np.diff(np.log(ctx.auxiliary_histories['soxx_hfq'].to_frame(tail=63).Close.to_numpy()))
    beta=np.cov(m[-42:-2],s[-42:-2],ddof=1)[0,1]/np.var(s[-42:-2],ddof=1)
    assert old['facts']['common_group']==bool(beta*s[-2:].sum() < .375*m[-2:].sum())
    assert old['facts']['observed_signal']==bool(np.all(np.diff(ctx.history.to_frame(tail=3).Close)<0))
    if not held:
        allocation=1. if old['facts']['common_group'] else .375
        assert new.decision.target==(.5*allocation if old['facts']['observed_signal'] else 0.)
    elif old['reason']=='complete':
        assert new.decision.target==0.
    else:
        assert new.cycle_values.get('promoted')==bool(old['execution']['orders'])
        assert new.decision.target==(.375 if old['execution']['orders'] else .1875)


@pytest.mark.parametrize('allocation',[1.,.375])
def test_target_stage_is_not_confused_with_fill_count(allocation):
    c,p,_,_=fixture(price=103.,sector_price=205.)
    _,ctx,state=context(c,p,held=3,allocation=allocation,buy_fills=4)
    new=implementation.step(ctx,state)
    _,old=legacy_step(ctx,state)
    assert old['execution']['orders']==()
    assert new.decision.target==allocation and new.cycle_values.get('promoted')


@pytest.mark.parametrize('promoted,exiting,expected',[(True,False,.375),(False,True,0.),(True,True,0.)])
def test_promoted_and_exiting_targets_survive_missing_fills_and_restart(promoted,exiting,expected):
    c,p,_,_=fixture(price=100.8,sector_price=201.)
    _,ctx,state=context(c,p,held=3,promoted=promoted,exiting=exiting)
    restored=AccountStrategyState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert implementation.step(ctx,state)==implementation.step(ctx,restored)
    result=implementation.step(ctx,restored)
    assert result.decision.target==expected
    if exiting:
        _,old=legacy_step(ctx,state)
        assert old['target']==1.  # Explicitly document the legacy nonsticky exit difference.


@pytest.mark.parametrize('target',[0.,.1875,.375,.5,1.])
@pytest.mark.parametrize('held',[0,3])
def test_tdr_and_pte_hosts_project_identical_typed_execution(target,held):
    c,p,_,_=fixture()
    engine,ctx,state=context(c,p,held=held)
    result=engine.propose(ctx.point.execution_interval,ctx.portfolio,ctx.account,state,
        ctx.position,owner='equivalence',fee_rate=.001)
    result=replace(result,proposal=replace(result.proposal,decision=replace(result.proposal.decision,target=target)))
    shared=dict(owner='equivalence',implementation=c.implementation_hash,fee_rate=.001,
        sell_remainder_policy='FULL_LIQUIDATION',execution_policy=c.definition.execution_policy,
        cycle_budget=None,locked_quantity=None)
    a=research_plan(result,ctx.account,c.definition.execution_spec,reference_price=102.,**shared)
    b=paper_plan(result,ctx.account,c.definition.execution_spec,reference=102.,**shared)
    assert a==b


def test_insufficient_remaining_cash_keeps_target_and_returns_blocked_plan():
    c,p,_,_=fixture()
    engine,ctx,state=context(c,p,held=3,quantity=999)
    result=engine.propose(ctx.point.execution_interval,ctx.portfolio,ctx.account,state,
        ctx.position,owner='diagnostic',fee_rate=.001)
    result=replace(result,proposal=replace(result.proposal,decision=replace(result.proposal.decision,target=1.)))
    account=replace(ctx.account,cash=100.,available_cash=100.)
    plan=research_plan(result,account,c.definition.execution_spec,owner='diagnostic',
        implementation=c.implementation_hash,fee_rate=.001,sell_remainder_policy='FULL_LIQUIDATION',
        reference_price=100.,execution_policy=c.definition.execution_policy)
    assert plan.planning_result.status is PlanningStatus.BLOCKED
    assert PlanningConstraint.INSUFFICIENT_CASH in plan.planning_result.reasons
    assert not plan.orders
    assert result.proposal.decision.target == 1.


@pytest.mark.parametrize('miss_first',[False,True])
def test_real_srt_and_ec_pending_entry_restart_and_full_replay_match(miss_first):
    c,p,b,r=fixture(descending=True)
    if miss_first:
        b.loc[70,['Open','High','Low','Close']]=[110.,111.,109.,110.]
        # Preserve the observation inputs: execution gap is in the execution channel only.
    executor=PortfolioHistoricalExecutor(specification=execution_spec(c.definition.execution_spec),
        initial_cash=100000.,fee_rate=.001,price_basis='HFQ')
    channel=HistoricalReplayChannel.from_executor(executor,account_id='durable',
        instrument=execution_instrument(c.instrument),bars=b.to_dict('records'),constraints=r.to_dict('records'))
    proposed=[]
    for i in range(70,76 if not miss_first else 71):
        start,end=p._data.starts[i],p._data.ends[i]
        engine=AccountDecisionEngine(c,p)
        channel.advance(start)
        snapshot=channel.snapshot('durable',at=start)
        state=AccountStrategyState.from_dict(json.loads(json.dumps(snapshot.strategy.to_dict())))
        account=strategy_snapshot(snapshot.account,c.instrument)
        result=engine.propose(TimeInterval(start,end),strategy_portfolio(snapshot.portfolio),account,state,
            strategy_feedback(snapshot.position),owner='durable',fee_rate=.001)
        plan=research_plan(result,account,c.definition.execution_spec,owner='durable',
            implementation=c.implementation_hash,fee_rate=.001,sell_remainder_policy='FULL_LIQUIDATION',
            reference_price=float(p._data.rows[i-1]['Close']),execution_policy=c.definition.execution_policy)
        decision=HistoricalDecision(plan,snapshot.strategy.revision,
            ECStateRecord.from_dict(result.proposal.account.to_dict()),
            None if result.proposal.cycle_values is None else ECStateRecord.from_dict(result.proposal.cycle_values.to_dict()),
            result.next_event_cursor,engine.state_binding('durable',.001))
        before_quantity=executor.quantity
        assert channel.adopt('durable',decision) is AdoptionStatus.ADOPTED
        assert channel.adopt('durable',decision) is AdoptionStatus.ALREADY_ADOPTED
        assert executor.quantity==before_quantity
        if i==70:
            assert channel.state.cycle is None
        channel.advance(end)
        proposed.append(result.proposal.decision.target)
        if i==70:
            assert (channel.state.cycle is not None)==(not miss_first)
            assert bool(executor.quantity)==(not miss_first)
    actual=channel.finish()
    if miss_first:
        assert actual.fills.empty and proposed[0]>0
        return
    assert proposed==[.1875,.1875,.1875,.375,.375,0.]
    expected=run_replay(p,c,PortfolioHistoricalExecutor(
        specification=execution_spec(c.definition.execution_spec),initial_cash=100000.,fee_rate=.001,price_basis='HFQ'),
        constraints=r,start=p._data.starts[70],end=p._data.ends[75],fee_rate=.001).execution_result
    for name,columns in [('fills',['side','quantity','price','fees']),
                         ('account_points',['cash','quantity','equity'])]:
        pd.testing.assert_frame_equal(getattr(actual,name)[columns],getattr(expected,name)[columns])
    assert executor.position_feedback.latest_closed is not None


def test_stateful_strategy_rejects_future_or_misaligned_auxiliary_observation():
    c,p,_,_=fixture()
    _,ctx,state=context(c,p)
    # Real visibility hides future rows; direct bad input is also rejected by the strategy.
    frame=ctx.auxiliary_histories['soxx_hfq'].to_frame()
    frame.loc[frame.index[-1],'AvailableDate']=ctx.point.decision_at+pd.Timedelta(seconds=1)
    bad=SimpleNamespace(**{name:getattr(ctx,name) for name in
        ('parameters','history','point','position','account','portfolio')},
        auxiliary_histories={'soxx_hfq':SimpleNamespace(to_frame=lambda **_:frame.tail(63))})
    with pytest.raises(ValueError,match='available'):
        implementation.step(bad,state)


def test_reusable_prefix_comparison_reports_both_formula_and_target_mapping():
    _,p,mu,_=fixture(descending=True)
    sector=pd.DataFrame(p._auxiliary[0][1].rows)
    report=financial_predicate_comparison(mu,sector)
    assert report['checked_points']==18 and report['differing_points']==0
    assert any(row['entry_signal'] for row in report['points'])
