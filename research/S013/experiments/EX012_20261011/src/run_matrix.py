"""One prospectively fixed Optuna queue; FULL TDR spawn evaluations."""
# ruff: noqa: E402
import os
for variable in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[variable]='1'
import time
import optuna
from common import (SOURCE, PROTOCOLS, RUNS, CACHE, WORKERS, SOURCE_CALLS, read, write,
                    request, context, cache_read, cache_write, file_hash)

def main():
    assert read(RUNS/'precheck.json')['status']=='PASS'
    assert not (RUNS/'matrix.json').exists(), 'Recorded matrix requires explicit recovery'
    plan=read(PROTOCOLS/'plan.json')
    for filename,expected in plan['source_files'].items():
        assert file_hash(SOURCE/filename)==expected
    study=optuna.create_study(direction='maximize',study_name=plan['name'],
        sampler=optuna.samplers.RandomSampler(seed=13))
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    for index in range(12):
        study.enqueue_trial({'configuration':index})
    research=context()
    started=time.perf_counter()
    rows=[]
    for offset in range(0,12,WORKERS):
        selected=[]
        pending=[]
        for index in range(offset,min(offset+WORKERS,12)):
            trial=study.ask()
            assert trial.suggest_int('configuration',0,11)==index
            config=plan['configurations'][index]
            label=config['background']+'-'+config['mode']
            if label=='B0-M1':
                bound,result=cache_read(CACHE/(label+'.pkl.gz'))
            else:
                bound=research.evaluation.prepare(request(config))
                result=None
                pending.append(bound)
            selected.append((trial,config,bound,result))
        print({'prepared_batch':len(selected),'pending_evaluations':len(pending)},flush=True)
        outcomes=iter(research.evaluation.evaluate_many(tuple(pending)))
        for trial,config,bound,result in selected:
            outcome=None if result is not None else next(outcomes)
            status='SUCCEEDED' if outcome is None else outcome.status.value
            row={k:config[k] for k in ('index','background','mode','candidate_id','content_sha256')}
            row.update(status=status,trial=trial.number)
            if status=='SUCCEEDED':
                result=result if result is not None else outcome.result
                assert result.runs[0].identity.content_sha256==config['content_sha256']
                row.update(net_cagr=result.runs[0].observation.net_cagr,
                           request_hash=result.request_hash,result_hash=result.result_hash)
                cache_write(CACHE/(config['background']+'-'+config['mode']+'.pkl.gz'),(bound,result))
                study.tell(trial,float(row['net_cagr']))
            else:
                row['error']={'code':outcome.error.code,'message':outcome.error.message}
                study.tell(trial,state=optuna.trial.TrialState.FAIL)
            rows.append(row)
        write(RUNS/'matrix.json',{'status':'COMPLETE' if len(rows)==12 else 'PARTIAL',
            'rows':rows,'workers':WORKERS,'elapsed_seconds':time.perf_counter()-started,
            'provider_calls':SOURCE_CALLS})
        cache_write(CACHE/'study.pkl.gz',study)
        print({'completed':len(rows),'succeeded':sum(r['status']=='SUCCEEDED' for r in rows),
               'elapsed_seconds':time.perf_counter()-started},flush=True)
        if any(r['status']!='SUCCEEDED' for r in rows):
            raise RuntimeError('Failed/unknown outcomes recorded; no automatic retry')
    assert not SOURCE_CALLS

if __name__=='__main__':
    main()
