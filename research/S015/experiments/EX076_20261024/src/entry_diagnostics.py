"""Actual fills and opportunity coverage; not a counterfactual avoidable-profit model."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
from pathlib import Path
import json,importlib.util
import numpy as np,pandas as pd
from czsc_trader.research_tools import EvidenceRef
H=Path(__file__).resolve().parents[1];B=H.parent;ROOT=H.parents[3]
def read(p):return json.loads(p.read_bytes())
def mod(p,n):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def stats(c):return {'n':len(c),'net_yuan':float(sum(v['net_yuan'] for v in c)),'profitable':sum(v['net_yuan']>0 for v in c)}
def main():
 assert not (H/'others/diagnosis.json').exists()
 audit=mod(H/'src/account_audit.py','audit');loader=mod(B/'EX051_20261024/src/study.py','loader');old,_=loader.loader();adj,raw,bars,rules,ids=old.inputs(old.sources())
 factors=dict(zip(pd.to_datetime(adj.Date).dt.strftime('%Y-%m-%d'),adj.Close.to_numpy(float)/raw.Close.to_numpy(float),strict=True));entries=[];refs={};baselines={}
 for row in read(H/'others/results.json')['rows']:
  cid=row['candidate_id'];ref=EvidenceRef.from_dict(row['evidence']);ev=read(ref.resolve(ROOT));refs[cid]=ref.to_dict();run=next(r for r in ev['runs'] if r['window_id']=='full');desc=audit.describe(run,row['runs']['full'])
  d=audit.frame(run['ledgers']['decisions']);fills=audit.frame(run['ledgers']['fills']);daily=audit.frame(run['ledgers']['account_daily']);daily['date']=daily.date.str[:10];before=daily.set_index('date').quantity_before
  cycles=[];allbuys=[]
  for c in desc['cycles']:
   buys=fills[fills.cycle_id.eq(c['cycle_id'])&fills.side.eq('BUY')];cycle_decisions=d[d.cycle_id.eq(c['cycle_id'])];opening=cycle_decisions.iloc[0];planned_first=str(opening.valid_session)[:10]
   for i,f in enumerate(buys.itertuples()):
    z=d[d.decision_id.eq(f.decision_id)].iloc[0];day=str(f.fill_time)[:10];target=float(np.exp(z.repair_target));adjusted=float(f.price)*factors[day]
    record={'cycle_id':c['cycle_id'],'fill_day':day,'activation_signal_day':str(opening.signal_date)[:10],'planned_first_session':planned_first,'role':'supplement' if i else 'delayed_first' if day>planned_first else 'immediate_first','adjusted_price':adjusted,'target_adjusted':target,'above_target':bool(adjusted>=target),'net_space_after_standard_fees':float(target/adjusted*.999/1.001-1),'quantity':int(f.quantity)};allbuys.append(record)
    if i==0:cycles.append({**c,**{k:v for k,v in record.items() if k!='quantity'}})
  p=row['parameters'];kind=p['center_kind'];loss=[c for c in cycles if c['first_entry_day_net_yuan']<0];at=[c for c in cycles if c['above_target']];netlack=[c for c in cycles if c['net_space_after_standard_fees']<=0]
  coverage=None
  if p['minimum_repair_space']==0:baselines[kind]=cycles
  else:
   basewins=[c for c in baselines[kind] if c['exit_day'] is not None and c['net_yuan']>0];entrydays={c['entry_day'] for c in cycles};missed=[c for c in basewins if c['entry_day'] not in entrydays]
   coverage={'baseline_profitable':stats(basewins),'not_repeated':stats(missed),'not_repeated_flat':stats([c for c in missed if before.loc[c['entry_day']]==0]),'not_repeated_holding':stats([c for c in missed if before.loc[c['entry_day']]>0])}
  entries.append({'candidate':cid,'parameters':p,'cycles':cycles,'buy_fills':allbuys,'roles':{k:sum(f['role']==k for f in allbuys) for k in ['immediate_first','delayed_first','supplement']},'entry_loss':stats(loss),'entry_loss_recovered':stats([c for c in loss if c['net_yuan']>0]),'filled_at_or_above_target':stats(at),'insufficient_net_space_at_fill':stats(netlack),'coverage':coverage,'description':{k:desc[k] for k in ['net_yuan','fees_yuan','years','cycle_distribution','frequency','exposure']}})
 out={'status':'DESCRIPTIVE_CHECKS_PASS','source_refs':refs,'input_ids':ids,'new_accounts':0,'entries':entries,'limits':['Activation gate does not prohibit later supplemental buys.','Actual future fill prices used only for diagnosis, never for entry filtering.','Missing profitable dates are coverage, not avoidable or foregone causal profit.','Reused development data; no new independent validation.']}
 (H/'others/diagnosis.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 print(json.dumps([{k:e[k] for k in ['candidate','roles','entry_loss','entry_loss_recovered','filled_at_or_above_target','insufficient_net_space_at_fill']} for e in entries]),flush=True)
if __name__=='__main__':main()
