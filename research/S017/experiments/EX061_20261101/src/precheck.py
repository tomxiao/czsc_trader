"""Causal C/frozen repair state boundaries and actual public execution, synthetic only."""
from datetime import date,datetime,timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import json
import numpy as np
import pandas as pd
from dataflows import BarFrequency,TradingSession,TimeInterval
from strategy_runtime import PreparedReplay,run_replay,ReadyValue,StateRecord
from trading_execution_engine import PortfolioHistoricalExecutor
from common import WORK,SPEC,candidate,save,digest
from strategy import step,OUTPUTS


def main():
 zone=ZoneInfo('America/New_York');current=datetime(2019,3,4,11,tzinfo=zone);entry=current-timedelta(hours=1)
 v=dict(close=92.,low=91.,previous_close=90.,previous_high=91.,previous_low=89.,previous_mean65=100.,previous_atr13=5.)
 def rec(**kwargs):
  vals=dict(signal_at=current-timedelta(days=200),frozen_target=100.,initial_support=89.,last_completed_at=current-timedelta(minutes=30),exit_due=False,exit_reason='NONE');vals.update(kwargs);return StateRecord(tuple(vals.items()))
 def call(state=None,cost=95.,qty=1):
  ctx=SimpleNamespace(parameters={'policy':'FROZEN_CENTER_REPAIR'},events=(),
   features=SimpleNamespace(get=lambda k:ReadyValue(v[k])),
   portfolio=SimpleNamespace(quantity=qty if state is not None else 0,cash=0. if state is not None else 100000.,reference_price_scale=1.,cycle_entry=entry if state is not None else None,cycle_cost=cost if state is not None else 0.),
   history=SimpleNamespace(last=lambda:{'Date':current}))
  return step(ctx,SimpleNamespace(cycle=None if state is None else SimpleNamespace(entry_at=entry,values=state)))
 def values(result):return dict(result.cycle_values.values)
 a=call();assert a.decision.target==1 and values(a)['frozen_target']==100. and values(a)['initial_support']==89.
 v['previous_close']=90.00001;assert call().decision.target==0,'Deep equality <= only';v['previous_close']=90.
 v['close']=91.;assert call().decision.target==0,'Reclaim equality rejects'
 v['close']=100.;assert call().decision.target==0,'Already at target is outside repair domain'
 v['close']=100.01;assert call().decision.target==0;v['close']=92.
 assert call(rec()).decision.target==1,'No200day cap'
 v['close']=89.;assert call(rec()).decision.target==1,'S0 equality holds'
 v['close']=88.99;assert values(call(rec()))['exit_reason']=='INITIAL_STRUCTURE_FAILED'
 v['close']=100.;assert values(call(rec()))['exit_reason']=='TARGET_REACHED'
 v['previous_mean65']=70.;assert values(call(rec()))['frozen_target']==100.,'New mean cannot reset target'
 v['close']=95.;assert call(rec(exit_due=True,exit_reason='TARGET_REACHED')).decision.target==0,'Due cannot reverse'
 assert call(rec(),cost=101.).decision.target==1,'Negative estimated target net space does not add entry/exit gate'
 v['low']=80.;assert call(rec()).decision.target==1,'Intrabar low crossing alone cannot trigger close stop'
 v.update(close=102.,low=101.);assert values(call(rec(),cost=103.))['exit_reason']=='TARGET_REACHED','Above-target actual cost still target exits, not guaranteed profit'
 # Public replay with forced deep reclaim and true interval-touch BUY.
 days=[];d=date(2019,1,2)
 while len(days)<50:
  if d.weekday()<5:days.append(d)
  d+=timedelta(days=1)
 sessions=tuple(TradingSession(x,str(zone),(TimeInterval(datetime(x.year,x.month,x.day,9,30,tzinfo=zone),datetime(x.year,x.month,x.day,16,tzinfo=zone)),)) for x in days)
 periods=[p for s in sessions for p in s.bars(BarFrequency.M30)]
 starts=pd.DatetimeIndex([p.start for p in periods]).tz_convert('UTC');ends=pd.DatetimeIndex([p.end for p in periods]).tz_convert('UTC')
 i=np.arange(len(periods));prices=100.+.02*i+.5*np.sin(i/8)
 bars=pd.DataFrame({'BarStart':starts,'Date':ends,'AvailableDate':ends,'Open':prices-.03,'High':prices+.15,'Low':prices-.15,'Close':prices,'Volume':1000000.,'Amount':prices*1000000.})
 for j in (273,330,410,490,570):
  bars.loc[j,['Open','High','Low','Close']]=[92.,92.2,89.8,90.]
  bars.loc[j+1,['Open','High','Low','Close']]=[91.,93.2,90.8,93.]
  bars.loc[j+2,['Open','High','Low','Close']]=[95.,96.,92.,94.]
  bars.loc[j+3,['Open','High','Low','Close']]=[94.,96.,93.,95.]
 # Force a real structure failure before later recovery.
 bars.loc[333,['Open','High','Low','Close']]=[88.,89.,87.,88.]
 # Entry interval traverses both frozen levels, but its Close remains inside.
 bars.loc[275,['High','Low']]=[200.,88.]
 constraints=pd.DataFrame({'Date':starts,'AvailableDate':starts,'QuantityStep':1,'PriceTick':.01,'Tradable':True,'PriceLimitPolicy':'EXPLICIT_UNBOUNDED','PriceLimitLower':None,'PriceLimitUpper':None,'BuySellableAt':starts,'SettlementAt':starts,'SellRemainderPolicy':'STRICT_STEP'})
 actions=pd.DataFrame([{'Date':starts[0],'AvailableDate':starts[0],'EventId':'none','Kind':'NONE','Ratio':1.,'CashPerShare':0.,'PayAt':None}])
 calendar=pd.DataFrame({'Date':[s.segments[0].start for s in sessions],'AvailableDate':[s.segments[0].start for s in sessions],'SessionDate':[s.session_date.isoformat() for s in sessions]})
 def replay(frame):
  c=candidate('C0321');p=PreparedReplay.from_frames(frame,constraints,c.definition.feature_graph,frequency=BarFrequency.M30,timezone=str(zone),sessions=calendar,trading_sessions=sessions)
  e=PortfolioHistoricalExecutor(specification=SPEC,initial_cash=100000.,fee_rate=.001,actions=actions,price_basis='RAW')
  return run_replay(p,c,e,start=starts[274].to_pydatetime(),end=ends[-1].to_pydatetime(),fee_rate=.001).execution_result
 base=replay(bars);changed=bars.copy();changed.loc[520:,['Open','High','Low','Close']]*=1.7
 future=replay(changed)
 for table,field in {'decisions':'decision_at','orders':'valid_start','fills':'interval_start','account_points':'time','account_daily':'time','trades':'exit_at'}.items():
  aa,bb=getattr(base,table),getattr(future,table)
  def prefix(f):
   f=f[pd.to_datetime(f[field],utc=True)<starts[520]];return f.drop(columns=[c for c in f if c.endswith('_id')]).to_json(orient='records',date_format='iso',double_precision=15)
  assert prefix(aa)==prefix(bb),'Future suffix affects '+table
 rows=json.loads(base.decisions.to_json(orient='records',date_format='iso'));facts=[{x['key']:x['text'] for x in r['explanation']['basis']} for r in rows]
 first=next(f for f in base.fills.to_dict('records') if f['side']=='BUY');assert str(first['time_precision']).endswith('BAR_INTERVAL') and pd.Timestamp(first['interval_start'])==starts[275]
 assert pd.Timestamp(first['executed_at'])==ends[275]
 orders={o['order_id']:o for o in base.orders.to_dict('records')};decisions={r['decision_id']:r for r in rows}
 source=decisions[orders[first['order_id']]['decision_id']];sf={x['key']:x['text'] for x in source['explanation']['basis']}
 sell=next(f for f in base.fills.to_dict('records') if f['side']=='SELL')
 inherited=[]
 for row,f in zip(rows,facts):
  if f['held']=='True' and pd.Timestamp(row['decision_at'])<=pd.Timestamp(sell['interval_start']):
   assert float(f['frozen_target'])==float(sf['frozen_target']) and float(f['initial_support'])==float(sf['initial_support'])
   assert pd.Timestamp(f['signal_at'])==pd.Timestamp(source['observed_through']);inherited.append(f)
 assert inherited and inherited[0]['exit_due']=='False','Actual interval high/low cross cannot trigger when completed close stays inside'
 reasons={f['exit_trigger'] for f in facts};assert 'TARGET_REACHED' in reasons and 'INITIAL_STRUCTURE_FAILED' in reasons
 # Recompute every raw C and frozen-domain flag from synthetic completed bars.
 tr=[None]+[max(bars.High.iloc[j]-bars.Low.iloc[j],abs(bars.High.iloc[j]-bars.Close.iloc[j-1]),abs(bars.Low.iloc[j]-bars.Close.iloc[j-1])) for j in range(1,len(bars))]
 ix={pd.Timestamp(t):j for j,t in enumerate(bars.Date)}
 for row,f in zip(rows,facts):
  j=ix[pd.Timestamp(row['observed_through'])];mean=sum(bars.Close.iloc[j-65:j])/65;atr=sum(tr[j-13:j])/13
  raw=bars.Close.iloc[j-1]<=mean-2*atr and bars.Close.iloc[j]>bars.High.iloc[j-1]
  assert (f['raw_c']=='True')==bool(raw) and abs(float(f['previous_mean65'])-mean)<1e-9 and abs(float(f['previous_atr13'])-atr)<1e-9
  assert (f['entry_signal']=='True')==bool(raw and bars.Close.iloc[j]<mean)
 failed=bars.copy();failed.loc[275,['Open','High','Low','Close']]=[95.,96.,94.5,95.]
 bad=replay(failed);bf=next(f for f in bad.fills.to_dict('records') if f['side']=='BUY');assert pd.Timestamp(bf['interval_start'])>starts[275]
 before=[r for r in json.loads(bad.decisions.to_json(orient='records',date_format='iso')) if pd.Timestamp(r['decision_at'])<pd.Timestamp(bf['interval_start'])]
 assert before and all({f['key']:f['text'] for f in r['explanation']['basis']}['cycle_present']=='False' for r in before)
 above=bars.copy();goal=float(bars.Close.iloc[274-65:274].mean());signal_close=goal-.1
 above.loc[274,['Open','High','Low','Close']]=[signal_close-.1,signal_close+.1,90.8,signal_close]
 above.loc[275,['Open','High','Low','Close']]=[goal+.05,goal+.2,goal,goal+.1]
 over=replay(above);ob=next(f for f in over.fills.to_dict('records') if f['side']=='BUY')
 assert pd.Timestamp(ob['interval_start'])==starts[275] and float(ob['price'])>=goal,'Actual above-target buy retained by original cap'
 ofacts=[{x['key']:x['text'] for x in r['explanation']['basis']} for r in json.loads(over.decisions.to_json(orient='records',date_format='iso'))]
 oh=next(f for f in ofacts if f['held']=='True');assert abs(float(oh['frozen_target'])-goal)<1e-9 and oh['exit_trigger']=='TARGET_REACHED' and float(oh['target_estimated_net_space'])<0,'Above-target fill keeps original target and can have negative net space'
 avg=len(base.decisions.to_json(orient='records',date_format='iso').encode())/len(rows);assert avg<15000
 save(WORK/'others/precheck.json',{'status':'PASS','strategy_sha256':digest(WORK/'src/strategy.py'),'precheck_sha256':digest(WORK/'src/precheck.py'),'synthetic_only':True,'checked_C_rows':len(rows),'price_future_suffix':'PASS','real_first_buy_precision':'BAR_INTERVAL','real_failed_buy_cycle_absent':True,'real_order_source_frozen_levels_checked_held_decisions':len(inherited),'real_interval_high_low_cross_no_close_exit':True,'real_above_target_buy_retained':True,'actual_exit_reasons':sorted(reasons),'average_decision_bytes':avg,'direct_boundaries':['priorATRlag1/meanlag1 independent scalar','deep<= equality','strict reclaim/room','target>=/stop<','frozen target despite changing mean','no200daycap','negative net target space not a gate','real above-target BUY still target exit with negative net space','intrabar low/high alone not close exit','blocked due never reverses'],'account_compute':0,'formal_SE':0})
 print('PUBLIC_FROZEN_REPAIR_PRECHECK_PASS',flush=True)

if __name__=='__main__':main()
