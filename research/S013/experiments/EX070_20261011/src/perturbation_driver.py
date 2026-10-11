"""EX070 prospective 14D standard32 and independent fee; finite no optimisation."""
from __future__ import annotations
import os
for n in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[n]='1'
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import argparse,json,shutil,traceback
from pathlib import Path
import driver as d
from strategy_evaluator import AssessmentCandidate,ParameterCoordinate,ParameterCoordinateKind,ParameterDesignRequest,ParameterPerturbationProtocol,ParameterSpace,build_parameter_perturbation_design
from strategy_runtime import StrategyCandidate
from strategy_manager import CandidateDerivation,CandidateDerivationKind,CandidateEvidence,CandidateKey
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import EvaluationCost,EvaluationEvidenceWrite,EvaluationLineage,ParameterEvaluationPlan
from czsc_trader.research_tools.parameter_evaluation import read_parameter_plan
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence
from czsc_trader.research_tools.evidence import EvidenceRef
ROOT,WORK=d.ROOT,d.WORK
FIRST=7070

def plain(x):return json.loads(json.dumps(x,default=dict))
def get(p,n):
    for q in n.split('.'):p=p[q]
    return p
def materialize(p,coords,values):
    p=deepcopy(p)
    for (n,lo,hi,kind),value in zip(coords,values,strict=True):
        parts=n.split('.');target=p
        for q in parts[:-1]:target=target[q]
        target[parts[-1]]=int(value) if kind=='INTEGER' else float(value)
    return p
def feasible(v):return bool(v[1]<v[2] and v[5]<v[6])
def save_state(x):
    (WORK/'perturbation_state.json').write_text(json.dumps(x,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
def material(ctx,exp,path,name,value):
    if Path(path).exists():assert d.read(path)==value,'Prospective bytes mismatch '+str(path)
    else:d.write(path,value)
    return d.put(ctx,exp,path,name)
def context():
    exp,plan,path=d.stage();common=d.oldcommon();ctx=common.context(1)
    return ctx,exp,plan,path,common
def declare():
    ctx,exp,centreplan,path,common=context()
    assert not (WORK/'perturbation_method.json').exists()
    assert d.read(WORK/'verification.json')['economics']['qualified']
    pair=common.cache_read(WORK/'centre.pkl.gz');center=pair[0]
    assert serialize_evaluation_evidence(*pair)==d.read(d.public(d.read(path/'protocols/centre_reference.json')))
    coords=d.read(d.OLD/'protocols/geometry.json')['coordinates']+[['short_confirmation_lookback4',1.,20.,'INTEGER']]
    ids=[f'C{n:04}' for n in range(FIRST,FIRST+32)]
    for ident in ids:
        assert not (ROOT/'research/S013/assets/candidates'/ident).exists()
        assert not (ROOT/'research/registrations/S013/candidates'/(ident+'.json')).exists()
    mapping={'version':'EX070-14-effective-complete-domain-v1','coordinates':coords,'normalisation':'LINEAR full domain widths','integer_rounding':'HALF_EVEN','new_integer_domain_reason':'4-day finite history expression can legally use 1..20 sessions; 20 original volatility horizon. Declared before account sampling; no sample quantile optimisation.'}
    feasibility={'version':'EX070-original-range-order-v1','coordinate_order':coords,'constraints':['bull.entry < bull.exit','bear.entry < bear.exit'],'implementation':'coordinates[1] < coordinates[2] and coordinates[5] < coordinates[6]'}
    mappingref=material(ctx,exp,WORK/'mapping14.json','short-alt-mapping14',mapping)
    feasref=material(ctx,exp,WORK/'feasibility14.json','short-alt-feasibility14',feasibility)
    protocol=ParameterPerturbationProtocol(radius=.05,point_count=32,seed=13)
    params=plain(center.strategy.payload['parameters'])
    space=ParameterSpace(tuple(ParameterCoordinate(n,float(get(params,n)),lo,hi,ParameterCoordinateKind(kind)) for n,lo,hi,kind in coords),mappingref['sha256'],feasref['sha256'])
    result=build_parameter_perturbation_design(ParameterDesignRequest(AssessmentCandidate(center.strategy.reference_id,centreplan['content_sha256']),protocol,space),feasibility=feasible)
    assert result.status.value=='COMPLETE'
    children=[]
    for ident,point in zip(ids,result.design.points,strict=True):
        payload=plain(center.strategy.payload);payload['parameters']=materialize(params,coords,point.coordinates)
        candidate=StrategyCandidate('S013',ident,payload,center.strategy.source_root)
        child=replace(center,strategy=candidate,runtime_binding={**center.runtime_binding,'candidate_id':candidate.reference_id},input_bindings={},lineage=None)
        children.append(ctx.evaluation.prepare(child))
    plan=ParameterEvaluationPlan.create(result.design,center,tuple(children),mapping_evidence=EvidenceRef.from_dict(mappingref),feasibility_evidence=EvidenceRef.from_dict(feasref),dataflows=ctx.data)
    planref=material(ctx,exp,WORK/'parameter_plan14.json','short-alt-parameter-plan14',plan.to_dict())
    bound=[];centreref=d.read(path/'protocols/centre_reference.json')
    for i,child in enumerate(children):
        changes={n:{'before':get(params,n),'after':get(child.strategy.payload['parameters'],n)} for n,*_ in coords if get(params,n)!=get(child.strategy.payload['parameters'],n)}
        derive=CandidateDerivation(CandidateKey('S013','C9070'),centreplan['content_sha256'],CandidateKey('S013',child.strategy.candidate_id),plan.children[i].candidate.content_sha256,CandidateDerivationKind.PARAMETERS,changes,protocol.sha256,CandidateEvidence(EvidenceRef.from_dict(centreref).repository_path,centreref['sha256']))
        bound.append(replace(child,lineage=EvaluationLineage(derive,plan.bind_point(EvidenceRef.from_dict(planref),i,repository_root=ROOT))))
    fee=replace(center,costs=(EvaluationCost('stress_20bp_per_side',.002,'STRESS'),))
    common.cache_write(WORK/'parameter_prepared.pkl.gz',(tuple(bound),fee))
    formal=path/'src/perturbation_driver.py';shutil.copyfile(Path(__file__),formal)
    audit_src=(path/'src/native_audit.py').read_text(encoding='utf-8').replace('def audit(ctx,bound,result,formal,*,new):','def audit(ctx,bound,result,formal,*,new,expected_cost=.001):').replace('bound.costs[0].one_way_cost==.001','bound.costs[0].one_way_cost==expected_cost')
    (path/'src/native_point_audit.py').write_text(audit_src,encoding='utf-8')
    sources={q.relative_to(ROOT).as_posix():d.digest(q) for q in (formal,path/'src/native_point_audit.py')}
    sourcerefs={q.name:d.put(ctx,exp,q,'short-alt-'+q.stem.replace('_','-')) for q in (formal,path/'src/native_point_audit.py')}
    baseline=d.read(ROOT/'research/S013/experiments/EX065_20261011/protocols/method.json')
    method={'status':'PROSPECTIVE_FROZEN','protocol':protocol.to_dict(),'parameter_plan_reference':planref,'mapping_reference':mappingref,'feasibility_reference':feasref,'effective_dimensions':14,'old_baseline_dimensions':13,'paired_point_comparison':False,'comparability':'same total normalized L2 radius .05 and seed13; different dimensions alter direction and per-coordinate amplitudes. No paired point/per-coordinate equal intensity claim.','lookback_actual_counts':dict(Counter(str(int(x.coordinates[-1])) for x in result.design.points)),'candidate_ids':ids,'prepared_cache_sha256':d.digest(WORK/'parameter_prepared.pkl.gz'),'source_files':sources,'source_references':sourcerefs,'budget':{'new_centre_completed':1,'new_standard_points':32,'new_independent_fee':1,'new_financial_total':34,'reused_baseline_standard':33,'reused_baseline_fee':1,'technical_financial_repeats':0},'fee':{'scenario':'stress_20bp_per_side','one_way_cost':.002,'same_centre_rules':True,'no_parameter_cross':True},'baseline_reuse':baseline['baseline_reuse'],'baseline_fee_reuse':baseline['baseline_fee_reuse'],'fivechecks_definition':'S013-EX062-five-independent-checks-v1','provider_calls':common.SOURCE_CALLS,'extra_3_5_diagnostic':'Not declared or run; parent decides separately if all32 lookback stay4.'}
    assert not common.SOURCE_CALLS
    ref=material(ctx,exp,WORK/'perturbation_method.json','short-alt-perturbation-method',method)
    d.write(path/'protocols/perturbation_method_reference.json',ref)
    d.write(path/'protocols/parameter_plan14_reference.json',planref)
    save_state({'status':'DECLARED','accounts':{},'method_reference':ref})
    return {'status':'DECLARED','lookback_actual_counts':method['lookback_actual_counts'],'new_account_total':34}
def stage():
    ctx,exp,centreplan,path,common=context();state=d.read(WORK/'perturbation_state.json')
    method=d.read(d.public(state['method_reference']))
    for q,h in method['source_files'].items():assert d.digest(ROOT/q)==h
    assert d.digest(WORK/'parameter_prepared.pkl.gz')==method['prepared_cache_sha256']
    requests,fee=common.cache_read(WORK/'parameter_prepared.pkl.gz')
    d.audits();audit=d.load('short_point_audit',path/'src/native_point_audit.py')
    return ctx,exp,path,common,state,method,requests,fee,audit
def run():
    ctx,exp,path,common,state,method,requests,fee,audit=stage()
    for label,request in [(f'P{i:02}',r) for i,r in enumerate(requests)]+[('FEE',fee)]:
        item=state['accounts'].get(label)
        if item and item['status']=='AUDITED':continue
        if item and item['status']=='INFLIGHT':raise RuntimeError('uncertain finance cannot retry '+label)
        cache=WORK/'parameters'/(label+'.pkl.gz')
        if item is None:
            state['accounts'][label]={'status':'INFLIGHT'};save_state(state)
            result=ctx.evaluation.evaluate(request)
            common.cache_write(cache,(request,result))
            ref=publish_evidence(ctx,EvaluationEvidenceWrite(exp,'short-alt-'+label.lower()+'-native',request,result)).to_dict()
            item={'status':'NATIVE_COMPLETE','reference':ref,'cache':cache.relative_to(ROOT).as_posix(),'cache_sha256':d.digest(cache),'request_hash':result.request_hash,'result_hash':result.result_hash}
            state['accounts'][label]=item;save_state(state)
        else:
            assert d.digest(cache)==item['cache_sha256'];request,result=common.cache_read(cache)
        report=audit.audit(ctx,request,result,d.read(d.public(item['reference'])),new=True,expected_cost=.002 if label=='FEE' else .001)
        report['actual_label']=label;report['parameter_diagnostic_status']='DECLARED14D_STANDARD32' if label!='FEE' else 'INDEPENDENT_DOUBLE_FEE'
        reportref=material(ctx,exp,WORK/'parameters'/(label+'-audit.json'),'short-alt-'+label.lower()+'-independent-audit',report)
        item.update(status='AUDITED',audit_reference=reportref,economics=report['economics']);save_state(state)
        assert not common.SOURCE_CALLS
        print(json.dumps({'label':label,'status':'AUDITED','cagr':report['economics']['net_cagr'],'qualified':report['economics']['qualified']},ensure_ascii=False),flush=True)
    state['status']='FINANCIAL34_COMPLETE';save_state(state)
    return {'status':state['status'],'new_financial_total':34}
def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('declare','run'));args=parser.parse_args()
    try:print(json.dumps(globals()[args.action](),ensure_ascii=False),flush=True)
    except Exception:
        print(traceback.format_exc(),flush=True);raise
if __name__=='__main__':main()
