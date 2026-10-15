"""Bounded FULL execution: one serial/spawn equivalence pair, one combination."""
import os
for variable in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[variable]='1'
import argparse
from dataclasses import asdict
import time
import pandas as pd
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite, EvaluationEvidenceWrite
from common import (ROOT, SRC, PROTOCOLS, RUNS, CACHE, EXPERIMENT, SOURCE_CALLS, context,
    read, write, request, file_hash, cache_write, cache_read)

def put(ctx,name,path):
    path=path.resolve()
    return publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,name,path.read_bytes(),'application/json','json')).to_dict()

def prepare():
    assert not (PROTOCOLS/'preflight.json').exists(), 'Input preflight already recorded'
    assert read(RUNS/'synthetic_checks.json')['status']=='PASS'
    plan=read(PROTOCOLS/'configurations.json'); ctx=context(1); inputs={}
    for config in plan['configurations']:
        bound=ctx.evaluation.prepare(request(config))
        assert bound.execution_data.pricing.anchor_date.isoformat()=='2019-12-31'
        assert bound.execution_data.pricing.anchor_factor==.2803
        cache_write(CACHE/(config['mode']+'-bound.pkl.gz'),bound)
        inputs[config['mode']]=dict(execution_data_fingerprint=bound.execution_data.fingerprint,
            execution_prepared=dict(space_id=str(bound.execution_data.prepared.space_id),
                preparation_id=str(bound.execution_data.prepared.preparation_id),
                manifest_sha256=bound.execution_data.prepared.manifest_sha256),
            execution_requests={k:asdict(v) for k,v in bound.execution_data.requests.items()},
            input_bindings={k:v.to_dict() for k,v in bound.input_bindings.items()},
            pricing=bound.execution_data.pricing.to_dict(),candidate_identity=config['content_sha256'])
        print({'prepared':config['mode'],'sessions':len(bound.execution_data.evaluation_sessions)},flush=True)
    assert not SOURCE_CALLS
    proof=dict(status='PASS',kind='PUBLIC_PREPARE_AND_SYNTHETIC_PREFLIGHT',
        contract='Two fixed centers; no real strategy history/account calculation yet',
        sources={p.relative_to(ROOT).as_posix():file_hash(p) for p in SRC.rglob('*.py')},
        synthetic=read(RUNS/'synthetic_checks.json'),inputs=inputs,
        source_requests=0,actual_full_account_evaluations=0,
        real_order=['TREND_ONLY serial','same TREND_ONLY spawn equivalence','COMBINED spawn'],
        maximum_full_evaluations=4,planned_full_evaluations=3)
    write(PROTOCOLS/'preflight.json',proof)
    refs=read(PROTOCOLS/'method_references.json')
    refs['preflight.json']=put(ctx,'trend-preflight',(PROTOCOLS/'preflight.json'))
    refs['synthetic_checks.json']=put(ctx,'trend-synthetic-checks',RUNS/'synthetic_checks.json')
    write(PROTOCOLS/'method_references.json',refs)
    print({'preflight':'PASS','source_requests':0,'full_accounts':0},flush=True)

def start(label):
    path=RUNS/'attempts.json'
    ledger=read(path) if path.exists() else dict(maximum=4,attempts=[])
    assert len(ledger['attempts'])<4, 'No evaluation budget left'
    assert label not in [x['label'] for x in ledger['attempts']], 'No automatic retry'
    ledger['attempts'].append(dict(label=label,status='STARTED',full_accounts=1))
    write(path,ledger)

def finish(label,result):
    path=RUNS/'attempts.json'; ledger=read(path)
    row=next(x for x in ledger['attempts'] if x['label']==label)
    row.update(status='SUCCEEDED',request_hash=result.request_hash,result_hash=result.result_hash)
    write(path,ledger)

def compare(first,second):
    assert first.request_hash==second.request_hash
    for a,b in zip(first.runs,second.runs,strict=True):
        pd.testing.assert_frame_equal(a.signals.decisions,b.signals.decisions,check_exact=True)
        for left,right in ((a.execution,b.execution),(a.buyhold.execution,b.buyhold.execution)):
            for field in ('decisions','orders','fills','account_daily','trades'):
                pd.testing.assert_frame_equal(getattr(left,field),getattr(right,field),check_exact=True)
    assert first.result_hash==second.result_hash

def execute():
    assert not (RUNS/'started.json').exists(), 'Already attempted: recovery requires explicit accounting'
    proof=read(PROTOCOLS/'preflight.json'); assert proof['status']=='PASS'
    assert (PROTOCOLS/'peer_review.json').exists(), 'Read-only implementation review required first'
    assert read(PROTOCOLS/'peer_review.json')['status']=='PASS'
    for name,h in proof['sources'].items(): assert file_hash(ROOT/name)==h, name
    write(RUNS/'started.json',dict(status='STARTED',business_configs=2,maximum_full_accounts=4))
    ctx=context(1); bound=cache_read(CACHE/'TREND_ONLY-bound.pkl.gz')
    started=time.perf_counter()
    start('TREND_ONLY_SERIAL'); serial=ctx.evaluation.evaluate(bound)
    cache_write(CACHE/'TREND_ONLY-serial.pkl.gz',(bound,serial)); finish('TREND_ONLY_SERIAL',serial)
    print({'account':'TREND_ONLY_SERIAL','status':'SUCCEEDED','elapsed_seconds':time.perf_counter()-started},flush=True)
    start('TREND_ONLY_SPAWN')
    outcome=context(2).evaluation.evaluate_many((bound,))[0]
    assert outcome.status.value=='SUCCEEDED',outcome.error
    parallel=outcome.result
    cache_write(CACHE/'TREND_ONLY-spawn.pkl.gz',(bound,parallel)); finish('TREND_ONLY_SPAWN',parallel)
    compare(serial,parallel)
    write(RUNS/'serial_spawn_equivalence.json',dict(status='PASS',all_signals='EXACT_EQUAL',
        strategy_and_benchmark_five_ledgers='EXACT_EQUAL',result_hash=serial.result_hash,
        actual_full_account_evaluations=2))
    print({'serial_spawn':'EXACT_EQUAL','elapsed_seconds':time.perf_counter()-started},flush=True)
    refs={}
    refs['TREND_ONLY']=publish_evidence(ctx,EvaluationEvidenceWrite(EXPERIMENT,'trend-only-full-account',bound,serial)).to_dict()
    write(PROTOCOLS/'account_references.json',refs)
    bound=cache_read(CACHE/'COMBINED-bound.pkl.gz')
    start('COMBINED_SPAWN'); outcome=context(2).evaluation.evaluate_many((bound,))[0]
    assert outcome.status.value=='SUCCEEDED',outcome.error
    result=outcome.result
    cache_write(CACHE/'COMBINED-spawn.pkl.gz',(bound,result)); finish('COMBINED_SPAWN',result)
    refs['COMBINED']=publish_evidence(ctx,EvaluationEvidenceWrite(EXPERIMENT,'trend-combined-full-account',bound,result)).to_dict()
    write(PROTOCOLS/'account_references.json',refs)
    assert not SOURCE_CALLS
    write(RUNS/'completion.json',dict(status='PASS',actual_full_accounts=3,new_business_configs=2,
        technical_duplicate_accounts=1,baseline_reused=True,provider_calls=0,model_fits=0,search_trials=0,
        standard32_accounts=0,fee_stress_accounts=0,remaining_full_account_budget=1,
        remaining_experiment_budget=0,research_state='PAUSED',elapsed_seconds=time.perf_counter()-started))
    print({'execution':'COMPLETE','full_accounts':3,'elapsed_seconds':time.perf_counter()-started},flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('action',choices=('prepare','execute'))
    args=parser.parse_args()
    prepare() if args.action=='prepare' else execute()
