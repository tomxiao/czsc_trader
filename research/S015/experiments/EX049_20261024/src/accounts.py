"""Public SRT/TDR stage-two fixed factorial account comparisons."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
import argparse,importlib.util,json
from collections.abc import Mapping
from datetime import date
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import numpy as np
import pandas as pd
import optuna
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence,open_research_execution
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,ExecutionResources,EvidenceRef,MaterialEvidenceWrite,EvaluationRequest,EvaluationWindow,EvaluationCost,EvaluationBenchmark,LimitBuyHold,EvaluationEvidenceWrite
from strategy_runtime import StrategyCandidate,implementation_sha256
ROOT=Path(__file__).resolve().parents[5];HERE=Path(__file__).resolve().parents[1];BASE=HERE.parent;SOURCE=HERE/'src/strategy_runtime';FILES=['strategies/price_information.py']
def read(p):return json.loads(p.read_bytes())
def plain(v):
    if isinstance(v,Mapping):return {k:plain(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [plain(x) for x in v]
    return v
def save(p,v):p.write_text(json.dumps(plain(v),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
def context():return create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=ExecutionResources(4,1,13))
def material(ex,p):return publish_evidence(context(),MaterialEvidenceWrite(ex,p.stem,p.read_bytes(),{'.py':'text/x-python','.json':'application/json','.csv':'text/csv','.md':'text/markdown'}[p.suffix],p.suffix[1:]))
def module(p,name):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def candidate(cid,p):
    params={**p,'schedule':read(HERE/f'others/models_{p["family"]}_{p["lag"]}.json')}
    return StrategyCandidate('S015',cid,{'decision_feedback':'MARKET_INTENT','parameters':params,'runtime':{'module':'strategy_runtime.strategies.price_information','qualname':'PriceInformation','contract_version':2,'source_files':FILES,'source_sha256':implementation_sha256(FILES,source_root=SOURCE)}},SOURCE)
def prepare():
    ex=ExperimentRef('S015',HERE.name);assert not (HERE/'others/account_refs.json').exists()
    assert read(HERE/'others/runtime_checks.json')['status']=='PASS';assert read(HERE/'others/training_audit.json')['status']=='PASS'
    proto={'configurations':[{'family':f,'lag':lag,'hold':3,'exposure':1.} for f,lag in [('U',1),('B',1),('BF',1),('BP',1),('BPF',1),('BF',3),('BPF',3)]],
      'training':read(HERE/'others/training_refs.json'),
      'execution':'CYCLE_TARGET signal_cash_fraction/entry_cycle allocation1 for every arm; locked cash budget including buy fees and target lots; fixed 3 positive signal days, no same exit-day reentry; independent100k full434/common415 windows; same canonical model schedule and pre-model cash.',
      'optuna':'7 preregistered fixed configurations, no threshold or holding optimization; four account objectives are bookkeeping only.',
      'preflight':'Serial first arm retained as formal evidence and five raw ledgers; parallel first arm equality before accepting remaining arms.',
      'counts':{'configurations':7,'account_scenarios':14,'technical_extra':2,'processes':4,'native_threads':1,'seed':13}}
    save(HERE/'protocols/accounts.json',proto)
    files=[Path(__file__),SOURCE/FILES[0],HERE/'protocols/accounts.json',HERE/'others/training_manifest.json',HERE/'others/training_audit.json',HERE/'others/runtime_checks.json',*sorted((HERE/'others').glob('models_*.json'))]
    save(HERE/'others/account_refs.json',{p.relative_to(HERE).as_posix():material(ex,p).to_dict() for p in files});print('ACCOUNT_DESIGN_FROZEN',flush=True)

def authenticate():
    for key,value in read(HERE/'others/account_refs.json').items():assert EvidenceRef.from_dict(value).resolve(ROOT).read_bytes()==(HERE/key).read_bytes()
    oldpath=BASE/'EX016_20261023/src/suite.py';sr=EvidenceRef.from_dict(read(BASE/'EX033_20261023/others/results.json')['summary_source']);assert sr.resolve(ROOT).read_bytes()==oldpath.read_bytes()
    return module(oldpath,'authenticated_account_summary'),sr
def request(ctx,ex,cid,p):
    c=candidate(cid,p)
    return ctx.evaluation.prepare(EvaluationRequest(ROOT,ex.experiment_id,c,{'candidate_id':c.reference_id,'source_files':FILES,'implementation_sha256':c.payload['runtime']['source_sha256']},'159326.SZ','etf',(EvaluationWindow('full',date(2025,1,2),date(2026,10,21)),EvaluationWindow('s011_common',date(2025,2,6),date(2026,10,21))),date(2026,10,21),100000.,(EvaluationCost('standard',.001),),benchmark=EvaluationBenchmark(LimitBuyHold(100,.01,.001,.1,1000000))))
def compact_summary(suite,req,result):
    row=suite.summary(req,result);p=plain(row['parameters']);schedule=p.pop('schedule');row['parameters']=p;row['schedule_sha256']=sha256(json.dumps(schedule,sort_keys=True,separators=(',',':')).encode()).hexdigest();return row
def run(exid,precheck=False):
    ex=ExperimentRef('S015',exid);home=BASE/exid;assert not (home/'others/results.json').exists();suite,sr=authenticate();proto=read(home/'protocols/accounts.json');ctx=context()
    study=optuna.create_study(directions=['maximize','minimize','maximize','minimize'],sampler=optuna.samplers.RandomSampler(seed=13));configs=proto['configurations']
    for i in range(len(configs)):study.enqueue_trial({'configuration_index':i})
    specs=[]
    for i,p in enumerate(configs):
        t=study.ask();assert t.suggest_int('configuration_index',0,len(configs)-1)==i;specs.append((t,request(ctx,ex,f'C{int(exid[2:5])*100+i:04d}',p)))
    print('PREPARED',exid,len(specs),flush=True);serial=ctx.evaluation.evaluate(specs[0][1]) if precheck else None
    if precheck:
        er=publish_evidence(ctx,EvaluationEvidenceWrite(ex,'serial_preflight',specs[0][1],serial))
        save(home/'others/serial_preflight_ref.json',er.to_dict())
        for run0 in serial.runs:
            for table in ('account_daily','decisions','orders','fills','trades'):getattr(run0.execution,table).to_csv(home/f'others/serial_{run0.window_id}_{table}.csv',index=False)
        print('SERIAL_PREFLIGHT_COMPLETE',flush=True)
    rows=[]
    with open_research_execution(ctx,experiment=ex) as session:
        for start in range(0,len(specs),4):
            block=specs[start:start+4];outcomes=ctx.evaluation.evaluate_many(tuple(req for _,req in block),execution=session)
            for j,((trial,req),out) in enumerate(zip(block,outcomes,strict=True)):
                if out.status.value!='SUCCEEDED':
                    save(home/'others/technical_failure.json',{'candidate':req.strategy.candidate_id,'status':out.status.value,'error':str(out.error),'finished':len(rows)});raise RuntimeError(out.error)
                result=out.result
                if precheck and start+j==0:
                    assert result.result_hash==serial.result_hash
                    for a,b in zip(serial.runs,result.runs,strict=True):
                        for table in ('account_daily','decisions','orders','fills','trades'):pd.testing.assert_frame_equal(getattr(a.execution,table),getattr(b.execution,table))
                row=compact_summary(suite,req,result)
                er=publish_evidence(ctx,EvaluationEvidenceWrite(ex,row['candidate_id'],req,result));row['evidence']=er.to_dict()
                for run in result.runs:
                    for table in ('account_daily','decisions','orders','fills','trades'):getattr(run.execution,table).to_csv(home/f'others/{row["candidate_id"]}_{run.window_id}_{table}.csv',index=False)
                study.tell(trial,[row['runs']['full']['net_return'],row['runs']['full']['dd'],row['runs']['s011_common']['net_return'],row['runs']['s011_common']['dd']]);rows.append(row)
                save(home/'others/progress.json',{'rows':rows,'total':len(specs),'completed':len(rows)})
                print(row['candidate_id'],row['parameters'],{k:{a:v[a] for a in ('net_return','dd','closed','frequency_median','frequency_good')} for k,v in row['runs'].items()},flush=True)
    save(home/'others/results.json',{'rows':rows,'new_configurations':len(rows),'account_scenarios':2*len(rows),'technical_precheck_extra_scenarios':2 if precheck else 0,'precheck_five_ledgers_equal':precheck,'qualified_centers':sum(r['both_center_pass'] for r in rows),'summary_source':sr.to_dict(),'execution_stats':asdict(session.stats),'optuna':[{'number':t.number,'params':t.params,'values':t.values,'state':str(t.state)} for t in study.trials]});print('ACCOUNTS_COMPLETE',exid,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','run','precheck']);p.add_argument('--experiment',default=HERE.name);a=p.parse_args()
    if a.mode=='prepare':prepare()
    else:run(a.experiment,a.mode=='precheck')
