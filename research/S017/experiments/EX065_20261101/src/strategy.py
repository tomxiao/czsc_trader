"""Market-first prior-session breakout/acceptance with frozen H or accepted swing support."""
from strategy_runtime import (AccountDecision,AccountStepResult,BarField,FeatureGraph,Lag,
    RawField,ReadyValue,StateField,StateRecord,StateValueType,StrategyStateSchema)
from .session_features import market_context

OUTPUTS=('close','high','low','previous_low','low2')


def feature_graph():
    return FeatureGraph((RawField('close',BarField.CLOSE),RawField('high',BarField.HIGH),
        RawField('low',BarField.LOW),Lag('previous_low','low',1),Lag('low2','low',2)),OUTPUTS)


def state_schema():
    fields=(('signal_at',StateValueType.DATETIME),('reference_prior_day',StateValueType.STR),
        ('initial_reference_high',StateValueType.FLOAT),('support',StateValueType.FLOAT),
        ('last_completed_at',StateValueType.DATETIME),('exit_due',StateValueType.BOOL),
        ('exit_reason',StateValueType.STR),('support_raises',StateValueType.INT),
        ('peak',StateValueType.FLOAT),('peak_before_last',StateValueType.FLOAT),
        ('pending_support',StateValueType.BOOL),('candidate_low',StateValueType.FLOAT),
        ('candidate_high',StateValueType.FLOAT),('candidate_at',StateValueType.DATETIME),
        ('accepted_low',StateValueType.FLOAT),('accepted_high',StateValueType.FLOAT))
    return StrategyStateSchema(cycle_fields=tuple(StateField(k,t) for k,t in fields))


def step(ctx,state):
    if set(ctx.parameters)!={'entry','support'} or ctx.parameters['entry'] not in ('UP_CROSS','UP_ACCEPT') or ctx.parameters['support'] not in ('STATIC_H','ACCEPTED'):
        raise ValueError('Declared prior-session 2x2 only')
    p=ctx.portfolio
    if p.reference_price_scale!=1. or ctx.events:raise ValueError('Retained RAW NONE contract only')
    v={}
    for k in OUTPUTS:
        x=ctx.features.get(k)
        if type(x) is not ReadyValue:raise ValueError('Completed ready feature required')
        v[k]=float(x.value)
    m=market_context(ctx.history,ctx.point,ctx.session)
    signal=m['up_cross'] if ctx.parameters['entry']=='UP_CROSS' else m['up_accept']
    current=ctx.history.last()['Date'];held=p.quantity>0;proposal=None
    facts={**v,**m,'entry_signal':bool(signal),'entry_policy':ctx.parameters['entry'],'support_policy':ctx.parameters['support'],
        'held':held,'portfolio_quantity':p.quantity,'portfolio_cash':p.cash,'cycle_present':state.cycle is not None,
        'exit_due':False,'exit_trigger':'NONE','pivot_confirmed':False,'candidate_created':False,
        'candidate_cancelled':False,'candidate_accepted':False,'support_raised':False}
    if held:
        if state.cycle is None or state.cycle.entry_at!=p.cycle_entry or p.cycle_cost<=0:raise ValueError('Actual activated holding required')
        s=dict(state.cycle.values.values)
        if current<=s['last_completed_at']:raise ValueError('Completed observation must advance')
        s['last_completed_at']=current
        if not s['exit_due']:
            if ctx.parameters['support']=='ACCEPTED':
                eligible=False
                if v['previous_low']<v['low2'] and v['previous_low']<v['low'] and v['previous_low']>s['support']:
                    three=ctx.history.to_frame(tail=3)
                    if len(three)!=3 or not three.Date.is_monotonic_increasing or three.Date.duplicated().any() or three.Date.iloc[-1]!=current:raise ValueError('Exactly three completed bars required')
                    eligible=three.BarStart.iloc[0]>p.cycle_entry
                facts['pivot_confirmed']=bool(eligible)
                if s['pending_support'] and v['low']<s['candidate_low']:
                    s['pending_support']=False;facts['candidate_cancelled']=True
                if eligible and not s['pending_support']:
                    if s['peak_before_last']<=0:raise ValueError('Completed held left-peak required')
                    s.update(pending_support=True,candidate_low=v['previous_low'],candidate_high=s['peak_before_last'],candidate_at=current);facts['candidate_created']=True
                if s['pending_support'] and v['close']>s['candidate_high']:
                    if not s['candidate_low']>s['support']:raise ValueError('Accepted support must rise')
                    s.update(support=s['candidate_low'],support_raises=s['support_raises']+1,pending_support=False,
                        accepted_low=s['candidate_low'],accepted_high=s['candidate_high'])
                    facts.update(candidate_accepted=True,support_raised=True)
            if v['close']<s['support']:
                s['exit_due']=True;s['exit_reason']='INITIAL_HIGH_FAILED' if s['support_raises']==0 else 'ACCEPTED_SUPPORT_FAILED'
            if ctx.parameters['support']=='ACCEPTED' and ctx.history.last()['BarStart']>p.cycle_entry:
                s['peak_before_last']=s['peak'];s['peak']=max(s['peak'],v['high'])
        target=int(not s['exit_due']);proposal=StateRecord(tuple(s.items()))
        facts.update({k:s[k] for k in ('signal_at','initial_reference_high','support','support_raises','peak','peak_before_last','pending_support','candidate_low','candidate_high','candidate_at','accepted_low','accepted_high','exit_due')})
        facts.update(entry_reference_prior_day=s['reference_prior_day'],exit_trigger=s['exit_reason'],
            actual_cycle_net_mark=p.quantity*v['close']*.999-p.cycle_cost)
    else:
        target=int(signal)
        if target:
            upper=m['setup_reference_high']
            if not v['close']>upper:raise ValueError('Selected event must close above frozen H')
            vals=dict(signal_at=current,reference_prior_day=m['reference_prior_day'],initial_reference_high=upper,
                support=upper,last_completed_at=current,exit_due=False,exit_reason='NONE',support_raises=0,
                peak=0.,peak_before_last=0.,pending_support=False,candidate_low=0.,candidate_high=0.,candidate_at=current,accepted_low=0.,accepted_high=0.)
            proposal=StateRecord(tuple(vals.items()));facts.update(signal_at=current,initial_reference_high=upper,support=upper)
    return AccountStepResult(AccountDecision.from_facts(target,'Prior-session range price acceptance and structural failure',facts=facts,
        next_watch='Frozen cycle H survives day changes;completed close failure,next interval;market-first independent of fill',capital_mode='full_available_cash'),StateRecord(),proposal)
