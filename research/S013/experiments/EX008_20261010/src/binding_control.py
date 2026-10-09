"""Same-parameter controls separate input-rebinding effects from perturbation effects."""
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from dataclasses import replace
from hashlib import sha256
import importlib.util
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import EvaluationCost, EvaluationEvidenceWrite
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence
from common import ROOT, RUNS, PROTOCOLS, EXPERIMENT, context, request_for, read, write, material, center_cache, cache_read

def compare_module():
    path=ROOT/'research/S013/experiments/EX007_20261009/src/economic_equivalence.py'
    spec=importlib.util.spec_from_file_location('s013_exact_economics',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def compute(case):
    research=context(1)
    identifier=case['candidate_id']
    old,previous=cache_read(center_cache(identifier))
    bound=research.evaluation.prepare(replace(request_for(case),costs=(EvaluationCost('baseline',.001,'FORMAL'),)))
    outcome=research.evaluation.evaluate_many((bound,))[0]
    row={'candidate_id':identifier,'status':outcome.status.value}
    if outcome.status.value!='SUCCEEDED':
        row['error']={'code':outcome.error.code,'message':outcome.error.message}
    else:
        result=outcome.result
        ref=publish_evidence(research,EvaluationEvidenceWrite(EXPERIMENT,'stage4-rebound-baseline-'+identifier.lower(),bound,result))
        row.update(reference=ref.to_dict(),old_request_hash=previous.request_hash,new_request_hash=result.request_hash,
            old_result_hash=previous.result_hash,new_result_hash=result.result_hash,
            old_cagr=previous.runs[0].observation.net_cagr,new_cagr=result.runs[0].observation.net_cagr)
        before=serialize_evaluation_evidence(old,previous)
        after=serialize_evaluation_evidence(bound,result)
        try:
            row['comparison']=compare_module().compare_evidence(before,after)
        except AssertionError as exc:
            row['comparison']={'status':'FAIL','error':str(exc)}
        row['old_input_bindings']=before['input_bindings']
        row['new_input_bindings']=after['input_bindings']
    write(RUNS/'binding_controls'/(identifier+'.json'),row)
    return row

def main():
    plan=read(PROTOCOLS/'plan.json')
    identifiers={'C9018','C1000','C2000','C2100','C3008','C2132','C3107','C2308'}
    cases=[c for c in plan['cases'] if c['kind']=='STRESS' and c['candidate_id'] in identifiers]
    assert len(cases)==8
    path=PROTOCOLS/'binding_control_plan.json'
    if not path.exists():
        write(path,{'date':'2026-10-10','main_plan_sha256':sha256((PROTOCOLS/'plan.json').read_bytes()).hexdigest(),
            'basis':'All632 perturbed accounts fail overall CAGR. Before interpreting sensitivity, verify unchanged parameters under a newly prepared signal binding against original formal accounts.',
            'cases':cases,'resources':{'outer_workers':4,'inner_workers':1,'native_threads':1},
            'qualification':'exact economic tables/dtypes/relational ID structure; no cash tolerance',
            'scope':'technical controls only; same identities/parameters/10bp/data; not new parameter trials or a changed economic gate'})
    ref=material('stage4-binding-control-plan',path)
    write(PROTOCOLS/'binding_control_reference.json',ref.to_dict())
    with ProcessPoolExecutor(max_workers=4,mp_context=get_context('spawn')) as pool:
        rows=list(pool.map(compute,cases))
    passed=all(r['status']=='SUCCEEDED' and r['comparison']['status']=='PASS' for r in rows)
    write(RUNS/'binding_controls.json',{'status':'PASS' if passed else 'FAIL','scope':'8 unchanged-parameter baseline controls across five implementations',
        'plan':ref.to_dict(),'rows':rows,'trial_count':'unchanged; repeated points are technical controls'})
    print({'binding_controls':'PASS' if passed else 'FAIL','rows':[{'candidate_id':r['candidate_id'],'comparison':r.get('comparison'),
        'old_cagr':r.get('old_cagr'),'new_cagr':r.get('new_cagr')} for r in rows]},flush=True)
    assert passed,'Same-parameter input rebinding changes economic facts; perturbation conclusions require a preserved successor correction'

if __name__=='__main__':
    main()
