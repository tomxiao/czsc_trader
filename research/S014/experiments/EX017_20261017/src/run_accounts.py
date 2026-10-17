"""Four authorized fixed accounts through the public batch evaluation facade."""
from dataclasses import asdict
from datetime import date
from pathlib import Path
import json
import requests
from strategy_runtime import StrategyCandidate
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import (EvaluationRequest, EvaluationWindow, EvaluationCost,
    EvaluationBenchmark, LimitBuyHold, EvaluationResources, EvaluationEvidenceWrite, ExperimentRef)
from pinned_inputs import get_context

ROOT=Path(__file__).resolve().parents[5]; EX=Path(__file__).resolve().parents[1]
VARIANTS=('parent_H1','parent_H3','high_H3','high_H3_low_H1')

def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')

def no_network(*args,**kwargs):
    raise RuntimeError('Stage-three account run is pinned and offline')

def main():
    destination=EX/'others/account_results.json'
    if destination.exists():raise RuntimeError('Preserve completed account evidence')
    requests.sessions.Session.request=no_network
    ctx=get_context(resources=EvaluationResources(max_workers=2,native_threads_per_worker=1,random_seed=17))
    bound=[]
    for i,variant in enumerate(VARIANTS,9):
        payload=json.loads((EX/f'protocols/payload_v3_{variant}.json').read_text(encoding='utf-8'))
        candidate=StrategyCandidate('S014',f'C{i:04}',payload,EX/'src/strategy_runtime')
        request=EvaluationRequest(repository_root=ROOT,experiment_id=EX.name,strategy=candidate,
            runtime_binding={'candidate_id':candidate.reference_id,'source_files':payload['runtime']['source_files'],
                             'implementation_sha256':payload['runtime']['source_sha256']},
            symbol='600722.SH',asset_type='stock',windows=(EvaluationWindow('full',date(2020,1,2),date(2026,10,15)),),
            data_cutoff=date(2026,10,15),initial_cash=100000,costs=(EvaluationCost('baseline',.001),),
            benchmark=EvaluationBenchmark(LimitBuyHold(100,.01,.01,.1,1000000)),workers=1)
        prepared=ctx.evaluation.prepare(request); bound.append(prepared)
        write(EX/f'others/binding_{variant}.json',{
            'candidate':candidate.reference_id,'payload':payload,'window':['2020-01-02','2026-10-15'],
            'initial_cash':100000,'one_way_cost':.001,'benchmark':request.benchmark.to_dict(),
            'execution_requests':{k:asdict(v) for k,v in prepared.execution_data.requests.items()},
            'execution_prepared':asdict(prepared.execution_data.prepared),
            'execution_identities':prepared.execution_data.input_identities,
            'execution_fingerprint':prepared.execution_data.fingerprint,
            'input_bindings':{k:v.to_dict() for k,v in prepared.input_bindings.items()}})
        print('BOUND',variant,flush=True)
    outcomes=ctx.evaluation.evaluate_many(tuple(bound)); records=[]
    for variant,request,outcome in zip(VARIANTS,bound,outcomes,strict=True):
        row={'variant':variant,'candidate':request.strategy.reference_id,'status':outcome.status.value,
             'error':asdict(outcome.error) if outcome.error else None}
        records.append(row)
        if outcome.result is not None:
            evidence=publish_evidence(ctx,EvaluationEvidenceWrite(ExperimentRef('S014',EX.name),
                f'account-{variant.replace("_","-").lower()}',request,outcome.result))
            row['evidence']=evidence.to_dict()
            row['result_hash']=outcome.result.result_hash
            run=outcome.result.runs[0]
            folder=ROOT/'research/S014/assets/runs'/EX.name/variant;folder.mkdir(parents=True,exist_ok=True)
            for name in ('decisions','orders','fills','account_daily','trades'):
                getattr(run.execution,name).to_csv(folder/f'{name}.csv',index=False)
            run.signals.decisions.to_csv(folder/'signals.csv',index=False)
            run.buyhold.account_daily.to_csv(folder/'buyhold.csv',index=False)
            write(folder/'observation.json',run.observation.to_dict())
            print('ACCOUNT',variant,'PASS',float(run.execution.equity.iloc[-1]),flush=True)
        else:print('ACCOUNT',variant,row['error'],flush=True)
        write(destination,{'records':records,'resources':{'max_workers':2,'native_threads_per_worker':1,'seed':17},
            'actual_external_calls':0,'distinct_configurations':4,'nominal_window':['2020-01-01','2026-10-15'],
            'actual_trading_window':['2020-01-02','2026-10-15']})
    if any(r['status']!='SUCCEEDED' for r in records):raise RuntimeError('Some fixed accounts failed; inspect evidence')

if __name__=='__main__':main()
