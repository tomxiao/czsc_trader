"""Optuna-managed fixed counterfactuals and local parameter perturbations."""
import argparse
import json
import time
import optuna
from common_adaptive import ROOT,RUNS,context,request,save,cache_read,cache_write, PROTOCOLS
from economics_r4 import summarize,search_value
from search import configuration_hash

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('plan')
    parser.add_argument('--through',type=int)
    parser.add_argument('--workers',type=int,choices=(4,8),default=8)
    args=parser.parse_args()
    plan=json.loads((PROTOCOLS/args.plan).read_text(encoding='utf-8'))
    research=context(args.workers)
    first,_=cache_read(ROOT/'.tmp/s013-stage3-hfq/precheck.pkl.gz')
    rows=json.loads((RUNS/'search_results_r4.json').read_text(encoding='utf-8'))['rows']
    existing={r['config_hash']:r for r in rows if r['status']=='SUCCEEDED'}
    next_number=max(int(r['candidate_id'][1:]) for r in rows)+1
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study_path=ROOT/f'.tmp/s013-negative-years/{plan["name"]}.study.pkl.gz'
    comparisons_path=RUNS/(plan['name']+'_comparisons.json')
    if study_path.exists():
        study=cache_read(study_path)
        comparisons=json.loads(comparisons_path.read_text(encoding='utf-8'))['comparisons']
    else:
        study=optuna.create_study(direction='maximize',sampler=optuna.samplers.RandomSampler(seed=13),study_name=plan['name'])
        for index in range(len(plan['configurations'])):
            study.enqueue_trial({'configuration':index})
        comparisons=[]
    completed=sum(t.state==optuna.trial.TrialState.COMPLETE for t in study.trials)
    target=min(args.through or len(plan['configurations']),len(plan['configurations']))
    started=time.perf_counter()
    for offset in range(completed,target,args.workers):
        pending,trials=[],[]
        for _ in range(min(args.workers,target-offset)):
            trial=study.ask()
            index=trial.suggest_int('configuration',0,len(plan['configurations'])-1)
            config=plan['configurations'][index]
            parameters=config['parameters']
            digest=configuration_hash(parameters)
            label=config['label']
            if digest in existing and not config.get('force',False):
                row=existing[digest]
                comparisons.append({'label':label,'candidate_id':row['candidate_id'],'reuse':True})
                study.tell(trial,search_value(row))
                continue
            number=next_number
            next_number+=1
            if config.get('explicit_retry_of'):
                trial.set_user_attr('explicit_retry_of',config['explicit_retry_of'])
                trial.set_user_attr('retry_reason',plan['reason'])
            trials.append((trial,number,parameters,digest,label))
            pending.append(research.evaluation.prepare(request(number,parameters,first.execution_data)))
        if pending:
            outcomes=research.evaluation.evaluate_many(tuple(pending))
            failures=[]
            for (trial,number,parameters,digest,label),outcome in zip(trials,outcomes,strict=True):
                row={'candidate_id':f'C{number:04}','parameters':parameters,'config_hash':digest,
                    'search':plan['name'],'trial':trial.number,'label':label,'status':outcome.status.value}
                row['trial_attributes']=trial.user_attrs
                row['resources']={'max_workers':args.workers,'native_threads':1,'request_workers':1}
                if outcome.status.value=='SUCCEEDED':
                    row.update(summarize(outcome.result))
                    study.tell(trial,search_value(row))
                    existing[digest]=row
                    cache_write(ROOT/f'.tmp/s013-stage3-hfq/C{number:04}.pkl.gz',outcome.result)
                    comparisons.append({'label':label,'candidate_id':row['candidate_id'],'reuse':False})
                else:
                    row['error']={'code':outcome.error.code,'message':outcome.error.message}
                    study.tell(trial,state=optuna.trial.TrialState.FAIL)
                    failures.append(row)
                rows.append(row)
            save('search_results_r4.json',{'rows':rows,'resources':{'max_workers':args.workers,'native_threads':1,'request_workers':1},
                'last_fixed_plan':plan['name']})
            save(plan['name']+'_comparisons.json',{'plan':plan['name'],'comparisons':comparisons,
                'elapsed_seconds':time.perf_counter()-started})
            valid=[r for r in rows if r['status']=='SUCCEEDED']
            best=min(valid,key=lambda r:r['deficit'])
            print(json.dumps({'fixed_search':plan['name'],'completed':len(comparisons),
                'qualified_total':sum(r['qualified'] for r in valid),
                'best':{k:best[k] for k in ('candidate_id','net_cagr','closed_trades','min_dd_margin','deficit')},
                'elapsed':time.perf_counter()-started}),flush=True)
            if failures:
                cache_write(study_path,study)
                raise RuntimeError('Explicit formal failures saved; researcher must decide retry')
        cache_write(study_path,study)
    save(plan['name']+'_comparisons.json',{'plan':plan['name'],'comparisons':comparisons,
        'elapsed_seconds':time.perf_counter()-started,'status':'COMPLETE' if target==len(plan['configurations']) else 'PARTIAL'})

if __name__=='__main__':
    main()
