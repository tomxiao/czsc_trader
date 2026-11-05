"""Publish migration reports and their selected immutable research materials."""
from pathlib import Path
from hashlib import sha256
import json
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence
from czsc_trader.research_tools import (ResearchBatchRef,ExperimentRef,EvidenceRef,MaterialEvidenceWrite,
    ExperimentReportWrite,ExperimentOutcome)

ROOT=Path(__file__).resolve().parents[5]

def main():
    context=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'))
    predecessor=[]
    for name,outcome in [('EX087_20261105',ExperimentOutcome.FAILED),('EX088_20261105',ExperimentOutcome.FAILED),('EX089_20261105',ExperimentOutcome.COMPLETED)]:
        exp=ExperimentRef('S015',name);home=exp.resolve(ROOT)
        assert not (home/'report_ref.json').exists()
        refs=[]
        for folder in ('src','protocols','others'):
            for path in sorted((home/folder).glob('*')):
                if not path.is_file() or path.suffix not in ('.py','.json','.parquet'):
                    continue
                media={'.py':'text/x-python','.json':'application/json','.parquet':'application/octet-stream'}[path.suffix]
                refs.append(publish_evidence(context,MaterialEvidenceWrite(exp,folder+'-'+path.stem,path.read_bytes(),media,path.suffix[1:])))
        for path in sorted((home/'others').glob('result_*.json')):
            value=json.loads(path.read_text(encoding='utf-8'))
            refs.append(EvidenceRef.from_dict(value['reference']))
        if name=='EX087_20261105':
            original=json.loads((home/'others/input_sources.json').read_text(encoding='utf-8'))['old_accounts']
            refs.extend(EvidenceRef.from_dict(v) for v in original.values())
        if name=='EX089_20261105':refs.extend(predecessor)
        report=publish_evidence(context,ExperimentReportWrite(exp,sha256((home/'report.md').read_bytes()).hexdigest(),outcome,tuple(dict.fromkeys(refs))))
        predecessor.append(report)
        print(name,outcome.value,report.sha256,flush=True)

if __name__=='__main__':main()
