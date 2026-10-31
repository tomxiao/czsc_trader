"""Post-reclaim swing support requires completed price acceptance, whole entry interval excluded, no timing exits."""
from strategy_runtime import (AccountDecision,AccountStepResult,BarField,FeatureGraph,Lag,Mean,RawField,ReadyValue,SameLocalSlotMedian,StateField,StateRecord,StateValueType,StrategyStateSchema,TrueRange)
OUTPUTS=('close','high','low','previous_low','low2','previous_close','previous_open','previous_high','previous_volume','previous_tr','atr_before_prior','same_slot_median20')
def feature_graph():
    return FeatureGraph((RawField('close',BarField.CLOSE),RawField('opening',BarField.OPEN),RawField('high',BarField.HIGH),RawField('low',BarField.LOW),RawField('volume',BarField.VOLUME),Lag('previous_close','close',1),Lag('previous_open','opening',1),Lag('previous_high','high',1),Lag('previous_low','low',1),Lag('low2','low',2),Lag('previous_volume','volume',1),TrueRange('tr','high','low','close'),Mean('atr13','tr',13),Lag('previous_tr','tr',1),Lag('atr_before_prior','atr13',2),SameLocalSlotMedian('same_slot_median20','volume',20,1)),OUTPUTS)
def state_schema():
    fields=(('holding_bars',StateValueType.INT),('last_completed_at',StateValueType.DATETIME),('exit_due',StateValueType.BOOL),('initial_support',StateValueType.FLOAT),('support',StateValueType.FLOAT),('support_raises',StateValueType.INT),('exit_reason',StateValueType.STR),('peak',StateValueType.FLOAT),('peak_before_last',StateValueType.FLOAT),('pending_support',StateValueType.BOOL),('candidate_low',StateValueType.FLOAT),('candidate_high',StateValueType.FLOAT),('candidate_at',StateValueType.DATETIME))
    return StrategyStateSchema(cycle_fields=tuple(StateField(k,v) for k,v in fields))
def step(ctx,state):
    if set(ctx.parameters)!={'entry','support'} or ctx.parameters['entry'] not in ('M005','M006') or ctx.parameters['support'] not in ('IMMEDIATE','ACCEPTED'):raise ValueError('Declared 2x2 only')
    p=ctx.portfolio
    if p.reference_price_scale!=1. or ctx.events:raise ValueError('RAW NONE contract only')
    v={}
    for k in OUTPUTS:
        x=ctx.features.get(k)
        if type(x) is not ReadyValue:raise ValueError('Ready complete observations required')
        v[k]=float(x.value)
    m006=v['previous_close']<v['previous_open'] and v['close']>v['previous_high'];m005=m006 and v['previous_volume']>=1.5*v['same_slot_median20'] and v['previous_tr']<=v['atr_before_prior']
    signal=m005 if ctx.parameters['entry']=='M005' else m006
    current=ctx.history.last()['Date'];held=p.quantity>0;proposal=None
    facts={**v,'entry_signal':bool(signal),'m005_signal':bool(m005),'m006_signal':bool(m006),'entry_policy':ctx.parameters['entry'],'support_policy':ctx.parameters['support'],'held':held,'portfolio_quantity':p.quantity,'portfolio_cash':p.cash,'cycle_present':state.cycle is not None,'holding_bars':0,'exit_due':False,'exit_trigger':'NONE','support_raised':False,'pivot_confirmed':False,'candidate_cancelled':False,'candidate_created':False,'candidate_accepted':False}
    if held:
        if state.cycle is None or state.cycle.entry_at!=p.cycle_entry or p.cycle_cost<=0:raise ValueError('Actual activated cycle required')
        s=dict(state.cycle.values.values)
        if current<=s['last_completed_at']:raise ValueError('Complete observation must advance')
        s['holding_bars']+=1;s['last_completed_at']=current
        if not s['exit_due']:
            pivot=v['previous_low']<v['low2'] and v['previous_low']<v['low'] and v['previous_low']>s['support']
            eligible=False
            if pivot:
                three=ctx.history.to_frame(tail=3)
                if len(three)!=3 or not three.Date.is_monotonic_increasing or three.Date.duplicated().any() or three.Date.iloc[-1]!=current:raise ValueError('Exactly last three completed bars required')
                eligible=three.BarStart.iloc[0]>p.cycle_entry
            facts['pivot_confirmed']=bool(eligible)
            if ctx.parameters['support']=='IMMEDIATE':
                if eligible:s['support']=v['previous_low'];s['support_raises']+=1;facts['support_raised']=True
            else:
                if s['pending_support'] and v['low']<s['candidate_low']:s['pending_support']=False;facts['candidate_cancelled']=True
                if eligible and not s['pending_support']:
                    if s['peak_before_last']<=0:raise ValueError('Pre-pivot full held peak required')
                    s.update(pending_support=True,candidate_low=v['previous_low'],candidate_high=s['peak_before_last'],candidate_at=current);facts['candidate_created']=True
                if s['pending_support'] and v['close']>s['candidate_high']:
                    if not s['candidate_low']>s['support']:raise ValueError('Support only increases')
                    s['support']=s['candidate_low'];s['support_raises']+=1;s['pending_support']=False;facts.update(support_raised=True,candidate_accepted=True)
            if v['close']<s['support']:s['exit_due']=True;s['exit_reason']='INITIAL_SUPPORT_BREAK' if s['support']==s['initial_support'] else 'CONFIRMED_HIGHER_SUPPORT_BREAK'
            if ctx.history.last()['BarStart']>p.cycle_entry:s['peak_before_last']=s['peak'];s['peak']=max(s['peak'],v['high'])
        proposal=StateRecord(tuple(s.items()));target=int(not s['exit_due']);facts.update(holding_bars=s['holding_bars'],exit_due=s['exit_due'],exit_trigger=s['exit_reason'],initial_support=s['initial_support'],support=s['support'],support_raises=s['support_raises'],pending_support=s['pending_support'],candidate_low=s['candidate_low'],candidate_high=s['candidate_high'],candidate_at=s['candidate_at'],peak=s['peak'],peak_before_last=s['peak_before_last'])
    else:
        target=int(signal)
        if target:
            floor=min(v['previous_low'],v['low']);proposal=StateRecord((('holding_bars',0),('last_completed_at',current),('exit_due',False),('initial_support',floor),('support',floor),('support_raises',0),('exit_reason','NONE'),('peak',0.),('peak_before_last',0.),('pending_support',False),('candidate_low',0.),('candidate_high',0.),('candidate_at',current)))
    return AccountStepResult(AccountDecision.from_facts(target,'Reclaimed continuation, confirmed swing and price acceptance',facts=facts,next_watch='Only real complete held structure; candidate is not yet support, all exits next interval and locked',capital_mode='full_available_cash'),StateRecord(),proposal)
