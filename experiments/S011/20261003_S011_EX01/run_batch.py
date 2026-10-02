"""Parent-owned fixed Optuna queue, isolated spawn workers, persistent outcomes."""
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import redirect_stdout, redirect_stderr
from multiprocessing import get_context
from pathlib import Path
import json
import os
import runpy
import sys
import time
import optuna

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[2]


def run_one(name):
    folder=REPO/'.tmp/s011-full-redelivery/logs';folder.mkdir(parents=True,exist_ok=True)
    started=time.time()
    with (folder/(name+'.log')).open('w',encoding='utf-8') as log:
        with redirect_stdout(log),redirect_stderr(log):
            runpy.run_path(str(ROOT.parent/name/'run_experiment.py'),run_name='__main__')
    return dict(experiment=name,pid=os.getpid(),started=started,finished=time.time())


def main(stage):
    destination=ROOT/f'{stage}_batch_result.json'
    assert not destination.exists()
    spec=json.loads((ROOT/f'{stage}_batch_specs.json').read_text())
    assert optuna.__version__==spec['optuna_version']
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        os.environ[name]='1'
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    study=optuna.create_study(storage=optuna.storages.InMemoryStorage(),sampler=optuna.samplers.RandomSampler(seed=spec['seed']))
    slots=[slot for job in spec['jobs'] for slot in job['slots']]
    trials={}
    for slot in slots:
        study.enqueue_trial({'candidate':slot})
        trial=study.ask();assert trial.suggest_categorical('candidate',slots)==slot
        trials[slot]=trial
    completed=[];errors=[]

    def save():
        value=dict(storage='InMemoryStorage',adaptive_search=False,workers=spec['workers'],native_threads=1,
            completed=completed,errors=errors,
            trials=[dict(number=t.number,candidate=t.params['candidate'],state=t.state.name) for t in study.trials])
        destination.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')

    with ProcessPoolExecutor(max_workers=spec['workers'],mp_context=get_context('spawn')) as pool:
        jobs={pool.submit(run_one,job['experiment']):job for job in spec['jobs']}
        for future in as_completed(jobs):
            job=jobs[future]
            try:
                completed.append(future.result())
                for slot in job['slots']:study.tell(trials[slot],0.)
                print(json.dumps(dict(stage=stage,completed=len(completed),experiment=job['experiment'])),flush=True)
            except Exception as exc:
                errors.append(dict(experiment=job['experiment'],error=str(exc)))
                for slot in job['slots']:study.tell(trials[slot],state=optuna.trial.TrialState.FAIL)
                for pending in jobs:pending.cancel()
            save()
    assert not errors and len(completed)==len(spec['jobs']),errors
    print(json.dumps(dict(stage=stage,status='PASS',slots=len(slots))),flush=True)


if __name__=='__main__':
    main(sys.argv[1])
