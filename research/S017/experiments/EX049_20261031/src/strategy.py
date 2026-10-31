"""Post-reclaim acceptance, frozen financial failure, no timed holdings."""
from strategy_runtime import (AccountDecision,AccountStepResult,BarField,FeatureGraph,Lag,Mean,RawField,ReadyValue,SameLocalSlotMedian,StateField,StateRecord,StateValueType,StrategyStateSchema,TrueRange)
OUTPUTS=('close','opening','low','previous_low','previous_close','previous_open','previous_high','previous_volume','previous_tr','atr_before_prior','same_slot_median20')
def feature_graph():
    return FeatureGraph((RawField('close',BarField.CLOSE),RawField('opening',BarField.OPEN),RawField('high',BarField.HIGH),RawField('low',BarField.LOW),RawField('volume',BarField.VOLUME),Lag('previous_close','close',1),Lag('previous_open','opening',1),Lag('previous_high','high',1),Lag('previous_low','low',1),Lag('previous_volume','volume',1),TrueRange('tr','high','low','close'),Mean('atr13','tr',13),Lag('previous_tr','tr',1),Lag('atr_before_prior','atr13',2),SameLocalSlotMedian('same_slot_median20','volume',20,1)),OUTPUTS)
def state_schema():
    return StrategyStateSchema(account_fields=(StateField('pending',StateValueType.BOOL),StateField('anchor_at',StateValueType.DATETIME),StateField('reclaimed_level',StateValueType.FLOAT),StateField('original_support',StateValueType.FLOAT)),cycle_fields=(StateField('holding_bars',StateValueType.INT),StateField('last_completed_at',StateValueType.DATETIME),StateField('exit_due',StateValueType.BOOL),StateField('support',StateValueType.FLOAT),StateField('original_support',StateValueType.FLOAT),StateField('anchor_at',StateValueType.DATETIME),StateField('confirmation_at',StateValueType.DATETIME),StateField('exit_reason',StateValueType.STR)))
def step(ctx,state):
    if set(ctx.parameters)!={'policy'} or ctx.parameters['policy'] not in ('STATIC_SUPPORT','BULLISH_RECLAIM','RETEST_ORIGINAL','RETEST_LOW'):raise ValueError('Declared policies only')
    policy=ctx.parameters['policy'];p=ctx.portfolio
    if p.reference_price_scale!=1. or ctx.events:raise ValueError('RAW NONE contract only')
    v={}
    for k in OUTPUTS:
        x=ctx.features.get(k)
        if type(x) is not ReadyValue:raise ValueError('Ready complete observations required')
        v[k]=float(x.value)
    a=dict(state.account.values)
    if set(a)!={'pending','anchor_at','reclaimed_level','original_support'}:raise ValueError('Exact pending state required')
    current=ctx.history.last()['Date'];held=p.quantity>0;proposal=None;target=0
    m005=v['previous_close']<v['previous_open'] and v['previous_volume']>=1.5*v['same_slot_median20'] and v['previous_tr']<=v['atr_before_prior'] and v['close']>v['previous_high']
    bullish=v['close']>v['opening'];entry=False;retest=False;cancelled=False;replaced=False
    facts={**v,'m005_signal':bool(m005),'policy':policy,'held':held,'portfolio_quantity':p.quantity,'portfolio_cash':p.cash,'cycle_present':state.cycle is not None,'exit_due':False,'exit_trigger':'NONE','holding_bars':0}
    if held:
        if state.cycle is None or state.cycle.entry_at!=p.cycle_entry or p.cycle_cost<=0:raise ValueError('Real activated cycle required')
        a['pending']=False;s=dict(state.cycle.values.values)
        if current<=s['last_completed_at']:raise ValueError('Observation must advance')
        s['holding_bars']+=1;s['last_completed_at']=current
        if not s['exit_due'] and v['close']<s['support']:s['exit_due']=True;s['exit_reason']='FROZEN_SUPPORT_BREAK'
        target=int(not s['exit_due']);proposal=StateRecord(tuple(s.items()))
        facts.update(holding_bars=s['holding_bars'],exit_due=s['exit_due'],exit_trigger=s['exit_reason'],support=s['support'],original_support=s['original_support'],pending_anchor=s['anchor_at'],confirmation_at=s['confirmation_at'])
    elif policy in ('STATIC_SUPPORT','BULLISH_RECLAIM'):
        a['pending']=False;entry=m005 and (policy=='STATIC_SUPPORT' or bullish)
        if entry:
            floor=min(v['previous_low'],v['low']);anchor=current;confirmation=current;original=floor
    else:
        if m005:
            replaced=a['pending'];a.update(pending=True,anchor_at=current,reclaimed_level=v['previous_high'],original_support=min(v['previous_low'],v['low']))
        elif a['pending']:
            if current<=a['anchor_at']:raise ValueError('Retest must be later than setup')
            if v['close']<a['original_support']:a['pending']=False;cancelled=True
            else:
                retest=v['low']<=a['reclaimed_level'] and v['close']>a['reclaimed_level'] and bullish
                entry=retest
                if entry:
                    anchor=a['anchor_at'];confirmation=current;original=a['original_support'];floor=original if policy=='RETEST_ORIGINAL' else v['low']
    if not held and entry:
        target=1;proposal=StateRecord((('holding_bars',0),('last_completed_at',current),('exit_due',False),('support',floor),('original_support',original),('anchor_at',anchor),('confirmation_at',confirmation),('exit_reason','NONE')))
        facts.update(support=floor,original_support=original,pending_anchor=anchor,confirmation_at=confirmation,retest_low=v['low'])
    facts.update(entry_signal=bool(entry),retest_confirmed=bool(retest),pending=bool(a['pending']),pending_replaced=bool(replaced),pending_cancelled=bool(cancelled),reclaimed_level=a['reclaimed_level'],pending_anchor=facts.get('pending_anchor',a['anchor_at']),original_support=facts.get('original_support',a['original_support']))
    return AccountStepResult(AccountDecision.from_facts(target,'Reclaimed price acceptance and frozen failure',facts=facts,next_watch='Complete observations only; wait for new retest after failed buy, actual fill activates support; exit locks',capital_mode='full_available_cash'),StateRecord(tuple(a.items())),proposal)
