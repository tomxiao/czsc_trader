"""Prospective complete bounded neighborhoods and same-identity cost stress."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
from pathlib import Path
from datetime import date
from dataclasses import replace
from collections.abc import Mapping
import json,sys,importlib.util
import pandas as pd
from czsc_trader.application import RepositoryContext,create_research_context,load_candidate,publish_evidence,open_research_execution
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,ExecutionResources,EvidenceRef,MaterialEvidenceWrite,EvaluationRequest,EvaluationWindow,EvaluationCost,EvaluationBenchmark,LimitBuyHold,EvaluationEvidenceWrite,ParameterEvaluationPlan,EvaluationLineage
from czsc_trader.research_tools import delivery as d
from strategy_manager import CandidateKey,CandidateDerivation,CandidateDerivationKind,CandidateEvidence
from strategy_runtime import StrategyRuntime,StrategyCandidate
from strategy_evaluator import research_models as m
from strategy_evaluator.parameter_neighborhood import ParameterAxis,RealDomain,IntegerDomain,CategoricalDomain,ExplicitValues,BoundedLocalStep,RelativeChangeLimit,AbsoluteChangeLimit,ParameterNeighborhoodSpace,ParameterNeighborhoodProtocol,ParameterNeighborhoodRequest,build_parameter_neighborhood_design
ROOT=Path(__file__).resolve().parents[5];HOME=Path(__file__).resolve().parents[1];OUT=HOME/'others';B=HOME.parent;EX=ExperimentRef('S015',HOME.name);BATCH=ResearchBatchRef('S015');VERSION='S015-EX080-price-repair-stage4-v1';CACHE=ROOT/'.tmp/s015-ex080';ZERO_SCALE=1.001/.999-1
def read(p):return json.loads(p.read_bytes())
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def plain(x):
 if isinstance(x,Mapping):return {k:plain(v) for k,v in x.items()}
 if isinstance(x,(tuple,list)):return [plain(v) for v in x]
 return x
def module(p,n):
 s=importlib.util.spec_from_file_location(n,p);v=importlib.util.module_from_spec(s);s.loader.exec_module(v);return v
def ctx(workers=8):return create_research_context(RepositoryContext.discover(ROOT),BATCH,resources=ExecutionResources(workers,1,13))
def material(c,p):return publish_evidence(c,MaterialEvidenceWrite(EX,p.stem,p.read_bytes(),{'.py':'text/x-python','.json':'application/json','.md':'text/markdown','.csv':'text/csv'}[p.suffix],p.suffix[1:]))
def predecessor(stage,revision,expected):
 h=ROOT/f'research/S015/assets/deliveries/{stage}/{revision}';r=d.DeliveryReceipt.from_dict(read(h/'receipt.json'));assert r.reference.content_sha256==expected;return r.reference,read(h/'delivery.json')['content']['payload']
def centers():return tuple(x['candidate_id'] for x in read(OUT/'centers.json'))
def request(c,candidate,stress=False):
 return c.evaluation.prepare(EvaluationRequest(ROOT,EX.experiment_id,candidate,{'candidate_id':candidate.reference_id,'source_files':list(candidate.payload['runtime']['source_files']),'implementation_sha256':candidate.payload['runtime']['source_sha256']},'159326.SZ','etf',(EvaluationWindow('full',date(2025,1,2),date(2026,10,21)),),date(2026,10,21),100000.,(EvaluationCost('fee_x2' if stress else 'standard',.002 if stress else .001,'STRESS' if stress else 'FORMAL'),),benchmark=EvaluationBenchmark(LimitBuyHold(100,.01,.001,.1,1000000))))
def prepare():
 assert not (OUT/'protocol_refs.json').exists();c=ctx(1)
 cref,panel=predecessor('CANDIDATES',9,'31272c048a128a7f0bbbadb784baa500d45120ed215ac738c59044e6eef5698b')
 mr,_=predecessor('MANDATE',5,'21b74f69453b3f9cd93ca674981e6f6cd0255ddb336af444215c3f457f83354b');save(OUT/'mandate_reference.json',mr.to_dict())
 ids={x['candidate_id'] for x in panel['handoff']};selection=read(B/'EX079_20261025/others/selection.json');rows=[r for r in selection['rows'] if r['candidate_id'] in ids];assert len(rows)==len(ids)==29;save(OUT/'centers.json',rows)
 reuse=[r for r in read(B/'EX079_20261025/others/results.json')['rows'] if r['candidate_id'] in ids];assert len(reuse)==5;save(OUT/'reused_stress.json',reuse)
 mapping={'version':VERSION,'payload_root':'parameters','axes':{'center_kind':{'domain':['mean','median'],'meaning':'price-center definition','treatment':'structure fixed, not a local perturbation'},'lookback':{'domain':'integer[1,30]','unit':'sessions','minimum_legal_step':1,'relative_limit':.05},'allocation':{'domain':'continuous(0,1]','unit':'fraction','relative_limit':.05,'meaning':'entry-cycle cash allocation; .025 search grid is not a lawful quantum'},'minimum_repair_space':{'domain':'continuous[0,.05]','unit':'price_ratio','positive_center':'relative .05','zero_reference_scale':ZERO_SCALE,'zero_absolute_limit':.05*ZERO_SCALE,'zero_reason':'Standard roundtrip fee hurdle is an ex ante business scale, not performance-selected. Zero has no relative scale; use5% of this reference only for zero centers.'}},'constraints':'Pure payload domains only; no performance-based feasibility, no clipping or rounding. Fixed center_kind and out-of-cap lookback.','comparison':'Exact design comparison_sha256, actual scales and shapes; never force a global ranking.'}
 feasibility={'version':VERSION,'method':'Complete Cartesian product includes each center coordinate; exclude only whole center, duplicates or illegal domain combinations. All axes active and no additional joint constraints.'}
 save(HOME/'protocols/mapping.json',mapping);save(HOME/'protocols/feasibility.json',feasibility);mapref=material(c,HOME/'protocols/mapping.json');feasref=material(c,HOME/'protocols/feasibility.json');records=[];number=9500
 for row in rows:
  cid=row['candidate_id'];candidate=load_candidate(RepositoryContext.discover(ROOT),CandidateKey('S015',cid));identity=StrategyRuntime().identify(candidate,dependencies=());assert identity.content_sha256==row['identity']['content_sha256'];p=plain(candidate.payload['parameters']);assert p==row['parameters'];center=request(c,candidate)
  ev=read(EvidenceRef.from_dict(row['evidence']).resolve(ROOT));assert center.input_bindings['full'].to_dict()==ev['input_bindings']['full']
  axes=(ParameterAxis('center_kind',p['center_kind'],CategoricalDomain(('mean','median')),ExplicitValues((p['center_kind'],)),('center_kind',),'definition'),ParameterAxis('lookback',p['lookback'],IntegerDomain(1,30),BoundedLocalStep(RelativeChangeLimit(.05)),('lookback',),'sessions'),ParameterAxis('allocation',p['allocation'],RealDomain(0.,1.,False,True),BoundedLocalStep(RelativeChangeLimit(.05)),('allocation',),'fraction'),ParameterAxis('minimum_repair_space',p['minimum_repair_space'],RealDomain(0.,.05),BoundedLocalStep(AbsoluteChangeLimit(.05*ZERO_SCALE) if p['minimum_repair_space']==0 else RelativeChangeLimit(.05)),('minimum_repair_space',),'price_ratio'))
  space=ParameterNeighborhoodSpace(axes,mapref.sha256,feasref.sha256);design=build_parameter_neighborhood_design(ParameterNeighborhoodRequest(m.AssessmentCandidate(candidate.reference_id,identity.content_sha256),ParameterNeighborhoodProtocol(),space),feasibility=lambda values:True).design;assert design is not None
  children=[];childids=[]
  for point in design.points:
   child=StrategyCandidate('S015',f'C{number}',{**plain(candidate.payload),'parameters':{**p,**{x.name:x.value for x in point.values}}},candidate.source_root);number+=1;childids.append(child.candidate_id);children.append(request(c,child))
  plan=ParameterEvaluationPlan.create(design,center,tuple(children),mapping_evidence=mapref,feasibility_evidence=feasref,dataflows=c.data);path=HOME/f'protocols/plans/{cid}.json';save(path,plan.to_dict());ref=material(c,path)
  records.append({'candidate_id':cid,'child_ids':childids,'design':design.to_dict(),'plan':plan.to_dict(),'plan_reference':ref.to_dict()});print('PLAN',cid,design.point_count,flush=True)
 assert number==9677;save(OUT/'plan_refs.json',records)
 protocol={'version':VERSION,'authorization':'批准自主执行并完成阶段四','source_candidates':cref.to_dict(),'source_mandate':mr.to_dict(),'centers':centers(),'formal_new_accounts':{'neighbors':177,'stress':24},'reused_accounts':{'standard_centers':29,'stress':5,'common_415':29},'technical_duplicates':2,'parameter_policy':mapping,'economic_targets':'Unchanged MANDATE/5; neighbor joint >=ceil(13N/16), all points DD<=25%; do not apply center frequency or415 thresholds to neighbors.','time_and_uncertainty':'Reuse standard434 centers; rolling252 step21 including all fitting starts, annual partial years retained and marked; bootstrap2000/block10/seed13, PBO10blocks; diagnostics not hard gates.','family':'Preserve original372 retained columns and append authenticated same-contract stage2/3 decisions after explicit content/refactor-only dedup. Never dedup all equal performance into independent hypotheses. Detailed source/exclusion manifest fixed before statistical assessment; all known earlier selection gaps disclosed.','ranking':'Preserve original raw Pareto and6 ordered diagnostics, original bins/variants, exact neighborhood comparison hashes; whole-set and supplemental same-method groups. No candidate preselected.','resources':{'workers':8,'native_threads':1,'seed':13},'scope':'Same434/415, inputs,costs,capital,execution; no new data, no search/neighborhood promotion, stage5/freeze/PTE/prod.','reuse_limit':'Existing standard centers and same-content stress reuse. Neighborhood accounts require new frozen-plan lineage; preserve any stage3 economic duplicate without editing its provenance.'}
 save(OUT/'protocol.json',protocol)
 refs={p.relative_to(ROOT).as_posix():material(c,p).to_dict() for p in (Path(__file__),OUT/'centers.json',OUT/'reused_stress.json',OUT/'protocol.json',OUT/'plan_refs.json',HOME/'protocols/mapping.json',HOME/'protocols/feasibility.json')};save(OUT/'protocol_refs.json',refs);print('PROTOCOL_FROZEN',29,177,24,flush=True)
def assert_protocol():
 for path,ref in read(OUT/'protocol_refs.json').items():assert EvidenceRef.from_dict(ref).resolve(ROOT).read_bytes()==(ROOT/path).read_bytes(),path
def tasks(c):
 result=[];reuse={r['candidate_id'] for r in read(OUT/'reused_stress.json')}
 for record in read(OUT/'plan_refs.json'):
  cid=record['candidate_id'];candidate=load_candidate(RepositoryContext.discover(ROOT),CandidateKey('S015',cid));p=plain(candidate.payload['parameters']);plan=ParameterEvaluationPlan.from_dict(record['plan']);ref=EvidenceRef.from_dict(record['plan_reference']);assert read(ref.resolve(ROOT))==record['plan']
  for i,(point,childid) in enumerate(zip(plan.design.points,record['child_ids'],strict=True)):
   child=StrategyCandidate('S015',childid,{**plain(candidate.payload),'parameters':{**p,**{v.name:v.value for v in point.values}}},candidate.source_root);req=request(c,child)
   deriv=CandidateDerivation(CandidateKey('S015',cid),plan.design.center.content_sha256,CandidateKey('S015',childid),plan.children[i].candidate.content_sha256,CandidateDerivationKind.PARAMETERS,{v.name:v.value for v in point.values},plan.design.protocol.sha256,CandidateEvidence(ref.repository_path,ref.sha256))
   result.append(('parameter',cid,replace(req,lineage=EvaluationLineage(deriv,plan.bind_point(ref,i,repository_root=ROOT)))))
  if cid not in reuse:result.append(('stress',None,request(c,candidate,True)))
 assert len(result)==201;return result
def run():
 assert_protocol();c=ctx();jobs=tasks(c);done=read(OUT/'results.json')['rows'] if (OUT/'results.json').exists() else read(OUT/'stress_results.json')['rows'];keys={(x['candidate_id'],x['source_role']) for x in done};pilots=[jobs[0],next(t for t in jobs if t[0]=='parameter' and t[1]=='C7601')]
 serial=[]
 if not (OUT/'equivalence.json').exists():
  for role,parent,req in pilots:
   r=ctx(1).evaluation.evaluate(req);ref=publish_evidence(c,EvaluationEvidenceWrite(EX,'serial_'+req.strategy.candidate_id,req,r));serial.append((r,ref))
  comparisons=[]
  with open_research_execution(c,experiment=EX) as session:
   outcomes=c.evaluation.evaluate_many(tuple(j[2] for j in pilots),execution=session)
   for (role,parent,req),(sr,sref),out in zip(pilots,serial,outcomes,strict=True):
    assert out.status.value=='SUCCEEDED',out.error;r=out.result;assert r.result_hash==sr.result_hash
    for name in ('account_daily','decisions','orders','fills','trades'):pd.testing.assert_frame_equal(getattr(r.runs[0].execution,name),getattr(sr.runs[0].execution,name))
    ref=publish_evidence(c,EvaluationEvidenceWrite(EX,req.strategy.candidate_id,req,r));done.append({'candidate_id':req.strategy.candidate_id,'source_role':role,'parent_candidate_id':parent,'request_hash':r.request_hash,'result_hash':r.result_hash,'evidence':ref.to_dict()});keys.add((req.strategy.candidate_id,role));comparisons.append({'candidate':req.strategy.candidate_id,'status':'PASS','serial':sref.to_dict(),'parallel':ref.to_dict(),'ledgers':5})
  save(OUT/'results.json',{'rows':done});save(OUT/'equivalence.json',comparisons);print('SERIAL_PARALLEL_PASS',flush=True)
 pending=[t for t in jobs if (t[2].strategy.candidate_id,t[0]) not in keys]
 with open_research_execution(c,experiment=EX) as session:
  for start in range(0,len(pending),8):
   block=pending[start:start+8];outs=c.evaluation.evaluate_many(tuple(t[2] for t in block),execution=session)
   for (role,parent,req),out in zip(block,outs,strict=True):
    assert out.status.value=='SUCCEEDED',out.error;r=out.result;ref=publish_evidence(c,EvaluationEvidenceWrite(EX,req.strategy.candidate_id,req,r));done.append({'candidate_id':req.strategy.candidate_id,'source_role':role,'parent_candidate_id':parent,'request_hash':r.request_hash,'result_hash':r.result_hash,'evidence':ref.to_dict()})
   save(OUT/'results.json',{'rows':done});print('ACCOUNTS',len(done),201,flush=True)
 assert len(done)==201;print('ACCOUNTS_COMPLETE',flush=True)
if __name__=='__main__':{'prepare':prepare,'run':run}[sys.argv[1]]()
