"""Publish a completed experiment's selected source/material/report references."""
from pathlib import Path
from hashlib import sha256
import json
import sys
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence,validate_experiment
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,ExecutionResources,MaterialEvidenceWrite,EvidenceRef,ExperimentReportWrite,ExperimentOutcome,ExperimentValidationRequest,ExperimentValidationScope

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
def read(p):return json.loads(p.read_bytes())
def main():
 ex=ExperimentRef('S015',sys.argv[1]);home=ex.resolve(ROOT)
 assert not (home/'others/published_report_v2.json').exists()
 repo=RepositoryContext.discover(ROOT);ctx=create_research_context(repo,ex.batch if hasattr(ex,'batch') else ResearchBatchRef('S015'),resources=ExecutionResources(1,1,13))
 refs=[];materials={}
 for p in sorted(home.rglob('*')):
  if not p.is_file() or p.suffix not in ('.py','.json','.csv') or not any(x in p.parts for x in ('src','protocols','others')):continue
  if p.name.endswith(('_account_daily.csv','_decisions.csv','_orders.csv','_fills.csv','_trades.csv')):continue
  if p.name in ('progress.json','published_report.json'):continue
  ref=publish_evidence(ctx,MaterialEvidenceWrite(ex,p.stem,p.read_bytes(),{'.py':'text/x-python','.json':'application/json','.csv':'text/csv'}[p.suffix],p.suffix[1:]));refs.append(ref);materials[str(p.relative_to(home))]=ref.to_dict()
 resultfile=home/'others/results.json'
 if resultfile.exists():
  x=read(resultfile);refs.extend(EvidenceRef.from_dict(r['evidence']) for r in x['rows'])
  if x.get('serial_ref'):refs.append(EvidenceRef.from_dict(x['serial_ref']))
 diagfile=home/'others/diagnosis.json'
 if diagfile.exists():refs.extend(EvidenceRef.from_dict(r) for r in read(diagfile)['source_refs'].values())
 refs=list(dict.fromkeys(refs))
 report=publish_evidence(ctx,ExperimentReportWrite(ex,sha256((home/'report.md').read_bytes()).hexdigest(),ExperimentOutcome.COMPLETED,tuple(refs),EvidenceRef.from_dict(read(home/'others/published_report.json')['report'])))
 validation=validate_experiment(repo,ExperimentValidationRequest(ex,ExperimentValidationScope.REPORT_PUBLICATION))
 assert validation.status.value=='PASS',validation
 receipt={'report':report.to_dict(),'materials':materials,'references':[r.to_dict() for r in refs],'validation':validation.to_dict()}
 (home/'others/published_report_v2.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(ex.experiment_id,'REPORT_PUBLICATION_PASS',len(refs),flush=True)
if __name__=='__main__':main()
