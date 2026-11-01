"""Public synthetic recovery state tests; no formal account or new market label."""
from datetime import date,datetime,timedelta,timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import json
import numpy as np
import pandas as pd
from dataflows import BarFrequency,TradingSession,TimeInterval
from strategy_runtime import PreparedReplay,run_replay,ReadyValue,StateRecord
from trading_execution_engine import PortfolioHistoricalExecutor
from common import ROOT,WORK,PARAMETERS,SPEC,candidate,save,digest
from strategy import step,OUTPUTS,initial_account,accepted_failure_line


def boundaries():
 zone=ZoneInfo('America/New_York');current=datetime(2019,3,4,11,tzinfo=zone);entry=current-timedelta(hours=3)
 v={k:1. for k in OUTPUTS};v.update(close=108.5,high=109.,low=107.,previous_low=105.,low2=108.,previous_close=106.,previous_open=107.,previous_high=108.,previous_volume=1.5,same_slot_median20=1.,previous_tr=1.,atr_before_prior=1.,previous_ma65=105.,previous_ma260=104.)
 def rec(**kwargs):
  z=dict(holding_bars=2,last_completed_at=current-timedelta(minutes=30),exit_due=False,initial_support=95.,support=108.,support_raises=1,exit_reason='NONE',peak=125.,peak_before_last=120.,pending_support=False,candidate_low=0.,candidate_high=0.,candidate_at=current-timedelta(minutes=30),raw_s0=90.,reclaimed_level=100.,accepted_active=True,accepted_low=100.,accepted_high=110.,accepted_peak_close=120.,entry_scale=1.,signal_reference_close=110.,entry_u=True,cycle_g=.75,entry_origin='E0');z.update(kwargs);return StateRecord(tuple(z.items()))
 def call(key,account=None,cycle=None,ce=None):
  nonlocal current
  current+=timedelta(minutes=30)
  actual_entry=entry if ce is None else ce
  frame=pd.DataFrame({'BarStart':[current-timedelta(minutes=m) for m in (90,60,30)],'Date':[current-timedelta(minutes=m) for m in (60,30,0)]})
  ctx=SimpleNamespace(parameters=PARAMETERS[key],events=(),features=SimpleNamespace(get=lambda k:ReadyValue(v[k])),portfolio=SimpleNamespace(quantity=int(cycle is not None),cash=0. if cycle else 100000.,reference_price_scale=1.,cycle_entry=actual_entry if cycle else None,cycle_cost=100. if cycle else 0.),history=SimpleNamespace(last=lambda:{'Date':current,'BarStart':current-timedelta(minutes=30)},to_frame=lambda tail:frame.tail(tail)))
  return step(ctx,SimpleNamespace(account=initial_account() if account is None else account,cycle=None if cycle is None else SimpleNamespace(entry_at=actual_entry,values=cycle)))
 def account(x):return dict(x.account.values)
 def cycle(x):return dict(x.cycle_values.values)
 created=call('C0330',cycle=rec());w=account(created);s=cycle(created)
 assert w['watch_active'] and w['watch_parent_low']==100. and w['watch_failed_line']==s['support']!=108.,'Freeze actual updated line,not old_effective_line'
 assert not account(call('C0329',cycle=rec()))['watch_active'],'Off source does not grant watch'
 v['close']=99.99;cancel=call('C0330',created.account,created.cycle_values);assert not account(cancel)['watch_active'] and cycle(cancel)['exit_due']
 v['close']=125.;late=call('C0330',cancel.account,cancel.cycle_values);assert not account(late)['watch_active'] and late.decision.target==0,'Blocked due cannot recreate cancelled watch'
 line=w['watch_failed_line'];v.update(previous_close=line,previous_open=line-.1,previous_high=line+.1,close=line)
 eq=call('C0330',created.account);assert eq.decision.target==0 and not account(eq)['watch_spent'],'Recovery line equality not upcross'
 v['close']=100.;eq=call('C0330',created.account);assert account(eq)['watch_active'],'Parent equality not invalidation'
 v.update(previous_close=line,previous_open=line+.1,previous_high=line+.2,close=line+.7,low=line-.1)
 priority=call('C0330',created.account);assert cycle(priority)['entry_origin']=='E0' and account(priority)['watch_spent'],'First cross consumed despite E0 priority'
 v.update(previous_close=line,previous_open=line-.1,previous_high=line+.2,close=line+.7)
 spent=call('C0330',priority.account);assert spent.decision.target==0,'Unfilled E0 first event cannot choose second recovery'
 for key,floor in (('C0330',100.),('C0331',line)):
  restore=call(key,created.account);z=cycle(restore)
  assert z['entry_origin']=='RECOVERY' and z['raw_s0']==100. and z['reclaimed_level']==line and z['support']==floor and not z['accepted_active'] and z['cycle_g']==.75
  v.update(close=floor-.01,previous_ma65=107.,previous_ma260=108.)
  firstheld=call(key,restore.account,restore.cycle_values,ce=current)
  assert not account(firstheld)['watch_active'] and cycle(firstheld)['exit_due'] and not cycle(firstheld)['accepted_active'],'New actual BUY clears old watch;initial recovery failure never grants watch'
  assert cycle(firstheld)['cycle_g']==.75,'Proposal g not replaced by fill-time current U'
  v.update(close=line+.7,previous_ma65=105.,previous_ma260=104.)
 v.update(close=112.,high=113.,low=111.)
 own=call('C0330',cycle=rec(entry_origin='RECOVERY',accepted_low=105.,accepted_high=110.,accepted_peak_close=120.,support=110.))
 assert account(own)['watch_active'] and account(own)['watch_parent_low']==105.,'Own new accepted pair can grant fresh watch'
 return {'actual_updated_line_frozen':True,'parent_break_pending_due_irreversible':True,'E0_priority_spends_even_unfilled':True,'two_recovery_initial_risks':True,'new_BUY_clear_initial_failure_no_watch':True,'own_postfill_accepted_required':True,'proposal_g_frozen':True}


def public_synthetic():
 zone=ZoneInfo('America/New_York');day=date(2019,1,2);days=[]
 while len(days)<50:
  if day.weekday()<5:days.append(day)
  day+=timedelta(days=1)
 sessions=tuple(TradingSession(d,str(zone),(TimeInterval(datetime(d.year,d.month,d.day,9,30,tzinfo=zone),datetime(d.year,d.month,d.day,16,tzinfo=zone)),)) for d in days)
 periods=[p for s in sessions for p in s.bars(BarFrequency.M30)];starts=pd.DatetimeIndex([p.start for p in periods]).tz_convert('UTC');ends=pd.DatetimeIndex([p.end for p in periods]).tz_convert('UTC')
 i=np.arange(len(periods));prices=100+.04*i+1.5*np.sin(i/6)
 bars=pd.DataFrame({'BarStart':starts,'Date':ends,'AvailableDate':ends,'Open':prices-.03,'High':prices+.08,'Low':prices-.08,'Close':prices,'Volume':1000000.,'Amount':prices*1000000.})
 for j in range(37,len(bars)-1,37):
  c=float(bars.loc[j,'Close']);bars.loc[j,['Open','High','Low']]=[c+.03,c+.07,c-.06]
  q=max(float(bars.loc[j+1,'Close']),c+.5);bars.loc[j+1,['Open','High','Low','Close']]=[q-.03,q+.08,q-.08,q]
 c=float(bars.loc[273,'Close']);bars.loc[273,['Open','High','Low','Close']]=[c+.01,c+.02,c-.02,c]
 q=c+.35;bars.loc[274,['Open','High','Low','Close']]=[q-.01,q+.02,q-.02,q]
 bars.loc[275,['Open','High','Low','Close']]=[q*1.02,q*1.025,q*.995,q*1.005]
 # Deliberate synthetic parent: accept a higher low, protect new advance,
 # exit above parent, recover only after real SELL, then own new postfill pair.
 for j,delta in {276:1.2,277:1.0,278:1.6,279:2.6,280:1.5,281:2.1,282:1.8,283:2.3,284:2.1,285:2.8,286:3.8,287:2.7,288:2.5,289:3.3}.items():
  close=c+delta;bars.loc[j,['Open','High','Low','Close']]=[close-.03,close+.1,close-.1,close]
 bars.loc[281,['Open','Low']]=[c+1.5,c+1.4]
 bars.loc[282,['Open','High']]=[c+2.1,c+2.2]
 constraints=pd.DataFrame({'Date':starts,'AvailableDate':starts,'QuantityStep':1,'PriceTick':.01,'Tradable':True,'PriceLimitPolicy':'EXPLICIT_UNBOUNDED','PriceLimitLower':None,'PriceLimitUpper':None,'BuySellableAt':starts,'SettlementAt':starts,'SellRemainderPolicy':'STRICT_STEP'})
 actions=pd.DataFrame([{'Date':starts[0],'AvailableDate':starts[0],'EventId':'none','Kind':'NONE','Ratio':1.,'CashPerShare':0.,'PayAt':None}]);calendar=pd.DataFrame({'Date':[s.segments[0].start for s in sessions],'AvailableDate':[s.segments[0].start for s in sessions],'SessionDate':[s.session_date.isoformat() for s in sessions]})
 def replay(key,frame,rules=constraints):
  c=candidate(key);p=PreparedReplay.from_frames(frame,rules,c.definition.feature_graph,frequency=BarFrequency.M30,timezone=str(zone),sessions=calendar,trading_sessions=sessions)
  e=PortfolioHistoricalExecutor(specification=SPEC,initial_cash=100000.,fee_rate=.001,actions=actions,price_basis='RAW')
  return run_replay(p,c,e,start=starts[274].to_pydatetime(),end=ends[-1].to_pydatetime(),fee_rate=.001).execution_result
 def facts(result):
  rows=json.loads(result.decisions.to_json(orient='records',date_format='iso'));return rows,[{x['key']:x['text'] for x in row['explanation']['basis']} for row in rows]
 changed=bars.copy();changed.loc[520:,['Open','High','Low','Close']]*=1.7
 result={key:replay(key,bars) for key in ('C0222',*PARAMETERS)};out={}
 fields={'decisions':('observed_through','decision_at','execution_start','execution_end','target','reference_price','limit_price','quantity','side','signal_status'),'orders':('valid_start','valid_end','side','quantity','limit_price','status','reason'),'fills':('interval_start','interval_end','side','quantity','price','fees','time_precision'),'account_points':('time','cash','quantity','receivable','equity','close','session','valuation_stale'),'account_daily':('time','cash','quantity','receivable','equity','close','session','valuation_stale'),'trades':('entry_at','exit_at','cost','income','net_pnl','net_return','status')}
 equivalent={k:getattr(result['C0222'],k)[list(cols)].to_json(orient='records',date_format='iso',double_precision=15)==getattr(result['C0329'],k)[list(cols)].to_json(orient='records',date_format='iso',double_precision=15) for k,cols in fields.items()};assert all(equivalent.values())
 for key in PARAMETERS:
  base=result[key];future=replay(key,changed)
  for table,field in {'decisions':'decision_at','orders':'valid_start','fills':'interval_start','account_points':'time','account_daily':'time','trades':'exit_at'}.items():
   def prefix(f):
    f=f[pd.to_datetime(f[field],utc=True)<starts[520]];return f.drop(columns=[c for c in f if c.endswith('_id')]).to_json(orient='records',date_format='iso',double_precision=15)
   assert prefix(getattr(base,table))==prefix(getattr(future,table)),key+' future prefix'
  rows,ff=facts(base);avg=len(base.decisions.to_json(orient='records',date_format='iso').encode())/len(rows);assert avg<16000
  out[key]={'fills':len(base.fills),'created_watch':sum(f['watch_created']=='True' for f in ff),'first_flat_recoveries':sum(f['first_recovery_event']=='True' for f in ff),'recovery_proposals':sum(f['recovery_entry_selected']=='True' and f['held']=='False' for f in ff),'average_decision_bytes':avg,'future_prefix':'PASS'}
 save(WORK/'others/synthetic_watch_trace.json',out)
 assert out['C0330']['created_watch'] and out['C0330']['first_flat_recoveries'] and out['C0330']['recovery_proposals'],'Actual watch/flat/recovery required'
 assert out['C0331']['created_watch'] and out['C0331']['first_flat_recoveries'] and out['C0331']['recovery_proposals']
 # Real blocked SELL: parent break cancels while still held, then a recovery
 # above frozen line cannot withdraw the old due or resurrect the watch.
 rows,ff=facts(result['C0330']);ix={pd.Timestamp(t):j for j,t in enumerate(bars.Date)}
 created_row=next((r,f) for r,f in zip(rows,ff) if f['watch_created']=='True');t=ix[pd.Timestamp(created_row[0]['observed_through'])];parent=float(created_row[1]['watch_parent_low']);line=float(created_row[1]['watch_failed_line'])
 blocked=bars.copy();rules=constraints.copy();rules.loc[t+1:t+2,'Tradable']=False
 blocked.loc[t+1,['Open','High','Low','Close']]=[parent-.05,parent+.05,parent-.2,parent-.1]
 blocked.loc[t+2,['Open','High','Low','Close']]=[parent+.1,line+.6,parent,line+.5]
 real_blocked=replay('C0330',blocked,rules);br,bf=facts(real_blocked)
 cancelled=next(f for r,f in zip(br,bf) if pd.Timestamp(r['observed_through'])==ends[t+1])
 later=next(f for r,f in zip(br,bf) if pd.Timestamp(r['observed_through'])==ends[t+2])
 assert cancelled['held']=='True' and cancelled['watch_cancelled_parent']=='True' and cancelled['exit_due']=='True'
 assert later['held']=='True' and later['exit_due']=='True' and later['watch_active']=='False' and later['first_recovery_event']=='False'
 assert any(o['side']=='SELL' and o['status']!='FILLED' for o in real_blocked.orders.to_dict('records'))
 # Real E0 priority on first recovery, then an actual failed BUY. A second
 # flat upcross above the same frozen line is spent, not a replacement entry.
 rr,rf=next((r,f) for r,f in zip(rows,ff) if f['first_recovery_event']=='True');j=ix[pd.Timestamp(rr['observed_through'])];line=float(rf['watch_failed_line']);parent=float(rf['watch_parent_low']);gap=line-parent
 failed=bars.copy();failed.loc[j-1,'Open']=float(failed.loc[j-1,'Close'])+.01
 cap_close=float(failed.loc[j,'Close']);high=cap_close*1.03
 failed.loc[j+1,['Open','High','Low','Close']]=[high,high+.2,high-.1,high+.1]
 below=line-gap/4;above=line+gap/4
 failed.loc[j+2,['Open','High','Low','Close']]=[below-.01,below+.05,below-.05,below]
 failed.loc[j+3,['Open','High','Low','Close']]=[above-.01,above+.05,above-.05,above]
 real_failed=replay('C0330',failed);fr,ffail=facts(real_failed)
 first=next(f for r,f in zip(fr,ffail) if pd.Timestamp(r['observed_through'])==ends[j]);second=next(f for r,f in zip(fr,ffail) if pd.Timestamp(r['observed_through'])==ends[j+3])
 assert first['first_recovery_event']=='True' and first['e0_priority_on_recovery']=='True' and first['entry_origin']=='E0' and first['watch_spent']=='True'
 assert second['held']=='False' and second['watch_active']=='True' and second['watch_spent']=='True' and second['first_recovery_event']=='False' and second['entry_signal']=='False'
 assert any(o['side']=='BUY' and pd.Timestamp(o['valid_start'])==starts[j+1] and o['status']!='FILLED' for o in real_failed.orders.to_dict('records'))
 return {'accounts':out,'off_old_source_six_economic_tables':equivalent,'real_blocked_sell_parent_cancel_no_resurrection':True,'real_first_recovery_E0_priority_failed_BUY_no_second_cross':True}


def main():
 direct=boundaries();public=public_synthetic()
 save(WORK/'others/precheck.json',{'status':'PASS','strategy_sha256':digest(WORK/'src/strategy.py'),'precheck_sha256':digest(WORK/'src/precheck.py'),'direct_boundaries':direct,'public_synthetic':public,'formal_account_compute':0,'new_return_labels':0})
 print('PUBLIC_PARENT_RECOVERY_STATE_PRECHECK_PASS',flush=True)

if __name__=='__main__':main()
