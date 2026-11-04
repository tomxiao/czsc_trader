"""Publish an authored report and its exact research implementation/materials."""
from pathlib import Path
from hashlib import sha256
from dataclasses import asdict
import json
import sys
from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, create_research_context, publish_evidence, validate_experiment)
from dataflows import ProviderConfig
from strategy_runtime.equity_definition import execution_spec_from_dict


def main():
    root = Path.cwd()
    work = root/'research/S018/experiments'/sys.argv[1]
    exp = d.ExperimentRef('S018', work.name)
    read = lambda p: json.loads(p.read_text(encoding='utf-8'))
    record = read(work/'others/results.json')
    definition = next(iter(record['accounts'].values()))['definition']
    repository = RepositoryContext.discover(root)
    context = create_research_context(repository, d.ResearchBatchRef('S018'),
        providers=ProviderConfig(bindings={}, equity_bindings={}), execution_spec=execution_spec_from_dict(definition['execution_spec']))
    refs = [d.EvidenceRef.from_dict(value) for value in read(work/'others/evidence_refs.json')]
    refs.append(d.EvidenceRef.from_dict(read(root/'research/S018/experiments/EX044_20261104/report_ref.json')['report']))
    for path in sorted((work/'src').glob('*.py')):
        refs.append(publish_evidence(context, d.MaterialEvidenceWrite(exp, 'source-'+path.stem,
            path.read_bytes(), 'text/x-python', 'py')))
    for path in sorted((work/'others').glob('analysis_*.json')):
        refs.append(publish_evidence(context, d.MaterialEvidenceWrite(exp, path.stem,
            path.read_bytes(), 'application/json', 'json')))
    refs = tuple(dict.fromkeys(refs))
    (work/'others/evidence_refs.json').write_text(json.dumps([r.to_dict() for r in refs],ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    body = (work/'report.md').read_bytes()
    ref = publish_evidence(context, d.ExperimentReportWrite(exp, sha256(body).hexdigest(), d.ExperimentOutcome.COMPLETED, refs))
    artifacts = tuple(d.ExperimentArtifactRef(exp, p.relative_to(work).as_posix(), sha256(p.read_bytes()).hexdigest())
        for folder in ('src','others') for p in sorted((work/folder).glob('*')) if p.is_file())
    checked = validate_experiment(repository, d.ExperimentValidationRequest(exp, d.ExperimentValidationScope.REPORT_PUBLICATION, artifacts))
    print(json.dumps({'report':ref.to_dict(),'validation':asdict(checked)},ensure_ascii=False,default=str),flush=True)
    assert checked.status.value == 'PASS', checked.issues


if __name__ == '__main__':
    main()
