"""Prospective technical correction of mathematical score ties; preserve r1."""
# ruff: noqa: E402
import os
for variable in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[variable]='1'
import shutil
from copy import deepcopy
import importlib.util
import types
import sys
import optuna
import numpy as np
import pandas as pd
from czsc_trader.application import publish_evidence, publish_evidence_many
from czsc_trader.research_tools import MaterialEvidenceWrite, EvaluationEvidenceWrite
from strategy_runtime import StrategyCandidate, StrategyRuntime, ParameterSet, implementation_sha256
from common import (SRC,SOURCE,PROTOCOLS,RUNS,CACHE,EXPERIMENT,DEPENDENCIES,
                    context,read,write,request,cache_read,cache_write,file_hash)

def main():
    assert not (PROTOCOLS/'plan_r2.json').exists()
    ctx=context()
    first=read(PROTOCOLS/'plan.json')
    originals=[]
    tie_audit=[]
    for config in first['configurations']:
        if config['mode'] not in ('M2','M3'):
            continue
        label=config['background']+'-'+config['mode']
        bound,result=cache_read(CACHE/(label+'.pkl.gz'))
        frame=result.runs[0].execution.decisions
        ties=frame.confirmation_delta.abs().lt(1e-12)
        tie_audit.append({'label':label,'near_zero_nonzero_days':int((ties & frame.confirmation_delta.ne(0)).sum()),
            'near_zero_opportunities':frame.loc[ties & frame.confirmation_opportunity,
                ['signal_date','confirmation_delta','signal_reason']].astype(str).to_dict('records')})
        originals.append(EvaluationEvidenceWrite(EXPERIMENT,'mechanism-r1-numeric-attempt-'+label.lower(),bound,result))
        cache_write(CACHE/(label+'-r1.pkl.gz'),(bound,result))
    publications=publish_evidence_many(ctx,tuple(originals))
    assert all(p.status.value=='PUBLISHED' for p in publications),[(p.status,p.error) for p in publications]
    old_refs=[p.reference.to_dict() for p in publications]
    write(RUNS/'numeric_r1_references.json',old_refs)
    second_source=SRC/'exact_delta/strategy_runtime'
    shutil.copytree(SOURCE,second_source)
    path=second_source/'strategies/score_change_range.py'
    source=path.read_text(encoding='utf-8')
    old='        score_delta = score.diff().reindex(sessions)'
    assert source.count(old)==1
    source=source.replace(old,'''        if c['profile'] != 'all' or settings['weighting'] != 'EQUAL_BLOCKS':
            raise ValueError('exact change gate requires the approved all/equal-blocks score')
        # Midrank has denominator 2*N; .5/.25/.25 weights give exact units 1/(8*N).
        # Rounding only removes arithmetic tails, never a business threshold.
        scale = 8 * c['lookback']
        exact_score_units = np.rint(score * scale)
        score_delta = (exact_score_units.diff() / scale).reindex(sessions)''')
    path.write_text(source,encoding='utf-8',newline='\n')
    second=deepcopy(first)
    second['revision']='technical-r2-exact-midrank-ties'
    second['original_plan_sha256']=file_hash(PROTOCOLS/'plan.json')
    for config in second['configurations']:
        if config['mode'] not in ('M2','M3'):
            continue
        config['prior_candidate_id']=config['candidate_id']
        config['prior_content_sha256']=config['content_sha256']
        config['source_directory']='exact_delta/strategy_runtime'
        config['candidate_id']=f"C{7020+config['index']:04d}"
        runtime=config['payload']['runtime']
        runtime['source_sha256']=implementation_sha256(runtime['source_files'],source_root=second_source)
        candidate=StrategyCandidate('S013',config['candidate_id'],config['payload'],second_source)
        config['content_sha256']=StrategyRuntime().identify(candidate,dependencies=DEPENDENCIES).content_sha256
    second['source_files']={p.relative_to(second_source).as_posix():file_hash(p)
                            for p in second_source.rglob('*.py')}
    second['numeric_correction']={'audit':tie_audit,'retained_original_accounts':old_refs,
        'definition':'Exact integer rank units 1/(8*N), same approved S(T)-S(T-1)>=0 or <=0. All profiles/weights fixed to approved all/equal blocks.',
        'scope':'Same 12 business configurations. Six changed technical identities replayed; no new parameter search. Old source and outcomes retained, not overwritten.'}
    write(PROTOCOLS/'plan_r2.json',second)
    ref=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'mechanism-exact-tie-correction-plan',
        (PROTOCOLS/'plan_r2.json').read_bytes(),'application/json','json'))
    write(PROTOCOLS/'plan_r2_reference.json',ref.to_dict())
    # Check the corrected arithmetic on actual known input, before full replays.
    package=types.ModuleType('_s013_exact_delta_check')
    package.__path__=[str(second_source/'strategies')]
    sys.modules[package.__name__]=package
    spec=importlib.util.spec_from_file_location(package.__name__+'.score_change_range',path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    bound,_=cache_read(CACHE/'B0-M2-r1.pkl.gz')
    binding=next(iter(bound.input_bindings.values()))
    fetched=ctx.data.fetch(binding.plan.requests['daily'],prepared=binding.prepared)
    assert fetched.ready,fetched.error
    sessions=pd.DatetimeIndex(pd.to_datetime(cache_read(CACHE/'B0-M2-r1.pkl.gz')[1].runs[0].execution.decisions.signal_date))
    histories=[]
    for direction in (1,-1):
        p=deepcopy(second['configurations'][2]['payload']['parameters'])
        p['confirmation']['direction']=direction
        instance=module.ScoreChangeRange(ParameterSet(p))
        history=instance.calculate_history({'daily':fetched.dataframe},sessions)
        assert history.confirmation_pass[history.confirmation_delta.eq(0)].all()
        cutoff=sessions[80]
        prefix=instance.calculate_history({'daily':fetched.dataframe.loc[
            pd.to_datetime(fetched.dataframe.Date)<=cutoff]},sessions[:81])
        pd.testing.assert_frame_equal(history.loc[:cutoff],prefix,check_exact=True)
        histories.append(history)
    pd.testing.assert_series_equal(histories[0].confirmation_delta,histories[1].confirmation_delta,check_exact=True)
    assert np.all(histories[0].confirmation_pass | histories[1].confirmation_pass)
    proof={'status':'PASS','equal_days':int(histories[0].confirmation_delta.eq(0).sum()),
        'checks':['exact rank-lattice arithmetic','all mathematical ties pass both',
                  'positive/negative exhaustive partition with equality overlap','actual causal prefix']}
    write(RUNS/'exact_tie_precheck.json',proof)
    proof_ref=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'mechanism-exact-tie-precheck',
        (RUNS/'exact_tie_precheck.json').read_bytes(),'application/json','json'))
    write(PROTOCOLS/'exact_tie_precheck_reference.json',proof_ref.to_dict())
    configs=[c for c in second['configurations'] if c['mode'] in ('M2','M3')]
    study=optuna.create_study(direction='maximize',sampler=optuna.samplers.RandomSampler(seed=13))
    trials=[]
    for i in range(6):
        study.enqueue_trial({'configuration':i})
    requests=[]
    for i,config in enumerate(configs):
        trial=study.ask()
        assert trial.suggest_int('configuration',0,5)==i
        trials.append(trial)
        requests.append(ctx.evaluation.prepare(request(config)))
    print({'exact_tie_precheck':'PASS','pending_correction_replays':6},flush=True)
    outcomes=ctx.evaluation.evaluate_many(tuple(requests))
    corrected=[]
    for config,trial,bound,outcome in zip(configs,trials,requests,outcomes,strict=True):
        row={key:config[key] for key in ('background','mode','candidate_id','content_sha256')}
        row['status']=outcome.status.value
        if outcome.status.value=='SUCCEEDED':
            result=outcome.result
            cache_write(CACHE/(config['background']+'-'+config['mode']+'.pkl.gz'),(bound,result))
            row.update(result_hash=result.result_hash,net_cagr=result.runs[0].observation.net_cagr)
            study.tell(trial,float(row['net_cagr']))
        else:
            row['error']={'code':outcome.error.code,'message':outcome.error.message}
            study.tell(trial,state=optuna.trial.TrialState.FAIL)
        corrected.append(row)
    write(RUNS/'numeric_correction.json',{'status':'PASS' if all(r['status']=='SUCCEEDED' for r in corrected) else 'FAILED',
        'rows':corrected,'prior_accounts':old_refs,'numeric_audit':tie_audit,'precheck':proof})
    assert all(r['status']=='SUCCEEDED' for r in corrected),corrected
    print({'correction':'PASS','replayed':6},flush=True)

if __name__=='__main__':
    main()
