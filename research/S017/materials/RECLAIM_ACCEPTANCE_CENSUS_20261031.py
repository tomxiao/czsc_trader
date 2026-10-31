import json,statistics as st,math
from pathlib import Path
from hashlib import sha256
from decimal import Decimal,ROUND_FLOOR
import pandas as pd
from trading_execution_engine import OrderSpec,resolve_fill
from czsc_trader.research_tools import EvidenceRef
ROOT=Path(__file__).resolve().parents[3];PARENT=ROOT/'research/S017/materials/M005_ALL_TRAINING_SIGNALS_20261031.json';prior=json.loads(PARENT.read_bytes());events=prior['event_rows'];record=json.loads((ROOT/'research/S017/experiments/EX048_20261031/others/accounts.json').read_bytes())['C0098'];ref=EvidenceRef.from_dict(record['evidence']);path=ref.resolve(ROOT);assert sha256(path.read_bytes()).hexdigest()==ref.sha256;env=json.loads(path.read_bytes());r=env['input_ref'];raw=(path.parent/(r['sha256']+'.json')).read_bytes();assert sha256(raw).hexdigest()==r['sha256'];bars=pd.DataFrame(json.loads(raw)['products']['bars']);bars['Date']=pd.to_datetime(bars.Date,utc=True);bars['BarStart']=pd.to_datetime(bars.BarStart,utc=True);assert bars.BarStart.min().date().isoformat()>='2023-11-01' and bars.BarStart.max().date().isoformat()<='2025-12-31'
H=(3,13,26,65,130);direct=[];retest=[];pending=None;replaced=cancelled=unfilled=0
for e in events:
 i=e['index'];t=bars.iloc[i]
 if e['m005']:
  if t.Close>t.Open:direct.append({**e,'anchor_index':i,'original_support':min(float(bars.Low.iloc[i-1]),float(t.Low))})
  replaced+=pending is not None;pending={'index':i,'R':float(bars.High.iloc[i-1]),'S0':min(float(bars.Low.iloc[i-1]),float(t.Low))};continue
 if pending:
  if t.Close<pending['S0']:cancelled+=1;pending=None
  elif t.Low<=pending['R'] and t.Close>pending['R'] and t.Close>t.Open:
   q=bars.iloc[i+1];limit=float((Decimal(str(t.Close))*Decimal('1.01')/Decimal('.01')).to_integral_value(rounding=ROUND_FLOOR)*Decimal('.01'));f=resolve_fill(OrderSpec('BUY','LIMIT',1,limit),session_open=float(q.Open),session_time=q.BarStart.to_pydatetime(),intraday_touches=((q.Date.to_pydatetime(),float(q.Low)),),inclusive_touch=False)
   retest.append({'index':i,'anchor_index':pending['index'],'signal_at':t.Date.isoformat(),'filled':bool(f.filled),'entry_price':f.price,'original_support':pending['S0'],'retest_low':float(t.Low),'R':pending['R']});unfilled+=not f.filled
   if f.filled:pending=None

def stats(seq):
 out={}
 for n in H:
  values=[float(bars.Open.iloc[e['index']+n+1])*.999/(e['entry_price']*1.001)-1 for e in seq if e['filled'] and e['index']+n+1<len(bars)]
  out[str(n)]={'population':len(seq),'filled_mature':len(values),'unmature':sum(e['index']+n+1>=len(bars) for e in seq),'mean':st.mean(values) if values else None,'median':st.median(values) if values else None,'positive_fraction':st.mean(v>0 for v in values) if values else None}
 return out
out={'status':'PASS','source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),'parent_sha256':sha256(PARENT.read_bytes()).hexdigest(),'input_sha256':r['sha256'],'training':['2024-01-02','2025-12-31'],'horizons_predeclared':H,'m005_population':sum(e['m005'] for e in events),'bullish_m005':stats(direct),'retest_opportunity_flow':stats(retest),'retest_state':{'replaced':replaced,'cancelled':cancelled,'unfilled':unfilled,'pending_at_end':pending},'retest_low_below_original':sum(e['retest_low']<e['original_support'] for e in retest),'direct_rows':direct,'retest_rows':retest,'limitations':'Unit independent opportunity flow ignoring account capital/holding. Retest pending starts only on a legal training M005, new M005 replaces/no samebar buy; strict close<S0 cancels; every subsequent Low<=R/Close>R/Close>Open triggers next-interval public unit fill; success consumes pending, failure retains and requires fresh confirmation. No held-state simulation, so not raw formal entry count/economic account. Fees .001 both sides, downward .01 tick, 1% limit strict Low touch, n held bars then next open; tail immature excluded, no2026. Events can overlap. Direct labels reuse verified prices, retest prices freshly resolved. No optimal horizon selection.'}
Path(__file__).with_suffix('.json').write_bytes((json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode());print(json.dumps({k:v for k,v in out.items() if k not in ('direct_rows','retest_rows')},ensure_ascii=False))
