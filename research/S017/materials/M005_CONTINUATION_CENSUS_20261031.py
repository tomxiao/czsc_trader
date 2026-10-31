"""Reuse known entries/costs; fixed legacy horizon census, never select a strategy period."""
import json,math,statistics as st
from pathlib import Path
from hashlib import sha256
from collections import defaultdict
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
ROOT=Path(__file__).resolve().parents[3];SOURCE=ROOT/'research/S017/materials/M005_ALL_TRAINING_SIGNALS_20261031.json';prior=json.loads(SOURCE.read_bytes());assert sha256(SOURCE.with_suffix('.py').read_bytes()).hexdigest()==prior['analysis_source_sha256'];rows=prior['event_rows']
record=json.loads((ROOT/'research/S017/experiments/EX042_20261031/others/accounts.json').read_bytes())['C0082'];ref=EvidenceRef.from_dict(record['evidence']);p=ref.resolve(ROOT);assert sha256(p.read_bytes()).hexdigest()==ref.sha256;envelope=json.loads(p.read_bytes());r=envelope['input_ref'];raw=(p.parent/(r['sha256']+'.json')).read_bytes();assert sha256(raw).hexdigest()==r['sha256'];data=json.loads(raw)
bars=pd.DataFrame(data['products']['bars']);bars['Date']=pd.to_datetime(bars.Date,utc=True);bars['BarStart']=pd.to_datetime(bars.BarStart,utc=True);assert bars.BarStart.min().tz_convert('America/New_York').date().isoformat()>='2023-11-01' and bars.BarStart.max().tz_convert('America/New_York').date().isoformat()<='2025-12-31'
H=(3,13,26,65,130);labels={}
for event in rows:
 i=event['index'];assert bars.Date.iloc[i]==pd.Timestamp(event['signal_at']) and bars.BarStart.iloc[i+1]==pd.Timestamp(event['execution_start']);v={}
 for n in H:
  exit_index=i+n+1;mature=exit_index<len(bars);ret=None
  if mature and event['filled']:ret=float(bars.Open.iloc[exit_index])*.999/(event['entry_price']*1.001)-1
  v[str(n)]={'mature':mature,'return':ret}
 for n in (26,65):
  if event['return'+str(n)] is not None:assert math.isclose(v[str(n)]['return'],event['return'+str(n)],abs_tol=1e-12)
 labels[i]=v
signals=[e for e in rows if e['m005']];ordinary=[e for e in rows if not e['m005']]
def stats(events,n):
 values=[labels[e['index']][str(n)]['return'] for e in events if labels[e['index']][str(n)]['return'] is not None]
 return {'population':len(events),'mature':sum(labels[e['index']][str(n)]['mature'] for e in events),'unmature':sum(not labels[e['index']][str(n)]['mature'] for e in events),'filled_mature':len(values),'mean':st.mean(values) if values else None,'median':st.median(values) if values else None,'positive_fraction':st.mean(v>0 for v in values) if values else None}
result={'schema':'s017-m005-fixed-multiple-horizon-census/v1','status':'PASS','source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),'parent_signal_diagnostic_sha256':sha256(SOURCE.read_bytes()).hexdigest(),'source_account':record['evidence'],'source_input_sha256':r['sha256'],'horizons_predeclared':H,'training':['2024-01-02','2025-12-31'],'warmup':'2023-11-01 only indicator initialization','per_horizon':{},'scope':'All known legal M005 signals, including held signals, unit-event labels using previously verified next-interval1% limit/tick/strict fills and .1% each side; entry to n completed held bars then next interval open. No account, search, horizon recommendation or test access. New policies have financial support/pressure failure, not time exits.'}
for n in H:
 controls=defaultdict(list)
 for e in ordinary:
  value=labels[e['index']][str(n)]['return']
  if value is not None:controls[(e['year'],e['slot'],e['volatility_layer'])].append(value)
 differences=[];support=[]
 for e in signals:
  value=labels[e['index']][str(n)]['return']
  if value is None:continue
  c=controls[(e['year'],e['slot'],e['volatility_layer'])];support.append(len(c))
  if c:differences.append(value-st.mean(c))
 kept=[];occupied=-1
 for e in signals:
  if e['index']>occupied:kept.append(e);occupied=e['index']+n+1
 common=[e for e in signals if labels[e['index']]['130']['return'] is not None]
 result['per_horizon'][str(n)]={'all_signal':stats(signals,n),'ordinary_excludes_all_signals':stats(ordinary,n),'common130_mature_signal':stats(common,n),'chronological_planned_nonoverlap':stats(kept,n),'coarse_control':{'matched_signals':len(differences),'signal_denominator':len(support),'minimum_controls':min(support,default=0),'mean_difference':st.mean(differences) if differences else None},'years':{y:stats([e for e in signals if e['year']==y],n) for y in ('2024','2025')}}
result['limitations']='Horizon populations differ at training end; common130 cohort shown. Overlapping events/control reuse are not independent. Greedy nonoverlap uses only planned chronological reservation before filling/maturity, not an account. Ordinary coarse year/signal-slot/fixed1% prior volatility is descriptive, no causality/significance gate. Positive post-entry labels do not supply holding or exit logic; already-reclaimed prior High is not remaining profit.'
Path(__file__).with_suffix('.json').write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode());print(json.dumps({n:{'signal':v['all_signal'],'ordinary_mean':v['ordinary_excludes_all_signals']['mean'],'matched_difference':v['coarse_control']['mean_difference']} for n,v in result['per_horizon'].items()}))
