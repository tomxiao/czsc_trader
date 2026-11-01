"""Outcome-blind all-clock equivalence plus public synthetic execution boundaries."""
from datetime import date,datetime,timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import json
import pandas as pd
from common import ROOT,WORK,SPEC,PARAMETERS,read,save,digest,authenticate,candidate
from session_features import market_context
from strategy_runtime import DecisionPoint,PreparedReplay,run_replay
from dataflows import TimeInterval,TradingSession,BarFrequency
from trading_execution_engine import PortfolioHistoricalExecutor
from czsc_trader.research_tools.equity_replay import materialize_equity


def at(x):return datetime.fromisoformat(x.replace('Z','+00:00'))


def all_clock():
 record=read(ROOT/'research/S017/experiments/EX061_20261101/others/accounts.json')['C0321'];path=authenticate(record['evidence']);envelope=read(path)
 owned={(envelope[k]['kind'],envelope[k]['sha256']) for k in ('input_ref','candidate_ref','benchmark_ref')}
 def resolve(ref):
  if (ref['kind'],ref['sha256']) not in owned:raise ValueError('Unowned prior dependency')
  return (path.parent/(ref['sha256']+'.json')).read_bytes()
 payload=materialize_equity(path.read_bytes(),resolve).payload;inp=read(path.parent/(envelope['input_ref']['sha256']+'.json'))
 if envelope['input_ref']['sha256']!='2d2a98bfe9f04891e47cb6c938d0eb1b27bb28f41622f73aef010ae23d6d717c':raise ValueError('Current approved input only')
 bars=pd.DataFrame(inp['products']['bars'])
 for k in ('BarStart','Date'):bars[k]=pd.to_datetime(bars[k],utc=True)
 ix={x:i for i,x in enumerate(bars.Date)};sessions={s['session_date']:s for s in inp['data']['sessions']['metadata']['sessions']}
 expected=read(ROOT/'research/S017/experiments/EX064_20261101/others/features.json')
 lock=read(ROOT/'research/S017/experiments/EX064_20261101/others/census_pre_run.json')
 if digest(ROOT/'research/S017/experiments/EX064_20261101/others/features.json')!=lock['features']['sha256']:raise ValueError('Locked feature bytes differ')
 expected_rows={pd.Timestamp(r['signal_at']):r for r in expected['feature_rows']}
 counts={'UP_CROSS':0,'UP_ACCEPT':0};out=[];crossday=0
 for d in payload['runs']['candidate']['decisions']:
  observed=pd.Timestamp(d['observed_through']);i=ix[observed]
  point=DecisionPoint(at(d['observed_through']),at(d['decision_at']),TimeInterval(at(d['execution_start']),at(d['execution_end'])))
  key=point.execution_interval.start.astimezone(ZoneInfo('America/New_York')).date().isoformat();ss=sessions[key]
  session=TradingSession(date.fromisoformat(key),ss['timezone'],tuple(TimeInterval(at(x['start']),at(x['end'])) for x in ss['segments']))
  context=market_context(SimpleNamespace(to_frame=lambda tail:bars.iloc[:i+1].tail(tail)),point,session)
  e=expected_rows.get(observed)
  for name,flag in (('UP_CROSS','up_cross'),('UP_ACCEPT','up_accept')):
   wanted=False if e is None else e[name]
   if context[flag]!=wanted:raise ValueError(('Market-first flag differs',d['observed_through'],name,context[flag],wanted))
   counts[name]+=int(context[flag])
  if context['observed_day']!=key:
   crossday+=1
   if context['up_cross'] or context['up_accept']:raise ValueError('Cross-day old observation cannot enter')
  if e and abs(context['setup_reference_high']-e['prior_session_high'])>1e-10:raise ValueError('Prior complete H differs')
  out.append({'observed_through':d['observed_through'],'execution_start':d['execution_start'],**context})
 assert len(out)==6490 and counts=={'UP_CROSS':113,'UP_ACCEPT':83}
 save(WORK/'others/all_clock_features_precheck.json',{'status':'PASS','helper_sha256':digest(WORK/'src/session_features.py'),'rows':len(out),'source_account':record['evidence'],'input_ref':envelope['input_ref'],'locked_feature_reference':read(ROOT/'research/S017/experiments/EX064_20261101/others/census_pre_run.json')['features'],'market_signal_counts':counts,'crossday_observations_no_entry':crossday,'first_warm_observation_flags':{k:out[0][k] for k in ('up_cross','up_accept')},'last_observation':out[-1],'new_accounts':0,'new_labels':0})
 return counts


def synthetic():
 zone=ZoneInfo('America/New_York');days=[];d=date(2019,1,2)
 while len(days)<50:
  if d.weekday()<5:days.append(d)
  d+=timedelta(days=1)
 sessions=tuple(TradingSession(x,str(zone),(TimeInterval(datetime.combine(x,datetime.min.time(),zone).replace(hour=9,minute=30),datetime.combine(x,datetime.min.time(),zone).replace(hour=13 if x==days[30] else 16)),)) for x in days)
 periods=[];records=[];prior=100.;dayrefs={}
 for k,s in enumerate(sessions):
  periods.extend(s.bars(BarFrequency.M30));dayrefs[k]=prior
  profile=[-1.,-.75,-.5,-.25,0.,.25,.5,.75,.65,1.,1.25,.3,1.5]
  local=[]
  for j,p in enumerate(s.bars(BarFrequency.M30)):
   c=prior+profile[j]-(10. if k in (26,39) else 0.);o=c-.04;hi=max(o,c)+.1;lo=min(o,c)-.1
   if j==5:lo=prior-.1 if k not in (26,39) else lo
   if k==22 and j in (6,7):o=prior+3.;hi=prior+3.2;lo=c-.1
   local.append({'BarStart':p.start,'Date':p.end,'AvailableDate':p.end,'Open':o,'High':hi,'Low':lo,'Close':c,'Volume':1000000.,'Amount':c*1000000.})
  records.extend(local);prior=max(x['High'] for x in local)
 bars=pd.DataFrame(records)
 for col in ('BarStart','Date','AvailableDate'):bars[col]=pd.to_datetime(bars[col],utc=True)
 starts=pd.DatetimeIndex(bars.BarStart);ends=pd.DatetimeIndex(bars.Date);begin=next(i for i,p in enumerate(periods) if p.start.date()==days[22]);cut=next(i for i,p in enumerate(periods) if p.start.date()==days[36])
 constraints=pd.DataFrame({'Date':starts,'AvailableDate':starts,'QuantityStep':1,'PriceTick':.01,'Tradable':True,'PriceLimitPolicy':'EXPLICIT_UNBOUNDED','PriceLimitLower':None,'PriceLimitUpper':None,'BuySellableAt':starts,'SettlementAt':starts,'SellRemainderPolicy':'STRICT_STEP'})
 actions=pd.DataFrame([{'Date':starts[0],'AvailableDate':starts[0],'EventId':'none','Kind':'NONE','Ratio':1.,'CashPerShare':0.,'PayAt':None}])
 calendar=pd.DataFrame({'Date':[s.segments[0].start for s in sessions],'AvailableDate':[s.segments[0].start for s in sessions],'SessionDate':[s.session_date.isoformat() for s in sessions]})
 def replay(key,frame):
  c=candidate(key);p=PreparedReplay.from_frames(frame,constraints,c.definition.feature_graph,frequency=BarFrequency.M30,timezone=str(zone),sessions=calendar,trading_sessions=sessions)
  executor=PortfolioHistoricalExecutor(specification=SPEC,initial_cash=100000.,fee_rate=.001,actions=actions,price_basis='RAW')
  return run_replay(p,c,executor,start=starts[begin].to_pydatetime(),end=ends[-1].to_pydatetime(),fee_rate=.001).execution_result
 def facts(result):
  rows=json.loads(result.decisions.to_json(orient='records',date_format='iso'));return rows,[{x['key']:x['text'] for x in r['explanation']['basis']} for r in rows]
 changed=bars.copy();changed.loc[cut:,['Open','High','Low','Close']]*=1.8;out={};base_results={};market_sets={}
 economic={'decisions':'decision_at','orders':'valid_start','fills':'interval_start','account_points':'time','account_daily':'time','trades':'exit_at'}
 for key in PARAMETERS:
  base=replay(key,bars);future=replay(key,changed);base_results[key]=base
  for table,field in economic.items():
   def prefix(f):
    f=f[pd.to_datetime(f[field],utc=True)<starts[cut]];return f.drop(columns=[c for c in f if c.endswith('_id')]).to_json(orient='records',date_format='iso',double_precision=15)
   assert prefix(getattr(base,table))==prefix(getattr(future,table)),key+' future prefix'
  rows,ff=facts(base);buy=next(x for x in base.fills.to_dict('records') if x['side']=='BUY');assert str(buy['time_precision']).endswith('BAR_INTERVAL')
  byid={r['decision_id']:r for r in rows};orders={r['order_id']:r for r in base.orders.to_dict('records')};source=byid[orders[buy['order_id']]['decision_id']];sf={x['key']:x['text'] for x in source['explanation']['basis']}
  first=next(f for f in ff if f['held']=='True');assert float(first['initial_reference_high'])==float(sf['initial_reference_high']) and pd.Timestamp(first['signal_at'])==pd.Timestamp(source['observed_through'])
  original={}
  for b in base.fills.to_dict('records'):
   if b['side']=='BUY':
    sr=byid[orders[b['order_id']]['decision_id']];z={x['key']:x['text'] for x in sr['explanation']['basis']};original[pd.Timestamp(sr['observed_through'])]=float(z['initial_reference_high'])
  changed_reference=0
  for f in ff:
   if f['held']=='True':
    assert float(f['initial_reference_high'])==original[pd.Timestamp(f['signal_at'])],'Every held cycle keeps actual source H across day changes'
    changed_reference+=int(float(f['setup_reference_high'])!=float(f['initial_reference_high']))
  if PARAMETERS[key]['support']=='STATIC_H':assert changed_reference>0
  market_sets[key]={name:[r['observed_through'] for r,f in zip(rows,ff) if f[name]=='True'] for name in ('up_cross','up_accept')}
  assert float(first['peak'])==0.,'Whole actual BAR_INTERVAL entry excluded'
  assert ff[0]['entry_signal']=='False' and ff[0]['same_day_next_execution']=='False','First warm observation not new entry'
  assert any(f['held']=='True' and f['same_day_next_execution']=='False' and f['exit_trigger']!='NONE' for f in ff) or any(f['held']=='True' and f['same_day_next_execution']=='False' for f in ff),'Overnight holder is evaluated,not automatically flat'
  assert all(f['entry_signal']=='False' for f in ff if f['same_day_next_execution']=='False')
  if PARAMETERS[key]['support']=='ACCEPTED':assert any(f['candidate_accepted']=='True' for f in ff),'Real accepted raise required'
  avg=len(base.decisions.to_json(orient='records',date_format='iso').encode())/len(rows);assert avg<15000
  out[key]={'fills':len(base.fills),'market_events':sum(f['entry_signal']=='True' for f in ff),'market_events_while_held':sum(f['entry_signal']=='True' and f['held']=='True' for f in ff),'actual_accepted':sum(f['candidate_accepted']=='True' for f in ff),'future_prefix':'PASS','first_buy_precision':str(buy['time_precision']),'every_actual_source_H_inherited':True,'held_current_reference_differs_without_reset':changed_reference,'average_decision_bytes':avg}
 assert all(v==market_sets['C0325'] for v in market_sets.values()),'Market-first time sets independent of held/exit policy'
 # Actual failed first BUY cannot buy a later repeated predicate in that session.
 failed_cases={}
 for key,slot in (('C0325',6),('C0327',7)):
  frame=bars.copy();j=begin+slot;h=dayrefs[22];frame.loc[j,['Open','High','Low','Close']]=[h+3.,h+3.2,h+2.,h+2.5]
  result=replay(key,frame);rows,ff=facts(result);actual=next(x for x in result.fills.to_dict('records') if x['side']=='BUY')
  assert pd.Timestamp(actual['interval_start']).astimezone(zone).date()>days[22]
  rejected=[r for r in rows if pd.Timestamp(r['decision_at']).astimezone(zone).date()==days[22]]
  assert sum({x['key']:x['text'] for x in r['explanation']['basis']}['entry_signal']=='True' for r in rejected)==1
  assert all({x['key']:x['text'] for x in r['explanation']['basis']}['cycle_present']=='False' for r in rejected)
  failed_cases[key]={'first_buy_unfilled_no_same_day_replacement':True,'first_actual_buy':str(actual['interval_start'])}
 # Open gap below original H remains a legitimate actual BUY, not a hidden filter.
 below={}
 for key,slot in (('C0325',6),('C0327',7)):
  frame=bars.copy();j=begin+slot;h=dayrefs[22];frame.loc[j,['Open','High','Low','Close']]=[h-.2,h+1.,h-.4,h]
  result=replay(key,frame);buy=next(x for x in result.fills.to_dict('records') if x['side']=='BUY');assert float(buy['price'])<h
  _,ff=facts(result);f=next(f for f in ff if f['held']=='True');assert float(f['initial_reference_high'])==h and f['exit_due']=='False'
  below[key]={'actual_fill_below_frozen_H_retained':True,'completed_close_equals_H_holds':True}
 return {'accounts':out,'failed_buy':failed_cases,'below_H_buy':below,'halfday_and_DST_calendar':True}


def main():
 counts=all_clock();public=synthetic()
 save(WORK/'others/precheck.json',{'status':'PASS','strategy_sha256':digest(WORK/'src/strategy.py'),'helper_sha256':digest(WORK/'src/session_features.py'),'precheck_sha256':digest(WORK/'src/precheck.py'),'all_clock_market_counts':counts,'public_synthetic':public,'formal_account_compute':0,'new_future_labels':0})
 print('ALL_CLOCK_AND_PUBLIC_SESSION_STATE_PRECHECK_PASS',counts,flush=True)

if __name__=='__main__':main()
