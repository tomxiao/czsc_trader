"""Reuse fixed controls, cover joint economic cases, then feedback-batch TPE."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
from pathlib import Path
from hashlib import sha256
from dataclasses import asdict
import json,importlib.util
import optuna,pandas as pd
from czsc_trader.application import open_research_execution,publish_evidence
from czsc_trader.research_tools import ExperimentRef,EvaluationEvidenceWrite,EvidenceRef
H=Path(__file__).resolve().parents[1];B=H.parent;ROOT=H.parents[3];EX=ExperimentRef('S015',H.name)
def read(p):return json.loads(p.read_bytes())
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def mod(p,n):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def key(p):return json.dumps(p,sort_keys=True)
def values(r):return [r['runs'][w][k] for w in ('full','s011_common') for k in ('net_return','dd')]
def constraints(r):
 a,b=r['runs']['full'],r['runs']['s011_common']
 return [1.5*a['benchmark_cagr']-a['cagr'],a['dd']-.8*a['benchmark_dd'],a['dd']-.25,6-a['frequency_median'],.9-a['frequency_good']/a['frequency_windows'],.9158029150000013-b['net_return'],b['dd']-.07248663749114126]
def main():
 assert not (H/'others/results.json').exists()
 plan=read(H/'protocols/search.json')
 for path,digest in plan['dependencies'].items():assert sha256((ROOT/path).read_bytes()).hexdigest()==digest,path
 for path,ref in read(H/'others/protocol_refs.json').items():assert EvidenceRef.from_dict(ref).resolve(ROOT).read_bytes()==(ROOT/path).read_bytes(),path
 api=mod(B/'EX076_20261024/src/accounts.py','api');api.START_ID=9300
 suite=mod(B/'EX016_20261023/src/suite.py','suite');audit=mod(B/'EX074_20261024/src/account_audit.py','audit');ctx=api.context(8)
 inherited=read(B/'EX076_20261024/others/results.json')['rows']+read(B/'EX077_20261024/others/results.json')['rows'];cache={key(r['parameters']):r for r in inherited}
 for r in inherited:EvidenceRef.from_dict(r['evidence']).resolve(ROOT)
 dists={'center_kind':optuna.distributions.CategoricalDistribution(['mean','median']),'lookback':optuna.distributions.IntDistribution(2,10),'allocation':optuna.distributions.FloatDistribution(.6,1.,step=.025),'minimum_repair_space':optuna.distributions.FloatDistribution(0.,.02)}
 db=ROOT/'.tmp/s015-stage3-EX078/search.sqlite';db.parent.mkdir(parents=True,exist_ok=True);assert not db.exists()
 sampler=optuna.samplers.TPESampler(seed=13,multivariate=True,n_startup_trials=24,constraints_func=lambda t:t.user_attrs['constraint_violations'])
 study=optuna.create_study(study_name='S015-EX078',storage='sqlite:///'+db.as_posix(),sampler=sampler,directions=['maximize','minimize','maximize','minimize'])
 warm=[]
 for r in inherited:
  study.enqueue_trial(r['parameters']);t=study.ask()
  t.suggest_categorical('center_kind',['mean','median']);t.suggest_int('lookback',2,10);t.suggest_float('allocation',.6,1.,step=.025);t.suggest_float('minimum_repair_space',0.,.02)
  t.set_user_attr('constraint_violations',constraints(r));t.set_user_attr('evidence_candidate',r['candidate_id']);t.set_user_attr('phase','replay_observed_accounts')
  study.tell(t,values(r))
  retained=study.get_trials(deepcopy=False)[-1]
  assert list(retained.system_attrs['constraints'])==constraints(r)
  warm.append({'candidate':r['candidate_id'],'trial':t.number,'sampler_constraints':list(retained.system_attrs['constraints']),'actual_account_evidence':r['evidence']})
 save(H/'others/warm_start_check.json',{'status':'PASS','method':'public enqueue/ask/suggest/set_user_attr/tell; actual retained accounts only','accounts_replayed':len(warm),'new_accounts':0,'trials':warm})
 print('WARM_START_CONSTRAINTS_PASS',len(warm),flush=True)
 fixed=[p for p in plan['fixed_grid'] if key(p) not in cache]
 assert len(fixed)==0
 for p in fixed:study.enqueue_trial(p)
 rows=[];audits=[];trials=[];serial=None;serial_ref=None
 with open_research_execution(ctx,experiment=EX) as session:
  for phase,total in [('fixed_joint',len(fixed)),('adaptive_TPE',32)]:
   for start in range(0,total,8):
    before=len(inherited)+len(trials);batch=[]
    for _ in range(min(8,total-start)):
     t=study.ask();p={'center_kind':t.suggest_categorical('center_kind',['mean','median']),'lookback':t.suggest_int('lookback',2,10),'allocation':round(t.suggest_float('allocation',.6,1.,step=.025),3),'minimum_repair_space':t.suggest_float('minimum_repair_space',0.,.02)};batch.append((t,p,key(p)))
    save(H/f'others/ask_{len(trials):03d}.json',{'phase':phase,'completed_before_ask':before,'trials':[{'number':t.number,'parameters':p} for t,p,_ in batch]})
    pending=[];seen=set(cache)
    for t,p,k in batch:
     if k not in seen:pending.append((k,api.request(ctx,EX,len(rows)+len(pending),p)));seen.add(k)
    if serial is None and pending:
     serial=api.context(1).evaluation.evaluate(pending[0][1]);serial_ref=publish_evidence(ctx,EvaluationEvidenceWrite(EX,'serial_control',pending[0][1],serial));print('SERIAL_PREFLIGHT',flush=True)
    outs=ctx.evaluation.evaluate_many(tuple(q for _,q in pending),execution=session) if pending else ()
    for (k,req),out in zip(pending,outs,strict=True):
     if out.status.value!='SUCCEEDED':save(H/'others/technical_failure.json',{'candidate':req.strategy.candidate_id,'error':str(out.error),'completed':len(rows)});raise RuntimeError(out.error)
     result=out.result
     if not rows:
      assert result.result_hash==serial.result_hash
      for a,b in zip(result.runs,serial.runs,strict=True):
       for name in ('account_daily','decisions','orders','fills','trades'):pd.testing.assert_frame_equal(getattr(a.execution,name),getattr(b.execution,name))
     r=suite.summary(req,result);ref=publish_evidence(ctx,EvaluationEvidenceWrite(EX,req.strategy.candidate_id,req,result));r['evidence']=ref.to_dict();r['identity']={'key':result.runs[0].identity.candidate.to_dict(),'content_sha256':result.runs[0].identity.content_sha256};r['dependencies']=[asdict(d) for d in req.dependencies]
     save(H/f"others/{r['candidate_id']}_payload.json",api.plain(req.strategy.payload));ev=read(ref.resolve(ROOT))
     for run in ev['runs']:
      desc=audit.describe(run,r['runs'][run['window_id']]);audits.append({'candidate':r['candidate_id'],'window':run['window_id'],'status':'PASS','cycle_sums':desc['cycle_sums'],'cycle_distribution':desc['cycle_distribution']})
     for run in result.runs:run.execution.account_daily.to_csv(H/f"others/{r['candidate_id']}_{run.window_id}_account_daily.csv",index=False)
     rows.append(r);cache[k]=r
    for t,p,k in batch:
     r=cache[k];t.set_user_attr('constraint_violations',constraints(r));t.set_user_attr('evidence_candidate',r['candidate_id']);study.tell(t,values(r));trials.append({'number':t.number,'phase':phase,'completed_before_ask':before,'parameters':p,'candidate_id':r['candidate_id'],'values':values(r),'constraints':constraints(r)})
    save(H/'others/progress.json',{'rows':rows,'trials':trials,'completed_proposals':len(trials)});save(H/'others/audit.json',{'status':'ARITHMETIC_CHECKS_PASS','accounts':audits})
    print('BATCH',phase,len(trials),'new',len(rows),'passes',sum(r['both_center_pass'] for r in rows),flush=True)
  stats=asdict(session.stats)
 save(H/'others/results.json',{'rows':rows,'new_configurations':len(rows),'formal_accounts':2*len(rows),'technical_accounts':2 if serial_ref else 0,'serial_equal':serial_ref is not None,'serial_ref':serial_ref.to_dict(),'inherited_rows':inherited,'fixed_new_proposals':0,'adaptive_proposals':32,'optuna':trials,'optuna_version':optuna.__version__,'execution_stats':stats,'center_pass_count':sum(r['both_center_pass'] for r in rows)})
 print('SEARCH_COMPLETE',len(rows),flush=True)
if __name__=='__main__':main()
