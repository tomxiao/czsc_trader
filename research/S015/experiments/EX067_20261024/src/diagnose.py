"""Authenticated state/ledger diagnostics; no new strategy accounts or fitted rules."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[key]='1'
import importlib.util
import json
from pathlib import Path
import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext,diagnose_accounts
from czsc_trader.research_tools import EvidenceRef,AccountRunRef,AccountDiagnosisRequest

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
HOME=Path(__file__).resolve().parents[1]; BASE=HOME.parent
def read(p):return json.loads(p.read_bytes())
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def mod(path,name):
 spec=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def stats(v):
 a=np.asarray(v,dtype=float); pos=a[a>0];neg=a[a<0]
 return dict(n=len(a),mean=float(a.mean()) if len(a) else None,net=float(a.sum()),profit=float(pos.sum()),loss=float(-neg.sum()),positive=int((a>0).sum()))

def main():
 assert not (HOME/'others/diagnosis.json').exists()
 for rel,ref in read(HOME/'others/protocol_refs.json').items():assert EvidenceRef.from_dict(ref).resolve(ROOT).read_bytes()==(ROOT/rel).read_bytes()
 study=mod(BASE/'EX051_20261024/src/study.py','study67');old,loaderref=study.loader();sources=old.sources();adj,raw,bars,rules,ids=old.inputs(sources)
 runtime=mod(BASE/'EX061_20261024/src/strategy_runtime/strategies/price_process.py','runtime67')
 audit=mod(BASE/'EX061_20261024/src/account_audit.py','audit67')
 fs={kind:runtime.causal_features(adj,raw,bars,3,kind) for kind in ('mean','median','daily_mid')}
 refs={'loader':loaderref.to_dict(),**{k:v.to_dict() for k,v in sources.items()}}
 eventref=EvidenceRef.from_dict(read(BASE/'EX026_20261023/others/delivery_validation.json')['materials']['events.csv'])
 refs['events']=eventref.to_dict();events=pd.read_csv(eventref.resolve(ROOT))
 opportunity=[]
 for kind,f in fs.items():
  z=f.reset_index();z['date']=z.date.dt.strftime('%Y-%m-%d')
  z['state']=np.where(z.center_gain>0,'up','nonup')+'_'+np.where(z.p<z.m,'below','above')
  joined=events.merge(z[['date','state','feature_ready']],on='date',validate='many_to_one');joined=joined[joined.feature_ready&joined.net.notna()]
  for (h,state),g in joined.groupby(['horizon','state']):
   for year in ('all','2025','2026'):
    q=g if year=='all' else g[g.date.str.startswith(year)]
    opportunity.append({'center':kind,'horizon':int(h),'state':state,'year':year,**stats(q.net),'entry':stats(q.entry_net.dropna())})
 states=[];accounts=[];repairs=[]
 for ex,cid in [('EX061_20261024','C6102'),('EX061_20261024','C6105'),('EX059_20261024','C5919'),('EX059_20261024','C5920'),('EX059_20261024','C5921'),('EX059_20261024','C5922')]:
  row=next(r for r in read(BASE/ex/'others/results.json')['rows'] if r['candidate_id']==cid);ref=EvidenceRef.from_dict(row['evidence']);refs[cid]=ref.to_dict();ev=read(ref.resolve(ROOT));run=next(r for r in ev['runs'] if r['window_id']=='full')
  diag=diagnose_accounts(RepositoryContext.discover(ROOT),AccountDiagnosisRequest(AccountRunRef(ref,audit.identity(run)),None,audit.WINDOWS['full']))
  assert diag.status.value not in ('INVALID_EVIDENCE','INCOMPARABLE')
  desc=audit.describe(run,row['runs']['full']);accounts.append({'candidate':cid,'public_diagnosis':diag.to_dict(),'description':desc})
  p={**row['parameters'],'rearm_mode':row['parameters'].get('rearm_mode','immediate' if row['parameters']['exit_mode']=='fixed' else 'positive_step')}
  f=fs[p['center_kind']];intent=runtime.intentions(f,p)
  intent['entry_anchor']=intent.m.where(intent.entry_signal.eq(1)).ffill()
  intent['signal_day']=intent.index.strftime('%Y-%m-%d')
  tab=audit.frame(run['ledgers']['account_daily']);tab['date']=tab.date.str[:10]
  dates=f.index.strftime('%Y-%m-%d').tolist();prev={dates[i]:dates[i-1] for i in range(1,len(dates))}
  feats=intent.set_index('signal_day');anchor=None
  # Actual cycle entries are used to anchor subsequent holding-state comparisons.
  entries={c['entry_day']:c for c in desc['cycles']}
  previous_eq=100000.;previous_q=0
  cycle_anchor={}
  for rec in tab.itertuples():
   day=rec.date; prior=feats.loc[prev[day]];delta=float(rec.equity-previous_eq)
   if day in entries:
    anchor=float(prior.entry_anchor);cycle_anchor[entries[day]['cycle_id']]=anchor
   role='ENTRY' if day in entries and previous_q==0 else 'CARRIED' if previous_q>0 else 'FLAT'
   anchored=bool(prior.p>=anchor) if anchor is not None else False
   state=('up' if prior.center_gain>0 else 'nonup')+'_'+('repaired' if anchored else 'unrepaired')
   states.append({'candidate':cid,'date':day,'role':role,'state':state,'dynamic_repaired':bool(prior.p>=prior.m),'pnl':delta,'before_quantity':int(previous_q),'after_quantity':int(rec.quantity),'year':day[:4]})
   previous_eq=float(rec.equity);previous_q=int(rec.quantity)
  assert abs(sum(x['pnl'] for x in states if x['candidate']==cid)-desc['net_yuan'])<1e-7
  for cycle in desc['cycles']:
   if cycle['cycle_id'] not in cycle_anchor:continue
   anchor=cycle_anchor[cycle['cycle_id']];start=cycle['entry_day'];end=cycle['exit_day'] or dates[-1]
   z=f.loc[start:end];hit=z[z.p>=z.m]
   if len(hit):
    first=hit.iloc[0];day=str(hit.index[0].date());repairs.append({'candidate':cid,'entry':start,'first_dynamic_repair':day,'price_reached_entry_center':bool(first.p>=anchor),'center_fell_from_entry':bool(first.m<anchor),'cycle_net':cycle['net_yuan'],'entry_loss':cycle['first_entry_day_net_yuan']<0,'final_profit':cycle['net_yuan']>0})
 df=pd.DataFrame(states);df.to_csv(HOME/'others/holding_states.csv',index=False)
 groups=[]
 for (cid,role,state),g in df.groupby(['candidate','role','state']):
  for year in ('all','2025','2026'):
   q=g if year=='all' else g[g.year.eq(year)]
   groups.append({'candidate':cid,'role':role,'state':state,'year':year,**stats(q.pnl)})
 result={'status':'DESCRIPTIVE_DIAGNOSIS_COMPLETE','source_refs':refs,'input_ids':ids,'new_accounts':0,'opportunities':opportunity,'holding_groups':groups,'repairs':repairs,'accounts':accounts,'limitations':['Account state PnL is description, not incremental causal contribution.','Entry anchors refer to signal centers, not fair value.','Standalone events overlap and do not constitute a portfolio.','Carried state includes actual exit/open gap and fees; not future-filtered.']}
 save(HOME/'others/diagnosis.json',result)
 print(json.dumps({'status':result['status'],'accounts':len(accounts),'opportunity_groups':len(opportunity),'holding_groups':len(groups),'repair_counts':{c:{'total':sum(r['candidate']==c for r in repairs),'without_anchor_recovery':sum(r['candidate']==c and not r['price_reached_entry_center'] for r in repairs)} for c in (a['candidate'] for a in accounts)}},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
