"""Publish reviewed S015 stage-three candidates through public APIs only."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
from pathlib import Path
from dataclasses import asdict
from hashlib import sha256
import json,re,sys
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence,register_candidate,CandidateRegistrationRequest,load_candidate,assemble_delivery
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,ExecutionResources,EvidenceRef,MaterialEvidenceWrite
from czsc_trader.research_tools import delivery as d
from strategy_manager import CandidateKey
from strategy_runtime import StrategyCandidate,StrategyRuntime,ImplementationDependency
HOME=Path(__file__).resolve().parent;ROOT=HOME.parents[3];B=ROOT/'research/S015/experiments';H=B/'EX079_20261025';SOURCE=B/'EX076_20261024/src/strategy_runtime'
def read(p):return json.loads(p.read_bytes())
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def main():
 assert sys.argv[1] in ('check','publish')
 repo=RepositoryContext.discover(ROOT);batch=ResearchBatchRef('S015');ctx=create_research_context(repo,batch,resources=ExecutionResources(8,1,13));runtime=StrategyRuntime()
 selection=read(H/'others/selection.json');assert selection['status']=='EXACT_SELECTION_CHECK_PASS' and not selection['extension_triggered'];assert len(selection['passing_ids'])==29
 assert read(H/'others/diagnosis.json')['status']=='DIAGNOSTICS_PASS';assert read(H/'others/clock_checks.json')['status']=='PASS'
 rows={r['candidate_id']:r for r in selection['rows']};stress={r['candidate_id']:r for r in read(H/'others/results.json')['rows']}
 refs=[];receipts={}
 for ex in ('EX076_20261024','EX077_20261024','EX078_20261024','EX079_20261025'):
  receipt=read(B/ex/'others/published_report.json');assert receipt['validation']['status']=='PASS';receipts[ex]=receipt
  reportref=EvidenceRef.from_dict(receipt['report']);reportref.resolve(ROOT);refs.append(reportref)
  refs.extend(EvidenceRef.from_dict(x) for x in receipt['references'])
  normalized={k.replace('\\','/'):v for k,v in receipt['materials'].items()}
  for filename in ('others/results.json','others/selection.json','others/diagnosis.json','others/audit.json'):
   if filename in normalized:assert EvidenceRef.from_dict(normalized[filename]).resolve(ROOT).read_bytes()==(B/ex/filename).read_bytes()
  for p,ref in read(B/ex/'others/protocol_refs.json').items():assert EvidenceRef.from_dict(ref).resolve(ROOT).read_bytes()==(ROOT/p).read_bytes()
 entries=[];requests=[];handoff=[];identities=[]
 for cid in selection['selected_ids']:
  row=rows[cid];ex=ExperimentRef('S015',row['origin_experiment']);payload=read(ex.resolve(ROOT)/f'others/{cid}_payload.json');assert payload['parameters']==row['parameters']
  candidate=StrategyCandidate('S015',cid,payload,SOURCE);deps=tuple(ImplementationDependency(**x) for x in row['dependencies']);identity=runtime.identify(candidate,dependencies=deps);assert identity.content_sha256==row['identity']['content_sha256']
  supporting=[EvidenceRef.from_dict(row['evidence'])]
  if cid in stress:
   assert stress[cid]['identity']==row['identity'];supporting.append(EvidenceRef.from_dict(stress[cid]['evidence']))
  for ref in supporting:
   ev=read(ref.resolve(ROOT));assert ev['request_identity']['content_sha256']==identity.content_sha256
   assert all(run['identity']['content_sha256']==identity.content_sha256 and run['identity']['candidate']['candidate_id']==cid for run in ev['runs'])
  passed=cid in selection['passing_ids'];judge='原434/415全部阶段三经济与频率目标通过；建议阶段四，稳健性尚未判定。' if passed else ('四项目标非支配取舍，但未满足完整阶段三条件；仅保留前沿，不放入达标交接。' if cid in selection['frontier_ids'] else '中位8日零门槛控制，用于解释费用门槛的收益回撤取舍；不达标，不交接。')
  entry=d.CandidateEntry(d.CandidateIdentityRef(CandidateKey('S015',cid),identity.content_sha256),'价格中心上移中的条件修复：信号修复空间过滤、激活目标完成或中心回退失效退出；无固定持有期。',judge,tuple(d.EvaluationEvidenceRef(x,()) for x in supporting))
  entries.append(entry);requests.append((CandidateRegistrationRequest(candidate,ex,tuple(supporting),deps),identity))
  if passed:handoff.append(entry.identity.key)
  identities.append({'candidate':cid,'content_sha256':identity.content_sha256,'center_pass':passed,'frontier':cid in selection['frontier_ids'],'supporting_accounts':[x.to_dict() for x in supporting]})
 assert {x.candidate_id for x in handoff}==set(selection['passing_ids']) and len(entries)==39
 predecessors=[]
 for stage,rev,expected in (('MANDATE',5,'21b74f69453b3f9cd93ca674981e6f6cd0255ddb336af444215c3f457f83354b'),('PROTOTYPES',4,'5b21365bfd4fbdeb82fddadbd625f3afea351168f037d87f338ba66d2480f39f'),('CANDIDATES',7,'b614f360e2d5448e5ad81a5c3f47b6f2271ddfff5b8b7639f3337bc8bedeb4e1')):
  a=read(ROOT/f'research/S015/deliveries/{stage}/{rev}/receipt.json');b=read(ROOT/f'research/S015/assets/deliveries/{stage}/{rev}/receipt.json');assert a==b
  ref=d.DeliveryReceipt.from_dict(a).reference;assert ref.content_sha256==expected;predecessors.append(ref)
 old=d.DeliveryContent.from_dict(read(ROOT/'research/S015/assets/deliveries/CANDIDATES/7/delivery.json')['content']).payload
 searches=list(old.searches)
 for ex,method,limitations in (
  ('EX076_20261024','Eight prospectively declared center/space controls; Optuna indexed fixed configurations.','Fixed comparisons; not adaptive inference. Signal-time space does not guarantee fill-time space.'),
  ('EX077_20261024','60 new joint-grid points plus64 multivariate constrained TPE proposals, batches8, seed13.','Initial8 true observations lacked sampler-side constraints through create_trial; sampling priority affected. Real accounts and final exact gates valid.'),
  ('EX078_20261024','Replay132 actual observations using public ask/tell with132 verified constraints, then32 TPE proposals.','Replay adds no accounts or independent information. Original initialization deviation remains in selection history.')
 ):
  result=read(B/ex/'others/results.json');rr=next(v for k,v in receipts[ex]['materials'].items() if k.replace('\\','/')=='others/results.json')
  searches.append(d.SearchSummary(ex+'-price-repair','Optuna: '+method,'Existing434/415 windows; mean/median center, background2..10, allocation.6..1 step.025, space0..02; exact EX076 runtime.',result['formal_accounts'],result['new_configurations'],'Retain every exact stage-three pass and every four-objective frontier; unchanged prior family qualifications via predecessor.',(limitations,'All development samples repeatedly seen. Parameter identities and equity paths are not independent mechanisms.','Stage4 not performed.'),(EvidenceRef.from_dict(rr),)))
 conclusion='阶段三完成：164新配置、156组双窗口权益路径；29达标身份、25组达标权益路径全部交接。保存39身份含9未达标前沿及1尺度控制。费用空间过滤有完整账户与成本压力依据，但频率触底、年份依赖及参数选择风险仍在；新家族未完成阶段四。原16历史数值合格及选择历史保持，固定持有家族阶段五推荐仍暂缓。'
 panel=d.CandidateSet(tuple(entries),tuple(handoff),tuple(searches),conclusion)
 source_report=(HOME/'report.md').read_text(encoding='utf-8');report_base=ROOT/'research/S015/deliveries/CANDIDATES/8'
 def rebase(match):
  label,target=match.groups()
  if '://' in target or target.startswith('#'):return match.group(0)
  absolute=(HOME/target).resolve();assert absolute.exists(),target
  return '['+label+']('+Path(os.path.relpath(absolute,report_base)).as_posix()+')'
 report=re.sub(r'\[([^\]]*)\]\(([^)]+)\)',rebase,source_report)
 definition=d.DeliveryDefinition(batch,d.DeliveryStage.CANDIDATES,8,tuple(predecessors))
 journal={'status':'TYPED_HANDOFF_CHECK_PASS','definition':definition.to_dict(),'registered_target_count':39,'handoff_count':29,'identities':identities,'panel_sha256':sha256(json.dumps(panel.to_dict(),sort_keys=True,ensure_ascii=False).encode()).hexdigest(),'report_sha256':sha256(report.encode()).hexdigest(),'source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),'historical_qualifications_unchanged':True,'stage4':'NOT_EXECUTED_NOT_AUTHORIZED'}
 if sys.argv[1]=='check':
  save(HOME/'check.json',journal);save(HOME/'panel.json',panel.to_dict());print('TYPED_HANDOFF_CHECK_PASS',len(entries),len(handoff),flush=True);return
 assert journal==read(HOME/'check.json');assert not (HOME/'publication_receipt.json').exists()
 registered=[]
 for request,expected in requests:
  r=register_candidate(repo,request);loaded=load_candidate(repo,r.key);assert runtime.identify(loaded,dependencies=request.dependencies)==expected;assert r.content_sha256==expected.content_sha256
  registered.append({'registration':r.to_dict(),'loaded_identity':asdict(expected)});print('REGISTERED_RELOAD_PASS',r.key.candidate_id,flush=True)
 save(HOME/'registration_summary.json',{'status':'ALL_REGISTERED_RELOAD_PASS','count':len(registered),'registrations':registered})
 for filename in ('publish.py','check.json','panel.json','registration_summary.json','report.md'):
  p=HOME/filename;refs.append(publish_evidence(ctx,MaterialEvidenceWrite(ExperimentRef('S015','EX079_20261025'),p.stem,p.read_bytes(),{'.py':'text/x-python','.json':'application/json','.md':'text/markdown'}[p.suffix],p.suffix[1:])))
 content=d.DeliveryContent(panel,d.DeliveryStatus.COMPLETE,(),(),report=report,evidence=tuple(dict.fromkeys(refs)))
 last=[None,0]
 def progress(v):
  if v.phase!=last[0] or v.elapsed_seconds-last[1]>=30:print(json.dumps(v.to_dict(),ensure_ascii=False),flush=True);last[:]=[v.phase,v.elapsed_seconds]
 assembled=assemble_delivery(repo,definition,content,resources=ExecutionResources(8,1,13),on_progress=progress)
 save(HOME/'publication_receipt.json',{'status':'FULL_PUBLICATION_PASS' if assembled.validation.status is d.ValidationStatus.PASS else 'FAIL','assembly':assembled.to_dict()})
 assert assembled.validation.status is d.ValidationStatus.PASS and assembled.validation.scope is d.DeliveryValidationScope.FULL
 print('CANDIDATES8_FULL_PASS',assembled.receipt.reference.content_sha256,flush=True)
if __name__=='__main__':main()
