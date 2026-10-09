"""Same declared accounts, public preparation/evaluation/publication per spawn worker."""
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import get_context
from hashlib import sha256
import time
import optuna
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import EvaluationEvidenceWrite
from czsc_trader.research_tools.assessment import build_assessment_evidence
from common import ROOT, RUNS, PROTOCOLS, CACHE, EXPERIMENT, context, request_for, read, write, cache_write, material

def compute(case):
    research=context(1)
    started=time.perf_counter()
    bound=research.evaluation.prepare(request_for(case))
    outcome=research.evaluation.evaluate_many((bound,))[0]
    row={'candidate_id':case['candidate_id'],'parent':case['parent'],'kind':case['kind'],
        'status':outcome.status.value,'request_hash':outcome.request_hash,
        'plan_sha256':sha256((PROTOCOLS/'plan.json').read_bytes()).hexdigest(),
        'child_content_sha256':case['child_content_sha256']}
    if outcome.status.value=='SUCCEEDED':
        result=outcome.result
        actual=build_assessment_evidence(bound,result)
        ref=publish_evidence(research,EvaluationEvidenceWrite(EXPERIMENT,
            'stage4-'+case['kind'].lower()+'-'+case['candidate_id'].lower(),bound,result))
        row.update(reference=ref.to_dict(),result_hash=result.result_hash,
            evaluations=[x.evaluation_id for x in actual],net_cagr=result.runs[0].observation.net_cagr)
        cache_write(CACHE/(case['candidate_id']+'_'+case['kind'].lower()+'.pkl.gz'),(bound,result))
    else:
        row['error']={'code':outcome.error.code,'message':outcome.error.message}
    row['elapsed_seconds']=time.perf_counter()-started
    write(RUNS/'parallel_cases'/(case['candidate_id']+'_'+case['kind'].lower()+'.json'),row)
    return row

def main():
    assert read(RUNS/'execution_precheck.json')['status']=='PASS'
    assert read(RUNS/'se_precheck.json')['status']=='PASS'
    plan=read(PROTOCOLS/'plan.json')
    plan_hash=sha256((PROTOCOLS/'plan.json').read_bytes()).hexdigest()
    scheduler_path=PROTOCOLS/'scheduler_supplement.json'
    if not scheduler_path.exists():
        write(scheduler_path,{'version':'same-plan-end-to-end-spawn4','date':'2026-10-10',
            'plan_sha256':plan_hash,'reason':'Initial32 public input binding and request authentication consumed >230 serial CPU seconds; move public prepare/evaluate_many/publish to four independent workers.',
            'resources':{'outer_spawn_workers':4,'inner_evaluation_workers':1,'native_threads_per_worker':1,'seed':13},
            'scope':'No candidate, parameter, cost, ranking, data, dependency or eligibility change. No nested process pools or fallback.',
            'verification':'First remaining exact planned bound account is computed in parent serial and one worker; identical request/result hashes required before remaining submission.',
            'original_execution_sources':{p.name:sha256(p.read_bytes()).hexdigest() for p in (ROOT/'research/S013/experiments/EX008_20261010/src').glob('*.py')}})
    assert read(scheduler_path)['plan_sha256']==plan_hash
    ref=material('stage4-scheduler-supplement',scheduler_path)
    write(PROTOCOLS/'scheduler_reference.json',ref.to_dict())
    if (RUNS/'scheduler_precheck.json').exists():
        checked=read(RUNS/'scheduler_precheck.json')
        assert checked['status']=='PASS' and checked['plan_sha256']==plan_hash
    else:
        persisted=list((RUNS/'parallel_cases').glob('*.json'))
        if persisted:
            control=read(RUNS/'scheduler_control.json')
            assert control['plan_sha256']==plan_hash
            assert len(persisted)==1, 'Unverified scheduler attempt cannot be reused or bypassed'
            row=read(persisted[0])
            assert (row['candidate_id'],row['kind'])==(control['case']['candidate_id'],control['case']['kind'])
            assert row['status']=='SUCCEEDED'
            assert (row['request_hash'],row['result_hash'])==(control['request_hash'],control['result_hash']), 'Same first scheduler control failed; retain evidence and repair explicitly'
            write(RUNS/'scheduler_precheck.json',{'status':'PASS','plan_sha256':plan_hash,
                'candidate_id':row['candidate_id'],'request_hash':row['request_hash'],'result_hash':row['result_hash'],
                'scope':'Recovered the original same-account serial/worker control; no control substitution'})
    rows=read(RUNS/'rows.json')['rows']
    done={(r['candidate_id'],r['kind']) for r in rows}
    pending=[c for c in plan['cases'] if (c['candidate_id'],c['kind']) not in done]
    already=[]
    for case in pending:
        path=RUNS/'parallel_cases'/(case['candidate_id']+'_'+case['kind'].lower()+'.json')
        if path.exists():
            row=read(path)
            assert row['status']=='SUCCEEDED'
            assert row['parent']==case['parent']
            assert row['plan_sha256']==plan_hash and row['child_content_sha256']==case['child_content_sha256']
            already.append(row)
    rows.extend(already)
    done={(r['candidate_id'],r['kind']) for r in rows}
    pending=[c for c in plan['cases'] if (c['candidate_id'],c['kind']) not in done]
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study=optuna.create_study(direction='maximize',sampler=optuna.samplers.RandomSampler(seed=13),study_name='S013-stage4-same-plan-parallel')
    for index in range(len(pending)):
        study.enqueue_trial({'configuration':index})
    serial=None
    if not (RUNS/'scheduler_precheck.json').exists() and pending:
        bound=context(1).evaluation.prepare(request_for(pending[0]))
        serial=context(1).evaluation.evaluate(bound)
        write(RUNS/'scheduler_control.json',{'case':pending[0],'request_hash':serial.request_hash,
            'result_hash':serial.result_hash,'plan_sha256':plan_hash})
    started=time.perf_counter()
    with ProcessPoolExecutor(max_workers=4,mp_context=get_context('spawn')) as pool:
        first=0
        if serial is not None:
            trial=study.ask()
            index=trial.suggest_int('configuration',0,len(pending)-1)
            assert index==0
            row=pool.submit(compute,pending[0]).result()
            assert row['status']=='SUCCEEDED'
            assert (row['request_hash'],row['result_hash'])==(serial.request_hash,serial.result_hash)
            write(RUNS/'scheduler_precheck.json',{'status':'PASS','request_hash':serial.request_hash,
                'result_hash':serial.result_hash,'candidate_id':row['candidate_id'],'scope':'Identical public bound account; parent serial vs end-to-end worker. Four account workers plus an orchestration parent; each inner evaluation explicitly 1.',
                'plan_sha256':plan_hash})
            study.tell(trial,row['net_cagr'])
            rows.append(row)
            write(RUNS/'rows.json',{'rows':rows,'complete':False})
            print({'scheduler_precheck':'PASS','progress':len(rows),'total':711},flush=True)
            first=1
        futures={}
        for _ in pending[first:]:
            trial=study.ask()
            index=trial.suggest_int('configuration',0,len(pending)-1)
            futures[pool.submit(compute,pending[index])]=(trial,pending[index])
        for future in as_completed(futures):
            trial,case=futures[future]
            try:
                row=future.result()
            except Exception as exc:
                row={'candidate_id':case['candidate_id'],'kind':case['kind'],'parent':case['parent'],
                    'status':'UNKNOWN','error':{'code':type(exc).__name__,'message':str(exc)}}
                write(RUNS/'parallel_cases'/(case['candidate_id']+'_'+case['kind'].lower()+'.json'),row)
            if row['status']=='SUCCEEDED':
                study.tell(trial,row['net_cagr'])
            else:
                study.tell(trial,state=optuna.trial.TrialState.FAIL)
            rows.append(row)
            write(RUNS/'rows.json',{'rows':rows,'complete':len(rows)==711})
            if len(rows)%8==0 or len(rows)==711:
                print({'progress':len(rows),'total':711,'failed':sum(x['status']!='SUCCEEDED' for x in rows),
                    'scheduler_wall_seconds':round(time.perf_counter()-started,2)},flush=True)
    write(RUNS/'parallel_scheduler.json',{'status':'COMPLETE' if all(x['status']=='SUCCEEDED' for x in rows) else 'INCOMPLETE',
        'plan_sha256':plan_hash,'wall_seconds':time.perf_counter()-started,'computed_requests':len(pending),
        'configuration_index':[{'index':i,'candidate_id':c['candidate_id'],'kind':c['kind']} for i,c in enumerate(pending)],
        'optuna':{'seed':13,'trials':[{'number':t.number,'params':t.params,'value':t.value,'state':t.state.name} for t in study.trials]}})
    assert len(rows)==711 and len({(r['candidate_id'],r['kind']) for r in rows})==711
    assert all(r['status']=='SUCCEEDED' for r in rows)

if __name__=='__main__':
    main()
