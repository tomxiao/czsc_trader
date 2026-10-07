"""One parent-owned Optuna study per mechanism; public FULL batch evaluation."""
import argparse
from datetime import datetime
import hashlib
import importlib.metadata
import json
import time
import optuna
from common import ROOT,WORK,BASE,context,request,save,cache_read,cache_write
from economics import summarize,search_value

TEMP=ROOT/'.tmp/s013-stage3-hfq'

def configuration_hash(p):
    return hashlib.sha256(json.dumps(p,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def proposal(trial,mechanism,expanded):
    p=dict(BASE)
    p['entry']=round(trial.suggest_float('entry',.05 if expanded else .10,.85 if expanded else .60,step=.025),6)
    gap=trial.suggest_float('exit_gap',.05 if expanded else .10,.40,step=.025)
    p['exit']=round(min(.99 if expanded else .95,max(.50 if expanded else .65,p['entry']+gap)),6)
    p['max_hold']=trial.suggest_int('max_hold',1 if expanded else 2,30 if expanded else 20)
    if expanded:
        p['range_window']=trial.suggest_categorical('range_window',[30,40,60,90,120])
    if mechanism=='confirmation':
        p['acf_min']=round(trial.suggest_float('acf_min',-.60 if expanded else -.40,.50 if expanded else .30,step=.025),6)
    elif mechanism=='risk':
        if trial.suggest_categorical('confirm',[False,True]):
            p['acf_min']=round(trial.suggest_float('acf_min',-.60 if expanded else -.40,.50 if expanded else .30,step=.025),6)
        p['stop_loss']=round(trial.suggest_float('stop_loss',.005 if expanded else .02,.18 if expanded else .12,step=.005),6)
        if trial.suggest_categorical('trail',[False,True]):
            p['trailing_stop']=round(trial.suggest_float('trailing_stop',.01 if expanded else .02,.20 if expanded else .15,step=.005),6)
        p['cooldown']=trial.suggest_int('cooldown',0,5 if expanded else 3)
    return p

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['initial','expanded'],required=True)
    parser.add_argument('--per-mechanism',type=int,default=32)
    parser.add_argument('--mechanism',choices=['range','confirmation','risk'])
    args=parser.parse_args()
    research=context()
    first,_=cache_read(TEMP/'precheck.pkl.gz')
    path=WORK/'search_results.json'
    rows=json.loads(path.read_text(encoding='utf-8'))['rows'] if path.exists() else []
    next_number=max([3]+[int(r['candidate_id'][1:]) for r in rows])+1
    existing={configuration_hash(r['parameters']):r for r in rows if r['status']=='SUCCEEDED'}
    elapsed_start=time.perf_counter()
    studies={}
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    for i,mechanism in enumerate(('range','confirmation','risk')):
        if args.mechanism is not None and mechanism!=args.mechanism:
            continue
        name=args.mode+'-'+mechanism
        study_path=TEMP/(name+'.study.pkl.gz')
        study=cache_read(study_path) if study_path.exists() else optuna.create_study(
            direction='maximize',sampler=optuna.samplers.TPESampler(
            seed=13+100*(args.mode=='expanded')+i,constant_liar=True,n_startup_trials=16),study_name=name)
        completed=sum(t.state==optuna.trial.TrialState.COMPLETE for t in study.trials)
        for row in rows:
            if row['search']==name and row['status']!='SUCCEEDED' and row['config_hash'] not in existing:
                study.enqueue_trial(study.trials[row['trial']].params,
                    user_attrs={'explicit_retry_of':row['candidate_id'],'reason':'Windows spawn invalid-handle interruption; outcome unknown'})
        studies[name]=study
        for offset in range(completed,args.per_mechanism,8):
            pending=[]
            trials=[]
            for _ in range(min(8,args.per_mechanism-offset)):
                trial=study.ask()
                parameters=proposal(trial,mechanism,args.mode=='expanded')
                digest=configuration_hash(parameters)
                if digest in existing:
                    trial.set_user_attr('reused_candidate',existing[digest]['candidate_id'])
                    study.tell(trial,search_value(existing[digest]))
                    continue
                number=next_number
                next_number+=1
                trials.append((trial,number,parameters,digest))
                pending.append(research.evaluation.prepare(request(number,parameters,first.execution_data)))
            if pending:
                started=time.perf_counter()
                outcomes=research.evaluation.evaluate_many(tuple(pending))
                failures=[]
                for (trial,number,parameters,digest),bound,outcome in zip(trials,pending,outcomes,strict=True):
                    row={'candidate_id':f'C{number:04}','parameters':parameters,'config_hash':digest,
                         'search':name,'trial':trial.number,'status':outcome.status.value,
                         'trial_attributes':trial.user_attrs}
                    if outcome.status.value=='SUCCEEDED':
                        row.update(summarize(outcome.result))
                        study.tell(trial,search_value(row))
                        existing[digest]=row
                        cache_write(TEMP/f'C{number:04}.pkl.gz',outcome.result)
                    else:
                        row['error']={'code':outcome.error.code,'message':outcome.error.message}
                        study.tell(trial,state=optuna.trial.TrialState.FAIL)
                        failures.append(row)
                    rows.append(row)
                save('search_results.json',{'rows':rows,'versions':{'optuna':importlib.metadata.version('optuna')},
                    'resources':{'max_workers':8,'native_threads':1,'request_workers':1},
                    'last_batch_seconds':time.perf_counter()-started,'updated_at':datetime.now().isoformat()})
                cache_write(TEMP/(name+'.study.pkl.gz'),study)
                group=[r for r in rows if r['search']==name and r['status']=='SUCCEEDED']
                best=min(group,key=lambda r:r['deficit'])
                print(json.dumps({'search':name,'completed':len(group),'qualified':sum(r['qualified'] for r in group),
                    'best':{k:best[k] for k in ('candidate_id','net_cagr','closed_trades','min_dd_margin','deficit','gates')},
                    'batch_seconds':time.perf_counter()-started,'elapsed':time.perf_counter()-elapsed_start}),flush=True)
                if failures:
                    raise RuntimeError('Formal evaluation failed; inspect saved explicit outcomes')
    save(args.mode+('-'+args.mechanism if args.mechanism else '')+'_search_summary.json',{'mode':args.mode,'elapsed_seconds':time.perf_counter()-elapsed_start,
        'studies':{name:{'trials':len(s.trials),'best_value':s.best_value,'best_params':s.best_params} for name,s in studies.items()},
        'selection_pool':'Entire development pool reused; no independent holdout'})

if __name__=='__main__':
    main()
