"""Publish this bounded migration experiment without advancing research stages."""
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.application import RepositoryContext, publish_evidence, validate_experiment, get_research_overview
from czsc_trader import research_tools as d
from candidate import build_candidate
from data_inputs import build_data_context

ROOT = Path(__file__).resolve().parents[5]
EXP = Path(__file__).resolve().parents[1]


def main():
    assert not (EXP/'report_ref.json').exists(), 'Do not overwrite a published report'
    candidate = build_candidate()
    repository = RepositoryContext.discover(ROOT)
    context, _, _ = build_data_context(repository, candidate.definition.execution_spec)
    experiment = d.ExperimentRef('S018', EXP.name)
    read = lambda path: json.loads(path.read_text(encoding='utf-8'))
    assert read(EXP/'others/replay_outcome.json')['status'] == 'SUCCEEDED'
    assert read(EXP/'others/pte_verification.json')['status'] == 'PASS'
    assert read(EXP/'others/candidate_registration.json')['load_verified']
    refs = [d.EvidenceRef.from_dict(read(EXP/'others'/name)) for name in
            ('account_reference.json','signal_evidence_reference.json')]
    artifacts = []
    for folder in ('src','others','protocols'):
        for path in sorted((EXP/folder).rglob('*')):
            if not path.is_file() or path.suffix not in ('.py','.json','.md') or path.name == 'publication_receipt.json':
                continue
            name = 'material-'+path.relative_to(EXP).with_suffix('').as_posix().replace('/','-')
            media = {'.py':'text/x-python','.json':'application/json','.md':'text/markdown'}[path.suffix]
            refs.append(publish_evidence(context,d.MaterialEvidenceWrite(experiment,name,path.read_bytes(),media,path.suffix[1:])))
            artifacts.append(d.ExperimentArtifactRef(experiment,path.relative_to(EXP).as_posix(),sha256(path.read_bytes()).hexdigest()))
    report = publish_evidence(context,d.ExperimentReportWrite(experiment,
        sha256((EXP/'report.md').read_bytes()).hexdigest(),d.ExperimentOutcome.COMPLETED,tuple(dict.fromkeys(refs))))
    validation = validate_experiment(repository,d.ExperimentValidationRequest(experiment,
        d.ExperimentValidationScope.REPORT_PUBLICATION,tuple(artifacts)))
    overview = get_research_overview(repository,d.ResearchBatchRef('S018'))
    receipt = {'report':report.to_dict(),'validation':asdict(validation),
               'research_overview':overview.to_dict(),
               'scope':'Candidate migration experiment only. No stage-four or stage-five acceptance inherited.'}
    (EXP/'others/publication_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps({'report':report.sha256,'validation':validation.status.value,'issues':validation.issues},default=str))
    assert validation.status.value == 'PASS', validation.issues


if __name__ == '__main__':
    main()
