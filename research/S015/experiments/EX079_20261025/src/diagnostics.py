"""Authenticate same-identity costs and describe retained standard accounts."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
from pathlib import Path
import importlib.util,json
import numpy as np
from czsc_trader.application import RepositoryContext,diagnose_accounts
from czsc_trader.research_tools import EvidenceRef,AccountRunRef,AccountDiagnosisRequest
H=Path(__file__).resolve().parents[1];B=H.parent;ROOT=H.parents[3]
def read(p):return json.loads(p.read_bytes())
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def mod(p,n):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def main():
 assert not (H/'others/diagnosis.json').exists()
 audit=mod(B/'EX074_20261024/src/account_audit.py','audit');stress=mod(B/'EX063_20261024/src/audit_stress.py','stress')
 repo=RepositoryContext.discover(ROOT);proto=read(H/'protocols/accounts.json');refs={};fees=[];descriptions=[]
 for r in read(H/'others/results.json')['rows']:
  cid=r['candidate_id'];spec=proto['standard_sources'][cid]
  priorrow=next(x for x in read(B/spec['experiment']/'others/results.json')['rows'] if x['candidate_id']==cid)
  assert priorrow['parameters']==r['parameters'];assert priorrow['identity']==r['identity']
  ref=EvidenceRef.from_dict(r['evidence']);ev=read(ref.resolve(ROOT));standardref=EvidenceRef.from_dict(spec['evidence']);prior=read(standardref.resolve(ROOT));refs[cid]=standardref.to_dict();refs[cid+'_fee_x2']=ref.to_dict()
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
   conditions={'positive_cagr':cagr>0,'beats_same_cost_buyhold_cagr':cagr>bhcagr,'beats_same_cost_buyhold_dd':dd<bhdd if bhdd>0 else dd<=bhdd,'dd_at_most_25pct':dd<=.25}
   fees.append({'candidate':cid,'window':w,'identity_unchanged':True,'signals_unchanged':True,'public_diagnosis':diag.to_dict(),'summary':r['runs'][w],'buyhold_cagr':bhcagr,'buyhold_dd':bhdd,'original_stress_conditions':conditions,'pass':all(conditions.values()),'account_description':desc})
   standarddesc=audit.describe(standard,priorrow['runs'][w]);cycles=standarddesc['cycles'];wins=sorted((c['net_yuan'] for c in cycles if c['net_yuan']>0),reverse=True)
   daily=audit.frame(standard['ledgers']['account_daily']);dates=daily.date.str[:10];equity=np.r_[100000.,daily.equity.to_numpy(float)];rolling=[]
   for start in range(0,len(daily)-251,21):
    z=equity[start:start+253];rolling.append({'start':dates.iloc[start],'end':dates.iloc[start+251],'net_return':float(z[-1]/z[0]-1),'dd':float(np.max(1-z/np.maximum.accumulate(z)))})
   split=[];previous=100000.
   for year in sorted(set(x[:4] for x in dates)):
    part=daily[dates.str.startswith(year)];last=float(part.equity.iloc[-1]);split.append({'year':year,'net_yuan':last-previous,'net_return':last/previous-1});previous=last
   descriptions.append({'candidate':cid,'window':w,'standard_summary':priorrow['runs'][w],'account_description':standarddesc,'top4_positive_profit_share':sum(wins[:4])/sum(wins) if wins else None,'top1_positive_profit_share':wins[0]/sum(wins) if wins else None,'years':split,'rolling252_step21':rolling})
 result={'status':'DIAGNOSTICS_PASS','new_accounts_created_by_diagnostics':0,'source_refs':refs,'fees':fees,'standard_descriptions':descriptions,'limitations':['All development data repeatedly seen; year/rolling views are descriptions, not independent tests or new hard gates.','Six representatives only; not all candidates and not a full stage-four selfcheck.','Signals and configured threshold remain unchanged under actual fee stress.','Public diagnosis unsupported is retained; ledger arithmetic is not market causal attribution.']}
 save(H/'others/diagnosis.json',result)
 print(json.dumps({'status':result['status'],'stress':[(x['candidate'],x['window'],x['pass'],x['summary']['net_return'],x['summary']['dd']) for x in fees]},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
