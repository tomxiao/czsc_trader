"""Training-only all-signal labels; public fill rule, descriptive coarse controls."""
import json,math,statistics as st
from decimal import Decimal,ROUND_FLOOR
from pathlib import Path
from hashlib import sha256
from collections import Counter
from zoneinfo import ZoneInfo
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from trading_execution_engine import OrderSpec,resolve_fill
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).with_suffix('.json');Z=ZoneInfo('America/New_York')
record=json.loads((ROOT/'research/S017/experiments/EX040_20261031/others/accounts.json').read_bytes())['C0077'];ref=EvidenceRef.from_dict(record['evidence']);path=ref.resolve(ROOT);raw=path.read_bytes();assert sha256(raw).hexdigest()==ref.sha256;env=json.loads(raw)
def dependency(name):
 r=env[name];raw=(path.parent/(r['sha256']+'.json')).read_bytes();assert sha256(raw).hexdigest()==r['sha256'];return json.loads(raw)
inputs=dependency('input_ref');run=dependency('candidate_ref')['run']
# The retained asset is unchanged; only this approved slice is cached/processed.
bars=pd.DataFrame([r for r in inputs['products']['bars'] if '2023-11-01'<=r['BarStart'][:10]<='2025-12-31'])
assert set(bars.BarStatus)=={'OBSERVED'} and not bars.ExecutionBlocked.any()
for k in ('Date','BarStart','AvailableDate'):bars[k]=pd.to_datetime(bars[k],utc=True)
bars['local_date']=bars.BarStart.dt.tz_convert(Z).dt.date.astype(str);bars['slot']=bars.BarStart.dt.tz_convert(Z).dt.strftime('%H:%M');assert not bars.duplicated(['local_date','slot']).any()
tr=pd.concat([bars.High-bars.Low,(bars.High-bars.Close.shift()).abs(),(bars.Low-bars.Close.shift()).abs()],axis=1).max(axis=1);tr.iloc[0]=float('nan');atr=tr.rolling(13,min_periods=13).mean()
slotmedian=bars.groupby('slot').Volume.transform(lambda s:s.shift().rolling(20,min_periods=20).median())
signal=(bars.Close.shift()<bars.Open.shift())&(bars.Close>bars.High.shift())&(bars.Volume.shift()>=1.5*slotmedian.shift())&(tr.shift()<=atr.shift(2));bars['signal']=signal
old={d['observed_through']:d for d in run['decisions'] if '2024-01-02'<=d['execution_start'][:10]<='2025-12-31'}
matched=0
for i in range(len(bars)-1):
 if not '2024-01-02'<=bars.iloc[i+1].local_date<='2025-12-31':continue
 stamp=bars.iloc[i].Date.strftime('%Y-%m-%dT%H:%M:%S.%fZ');d=old[stamp];facts={v['key']:v['text'] for v in d['explanation']['basis']};assert bool(signal.iloc[i])==(facts['entry_signal']=='True');matched+=1
boundary_time=bars.iloc[0].BarStart.to_pydatetime()
assert resolve_fill(OrderSpec('BUY','LIMIT',1,100.),session_open=100.,session_time=boundary_time,intraday_touches=()).filled
assert not resolve_fill(OrderSpec('BUY','LIMIT',1,100.),session_open=101.,session_time=boundary_time,intraday_touches=((boundary_time,100.),),inclusive_touch=False).filled
assert resolve_fill(OrderSpec('BUY','LIMIT',1,100.),session_open=101.,session_time=boundary_time,intraday_touches=((boundary_time,99.99),),inclusive_touch=False).filled
rows=[];fill_checks=0;buy_by_start={f['interval_start']:f for f in run['fills'] if f['side']=='BUY'}
for i in range(len(bars)-1):
 t=bars.iloc[i];j=i+1;b=bars.iloc[j]
 if not '2024-01-02'<=b.local_date<='2025-12-31':continue
 limit=float((Decimal(str(t.Close))*Decimal('1.01')/Decimal('.01')).to_integral_value(rounding=ROUND_FLOOR)*Decimal('.01'))
 f=resolve_fill(OrderSpec('BUY','LIMIT',1,limit),session_open=float(b.Open),session_time=b.BarStart.to_pydatetime(),intraday_touches=((b.Date.to_pydatetime(),float(b.Low)),),inclusive_touch=False)
 mature=i+66<len(bars) and bars.iloc[i+66].local_date<='2025-12-31'
 row={'index':i,'signal_at':t.Date.isoformat(),'execution_start':b.BarStart.isoformat(),'year':b.local_date[:4],'slot':t.slot,'volatility_layer':'LE_1PCT' if atr.iloc[i-1]/bars.Close.iloc[i-1]<=.01 else 'GT_1PCT','m005':bool(signal.iloc[i]),'mature65':bool(mature),'filled':bool(f.filled),'limit':limit,'entry_price':f.price,'return65':None,'return26':None}
 if f.filled and mature:
  row['return65']=float(bars.iloc[i+66].Open)*.999/(f.price*1.001)-1;row['return26']=float(bars.iloc[i+27].Open)*.999/(f.price*1.001)-1
 stamp=b.BarStart.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
 if stamp in buy_by_start and row['m005']:
  actual=buy_by_start[stamp];assert f.filled and math.isclose(f.price,actual['price'],abs_tol=1e-10);fill_checks+=1
 rows.append(row)
def stats(seq):
 usable=[r for r in seq if r['mature65'] and r['filled']];returns=[r['return65'] for r in usable]
 return {'n_total':len(seq),'mature':sum(r['mature65'] for r in seq),'unmature':sum(not r['mature65'] for r in seq),'filled_mature':len(usable),'unfilled_mature':sum(r['mature65'] and not r['filled'] for r in seq),'mean65':st.mean(returns) if returns else None,'median65':st.median(returns) if returns else None,'mean26_on_same65_mature_population':st.mean(r['return26'] for r in usable) if usable else None,'win_rate65':st.mean(v>0 for v in returns) if returns else None,'years':{y:{'n':len(q:=[r for r in usable if r['year']==y]),'mean65':st.mean(r['return65'] for r in q) if q else None} for y in ('2024','2025')}}
signals=[r for r in rows if r['m005']];ordinary=[r for r in rows if not r['m005']];matched_results={}
for name,fields in [('year_slot',('year','slot')),('year_slot_volatility',('year','slot','volatility_layer'))]:
 groups={}
 for r in ordinary:
  if r['mature65'] and r['filled']:groups.setdefault(tuple(r[f] for f in fields),[]).append(r)
 paired=[];used=Counter();support=[]
 for r in signals:
  if not r['mature65'] or not r['filled']:continue
  controls=groups.get(tuple(r[f] for f in fields),[]);support.append(len(controls))
  if controls:
   paired.append({'signal_index':r['index'],'controls':len(controls),'signal_return':r['return65'],'ordinary_mean':st.mean(c['return65'] for c in controls),'difference':r['return65']-st.mean(c['return65'] for c in controls)})
   used.update(c['index'] for c in controls)
 matched_results[name]={'signal_denominator':len(support),'supported':len(paired),'unsupported':sum(n==0 for n in support),'support_min':min(support,default=0),'support_median':st.median(support) if support else None,'unique_controls':len(used),'total_control_assignments':sum(used.values()),'max_control_reuse':max(used.values(),default=0),'mean_signal65':st.mean(r['signal_return'] for r in paired) if paired else None,'mean_ordinary65':st.mean(r['ordinary_mean'] for r in paired) if paired else None,'mean_difference65':st.mean(r['difference'] for r in paired) if paired else None,'years':{y:{'n':len(q:=[r for r in paired if next(s for s in signals if s['index']==r['signal_index'])['year']==y]),'mean_difference65':st.mean(r['difference'] for r in q) if q else None} for y in ('2024','2025')},'pairs':paired}
by_start={r['execution_start']:r for r in rows};return_checks=0
for trade in run['trades']:
 if trade['status']!='CLOSED' or not '2024-01-02'<=trade['entry_at'][:10]<='2025-12-31':continue
 fill=next(f for f in run['fills'] if f['cycle_id']==trade['cycle_id'] and f['side']=='BUY');stamp=pd.Timestamp(fill['interval_start']).isoformat();event=by_start[stamp]
 assert math.isclose(event['return65'],trade['net_return'],abs_tol=1e-9);return_checks+=1
usable=[r for r in signals if r['mature65'] and r['filled']];kept=[];last_exit=-1
for r in usable:
 if r['index']+1>last_exit:kept.append(r);last_exit=r['index']+66
sessions=sorted({r['local_date'] for _,r in bars.iterrows() if '2024-01-02'<=r['local_date']<='2025-12-31'})
result={'schema':'s017-m005-all-training-signal-diagnostic/v1','status':'PASS','analysis_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),'source_evidence':record['evidence'],'source_dependencies':{k:env[k] for k in ('input_ref','candidate_ref')},'training':['2024-01-02','2025-12-31'],'warmup_start':'2023-11-01','actual_training_sessions':len(sessions),'signal_flags_compared':matched,'actual_buy_prices_compared':fill_checks,'actual_cycle_returns_compared':return_checks,'public_fill_boundary_checks':'PASS','all_m005_signals':stats(signals),'ordinary_excluding_all_m005':stats(ordinary),'matched':matched_results,'overlap':{'mature_filled_signal_events':len(usable),'greedy_nonoverlap65':stats(kept),'overlapping_consecutive_signal_pairs':sum(b['index']<=a['index']+66 for a,b in zip(usable,usable[1:]))},'warmup_signal_for_first_training_execution':sum(r['signal_at'][:10]<'2024-01-02' for r in signals),'event_rows':rows,'scope':'All legal decision/planned execution points in 2024-25, including prior warmup signal at first training execution. Equal-weight unit-event labels, not accounts or annualized returns. Next-bar limit uses downward .01 tick and public resolve_fill; 65 completed held bars then next-bar market open with .1% each side. Unmature labels excluded, never filled from 2026. Coarse year/slot and preset previous ATR/Close 1% layers are descriptive controls, reused and overlapping; no independence, causality or new signal gate. No test access, account replay, new experiment or parameter search.'}
OUT.write_bytes((json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode());print(json.dumps({k:result[k] for k in ('status','actual_training_sessions','signal_flags_compared','actual_buy_prices_compared','all_m005_signals','ordinary_excluding_all_m005','overlap')},ensure_ascii=False));print(json.dumps({k:{f:v for f,v in a.items() if f!='pairs'} for k,a in matched_results.items()},ensure_ascii=False))
