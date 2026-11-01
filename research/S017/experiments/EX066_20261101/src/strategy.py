"""Fixed C222 plus one-shot flat recovery while its accepted parent structure survives."""
from math import isfinite
from datetime import datetime,timezone
from strategy_runtime import (AccountDecision,AccountStepResult,BarField,FeatureGraph,Lag,Mean,RawField,ReadyValue,SameLocalSlotMedian,StateField,StateRecord,StateValueType,StrategyStateSchema,TrueRange)
OUTPUTS=('close','high','low','previous_low','low2','previous_close','previous_open','previous_high','previous_volume','previous_tr','atr_before_prior','same_slot_median20','previous_ma65','previous_ma260')
def feature_graph():
    return FeatureGraph((RawField('close',BarField.CLOSE),RawField('opening',BarField.OPEN),RawField('high',BarField.HIGH),RawField('low',BarField.LOW),RawField('volume',BarField.VOLUME),Lag('previous_close','close',1),Lag('previous_open','opening',1),Lag('previous_high','high',1),Lag('previous_low','low',1),Lag('low2','low',2),Lag('previous_volume','volume',1),TrueRange('tr','high','low','close'),Mean('atr13','tr',13),Lag('previous_tr','tr',1),Lag('atr_before_prior','atr13',2),SameLocalSlotMedian('same_slot_median20','volume',20,1),Mean('ma65','close',65),Mean('ma260','close',260),Lag('previous_ma65','ma65',1),Lag('previous_ma260','ma260',1)),OUTPUTS)

WATCH_FIELDS=(('watch_active',StateValueType.BOOL),('watch_spent',StateValueType.BOOL),('watch_parent_low',StateValueType.FLOAT),('watch_failed_line',StateValueType.FLOAT),('watch_source_entry',StateValueType.DATETIME),('watch_created_at',StateValueType.DATETIME))

def empty_watch():
    epoch=datetime(1970,1,1,tzinfo=timezone.utc)
    return dict(watch_active=False,watch_spent=False,watch_parent_low=0.,watch_failed_line=0.,watch_source_entry=epoch,watch_created_at=epoch)

def initial_account():
    return StateRecord(tuple(empty_watch().items()))

def state_schema():
    fields=(('holding_bars',StateValueType.INT),('last_completed_at',StateValueType.DATETIME),('exit_due',StateValueType.BOOL),('initial_support',StateValueType.FLOAT),('support',StateValueType.FLOAT),('support_raises',StateValueType.INT),('exit_reason',StateValueType.STR),('peak',StateValueType.FLOAT),('peak_before_last',StateValueType.FLOAT),('pending_support',StateValueType.BOOL),('candidate_low',StateValueType.FLOAT),('candidate_high',StateValueType.FLOAT),('candidate_at',StateValueType.DATETIME),('raw_s0',StateValueType.FLOAT),('reclaimed_level',StateValueType.FLOAT),('accepted_active',StateValueType.BOOL),('accepted_low',StateValueType.FLOAT),('accepted_high',StateValueType.FLOAT),('accepted_peak_close',StateValueType.FLOAT),('entry_scale',StateValueType.FLOAT),('signal_reference_close',StateValueType.FLOAT),('entry_u',StateValueType.BOOL),('cycle_g',StateValueType.FLOAT))
    return StrategyStateSchema(account_fields=tuple(StateField(k,v) for k,v in WATCH_FIELDS),cycle_fields=tuple(StateField(k,v) for k,v in (*fields,('entry_origin',StateValueType.STR))))
def accepted_failure_line(L,H,P,b,g):
    if not H>L or P<H:raise ValueError('Accepted structural pair and completed peak required')
    if g==0:return L+b*(H-L)
    if g==1:return P-(1-b)*(H-L)
    return L+b*(H-L)+g*max(0.,P-H)

def step(ctx,state):
    if set(ctx.parameters)!={'alpha','initial_fraction','accepted_fraction','g_when_u','g_when_other','recovery_enabled','reentry_floor'}:raise ValueError('Three fixed financial parameters and two background mappings required')
    pars={k:float(x) for k,x in ctx.parameters.items() if type(x) in (int,float)}
    if len(pars)!=5 or not all(isfinite(x) for x in pars.values()) or not 0<=pars['alpha'] or not all(0<=pars[k]<=1 for k in ('initial_fraction','accepted_fraction','g_when_u','g_when_other')):raise ValueError('Declared initial/extension and natural parameter domains only')
    fixed={'alpha':.3435458360048906,'initial_fraction':.42823406094793653,'accepted_fraction':.1569056351519751,'g_when_u':.75,'g_when_other':0.}
    if pars!=fixed or type(ctx.parameters['recovery_enabled']) is not bool or ctx.parameters['reentry_floor'] not in ('PARENT_LOW','RECLAIM_LINE'):raise ValueError('Only fixed C222 and two predeclared recovery risks permitted')
    enabled=ctx.parameters['recovery_enabled']
    if not enabled and ctx.parameters['reentry_floor']!='PARENT_LOW':raise ValueError('Disabled baseline has one canonical parameter identity')
    p=ctx.portfolio
    if p.reference_price_scale!=1. or ctx.events:raise ValueError('RAW NONE contract only')
    v={}
    for k in OUTPUTS:
        x=ctx.features.get(k)
        if type(x) is not ReadyValue:raise ValueError('Ready complete observations required')
        v[k]=float(x.value)
    m006=v['previous_close']<v['previous_open'] and v['close']>v['previous_high'];m005=m006 and v['previous_volume']>=1.5*v['same_slot_median20'] and v['previous_tr']<=v['atr_before_prior']
    delta=v['close']-v['previous_high'];scale=v['atr_before_prior']
    if scale<0:raise ValueError('True range scale cannot be negative')
    signal=m006 and delta>pars['alpha']*scale
    entry_u=v['previous_close']>v['previous_ma65']>v['previous_ma260'];selected_g=pars['g_when_u'] if entry_u else pars['g_when_other']
    current=ctx.history.last()['Date'];held=p.quantity>0;proposal=None
    if not held and state.cycle is not None:raise ValueError('Flat recovery requires confirmed cleared cycle state')
    watch=dict(state.account.values)
    if set(watch)!={k for k,_ in WATCH_FIELDS} or type(watch['watch_active']) is not bool or type(watch['watch_spent']) is not bool:raise ValueError('Typed explicit initial watch state required')
    if watch['watch_active'] and not watch['watch_failed_line']>watch['watch_parent_low']>0:raise ValueError('Active frozen watch must have positive parent span')
    if not enabled and watch['watch_active']:raise ValueError('Disabled control cannot carry recovery state')
    created=cancelled_parent=cleared_buy=first_recovery=False
    if watch['watch_active'] and v['close']<watch['watch_parent_low']:
        watch=empty_watch();cancelled_parent=True
    if watch['watch_active'] and held and p.cycle_entry!=watch['watch_source_entry']:
        watch=empty_watch();cleared_buy=True
    origin='NONE'
    facts={**v,'entry_signal':bool(signal),'m005_signal':bool(m005),'m006_signal':bool(m006),'alpha':pars['alpha'],'initial_fraction':pars['initial_fraction'],'accepted_fraction':pars['accepted_fraction'],'current_u':bool(entry_u),'current_setup_g_choice':selected_g,'reclaim_margin_atr':delta/scale if scale>0 else None,'setup_risk_distance_atr':(v['close']-min(v['previous_low'],v['low']))/scale if scale>0 else None,'normalization_defined':scale>0,'held':held,'portfolio_quantity':p.quantity,'portfolio_cash':p.cash,'cycle_present':state.cycle is not None,'holding_bars':0,'exit_due':False,'exit_trigger':'NONE','support_raised':False,'pivot_confirmed':False,'candidate_cancelled':False,'candidate_created':False,'candidate_accepted':False,'candidate_lost_line_qualification':False,'dynamic_line_raised':False,'old_effective_line':None,'accepted_base_failure_line':None,'progress_increment':0.,'base_failure':False,'dynamic_failure_only':False}
    if held:
        if state.cycle is None or state.cycle.entry_at!=p.cycle_entry or p.cycle_cost<=0:raise ValueError('Actual activated cycle required')
        s=dict(state.cycle.values.values)
        was_due=s['exit_due'];origin=s['entry_origin']
        cycle_g=s['cycle_g']
        if type(s['entry_u']) is not bool or type(cycle_g) is not float or not 0<=cycle_g<=1:raise ValueError('Typed frozen entry background and cycle protection required')
        if current<=s['last_completed_at']:raise ValueError('Complete observation must advance')
        s['holding_bars']+=1;s['last_completed_at']=current
        facts['old_effective_line']=s['support']
        if not s['exit_due']:
            if s['accepted_active']:
                s['accepted_peak_close']=max(s['accepted_peak_close'],v['close'])
                updated=accepted_failure_line(s['accepted_low'],s['accepted_high'],s['accepted_peak_close'],pars['accepted_fraction'],cycle_g)
                if updated<s['support']:raise ValueError('Dynamic line must not decrease; no hidden clamp')
                facts['dynamic_line_raised']=updated>s['support'];s['support']=updated
                base_line=s['accepted_low']+pars['accepted_fraction']*(s['accepted_high']-s['accepted_low'])
                facts.update(accepted_base_failure_line=base_line,progress_increment=updated-base_line,base_failure=v['close']<base_line,dynamic_failure_only=base_line<=v['close']<updated)
            if v['close']<s['support']:
                s['exit_due']=True;s['exit_reason']='INITIAL_SUPPORT_BREAK' if not s['accepted_active'] else 'CONFIRMED_HIGHER_SUPPORT_BREAK'
            if not s['exit_due']:
                if s['pending_support'] and (v['low']<s['candidate_low'] or s['candidate_low']<=s['support']):
                    facts['candidate_lost_line_qualification']=s['candidate_low']<=s['support'];s['pending_support']=False;facts['candidate_cancelled']=True
                pivot=v['previous_low']<v['low2'] and v['previous_low']<v['low'] and v['previous_low']>s['support']
                eligible=False
                if pivot:
                    three=ctx.history.to_frame(tail=3)
                    if len(three)!=3 or not three.Date.is_monotonic_increasing or three.Date.duplicated().any() or three.Date.iloc[-1]!=current:raise ValueError('Exactly last three completed bars required')
                    eligible=three.BarStart.iloc[0]>p.cycle_entry
                facts['pivot_confirmed']=bool(eligible)
                if eligible and not s['pending_support']:
                    if s['peak_before_last']<=0:raise ValueError('Pre-pivot full held peak required')
                    s.update(pending_support=True,candidate_low=v['previous_low'],candidate_high=s['peak_before_last'],candidate_at=current);facts['candidate_created']=True
                if s['pending_support'] and v['close']>s['candidate_high']:
                    L=s['candidate_low'];H=s['candidate_high']
                    if not L>s['support']:raise ValueError('Accepted low must remain above current dynamic line')
                    new_line=accepted_failure_line(L,H,v['close'],pars['accepted_fraction'],cycle_g)
                    if not s['support']<new_line<=v['close']:raise ValueError('New accepted line naturally increases without acceptance-bar self-exit')
                    s.update(support=new_line,accepted_active=True,accepted_low=L,accepted_high=H,accepted_peak_close=v['close']);s['support_raises']+=1;s['pending_support']=False;facts.update(support_raised=True,candidate_accepted=True,accepted_base_failure_line=L+pars['accepted_fraction']*(H-L),progress_increment=new_line-(L+pars['accepted_fraction']*(H-L)))
            if ctx.history.last()['BarStart']>p.cycle_entry:s['peak_before_last']=s['peak'];s['peak']=max(s['peak'],v['high'])
        proposal=StateRecord(tuple(s.items()));target=int(not s['exit_due']);facts.update(entry_u=s['entry_u'],cycle_g=cycle_g,holding_bars=s['holding_bars'],exit_due=s['exit_due'],exit_trigger=s['exit_reason'],initial_support=s['initial_support'],support=s['support'],support_raises=s['support_raises'],pending_support=s['pending_support'],candidate_low=s['candidate_low'],candidate_high=s['candidate_high'],candidate_at=s['candidate_at'],peak=s['peak'],peak_before_last=s['peak_before_last'],raw_s0=s['raw_s0'],reclaimed_level=s['reclaimed_level'],accepted_active=s['accepted_active'],accepted_low=s['accepted_low'],accepted_high=s['accepted_high'],initial_position=(v['close']-s['raw_s0'])/(s['reclaimed_level']-s['raw_s0']),entry_signal_risk_atr=(s['signal_reference_close']-s['raw_s0'])/s['entry_scale'] if s['entry_scale']>0 else None,entry_scale=s['entry_scale'],signal_reference_close=s['signal_reference_close'],actual_cycle_net_mark_return=(p.quantity*v['close']*.999-p.cycle_cost)/p.cycle_cost)
        if s['accepted_active']:
            D=s['accepted_high']-s['accepted_low']
            if D<=0:raise ValueError('Accepted H/L pair must have positive span')
            facts.update(accepted_position=(v['close']-s['accepted_low'])/D,accepted_progress=(s['accepted_peak_close']-s['accepted_high'])/D,accepted_retracement=(s['accepted_peak_close']-v['close'])/D)
        if enabled and not was_due and s['exit_due'] and s['accepted_active'] and v['close']>=s['accepted_low'] and s['support']>s['accepted_low']:
            if watch['watch_active']:raise ValueError('A new actual accepted failure cannot overwrite an active prior watch')
            watch=dict(watch_active=True,watch_spent=False,watch_parent_low=s['accepted_low'],watch_failed_line=s['support'],watch_source_entry=p.cycle_entry,watch_created_at=current);created=True
    else:
        first_recovery=bool(enabled and watch['watch_active'] and not watch['watch_spent'] and v['previous_close']<=watch['watch_failed_line']<v['close'])
        if first_recovery:watch['watch_spent']=True
        origin='E0' if signal else 'RECOVERY' if first_recovery else 'NONE'
        target=int(signal or first_recovery)
        if target:
            raw=min(v['previous_low'],v['low']) if origin=='E0' else watch['watch_parent_low']
            R=v['previous_high'] if origin=='E0' else watch['watch_failed_line']
            if not R>raw:raise ValueError('Reclaim structure must have positive width')
            floor=raw+pars['initial_fraction']*(R-raw) if origin=='E0' else raw if ctx.parameters['reentry_floor']=='PARENT_LOW' else R
            proposal=StateRecord((('holding_bars',0),('last_completed_at',current),('exit_due',False),('initial_support',floor),('support',floor),('support_raises',0),('exit_reason','NONE'),('peak',0.),('peak_before_last',0.),('pending_support',False),('candidate_low',0.),('candidate_high',0.),('candidate_at',current),('raw_s0',raw),('reclaimed_level',R),('accepted_active',False),('accepted_low',0.),('accepted_high',0.),('accepted_peak_close',0.),('entry_scale',scale),('signal_reference_close',v['close']),('entry_u',bool(entry_u)),('cycle_g',float(selected_g)),('entry_origin',origin)))
    facts.update(e0_signal=bool(signal),entry_signal=bool(signal or first_recovery),entry_origin=origin,recovery_enabled=enabled,reentry_floor=ctx.parameters['reentry_floor'],first_recovery_event=first_recovery,e0_priority_on_recovery=bool(signal and first_recovery),recovery_entry_selected=bool(not held and origin=='RECOVERY'),watch_created=created,watch_cancelled_parent=cancelled_parent,watch_cleared_confirmed_buy=cleared_buy,confirmed_flat=p.quantity==0,**watch)
    return AccountStepResult(AccountDecision.from_facts(target,'Reclaimed continuation, confirmed swing and price acceptance',facts=facts,next_watch='Only real complete held structure; candidate is not yet support, all exits next interval and locked',capital_mode='full_available_cash'),StateRecord(tuple(watch.items())),proposal)

