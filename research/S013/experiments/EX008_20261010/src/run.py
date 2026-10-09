"""Bounded spawn evaluations; each exact planned case is independently preserved."""
import argparse
import time
from hashlib import sha256
import optuna
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import EvaluationEvidenceWrite
from czsc_trader.research_tools.assessment import build_assessment_evidence
from common import PROTOCOLS, RUNS, CACHE, EXPERIMENT, context, request_for, write, cache_write, read

def execute(cases, label, *, check=False):
    research = context(4)
    study = optuna.create_study(direction='maximize', sampler=optuna.samplers.RandomSampler(seed=13),
        study_name='S013-stage4-'+label)
    for index in range(len(cases)):
        study.enqueue_trial({'configuration':index})
    pending, trials = [], []
    for _ in cases:
        trial = study.ask()
        index = trial.suggest_int('configuration',0,len(cases)-1)
        case = cases[index]
        bound = research.evaluation.prepare(request_for(case))
        pending.append(bound)
        trials.append((trial,case))
    serial = research.evaluation.evaluate(pending[0]) if check else None
    started = time.perf_counter()
    outcomes = research.evaluation.evaluate_many(tuple(pending))
    if check:
        assert outcomes[0].status.value == 'SUCCEEDED'
        assert serial.result_hash == outcomes[0].result.result_hash
        write(RUNS/'execution_precheck.json', {'status':'PASS','scope':'same bound full-account serial/spawn4 equality; five implementation families transmitted',
            'request_hash':serial.request_hash,'result_hash':serial.result_hash,'workers':4,'native_threads':1,
            'provider_access':'forbidden; existing prepared assets only'})
    rows = []
    for (trial,case),bound,outcome in zip(trials,pending,outcomes,strict=True):
        row = {'candidate_id':case['candidate_id'],'parent':case['parent'],'kind':case['kind'],
            'status':outcome.status.value,'request_hash':outcome.request_hash,'trial':trial.number}
        if outcome.status.value == 'SUCCEEDED':
            result = outcome.result
            facts = build_assessment_evidence(bound,result)
            ref = publish_evidence(research, EvaluationEvidenceWrite(EXPERIMENT,
                'stage4-'+case['kind'].lower()+'-'+case['candidate_id'].lower(),bound,result))
            row.update(reference=ref.to_dict(),result_hash=result.result_hash,
                evaluations=[x.evaluation_id for x in facts])
            cache_write(CACHE/(case['candidate_id']+'_'+case['kind'].lower()+'.pkl.gz'),(bound,result))
            study.tell(trial,result.runs[0].observation.net_cagr)
        else:
            row['error']={'code':outcome.error.code,'message':outcome.error.message}
            study.tell(trial,state=optuna.trial.TrialState.FAIL)
        rows.append(row)
    record = {'label':label,'elapsed_seconds':time.perf_counter()-started,'rows':rows,
        'plan_sha256':sha256((PROTOCOLS/'plan.json').read_bytes()).hexdigest(),
        'optuna':{'seed':13,'trials':[{'number':t.number,'params':t.params,'value':t.value,'state':t.state.name} for t in study.trials]}}
    write(RUNS/(label+'.json'),record)
    print({'label':label,'completed':len(rows),'success':sum(r['status']=='SUCCEEDED' for r in rows),
        'seconds':round(record['elapsed_seconds'],2)},flush=True)
    if any(r['status']!='SUCCEEDED' for r in rows):
        raise RuntimeError('Declared failed attempts preserved; explicit successor retry required')
    return rows

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--precheck',action='store_true')
    args=parser.parse_args()
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    plan=read(PROTOCOLS/'plan.json')
    if args.precheck:
        assert not (RUNS/'precheck_cases.json').exists()
        seen, chosen=set(),[]
        for c in plan['cases']:
            if c['kind']=='PARAMETERS' and c['parent_source_sha256'] not in seen:
                chosen.append(c)
                seen.add(c['parent_source_sha256'])
        assert len(chosen)==5
        for c in plan['cases']:
            if c['kind']=='STRESS' and c['parent']['key']['candidate_id'] in {x['parent']['key']['candidate_id'] for x in chosen}:
                chosen.append(c)
        assert len(chosen)==10
        execute(chosen,'precheck_cases',check=True)
        return
    assert read(RUNS/'execution_precheck.json')['status']=='PASS'
    rows=read(RUNS/'precheck_cases.json')['rows']
    done={(r['candidate_id'],r['kind']) for r in rows}
    remaining=[c for c in plan['cases'] if (c['candidate_id'],c['kind']) not in done]
    for start in range(0,len(remaining),32):
        label=f'batch_{start//32:02}'
        path=RUNS/(label+'.json')
        if path.exists():
            record=read(path)
            assert all(r['status']=='SUCCEEDED' for r in record['rows'])
            assert record['plan_sha256']==sha256((PROTOCOLS/'plan.json').read_bytes()).hexdigest()
            assert [(r['candidate_id'],r['kind']) for r in record['rows']]==[(c['candidate_id'],c['kind']) for c in remaining[start:start+32]]
            batch=record['rows']
        else:
            batch=execute(remaining[start:start+32],label)
        rows.extend(batch)
        write(RUNS/'rows.json',{'rows':rows,'complete':len(rows)==len(plan['cases'])})
        print({'progress':len(rows),'total':len(plan['cases'])},flush=True)
        if start==0:
            from precheck_se import main as precheck_se
            precheck_se()
    assert len(rows)==711 and len({(r['candidate_id'],r['kind']) for r in rows})==711

if __name__=='__main__':
    main()
