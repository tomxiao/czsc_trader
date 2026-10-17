"""Two complementary conditional-reservation accounts through the public batch evaluation facade."""
from dataclasses import asdict
from datetime import date
from pathlib import Path
import json
import requests
import optuna
import pandas as pd
from compare_accounts import annual
from strategy_runtime import StrategyCandidate
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import (EvaluationRequest, EvaluationWindow, EvaluationCost,
    EvaluationBenchmark, LimitBuyHold, EvaluationResources, EvaluationEvidenceWrite, ExperimentRef)
import sys
sys.path.append(str(Path(__file__).resolve().parents[2]/'EX017_20261017/src'))
from pinned_inputs import get_context

ROOT=Path(__file__).resolve().parents[5]; EX=Path(__file__).resolve().parents[1]
VARIANTS=('support_exit_profit_reserve_H10', 'support_exit_nonprofit_reserve_H10')
IDS={v:i for i,v in enumerate(VARIANTS,75)}


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8',newline='\n')

def no_network(*args,**kwargs):
    raise RuntimeError('Stage-three account run is pinned and offline')

def main():
    destination=EX/'others/account_results.json'
    if destination.exists():raise RuntimeError('Preserve completed account evidence')
    lock=json.loads((EX/'protocols/comparison_lock.json').read_text(encoding='utf-8'))
    assert tuple(lock['new_variants'])==VARIANTS and lock['status']=='LOCKED_BEFORE_NEW_ACCOUNTS'
    assert json.loads((EX/'others/precheck.json').read_text(encoding='utf-8'))['status']=='PASS'
    requests.sessions.Session.request=no_network
    ctx=get_context(resources=EvaluationResources(max_workers=2,native_threads_per_worker=1,random_seed=17))
    bound=[];trials=[]
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study=optuna.create_study(study_name='s014-ex029-conditional-reservation',direction='maximize',sampler=optuna.samplers.RandomSampler(seed=17))
    for variant in VARIANTS:study.enqueue_trial({'variant':variant})
    for variant in VARIANTS:
        trial=study.ask()
        assert trial.suggest_categorical('variant',VARIANTS)==variant
        trials.append(trial)
        i=IDS[variant]
        payload=json.loads((EX/f'protocols/payload_{variant}.json').read_text(encoding='utf-8'))
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
    for variant,request,outcome,trial in zip(VARIANTS,bound,outcomes,trials,strict=True):
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
                getattr(run.execution,name).to_csv(folder/f'{name}.csv',index=False,lineterminator="\n")
            run.signals.decisions.to_csv(folder/'signals.csv',index=False,lineterminator="\n")
            run.buyhold.account_daily.to_csv(folder/'buyhold.csv',index=False,lineterminator="\n")
            write(folder/'observation.json',run.observation.to_dict())
            a=annual(run.execution.account_daily);b=annual(run.buyhold.account_daily)
            returns=a['return']-b['return'].where(b['return']>0,0)*1.5
            dd=b.max_drawdown-a.max_drawdown
            closed=int(run.execution.trades.status.eq('CLOSED').sum())
            value=float(min(returns.min(),dd.min(),60*closed/1642/3-1))
            study.tell(trial,value)
            row['optuna_trial']=trial.number;row['worst_target_margin']=value
            print('ACCOUNT',variant,'PASS',float(run.execution.equity.iloc[-1]),flush=True)
        else:
            study.tell(trial,state=optuna.trial.TrialState.FAIL)
            print('ACCOUNT',variant,row['error'],flush=True)
        write(destination,{'records':records,'resources':{'max_workers':2,'native_threads_per_worker':1,'seed':17},
            'actual_external_calls':0,'distinct_configurations':2,'nominal_window':['2020-01-01','2026-10-15'],
            'actual_trading_window':['2020-01-02','2026-10-15']})
    write(EX/'others/optuna_trials.json',{'library_version':optuna.__version__,'method':'Two fixed complementary conditional-reservation configurations enqueued before any result; seeded sampler never used for free sampling; no pruning','objective':'Minimum annual return margin, annual DD improvement, frequency/3-1. Separate exact strict target checks remain authoritative.',
        'trials':[{'number':t.number,'params':t.params,'state':t.state.name,'value':t.value} for t in study.trials]})
    assert len(study.trials)==len(VARIANTS) and len({tuple(t.params.items()) for t in study.trials})==len(VARIANTS)
    if any(r['status']!='SUCCEEDED' for r in records):raise RuntimeError('Some fixed accounts failed; inspect evidence')

if __name__=='__main__':main()
