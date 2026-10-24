"""Authenticate retained full-window sources without replaying strategies."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
from pathlib import Path
from hashlib import sha256
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
import json,sys
import numpy as np
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from strategy_evaluator import research_models as m
H=Path(__file__).resolve().parents[1];B=H.parent;ROOT=H.parents[3];OUT=H/'others';CACHE=ROOT/'.tmp/s015-ex080'
def read(p):return json.loads(p.read_bytes())
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def rows():
 numbers=(*range(52,57),*range(58,63),65,*range(68,75),76,77,78)
 result=[dict(r,source_role='family',origin_experiment=f'EX{n:03}_20261024') for n in numbers for r in read(B/f'EX{n:03}_20261024/others/results.json')['rows']];assert len(result)==627
 result.extend(dict(r,source_role='stress') for r in read(OUT/'reused_stress.json'));result.extend(read(OUT/'stress_results.json')['rows']);assert len(result)==656;return result
def authenticate(row):
 ref=EvidenceRef.from_dict(row['evidence']);raw=ref.resolve(ROOT).read_bytes();assert sha256(raw).hexdigest()==ref.sha256;value=json.loads(raw);validate_evaluation_evidence(value);assert value['request_hash']==row['request_hash'] and value['result_hash']==row['result_hash']
 projections=[m.AssessmentEvidence.from_dict(x) for x in value['assessment_evidence']];item=next(x for x in projections if x.window_id=='full');assert len(item.account)==434 and item.initial_cash==100000. and item.opening_quantity==0 and item.frequency_window_days==60;assert item.account[0].session=='2025-01-02' and item.account[-1].session=='2026-10-21';assert item.candidate.candidate_id.removeprefix('S015-')==row['candidate_id'];assert item.scenario_id==('fee_x2' if row['source_role']=='stress' else 'standard')
 assert item.scenario_context.one_way_cost==(.002 if row['source_role']=='stress' else .001);assert item.parameter_point is None
 common=None
 if row['candidate_id'] in {r['candidate_id'] for r in read(OUT/'centers.json')} and row['source_role']=='family':
  other=next(x for x in projections if x.window_id=='s011_common');assert len(other.account)==415;e=np.r_[other.initial_cash,[x.equity for x in other.account]];ret=float(e[-1]/e[0]-1);dd=float(np.max(1-e/np.maximum.accumulate(e)));common={'net_return':ret,'drawdown':dd,'evaluation_id':other.evaluation_id,'sessions':415,'return_threshold':.9158029150000013,'drawdown_threshold':.07248663749114126,'passed':ret>.9158029150000013 and dd<.07248663749114126};assert common['passed']
 meta={'candidate_id':row['candidate_id'],'source_role':row['source_role'],'evidence':ref.to_dict(),'evaluation_id':item.evaluation_id,'request_hash':row['request_hash'],'result_hash':row['result_hash'],'content_sha256':item.candidate.content_sha256,'common_415':common}
 return item.to_dict(),meta
def main():
 assert not (OUT/'retained_sources.json').exists();rs=rows();values=[];meta=[]
 with ProcessPoolExecutor(max_workers=8,mp_context=get_context('spawn')) as pool:
  for i,(x,y) in enumerate(pool.map(authenticate,rs)):
   values.append(x);meta.append(y)
   if i%32==31:print('AUTHENTICATED',i+1,len(rs),flush=True)
 save(CACHE/'retained_accounts.json',values);save(OUT/'retained_sources.json',meta);save(OUT/'common_415_checks.json',[dict(candidate_id=x['candidate_id'],**x['common_415']) for x in meta if x['common_415'] is not None]);print('RETAINED_AUTHENTICATION_PASS',len(values),flush=True)
if __name__=='__main__':main()
