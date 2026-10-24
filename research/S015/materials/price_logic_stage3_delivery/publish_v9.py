"""Immutable report-scope clarification, with unchanged candidate identities."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
from pathlib import Path
from hashlib import sha256
import json,re,sys
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence,validate_experiment,assemble_delivery
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,ExecutionResources,EvidenceRef,MaterialEvidenceWrite,ExperimentReportWrite,ExperimentOutcome,ExperimentValidationRequest,ExperimentValidationScope
from czsc_trader.research_tools import delivery as d
HOME=Path(__file__).resolve().parent;ROOT=HOME.parents[3];H=ROOT/'research/S015/experiments/EX079_20261025';EX=ExperimentRef('S015',H.name)
def read(p):return json.loads(p.read_bytes())
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def main():
 repo=RepositoryContext.discover(ROOT);batch=ResearchBatchRef('S015');ctx=create_research_context(repo,batch,resources=ExecutionResources(8,1,13));oldreceipt=read(H/'others/published_report.json')
 if sys.argv[1]=='report':
  assert not (H/'others/published_report_v2.json').exists()
  previous=EvidenceRef.from_dict(oldreceipt['report']);refs=tuple(EvidenceRef.from_dict(x) for x in oldreceipt['references'])
  report=publish_evidence(ctx,ExperimentReportWrite(EX,sha256((H/'report.md').read_bytes()).hexdigest(),ExperimentOutcome.COMPLETED,refs,previous))
  validation=validate_experiment(repo,ExperimentValidationRequest(EX,ExperimentValidationScope.REPORT_PUBLICATION));assert validation.status.value=='PASS'
  save(H/'others/published_report_v2.json',{'reason':'Limit rolling252 claims to9 intervals sampled every21 sessions. Same accounts, candidates and eligibility.','previous':previous.to_dict(),'report':report.to_dict(),'validation':validation.to_dict()});print('EX079_REPORT_V2_PASS',flush=True);return
 assert sys.argv[1] in ('check','publish')
 old=read(HOME/'publication_receipt.json');assert old['status']=='FULL_PUBLICATION_PASS';reference=d.DeliveryReceipt.from_dict(read(ROOT/'research/S015/assets/deliveries/CANDIDATES/8/receipt.json')).reference
 prior=d.DeliveryContent.from_dict(read(ROOT/'research/S015/assets/deliveries/CANDIDATES/8/delivery.json')['content']);panel=prior.payload
 assert len(panel.candidates)==39 and len(panel.handoff)==29
 report=(HOME/'report.md').read_text(encoding='utf-8');target=ROOT/'research/S015/deliveries/CANDIDATES/9'
 def rebase(m):
  label,path=m.groups()
  if '://' in path or path.startswith('#'):return m.group(0)
  absolute=(HOME/path).resolve();assert absolute.exists();return '['+label+']('+Path(os.path.relpath(absolute,target)).as_posix()+')'
 report=re.sub(r'\[([^\]]*)\]\(([^)]+)\)',rebase,report)
 report+='\n交付修订说明：本修订仅将滚动收益描述限定为每21交易日抽取的9个252日区段，并将首次成交描述限定于EX076固定八组；CANDIDATES/8与本修订的候选集合、账户、资格及判断完全相同。原报告与回执保留。\n'
 refs=[EvidenceRef.from_dict(read(H/'others/published_report_v2.json')['report'])]
 definition=d.DeliveryDefinition(batch,d.DeliveryStage.CANDIDATES,9,(reference,))
 check={'status':'REPORT_SCOPE_CHECK_PASS','prior':reference.to_dict(),'candidate_panel_unchanged':True,'report_sha256':sha256(report.encode()).hexdigest(),'source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),'handoff_count':29,'candidate_count':39}
 if sys.argv[1]=='check':save(HOME/'check_v9.json',check);print('REPORT_SCOPE_CHECK_PASS',flush=True);return
 assert check==read(HOME/'check_v9.json');assert not (HOME/'publication_receipt_v9.json').exists()
 for p in (Path(__file__),HOME/'report.md',HOME/'check_v9.json',H/'others/published_report_v2.json'):
  refs.append(publish_evidence(ctx,MaterialEvidenceWrite(EX,p.stem,p.read_bytes(),{'.py':'text/x-python','.md':'text/markdown','.json':'application/json'}[p.suffix],p.suffix[1:])))
 content=d.DeliveryContent(panel,d.DeliveryStatus.COMPLETE,(),(),report=report,evidence=tuple(refs))
 last=[None,0]
 def progress(v):
  if v.phase!=last[0] or v.elapsed_seconds-last[1]>=30:print(json.dumps(v.to_dict(),ensure_ascii=False),flush=True);last[:]=[v.phase,v.elapsed_seconds]
 result=assemble_delivery(repo,definition,content,resources=ExecutionResources(8,1,13),on_progress=progress)
 save(HOME/'publication_receipt_v9.json',{'status':'FULL_PUBLICATION_PASS' if result.validation.status is d.ValidationStatus.PASS else 'FAIL','assembly':result.to_dict()})
 assert result.validation.status is d.ValidationStatus.PASS and result.validation.scope is d.DeliveryValidationScope.FULL
 print('CANDIDATES9_FULL_PASS',result.receipt.reference.content_sha256,flush=True)
if __name__=='__main__':main()
