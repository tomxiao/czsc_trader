"""Synthetic public V4 prefix invariance and confirmed-state contract checks."""
from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
from types import SimpleNamespace
import numpy as np
import pandas as pd
from dataflows import BarFrequency,TradingSession,TimeInterval
from strategy_runtime import PreparedReplay,run_replay,ReadyValue,AccountStrategyState,CycleState,StateRecord
from trading_execution_engine import PortfolioHistoricalExecutor
from common import WORK,PARAMETERS,SPEC,candidate,save,digest
from strategy import step,OUTPUTS

def main():
    zone=ZoneInfo('America/New_York'); day=date(2019,1,2); days=[]
    while len(days)<50:
        if day.weekday()<5: days.append(day)
        day+=timedelta(days=1)
    sessions=tuple(TradingSession(d,str(zone),(TimeInterval(datetime(d.year,d.month,d.day,9,30,tzinfo=zone),datetime(d.year,d.month,d.day,(13 if k==10 else 16),tzinfo=zone)),)) for k,d in enumerate(days))
    periods=[p for s in sessions for p in s.bars(BarFrequency.M30)]
    starts=pd.DatetimeIndex([p.start for p in periods]).tz_convert('UTC'); ends=pd.DatetimeIndex([p.end for p in periods]).tz_convert('UTC')
    i=np.arange(len(periods)); prices=100+.04*i+1.5*np.sin(i/6)
    bars=pd.DataFrame({'BarStart':starts,'Date':ends,'AvailableDate':ends,'Open':prices-.03,'High':prices+.08,'Low':prices-.08,'Close':prices,'Volume':1000000.,'Amount':prices*1000000})
    constraints=pd.DataFrame({'Date':starts,'AvailableDate':starts,'QuantityStep':1,'PriceTick':.01,'Tradable':True,'PriceLimitPolicy':'EXPLICIT_UNBOUNDED','PriceLimitLower':None,'PriceLimitUpper':None,'BuySellableAt':starts,'SettlementAt':starts,'SellRemainderPolicy':'STRICT_STEP'})
    actions=pd.DataFrame([{'Date':starts[0],'AvailableDate':starts[0],'EventId':'synthetic-none','Kind':'NONE','Ratio':1.,'CashPerShare':0.,'PayAt':None}])
    calendar=pd.DataFrame({'Date':[s.segments[0].start for s in sessions],'AvailableDate':[s.segments[0].start for s in sessions],'SessionDate':[s.session_date.isoformat() for s in sessions]})
    for j in range(37,len(bars)-1,37):
        c=float(bars.loc[j,'Close']);bars.loc[j,['Open','High','Low','Volume']]=[c+.03,c+.07,c-.06,3000000.]
        n=max(float(bars.loc[j+1,'Close']),c+.12);bars.loc[j+1,['Open','High','Low','Close']]=[n-.03,n+.08,n-.08,n]
    changed=bars.copy(); changed.loc[520:,['Open','High','Low','Close']]*=1.7; changed.loc[520:,'Amount']*=1.7
    market_prices=200.+.2*np.arange(len(sessions))
    market=pd.DataFrame({'BarStart':pd.to_datetime([s.segments[0].start for s in sessions],utc=True),'Date':pd.to_datetime([s.segments[-1].end for s in sessions],utc=True),'AvailableDate':pd.to_datetime([s.segments[-1].end for s in sessions],utc=True),'Open':market_prices-.03,'High':market_prices+.1,'Low':market_prices-.1,'Close':market_prices,'Volume':1000000.,'Amount':market_prices*1000000.})
    changed_market=market.copy();changed_market.loc[changed_market.Date>=starts[520],['Open','High','Low','Close']]*=1.7
    def replay(key,frame,market_frame):
        c=candidate(key); p=PreparedReplay.from_frames(frame,constraints,c.definition.feature_graph,frequency=BarFrequency.M30,timezone=str(zone),sessions=calendar,trading_sessions=sessions,auxiliary_histories={'market':market_frame})
        executor=PortfolioHistoricalExecutor(specification=SPEC,initial_cash=100000.,fee_rate=.001,actions=actions,price_basis='RAW')
        return run_replay(p,c,executor,start=starts[274].to_pydatetime(),end=ends[-1].to_pydatetime(),fee_rate=.001)
    def prefix(result):
        output={}
        for name,field in {'decisions':'decision_at','orders':'valid_start','fills':'interval_start','account_points':'time','account_daily':'time','trades':'exit_at'}.items():
            f=getattr(result,name)
            if f.empty: output[name]='[]'; continue
            f=f[pd.to_datetime(f[field],utc=True)<starts[520]]
            f=f.drop(columns=[c for c in f if c.endswith('_id')])
            output[name]=f.to_json(orient='records',date_format='iso',double_precision=15)
        return output
    from strategy import relative_eligibility
    dt=market.Date.iloc[:21].reset_index(drop=True);primary=pd.DataFrame({'Date':dt,'AvailableDate':dt,'BarStart':dt-pd.Timedelta(minutes=30),'Close':100.+np.arange(21)})
    spy=market.iloc[:21].copy();spy['Close']=200.+np.arange(21)
    point=SimpleNamespace(observed_through=dt.iloc[-1].to_pydatetime(),decision_at=dt.iloc[-1].to_pydatetime())
    def relative_context(primary_frame=primary,spy_frame=spy):
        return SimpleNamespace(point=point,history=SimpleNamespace(to_frame=lambda tail:primary_frame.tail(tail)),auxiliary_histories={'market':SimpleNamespace(to_frame=lambda tail:spy_frame.tail(tail))})
    qualified,detail=relative_eligibility(relative_context());assert qualified and detail['relative_points']==20
    current_changed=spy.copy();current_changed.loc[current_changed.index[-1],'Close']*=10
    assert relative_eligibility(relative_context(spy_frame=current_changed))==relative_eligibility(relative_context()),'Current daily point must be excluded'
    equal=spy.copy();equal.loc[equal.index[-2],'Close']=float(equal.Close.iloc[0])*float(primary.Close.iloc[-2]/primary.Close.iloc[0]);assert not relative_eligibility(relative_context(spy_frame=equal))[0],'Relative equality fails'
    flat=primary.copy();flat.loc[flat.index[-2],'Close']=float(flat.Close.iloc[0]);down=spy.copy();down.loc[down.index[-2],'Close']=float(down.Close.iloc[0])*.9;assert not relative_eligibility(relative_context(primary_frame=flat,spy_frame=down))[0],'Absolute equality fails despite relative outperformance'
    for bad in (primary.drop(index=5),pd.concat([primary,primary.iloc[[5]]]).sort_values('Date')):
        try:relative_eligibility(relative_context(primary_frame=bad))
        except ValueError:pass
        else:raise AssertionError('Missing/duplicate main endpoint cannot be filled')
    values={k:1. for k in OUTPUTS};values.update(close=103.,ma65=102.,ma260=100.,previous_close=100.,previous_open=101.,previous_high=101.,previous_volume=3.,same_slot_median20=1.,previous_tr=.5,atr_before_prior=1.)
    current=point.decision_at;entry=current-timedelta(hours=2);last=current-timedelta(minutes=30)
    def call(policy,record=None,market_frame=spy):
        held=record is not None;state=SimpleNamespace(cycle=None if not held else SimpleNamespace(entry_at=entry,values=record));ctx=relative_context(spy_frame=market_frame)
        ctx.parameters={'policy':policy};ctx.events=();ctx.features=SimpleNamespace(get=lambda k:ReadyValue(values[k]));ctx.portfolio=SimpleNamespace(quantity=int(held),cash=0. if held else 100000.,reference_price_scale=1.,cycle_entry=entry if held else None,cycle_cost=100. if held else 0.);ctx.history.last=lambda:{'Date':current}
        return step(ctx,state)
    def record(bars=25,active=False,due=False):return StateRecord((('holding_bars',bars),('last_completed_at',last),('exit_due',due),('origin','M005'),('trend_active',active),('promoted',active),('exit_reason','FIXED_26' if due else 'NONE')))
    assert dict(call('RELATIVE_AT26',record()).cycle_values.values)['promoted']
    failed26=call('RELATIVE_AT26',record(),market_frame=equal);assert failed26.decision.target==0
    assert call('CONTROL_SLOW',record(),market_frame=equal).decision.target==1
    assert call('RELATIVE_AT26',record(bars=24),market_frame=equal).decision.target==1
    current+=timedelta(minutes=30);assert call('RELATIVE_AT26',failed26.cycle_values).decision.target==0,'Qualified27 cannot reverse failed26'
    assert call('RELATIVE_AT26',record(bars=26,active=True),market_frame=equal).decision.target==1,'Relative weakness after promotion is not a new exit'
    values['close']=99.;assert call('RELATIVE_AT26',record(bars=26,active=True)).decision.target==0
    results={}
    import json
    for key in PARAMETERS:
        a=replay(key,bars,market);bm=replay(key,changed,market);ba=replay(key,bars,changed_market)
        assert prefix(a.execution_result)==prefix(bm.execution_result)==prefix(ba.execution_result)
        assert len(a.execution_result.fills)>0 and (a.execution_result.account_points.cash>=0).all()
        rows=json.loads(a.execution_result.decisions.to_json(orient='records',date_format='iso'));facts=[{v['key']:v['text'] for v in row['explanation']['basis']} for row in rows];assert facts[0]['portfolio_quantity']=='0' and facts[0]['cycle_present']=='False'
        average=len(a.execution_result.decisions.to_json(orient='records',date_format='iso').encode())/len(rows);assert average<20000
        results[key]={'average_decision_bytes':average,'main_and_aux_separate_prefix_invariance':'PASS','fills':len(a.execution_result.fills),'module_loads':a.statistics.module_loads,'relative_qualification_checks':sum('relative_qualified' in f for f in facts)}
    save(WORK/'others/precheck.json',{'status':'PASS','strategy_sha256':digest(WORK/'src/strategy.py'),'precheck_sha256':digest(WORK/'src/precheck.py'),'synthetic_only':True,'accounts':results,'direct_boundaries':['20 points19 intervals','strictly prior local day even visible current day','half-day exact13 endpoint','relative equality fails','absolute equality fails','missing/duplicate endpoint fails','actual26 only','failed26 cannot reverse27','no relative exit after promotion','original F exit'],'limitations':'Public main/aux replay and direct boundaries, not source historical publication-time upgrade or all calendar/rights events.'})
    print('PUBLIC_MAIN_AUX_SYNTHETIC_PRECHECK_PASS',flush=True)
if __name__=='__main__':main()
