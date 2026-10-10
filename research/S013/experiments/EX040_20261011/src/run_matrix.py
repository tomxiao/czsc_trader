"""Fixed two-configuration queue, one prechecked reuse and one new spawn evaluations."""
# ruff: noqa: E402
import os
for variable in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[variable]='1'
import time
import optuna
from common import PROTOCOLS,RUNS,CACHE,SRC,WORKERS,SOURCE_CALLS,read,write,request,context,cache_read,cache_write,file_hash

def main():
    assert read(RUNS/'precheck.json')['status']=='PASS'
    assert not (RUNS/'matrix.json').exists()
    plan=read(PROTOCOLS/'plan.json')
    for path,digest in plan['source_files'].items():
        assert file_hash(SRC/path)==digest
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study=optuna.create_study(direction='maximize',study_name=plan['name'],sampler=optuna.samplers.RandomSampler(seed=13))
    for index in range(4):
        study.enqueue_trial({'configuration':index})
    ctx=context(WORKERS)
    selected=[]
    pending=[]
    started=time.perf_counter()
    for index in range(4):
        trial=study.ask()
        assert trial.suggest_int('configuration',0,3)==index
        config=plan['configurations'][index]
        if config['label']=='N0':
            bound,result=cache_read(CACHE/'N0.pkl.gz')
        else:
            bound=ctx.evaluation.prepare(request(config))
            result=None
            pending.append(bound)
        selected.append((trial,config,bound,result))
    print({'fixed_configurations':4,'pending_spawn_accounts':len(pending)},flush=True)
    outcomes=iter(ctx.evaluation.evaluate_many(tuple(pending)))
    rows=[]
    for trial,config,bound,result in selected:
        outcome=None if result is not None else next(outcomes)
        status='SUCCEEDED' if outcome is None else outcome.status.value
        row={k:config[k] for k in ('label','index','candidate_id','content_sha256')}
        row.update(status=status,trial=trial.number,prechecked_reuse=outcome is None)
        if status=='SUCCEEDED':
            result=result if result is not None else outcome.result
            assert result.runs[0].identity.content_sha256==config['content_sha256']
            row.update(net_cagr=result.runs[0].observation.net_cagr,request_hash=result.request_hash,result_hash=result.result_hash)
            cache_write(CACHE/(config['label']+'.pkl.gz'),(bound,result))
            study.tell(trial,float(row['net_cagr']))
        else:
            row['error']={'code':outcome.error.code,'message':outcome.error.message}
            study.tell(trial,state=optuna.trial.TrialState.FAIL)
        rows.append(row)
        write(RUNS/'matrix.json',{'status':'COMPLETE' if len(rows)==4 else 'PARTIAL','rows':rows,
            'workers':WORKERS,'elapsed_seconds':time.perf_counter()-started,'provider_calls':SOURCE_CALLS,
            'new_account_evaluations':5,'new_business_configurations':4,'historical_controls':2})
    cache_write(CACHE/'study.pkl.gz',study)
    assert all(r['status']=='SUCCEEDED' for r in rows), rows
    assert not SOURCE_CALLS
    print({'matrix':'COMPLETE','successful':len(rows),'seconds':time.perf_counter()-started},flush=True)

if __name__=='__main__':
    main()
