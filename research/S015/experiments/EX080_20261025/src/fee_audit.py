"""Independent same-identity cost-stress reconciliation and original gates."""
from pathlib import Path
import importlib.util,json
import numpy as np
from czsc_trader.research_tools import EvidenceRef
H=Path(__file__).resolve().parents[1];ROOT=H.parents[3];B=H.parent
def read(p):return json.loads(p.read_bytes())
def mod(p,n):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def main():
 out=H/'others/fee_audit.json';assert not out.exists();stress=mod(B/'EX063_20261024/src/audit_stress.py','stress');audit=mod(B/'EX066_20261024/src/audit.py','audit');standards={r['candidate_id']:r for r in read(H/'others/centers.json')};rows=read(H/'others/reused_stress.json')+read(H/'others/stress_results.json')['rows'];assert len(rows)==29;checks=[]
 for r in rows:
  cid=r['candidate_id'];ev=read(EvidenceRef.from_dict(r['evidence']).resolve(ROOT));prior=read(EvidenceRef.from_dict(standards[cid]['evidence']).resolve(ROOT));run=next(x for x in ev['runs'] if x['window_id']=='full');original=next(x for x in prior['runs'] if x['window_id']=='full');assert run['identity']['candidate']==original['identity']['candidate'];assert run['identity']['content_sha256']==original['identity']['content_sha256'];assert run['signals']==original['signals'];assert run['signal_support']['input_binding']==original['signal_support']['input_binding']
  proj=next(x for x in ev['assessment_evidence'] if x['window_id']=='full');summary=audit.projection_summary(proj);desc=stress.describe(run,summary);n=len(proj['account']);cagr=(1+summary['net_return'])**(252/n)-1;bh=np.r_[proj['initial_cash'],[x['equity'] for x in proj['benchmark_equity']]] if isinstance(proj['benchmark_equity'][0],dict) else np.r_[proj['initial_cash'],proj['benchmark_equity']]
  bhcagr=(bh[-1]/bh[0])**(252/n)-1;bhdd=float(np.max(1-bh/np.maximum.accumulate(bh)));conditions={'positive_cagr':cagr>0,'beats_same_cost_bh_cagr':cagr>bhcagr,'beats_same_cost_bh_dd':summary['dd']<bhdd if bhdd>0 else summary['dd']==0,'absolute_dd':summary['dd']<=.25}
  checks.append({'candidate_id':cid,'evidence':r['evidence'],'summary':summary,'cagr':float(cagr),'benchmark_cagr':float(bhcagr),'benchmark_dd':bhdd,'conditions':{k:bool(v) for k,v in conditions.items()},'pass':bool(all(conditions.values())),'identity_and_signals_unchanged':True,'account_description':desc})
 result={'status':'ARITHMETIC_AND_IDENTITY_PASS','candidates':29,'new_pressure_accounts':24,'reused_pressure_accounts':5,'stress_target_passes':sum(r['pass'] for r in checks),'rows':checks,'scope':'Cost component only; parameter applicability and complete selfcheck not inferred.'};out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');print('FEE_AUDIT_PASS',result['stress_target_passes'],29,flush=True)
if __name__=='__main__':main()
