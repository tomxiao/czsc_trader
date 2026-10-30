"""V4 computation/clock parity and actual position execution, using synthetic facts."""
from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo
import json

import pandas as pd
import pytest
from dataflows import AssetClass, BarFrequency, InstrumentId, MarketId, TradingSession, TimeInterval
from strategy_runtime import (AccountPolicy, CashAvailabilityPolicy, CnEquitySpec, UsEquitySpec,
    ResearchExecutionSpec, EquityStrategyCandidate, EquityStrategyDefinition, equity_source_hash,
    StrategyComputation)
from strategy_runtime.equity_features import FeatureGraph, RawField, BarField
from strategy_runtime.equity_replay import PreparedReplay, StrategyStateSchema, run_replay
from trading_execution_engine import PortfolioHistoricalExecutor


STEP = """from strategy_runtime import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord
def step(ctx,state):
    target=(.25,.5,.25,0.)[int(ctx.history.last()['Close']-10)%4]
    return AccountStepResult(AccountDecision.from_facts(target,'repair target',facts={'target':target},next_watch='next bar'), cycle_values=StateRecord())
"""
BATCH = """from strategy_runtime import AccountDecision
def calculate(ctx):
    return tuple(AccountDecision.from_facts((.25,.5,.25,0.)[int(row.history.last()['Close']-10)%4], 'repair target', facts={'close':row.history.last()['Close']},next_watch='next bar') for row in ctx.observations)
"""


def setup(root, market, frequency, computation):
    root.mkdir(parents=True,exist_ok=True)
    (root/'strategy.py').write_text(STEP if computation is StrategyComputation.STATEFUL_STEP else BATCH,encoding='utf-8')
    instrument=InstrumentId(market,AssetClass.STOCK,'600000.SH' if market is MarketId.CN else 'TEST')
    spec=ResearchExecutionSpec(CnEquitySpec() if market is MarketId.CN else UsEquitySpec(),frequency,
        AccountPolicy('CNY' if market is MarketId.CN else 'USD',CashAvailabilityPolicy.IMMEDIATE_RESEARCH),100,.01,.01,0.)
    definition=EquityStrategyDefinition(instrument,spec,1,'strategy:step' if computation is StrategyComputation.STATEFUL_STEP else 'strategy:calculate',
        ('strategy.py',),equity_source_hash(root,('strategy.py',)),contract_version=4,computation=computation,
        feature_graph=FeatureGraph((RawField('close',BarField.CLOSE),),('close',)),state_schema=StrategyStateSchema())
    candidate=EquityStrategyCandidate('S999','C0001',definition,root)
    zone=ZoneInfo(instrument.timezone)
    # Declared synthetic sessions, not an official exchange calendar.
    sessions=tuple(TradingSession(date(2024,3,d),str(zone),(TimeInterval(datetime(2024,3,d,9,30,tzinfo=zone),datetime(2024,3,d,11,30,tzinfo=zone)),)) for d in (4,5,6,7,8))
    periods=tuple(p for s in sessions for p in ((TimeInterval(s.segments[0].start,s.segments[-1].end),) if frequency is BarFrequency.DAILY else s.bars(frequency)))
    starts=pd.DatetimeIndex([p.start for p in periods]).tz_convert('UTC')
    ends=pd.DatetimeIndex([p.end for p in periods]).tz_convert('UTC')
    bars=pd.DataFrame({'BarStart':starts,'Date':ends,'AvailableDate':ends,'Open':10.,'High':15.,'Low':9.,'Close':[10.+i%4 for i in range(len(periods))],'Volume':1000000.,'Amount':10000000.})
    constraints=pd.DataFrame({'Date':starts,'AvailableDate':starts,'QuantityStep':100,'PriceTick':.01,'Tradable':True,
        'SellRemainderPolicy':'STRICT_STEP','PriceLimitPolicy':'EXPLICIT_UNBOUNDED','PriceLimitLower':None,'PriceLimitUpper':None,'BuySellableAt':starts})
    actions=pd.DataFrame([{'Date':starts[0],'AvailableDate':starts[0],'EventId':'none','Kind':'NONE','Ratio':1.,'CashPerShare':0.,'PayAt':None}])
    session_frame=pd.DataFrame({'Date':[s.segments[0].start for s in sessions], 'AvailableDate':[s.segments[0].start for s in sessions], 'SessionDate':[s.session_date.isoformat() for s in sessions]})
    prepared=PreparedReplay.from_frames(bars,constraints,definition.feature_graph,frequency=frequency,timezone=instrument.timezone,sessions=session_frame,trading_sessions=sessions)
    executor=PortfolioHistoricalExecutor(specification=spec,initial_cash=100000.,fee_rate=.001,actions=actions,price_basis='RAW')
    return candidate,prepared,executor,bars,constraints,sessions,session_frame


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
@pytest.mark.parametrize('frequency',[BarFrequency.DAILY,BarFrequency.M30])
@pytest.mark.parametrize('computation',[StrategyComputation.BATCH_HISTORY,StrategyComputation.STATEFUL_STEP])
def test_v4_computation_and_clock_are_market_independent(tmp_path,market,frequency,computation):
    candidate,prepared,executor,bars,_,_,_=setup(tmp_path,market,frequency,computation)
    outcome=run_replay(prepared,candidate,executor,start=bars.BarStart.iloc[1].to_pydatetime(),end=bars.Date.iloc[-1].to_pydatetime(),fee_rate=.001)
    account=outcome.execution_result
    assert outcome.statistics.module_loads==1
    assert outcome.statistics.source_checks==0
    assert set(account.fills.side)=={'BUY','SELL'}
    assert (account.account_points.cash>=0).all()
    assert account.account_points.quantity.max()>0
    assert EquityStrategyDefinition.from_dict(json.loads(json.dumps(candidate.definition.to_dict())))==candidate.definition


@pytest.mark.parametrize('computation',[StrategyComputation.BATCH_HISTORY,StrategyComputation.STATEFUL_STEP])
def test_equivalent_rules_produce_same_numeric_accounts(tmp_path,computation):
    outputs=[]
    for market in (MarketId.CN,MarketId.US):
        c,p,e,b,_,_,_=setup(tmp_path/market.value,market,BarFrequency.M30,computation)
        outputs.append(run_replay(p,c,e,start=b.BarStart.iloc[1].to_pydatetime(),end=b.Date.iloc[-1].to_pydatetime(),fee_rate=.001).execution_result)
    for field in ('cash','quantity','equity'):
        assert outputs[0].account_points[field].tolist()==outputs[1].account_points[field].tolist()
    for field in ('side','quantity','price','fees'):
        assert outputs[0].fills[field].tolist()==outputs[1].fills[field].tolist()


def test_v4_requires_real_declared_clock_and_preserves_legacy_identity(tmp_path):
    c,p,_,bars,constraints,_,_=setup(tmp_path,MarketId.CN,BarFrequency.DAILY,StrategyComputation.STATEFUL_STEP)
    with pytest.raises(ValueError,match='calendar|session'):
        run_replay(PreparedReplay.from_frames(bars,constraints,p.graph,frequency=BarFrequency.DAILY,timezone=c.instrument.timezone),c,
            PortfolioHistoricalExecutor(specification=c.definition.execution_spec,initial_cash=100000.,fee_rate=.001,
                actions=pd.DataFrame([{'Date':bars.BarStart.iloc[0],'AvailableDate':bars.BarStart.iloc[0],'EventId':'none','Kind':'NONE','Ratio':1.,'CashPerShare':0.,'PayAt':None}]),price_basis='RAW'),
            start=bars.BarStart.iloc[1].to_pydatetime(),end=bars.Date.iloc[-1].to_pydatetime(),fee_rate=.001)
    with pytest.raises(ValueError,match='restricted to US'):
        replace(c.definition,contract_version=3,computation=None)


EXPLICIT = """from strategy_runtime import AccountDecision,AccountStepResult,ReplayOrder
from strategy_runtime.contracts import OrderSide,OrderType
from strategy_runtime.equity_replay import StateRecord
def step(ctx,state):
    q=ctx.portfolio.quantity
    if ctx.portfolio.revision==0:
        orders=(ReplayOrder(OrderSide.BUY,100,OrderType.LIMIT,11.),ReplayOrder(OrderSide.BUY,100,OrderType.LIMIT,11.))
    elif q:
        orders=(ReplayOrder(OrderSide.SELL,100,OrderType.MARKET),)
    else: orders=()
    feedback=ctx.position.active or ctx.position.latest_closed
    facts={'buys':feedback.buy_fills if feedback else 0,'sells':feedback.sell_fills if feedback else 0}
    return AccountStepResult(AccountDecision.from_facts(.5 if ctx.portfolio.revision==0 else 0.,'explicit ladder',facts=facts,next_watch='next bar',orders=orders),cycle_values=StateRecord())
"""


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_explicit_orders_retain_position_cycle_feedback(tmp_path,market):
    c,p,e,b,_,_,_=setup(tmp_path,market,BarFrequency.M30,StrategyComputation.STATEFUL_STEP)
    (tmp_path/'strategy.py').write_text(EXPLICIT,encoding='utf-8')
    c=replace(c,definition=replace(c.definition,source_sha256=equity_source_hash(tmp_path,('strategy.py',))))
    result=run_replay(p,c,e,start=b.BarStart.iloc[1].to_pydatetime(),end=b.Date.iloc[-1].to_pydatetime(),fee_rate=.001)
    fills=result.execution_result.fills
    assert fills.side.tolist()==['BUY','BUY','SELL','SELL']
    assert fills.quantity.tolist()==[100,100,100,100]
    assert e.position_feedback.latest_closed.buy_fills==2
    assert e.position_feedback.latest_closed.sell_fills==2
    assert e.position_feedback.latest_closed.quantity==0
    facts=[{row['key']:row['text'] for row in explanation['basis']} for explanation in result.execution_result.decisions.explanation]
    assert facts[1]=={'buys':'2','sells':'0'}
    assert facts[2]=={'buys':'2','sells':'1'}
    assert facts[3]=={'buys':'2','sells':'2'}


@pytest.mark.parametrize('computation',[StrategyComputation.BATCH_HISTORY,StrategyComputation.STATEFUL_STEP])
def test_future_suffix_does_not_change_prefix_accounts(tmp_path,computation):
    c,p,e,b,r,sessions,frame=setup(tmp_path/'first',MarketId.US,BarFrequency.M30,computation)
    end=b.Date.iloc[-1].to_pydatetime()
    first=run_replay(p,c,e,start=b.BarStart.iloc[1].to_pydatetime(),end=end,fee_rate=.001).execution_result
    altered=b.copy()
    altered.loc[8:,['Open','High','Low','Close']]*=10
    current=PreparedReplay.from_frames(altered,r,c.definition.feature_graph,frequency=BarFrequency.M30,
        timezone=c.instrument.timezone,sessions=frame,trading_sessions=sessions)
    actions=e.actions.drop(columns=['_priority'])
    second=run_replay(current,c,PortfolioHistoricalExecutor(specification=c.definition.execution_spec,initial_cash=100000.,
        fee_rate=.001,actions=actions,price_basis='RAW'),start=b.BarStart.iloc[1].to_pydatetime(),end=end,fee_rate=.001).execution_result
    for key in ('cash','quantity','equity'):
        assert first.account_points[key].iloc[:7].tolist()==second.account_points[key].iloc[:7].tolist()
    assert first.decisions.explanation.iloc[:7].tolist()==second.decisions.explanation.iloc[:7].tolist()


def test_v4_rejects_mismatched_prepared_frequency(tmp_path):
    c,p,e,b,_,_,_=setup(tmp_path,MarketId.US,BarFrequency.M30,StrategyComputation.STATEFUL_STEP)
    with pytest.raises(ValueError,match='decision clock'):
        run_replay(replace(p,frequency=BarFrequency.DAILY),c,e,start=b.BarStart.iloc[1].to_pydatetime(),end=b.Date.iloc[-1].to_pydatetime(),fee_rate=.001)


def test_execution_quote_role_is_typed_and_not_an_auxiliary_alias(tmp_path):
    from dataflows import SourceRef,EquityProduct
    from strategy_runtime import ExecutionInput,EquityAuxiliaryInput
    c,_,_,_,_,_,_=setup(tmp_path,MarketId.CN,BarFrequency.DAILY,StrategyComputation.STATEFUL_STEP)
    source=SourceRef('synthetic','v1')
    execution=ExecutionInput(c.instrument,source,BarFrequency.M30)
    definition=replace(c.definition,execution_input=execution)
    assert EquityStrategyDefinition.from_dict(json.loads(json.dumps(definition.to_dict())))==definition
    assert execution.data_key(EquityProduct.BARS)=='execution:bars'
    assert {x.parameters.query.product for x in execution.requests(date(2024,3,4),date(2024,3,8))}=={EquityProduct.BARS,EquityProduct.SESSIONS}
    aux=EquityAuxiliaryInput('execution_alias',c.instrument,source,BarFrequency.M30,1,3600)
    with pytest.raises(ValueError,match='duplicates an auxiliary'):
        replace(definition,auxiliary_inputs=(aux,))
    with pytest.raises(ValueError,match='DAILY'):
        replace(definition,execution_spec=replace(definition.execution_spec,decision_clock=BarFrequency.M30))


def test_legacy_definitions_do_not_acquire_v4_fields_or_cn_auxiliary(tmp_path):
    from dataflows import SourceRef
    from strategy_runtime import EquityAuxiliaryInput
    c,_,_,_,_,_,_=setup(tmp_path,MarketId.US,BarFrequency.M30,StrategyComputation.STATEFUL_STEP)
    legacy=replace(c.definition,contract_version=3,computation=None)
    encoded=legacy.to_dict()
    assert encoded['runtime_kind']=='US_EQUITY'
    assert 'computation' not in encoded and 'execution_input' not in encoded
    aux=EquityAuxiliaryInput('cn_market',InstrumentId(MarketId.CN,AssetClass.ETF,'588080.SH'),SourceRef('synthetic','v1'),BarFrequency.DAILY,1,86400)
    assert replace(c.definition,auxiliary_inputs=(aux,)).auxiliary_inputs==(aux,)
    with pytest.raises(ValueError,match='legacy auxiliary'):
        replace(legacy,auxiliary_inputs=(aux,))


@pytest.mark.parametrize('market',[MarketId.CN,MarketId.US])
def test_calendar_breaks_and_dst_drive_actual_clock_without_filling_closed_time(tmp_path,market):
    c,_,e,old,old_rules,_,_=setup(tmp_path,market,BarFrequency.M30,StrategyComputation.STATEFUL_STEP)
    zone=ZoneInfo(c.instrument.timezone)
    if market is MarketId.CN:
        days=(date(2024,3,4),date(2024,3,5))
        clocks=((9,30,11,30),(13,0,15,0))
    else:
        days=(date(2024,3,8),date(2024,3,11))
        clocks=((9,30,11,30),)
    sessions=tuple(TradingSession(day,str(zone),tuple(TimeInterval(datetime(day.year,day.month,day.day,a,b,tzinfo=zone),
        datetime(day.year,day.month,day.day,d,f,tzinfo=zone)) for a,b,d,f in clocks)) for day in days)
    periods=tuple(interval for session in sessions for interval in session.bars(BarFrequency.M30))
    starts=pd.DatetimeIndex([interval.start for interval in periods]).tz_convert('UTC')
    ends=pd.DatetimeIndex([interval.end for interval in periods]).tz_convert('UTC')
    bars=old.iloc[:len(periods)].copy()
    bars['BarStart'],bars['Date'],bars['AvailableDate']=starts,ends,ends
    rules=old_rules.iloc[:len(periods)].copy()
    rules['Date'],rules['AvailableDate'],rules['BuySellableAt']=starts,starts,starts
    calendar=pd.DataFrame({'Date':[s.segments[0].start for s in sessions], 'AvailableDate':[s.segments[0].start for s in sessions],
        'SessionDate':[s.session_date.isoformat() for s in sessions]})
    prepared=PreparedReplay.from_frames(bars,rules,c.definition.feature_graph,frequency=BarFrequency.M30,
        timezone=c.instrument.timezone,sessions=calendar,trading_sessions=sessions)
    # Reset the synthetic NONE timestamp to this independently declared history.
    actions=e.actions.drop(columns=['_priority']).copy()
    actions.loc[0,'Date']=actions.loc[0,'AvailableDate']=starts[0]
    account=run_replay(prepared,c,PortfolioHistoricalExecutor(specification=c.definition.execution_spec,initial_cash=100000.,fee_rate=.001,
        actions=actions,price_basis='RAW'),start=starts[1].to_pydatetime(),end=ends[-1].to_pydatetime(),fee_rate=.001).execution_result
    assert len(account.account_points)==len(periods)-1
    assert account.account_daily.session.tolist()==[day.isoformat() for day in days]
    if market is MarketId.CN:
        assert not any(11*60+30<=value.hour*60+value.minute<13*60 for value in starts.tz_convert(zone))
    else:
        assert starts[0].hour==14 and starts[4].hour==13


@pytest.mark.parametrize('computation',[StrategyComputation.BATCH_HISTORY,StrategyComputation.STATEFUL_STEP])
def test_cn_auxiliary_and_calendar_observations_are_asof_in_both_modes(tmp_path,computation):
    from dataflows import SourceRef
    from strategy_runtime import EquityAuxiliaryInput
    c,_,e,b,r,sessions,frame=setup(tmp_path,MarketId.CN,BarFrequency.DAILY,computation)
    aux=EquityAuxiliaryInput('sector',InstrumentId(MarketId.CN,AssetClass.ETF,'588080.SH'),SourceRef('synthetic','v1'),BarFrequency.DAILY,1,86400)
    if computation is StrategyComputation.STATEFUL_STEP:
        source="""from strategy_runtime import AccountDecision,AccountStepResult
from strategy_runtime.equity_replay import StateRecord
def step(ctx,state):
    price=ctx.auxiliary_histories['sector'].last()['Close']
    assert ctx.session is not None
    return AccountStepResult(AccountDecision.from_facts(.25,'sector observation',facts={'sector':price,'close':ctx.session.segments[-1].end.isoformat()},next_watch='next day'),cycle_values=StateRecord())
"""
    else:
        source="""from strategy_runtime import AccountDecision
def calculate(ctx):
    return tuple(AccountDecision.from_facts(.25,'sector observation',facts={'sector':row.auxiliary_histories['sector'].last()['Close'],'close':row.session.segments[-1].end.isoformat()},next_watch='next day') for row in ctx.observations)
"""
    (tmp_path/'strategy.py').write_text(source,encoding='utf-8')
    definition=replace(c.definition,auxiliary_inputs=(aux,),session_context=True,source_sha256=equity_source_hash(tmp_path,('strategy.py',)))
    c=replace(c,definition=definition)
    observed=b.copy()
    observed.loc[:,['Open','High','Low','Close']]=[500.,501.,499.,500.]
    prepared=PreparedReplay.from_frames(b,r,definition.feature_graph,frequency=BarFrequency.DAILY,timezone=c.instrument.timezone,
        sessions=frame,trading_sessions=sessions,auxiliary_histories={'sector':observed})
    result=run_replay(prepared,c,e,start=b.BarStart.iloc[1].to_pydatetime(),end=b.Date.iloc[-1].to_pydatetime(),fee_rate=.001)
    for explanation in result.execution_result.decisions.explanation:
        facts={row['key']:row['text'] for row in explanation['basis']}
        assert facts['sector']=='500.0'
        assert pd.Timestamp(facts['close']).tz_convert('Asia/Shanghai').strftime('%H:%M')=='11:30'


EVENT_STATE = """from strategy_runtime import AccountDecision,AccountStepResult,RecognizedEventKind
from strategy_runtime.equity_replay import StateRecord
def step(ctx,state):
    stop=state.account.get('stop')
    splits=state.account.get('splits')
    payments=state.account.get('payments')
    for event in ctx.events:
        assert event.effective_at<=ctx.point.decision_at
        if event.kind is RecognizedEventKind.SPLIT:
            stop/=event.ratio
            splits+=1
        if event.kind is RecognizedEventKind.DIVIDEND_PAYMENT:
            payments+=1
    facts={'stop':stop,'splits':splits,'payments':payments}
    return AccountStepResult(AccountDecision.from_facts(1,'unit-aware holding',facts=facts,next_watch='next bar',capital_mode='full_available_cash'),
        account=StateRecord((('stop',stop),('splits',splits),('payments',payments))),cycle_values=StateRecord())
"""


@pytest.mark.parametrize('suppressed_at_split',[False,True])
def test_recognized_split_adjusts_explicit_state_once_and_preserves_end_payment(tmp_path,suppressed_at_split):
    from strategy_runtime.equity_replay import StateRecord,StateField,StateValueType
    c,_,e,b,r,sessions,frame=setup(tmp_path,MarketId.US,BarFrequency.M30,StrategyComputation.STATEFUL_STEP)
    (tmp_path/'strategy.py').write_text(EVENT_STATE,encoding='utf-8')
    schema=StrategyStateSchema(account_fields=(StateField('stop',StateValueType.FLOAT),StateField('splits',StateValueType.INT),StateField('payments',StateValueType.INT)))
    initial=StateRecord((('stop',10.),('splits',0),('payments',0)))
    definition=replace(c.definition,state_schema=schema,initial_account=initial,source_sha256=equity_source_hash(tmp_path,('strategy.py',)))
    assert EquityStrategyDefinition.from_dict(json.loads(json.dumps(definition.to_dict())))==definition
    c=replace(c,definition=definition)
    first_split=b.BarStart.iloc[3]
    dividend=b.BarStart.iloc[4]
    pay=b.Date.iloc[4]
    future_split=b.BarStart.iloc[8]
    b.loc[3:,['Open','High','Low','Close']]/=2
    b.loc[8:,['Open','High','Low','Close']]/=2
    if suppressed_at_split:
        b['BarStatus']='OBSERVED'
        b.loc[2,'BarStatus']='MISSING'
        b.loc[2,['Open','High','Low','Close','Volume','Amount']]=float('nan')
    actions=pd.DataFrame([
        {'Date':first_split,'AvailableDate':first_split,'EventId':'split-one','Kind':'SPLIT','Ratio':2.,'CashPerShare':0.,'PayAt':None},
        {'Date':dividend,'AvailableDate':dividend,'EventId':'dividend','Kind':'CASH_DIVIDEND','Ratio':1.,'CashPerShare':.1,'PayAt':pay},
        {'Date':future_split,'AvailableDate':future_split,'EventId':'split-future','Kind':'SPLIT','Ratio':2.,'CashPerShare':0.,'PayAt':None}])
    prepared=PreparedReplay.from_frames(b,r,definition.feature_graph,frequency=BarFrequency.M30,timezone=c.instrument.timezone,
        sessions=frame,trading_sessions=sessions)
    executor=PortfolioHistoricalExecutor(specification=definition.execution_spec,initial_cash=100000.,fee_rate=.001,actions=actions,price_basis='RAW')
    result=run_replay(prepared,c,executor,start=b.BarStart.iloc[1].to_pydatetime(),end=b.Date.iloc[7].to_pydatetime(),fee_rate=.001)
    assert result.state.account.get('stop')==5.
    assert result.state.account.get('splits')==1
    assert result.state.account.get('payments')==1
    explanation=result.execution_result.decisions.explanation
    before={row['key']:row['text'] for row in explanation.iloc[3]['basis']}
    after={row['key']:row['text'] for row in explanation.iloc[4]['basis']}
    assert before['payments']=='0' and after['payments']=='1'
    assert before['splits']=='1' and after['splits']=='1'
    assert len(result.execution_result.fills)==1  # dividends do not cause residual reinvestment
    assert result.state.event_cursor==len(executor.rows['actions'])
    assert not any(row['event_id']=='split-future' for row in executor.rows['actions'])
