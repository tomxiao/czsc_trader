"""EX070 separately authorised fixed3/5 sensitivity; never replace32 or optimise."""
from __future__ import annotations
import os
for n in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[n]='1'
from dataclasses import replace
from copy import deepcopy
import json,argparse,shutil
from pathlib import Path
import driver as d
import perturbation_driver as p
from strategy_runtime import StrategyCandidate
from strategy_manager import CandidateDerivation,CandidateDerivationKind,CandidateEvidence,CandidateKey
from czsc_trader.research_tools import EvaluationLineage,EvaluationEvidenceWrite
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence
WORK,ROOT=d.WORK,d.ROOT

def declare():
    ctx,exp,path,common,state,method,requests,fee,audit=p.stage()
    assert method['lookback_actual_counts']=={'4':32}
    assert not (WORK/'neighbour_method.json').exists()
    centre,result=common.cache_read(WORK/'centre.pkl.gz');ref=d.read(path/'protocols/centre_reference.json')
    reqs=[];manifest=[]
    for lookback,cid in ((3,'C7102'),(5,'C7103')):
        assert not (ROOT/'research/S013/assets/candidates'/cid).exists()
        assert not (ROOT/'research/registrations/S013/candidates'/(cid+'.json')).exists()
        payload=p.plain(centre.strategy.payload);payload['parameters']['short_confirmation_lookback4']=lookback
        child=StrategyCandidate('S013',cid,payload,centre.strategy.source_root)
        ident=ctx.runtime.identify(child,dependencies=centre.dependencies)
        derive=CandidateDerivation(CandidateKey('S013','C9070'),ctx.runtime.identify(centre.strategy,dependencies=centre.dependencies).content_sha256,CandidateKey('S013',cid),ident.content_sha256,CandidateDerivationKind.PARAMETERS,{'short_confirmation_lookback4':{'before':4,'after':lookback}},method['parameter_plan_reference']['sha256'],CandidateEvidence(EvidenceRef.from_dict(ref).repository_path,ref['sha256']))
        request=ctx.evaluation.prepare(replace(centre,strategy=child,runtime_binding={**centre.runtime_binding,'candidate_id':child.reference_id},input_bindings={},lineage=EvaluationLineage(derive)))
        reqs.append(request);manifest.append({'lookback':lookback,'candidate_id':cid,'content_sha256':ident.content_sha256,'payload':payload,'input_bindings':{k:v.to_dict() for k,v in request.input_bindings.items()}})
    common.cache_write(WORK/'neighbours_prepared.pkl.gz',tuple(reqs))
    formal=path/'src/neighbour_driver.py';shutil.copyfile(Path(__file__),formal)
    failed=WORK/'perturbation_driver_failed_declaration.py'
    failure={'status':'TECHNICAL_PREACCOUNT_DECLARATION_FAILED','financial_accounts':0,'source_sha256':d.digest(failed),'failed_line':72,'failed_assertion':"CandidateEvidence(centreref['repository_path'],centreref['sha256'])",'exception':"KeyError: 'repository_path'",'traceback':'File .tmp/s013-short-alt/perturbation_driver.py, line123, main -> line72, declare -> CandidateEvidence(centreref[repository_path],centreref[sha256]); KeyError: repository_path','fix':'Use EvidenceRef.from_dict(centreref).repository_path; EvidenceRef.to_dict intentionally omits computed property. Scientific runtime, point geometry/materialisation and all financial rules unchanged; public plan bytes resumed exact, no financial attempt.'}
    d.write(WORK/'perturbation_declaration_failure.json',failure)
    technical={'failure':d.put(ctx,exp,WORK/'perturbation_declaration_failure.json'),'failed_source':d.put(ctx,exp,failed),'corrected_prospective_method':state['method_reference']}
    method2={'status':'PROSPECTIVE_NEIGHBOUR_FROZEN','reason':'14D canonical standard32 all round to lookback4. Root separately authorised fixed3 and5 to reveal local integer sensitivity; no optimise/select/update centre, no replacement of prescribed32, no new hardgate.','previous_34_method':state['method_reference'],'previous_budget_preserved':method['budget'],'new_budget':{'centre':1,'standard32':32,'independent_fee':1,'local_integer_neighbours':2,'new_total':36,'technical_financial_repeats':0,'baseline_reuse':34},'accounts':manifest,'prepared_cache_sha256':d.digest(WORK/'neighbours_prepared.pkl.gz'),'source_files':{formal.relative_to(ROOT).as_posix():d.digest(formal)},'source_reference':d.put(ctx,exp,formal),'technical_declaration_revision':technical,'standard_point_binding':None,'diagnostic_only':True,'provider_calls':common.SOURCE_CALLS}
    assert not common.SOURCE_CALLS
    ref2=p.material(ctx,exp,WORK/'neighbour_method.json','short-alt-local-integer-neighbours-method',method2)
    d.write(path/'protocols/neighbour_method_reference.json',ref2)
    (WORK/'neighbours_state.json').write_text(json.dumps({'status':'DECLARED','method_reference':ref2,'accounts':{}},indent=2)+'\n',encoding='utf-8')
    return {'status':'NEIGHBOURS_DECLARED','new_total_financial_budget':36}
def run():
    ctx,exp,path,common,state,method,requests,fee,audit=p.stage()
    assert state['status']=='FINANCIAL34_COMPLETE'
    local=d.read(WORK/'neighbours_state.json');method2=d.read(d.public(local['method_reference']))
    for q,h in method2['source_files'].items():assert d.digest(ROOT/q)==h
    assert d.digest(WORK/'neighbours_prepared.pkl.gz')==method2['prepared_cache_sha256']
    reqs=common.cache_read(WORK/'neighbours_prepared.pkl.gz')
    def save(): (WORK/'neighbours_state.json').write_text(json.dumps(local,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    for row,req in zip(method2['accounts'],reqs,strict=True):
        label='L'+str(row['lookback']);cache=WORK/'parameters'/(label+'.pkl.gz');item=local['accounts'].get(label)
        if item and item['status']=='AUDITED':continue
        if item and item['status']=='INFLIGHT':raise RuntimeError('Uncertain finance cannot replay '+label)
        if item is None:
            local['accounts'][label]={'status':'INFLIGHT'};save()
            result=ctx.evaluation.evaluate(req);common.cache_write(cache,(req,result))
            ref=publish_evidence(ctx,EvaluationEvidenceWrite(exp,'short-alt-'+label.lower()+'-native',req,result)).to_dict()
            item={'status':'NATIVE_COMPLETE','reference':ref,'cache':cache.relative_to(ROOT).as_posix(),'cache_sha256':d.digest(cache),'request_hash':result.request_hash,'result_hash':result.result_hash}
            local['accounts'][label]=item;save()
        else:
            assert d.digest(cache)==item['cache_sha256'];req,result=common.cache_read(cache)
        report=audit.audit(ctx,req,result,d.read(d.public(item['reference'])),new=True)
        report['parameter_diagnostic_status']='ADDITIONAL_LOCAL_INTEGER_SENSITIVITY_ONLY_NOT_STANDARD32'
        reportref=p.material(ctx,exp,WORK/'parameters'/(label+'-audit.json'),'short-alt-'+label.lower()+'-independent-audit',report)
        item.update(status='AUDITED',audit_reference=reportref,economics=report['economics']);save()
        print(json.dumps({'label':label,'economics':report['economics']},ensure_ascii=False),flush=True)
    local['status']='FINANCIAL36_COMPLETE';save();assert not common.SOURCE_CALLS
    return {'status':local['status'],'new_financial_accounts':36}
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('declare','run'));args=parser.parse_args()
    print(json.dumps(globals()[args.action](),ensure_ascii=False),flush=True)
