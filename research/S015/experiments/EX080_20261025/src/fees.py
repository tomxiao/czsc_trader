"""Complete the unaffected same-identity standard-window fee stress coverage."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
from pathlib import Path
from datetime import date
import json,sys
from czsc_trader.application import RepositoryContext,create_research_context,load_candidate,publish_evidence,open_research_execution
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,ExecutionResources,EvidenceRef,MaterialEvidenceWrite,EvaluationRequest,EvaluationWindow,EvaluationCost,EvaluationBenchmark,LimitBuyHold,EvaluationEvidenceWrite
from strategy_manager import CandidateKey
from strategy_runtime import StrategyRuntime
H=Path(__file__).resolve().parents[1];ROOT=H.parents[3];EX=ExperimentRef('S015',H.name)
def read(p):return json.loads(p.read_bytes())
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def main():
 c=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=ExecutionResources(8,1,13));rows=read(H/'others/centers.json');reuse={r['candidate_id'] for r in read(H/'others/reused_stress.json')};new=[r for r in rows if r['candidate_id'] not in reuse];assert len(new)==24
 if sys.argv[1]=='prepare':
  p=H/'protocols/fees.json';save(p,{'authorization':'批准自主执行并完成阶段四','centers':[r['candidate_id'] for r in rows],'new_pressure_ids':[r['candidate_id'] for r in new],'reused_pressure_ids':sorted(reuse),'contract':'Same frozen candidate identity, original434 window and inputs, original execution and initial100000; only actual one-way fee=.002. Signal parameters fixed. Original MANDATE5 targets; no new gates.','new_accounts':24,'resources':{'workers':8,'native_threads':1,'seed':13},'independent_of':'Pending continuous-parameter boundary repair; no parameter design or code mutation.'})
  refs={}
  for p in (p,Path(__file__),H/'others/centers.json',H/'others/reused_stress.json'):
   ref=publish_evidence(c,MaterialEvidenceWrite(EX,p.stem,p.read_bytes(),'text/x-python' if p.suffix=='.py' else 'application/json',p.suffix[1:]));refs[p.relative_to(ROOT).as_posix()]=ref.to_dict()
  save(H/'others/fee_protocol_refs.json',refs);print('FEE_PROTOCOL_FROZEN',flush=True);return
 assert sys.argv[1]=='run'
 for p,r in read(H/'others/fee_protocol_refs.json').items():assert EvidenceRef.from_dict(r).resolve(ROOT).read_bytes()==(ROOT/p).read_bytes()
 assert not (H/'others/stress_results.json').exists();reqs=[]
 for row in new:
  candidate=load_candidate(RepositoryContext.discover(ROOT),CandidateKey('S015',row['candidate_id']));assert StrategyRuntime().identify(candidate,dependencies=()).content_sha256==row['identity']['content_sha256']
  req=c.evaluation.prepare(EvaluationRequest(ROOT,EX.experiment_id,candidate,{'candidate_id':candidate.reference_id,'source_files':list(candidate.payload['runtime']['source_files']),'implementation_sha256':candidate.payload['runtime']['source_sha256']},'159326.SZ','etf',(EvaluationWindow('full',date(2025,1,2),date(2026,10,21)),),date(2026,10,21),100000.,(EvaluationCost('fee_x2',.002,'STRESS'),),benchmark=EvaluationBenchmark(LimitBuyHold(100,.01,.001,.1,1000000))))
  standard=read(EvidenceRef.from_dict(row['evidence']).resolve(ROOT));assert req.input_bindings['full'].to_dict()==standard['input_bindings']['full'];reqs.append(req)
 done=[]
 with open_research_execution(c,experiment=EX) as session:
  for start in range(0,24,8):
   block=reqs[start:start+8];outs=c.evaluation.evaluate_many(tuple(block),execution=session)
   for req,out in zip(block,outs,strict=True):
    assert out.status.value=='SUCCEEDED',out.error;r=out.result;ref=publish_evidence(c,EvaluationEvidenceWrite(EX,req.strategy.candidate_id,req,r));done.append({'candidate_id':req.strategy.candidate_id,'source_role':'stress','parent_candidate_id':None,'request_hash':r.request_hash,'result_hash':r.result_hash,'evidence':ref.to_dict()})
   save(H/'others/stress_results.json',{'rows':done});print('STRESS_ACCOUNTS',len(done),24,flush=True)
 assert len(done)==24
if __name__=='__main__':main()
