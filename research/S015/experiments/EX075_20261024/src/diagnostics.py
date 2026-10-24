"""Authenticate fee comparisons and describe actual entry/holding outcomes."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[key]='1'
from pathlib import Path
import importlib.util,json
import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext,diagnose_accounts
from czsc_trader.research_tools import EvidenceRef,AccountRunRef,AccountDiagnosisRequest

H=Path(__file__).resolve().parents[1];B=H.parent;ROOT=H.parents[3]
def read(p):return json.loads(p.read_bytes())
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def mod(p,n):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def evidence(r):
 ref=EvidenceRef.from_dict(r);return ref,read(ref.resolve(ROOT))
def stats(cycles):
 a=np.array([c['net_yuan'] for c in cycles],float)
 return {'n':len(a),'net_yuan':float(a.sum()),'profitable':int((a>0).sum()),'gross_positive_yuan':float(a[a>0].sum())}

def main():
 assert not (H/'others/diagnosis.json').exists()
 audit=mod(B/'EX074_20261024/src/account_audit.py','audit');stress=mod(B/'EX063_20261024/src/audit_stress.py','stress')
 repo=RepositoryContext.discover(ROOT);refs={};fees=[];descriptions={};rawaccounts={};entry=[]
 loader=mod(B/'EX051_20261024/src/study.py','loader');old,lref=loader.loader();sources=old.sources();adj,raw,bars,rules,ids=old.inputs(sources)
 factor=pd.Series(adj.Close.to_numpy(float)/raw.Close.to_numpy(float),index=pd.to_datetime(adj.Date).dt.strftime('%Y-%m-%d'))
 for ex,cid in [('EX061_20261024','C6105'),('EX074_20261024','C7400'),('EX074_20261024','C7401')]:
  row=next(r for r in read(B/ex/'others/results.json')['rows'] if r['candidate_id']==cid)
  ref,ev=evidence(row['evidence']);refs[cid]=ref.to_dict();run=next(r for r in ev['runs'] if r['window_id']=='full')
  desc=audit.describe(run,row['runs']['full']);descriptions[cid]=desc;rawaccounts[cid]=(row,ev,run)
  if cid=='C6105':continue
  for source,rr in read(B/ex/'others/protocol_refs.json').items():assert EvidenceRef.from_dict(rr).resolve(ROOT).read_bytes()==(ROOT/source).read_bytes()
  decisions=audit.frame(run['ledgers']['decisions']).set_index('decision_id');fills=audit.frame(run['ledgers']['fills'])
  rows=[]
  for c in desc['cycles']:
   buys=fills[fills.cycle_id.eq(c['cycle_id'])&fills.side.eq('BUY')];first=buys.iloc[0];d=decisions.loc[first.decision_id]
   target=float(np.exp(d.repair_target));entry_adjusted=float(first.price)*factor.loc[c['entry_day']]
   rows.append({**c,'first_fill_signal_day':str(first.signal_date)[:10],'repair_target_adjusted':target,'first_fill_adjusted':float(entry_adjusted),'filled_at_or_above_target':bool(entry_adjusted>=target),'gap_to_target_fraction':float(target/entry_adjusted-1)})
  loss=[c for c in rows if c['first_entry_day_net_yuan']<0];ab=[c for c in rows if c['filled_at_or_above_target']]
  daily=audit.frame(run['ledgers']['account_daily']);daily['date']=daily.date.str[:10];before=daily.set_index('date').quantity_before
  entries={c['entry_day'] for c in rows};oldwins=[c for c in descriptions['C6105']['cycles'] if c['exit_day'] is not None and c['net_yuan']>0]
  missed=[c for c in oldwins if c['entry_day'] not in entries];holding=[c for c in missed if before.loc[c['entry_day']]>0];flat=[c for c in missed if before.loc[c['entry_day']]==0]
  eq=np.r_[100000.,daily.equity.to_numpy(float)];rolling=[]
  for start in range(0,len(daily)-251,21):
   z=eq[start:start+253];rolling.append({'start':daily.date.iloc[start],'end':daily.date.iloc[start+251],'net_return':float(z[-1]/z[0]-1),'dd':float(np.max(1-z/np.maximum.accumulate(z)))})
  entry.append({'candidate':cid,'cycles':rows,'entry_loss':stats(loss),'entry_loss_final_profitable':stats([c for c in loss if c['net_yuan']>0]),'entry_day_loss_yuan':float(-sum(c['first_entry_day_net_yuan'] for c in loss)),
    'filled_at_or_above_target':stats(ab),'filled_below_target':stats([c for c in rows if not c['filled_at_or_above_target']]),'old_profitable_entries':stats(oldwins),'old_entry_dates_not_repeated':stats(missed),'not_repeated_already_holding':stats(holding),'not_repeated_flat':stats(flat),'years':row['years'],'rolling252_step21':rolling,'account_description':desc})
 for r in read(H/'others/results.json')['rows']:
  cid=r['candidate_id'];ref,ev=evidence(r['evidence']);refs[cid+'_fee_x2']=ref.to_dict();prior=rawaccounts[cid][1]
  for key in ['strategy_reference','content_sha256','strategy_identity','runtime_binding_hash','symbol','asset_type','data_cutoff','initial_cash','price_basis','pricing','benchmark','market_rules','execution_mode']:
   assert ev['request_identity'][key]==prior['request_identity'][key],(cid,key)
  for run in ev['runs']:
   w=run['window_id'];standard=next(z for z in prior['runs'] if z['window_id']==w)
   assert run['identity']['candidate']==standard['identity']['candidate'] and run['identity']['content_sha256']==standard['identity']['content_sha256']
   assert run['signals']==standard['signals'];assert run['signal_support']['evaluation_fee_rate']==.002
   assert run['signal_support']['input_binding']==standard['signal_support']['input_binding']
   desc=stress.describe(run,r['runs'][w]);diag=diagnose_accounts(repo,AccountDiagnosisRequest(AccountRunRef(ref,audit.identity(run)),None,audit.WINDOWS[w]));assert diag.status.value not in ('INVALID_EVIDENCE','INCOMPARABLE')
   bh=audit.frame(run['buyhold']['account_daily']);bhf=audit.frame(run['buyhold']['fills']);np.testing.assert_allclose(bhf.fees,bhf.price*bhf.quantity*.002,rtol=1e-10,atol=1e-7)
   e=np.r_[100000.,bh.equity.to_numpy(float)];bhdd=float(np.max(1-e/np.maximum.accumulate(e)));bhcagr=float((e[-1]/e[0])**(252/len(bh))-1);cagr=r['runs'][w]['cagr'];dd=r['runs'][w]['dd']
   conditions={'positive_cagr':cagr>0,'beats_same_cost_buyhold_cagr':cagr>bhcagr,'beats_same_cost_buyhold_dd':dd<bhdd,'dd_at_most_25pct':dd<=.25}
   fees.append({'candidate':cid,'window':w,'identity_unchanged':True,'signals_unchanged':True,'public_diagnosis':diag.to_dict(),'summary':r['runs'][w],'buyhold_cagr':bhcagr,'buyhold_dd':bhdd,'original_stress_conditions':conditions,'pass':all(conditions.values()),'account_description':desc})
 result={'status':'DIAGNOSTICS_PASS','new_accounts_created_by_diagnostics':0,'source_refs':refs,'input_ids':ids,'fees':fees,'entries':entry,'old_C6105':descriptions['C6105'],'limitations':['All development data repeatedly seen; rolling/year views are not independent tests.','Opportunity anchors freeze on signal activation, not fill; entry gap comparison uses first fill adjusted to same price basis.','Missing old profitable entry dates are coverage descriptions, not counterfactual foregone profit; current holding can overlap old opportunities.','Public attribution unsupported remains unsupported; ledger arithmetic is not causal attribution.','Fee stress and descriptions are stage-two support, not a completed stage-four selfcheck.']}
 save(H/'others/diagnosis.json',result)
 print(json.dumps({'status':result['status'],'stress_pass':[(f['candidate'],f['window'],f['pass']) for f in fees],'entry':[{k:x[k] for k in ['candidate','entry_loss','entry_loss_final_profitable','filled_at_or_above_target','filled_below_target','not_repeated_flat']} for x in entry]},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
