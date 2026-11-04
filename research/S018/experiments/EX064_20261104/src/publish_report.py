"""Publish the bounded sensitivity experiment, not a complete stage-four assessment."""
from pathlib import Path
import sys
import os

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
SCRATCH=ROOT/'.tmp/s018-c9380-stage4'
SCRATCH.mkdir(parents=True,exist_ok=True)
sys.pycache_prefix=str(SCRATCH/'pycache')
os.environ['TMP']=os.environ['TEMP']=str(SCRATCH)

from dataclasses import asdict
from hashlib import sha256
import json
from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, create_research_context, publish_evidence, validate_experiment)
from dataflows import ProviderConfig
from strategy_runtime.equity_definition import execution_spec_from_dict


def main():
    work=ROOT/'research/S018/experiments/EX064_20261104'
    out=work/'others/recovery_01'
    read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
    result=read(out/'results.json')
    assert result['status']=='COMPLETED' and len(result['accounts'])==81
    assert (work/'others/analysis_sensitivity.json').exists()
    assert not (work/'report_ref.json').exists(), 'Do not overwrite a published report.'
    exp=d.ExperimentRef('S018',work.name)
    repo=RepositoryContext.discover(ROOT)
    context=create_research_context(repo,d.ResearchBatchRef('S018'),
        providers=ProviderConfig(bindings={},equity_bindings={}),
        execution_spec=execution_spec_from_dict(result['accounts']['CENTER']['definition']['execution_spec']))
    refs=[d.EvidenceRef.from_dict(v) for path in (work/'others/evidence_refs.json',out/'evidence_refs.json') for v in read(path)]
    # Preserve the unsuccessful attempt and the explicit recovery, as well as all successful accounts.
    for folder in ('src','others'):
        for path in sorted((work/folder).rglob('*')):
            if not path.is_file() or path.suffix not in ('.py','.json') or path.name=='publication_receipt.json':
                continue
            name='material-'+path.relative_to(work).with_suffix('').as_posix().replace('/','-')
            refs.append(publish_evidence(context,d.MaterialEvidenceWrite(exp,name,path.read_bytes(),
                'text/x-python' if path.suffix=='.py' else 'application/json',path.suffix[1:])))
    refs=tuple(dict.fromkeys(refs))
    body=(work/'report.md').read_bytes()
    report=publish_evidence(context,d.ExperimentReportWrite(exp,sha256(body).hexdigest(),d.ExperimentOutcome.COMPLETED,refs))
    artifacts=tuple(d.ExperimentArtifactRef(exp,path.relative_to(work).as_posix(),sha256(path.read_bytes()).hexdigest())
        for folder in ('src','others') for path in sorted((work/folder).rglob('*'))
        if path.is_file() and path.name!='publication_receipt.json')
    checked=validate_experiment(repo,d.ExperimentValidationRequest(exp,d.ExperimentValidationScope.REPORT_PUBLICATION,artifacts))
    receipt={'report':report.to_dict(),'validation':asdict(checked),'scope':'Published experiment only; not complete stage-four acceptance.'}
    (work/'others/publication_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps({'report':report.sha256,'validation':checked.status.value,'issues':checked.issues},ensure_ascii=False,default=str),flush=True)
    assert checked.status.value=='PASS',checked.issues


if __name__=='__main__':
    main()
