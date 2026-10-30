"""Publish this experiment's source-bound report and result metadata."""
from common import (ROOT, WORK, EXPERIMENT, REPOSITORY, read, save, digest, context, material, authenticate)
from czsc_trader.application import publish_evidence, validate_experiment
from czsc_trader.research_tools import (EvidenceRef, ExperimentReportWrite, ExperimentOutcome,
    ExperimentValidationRequest, ExperimentValidationScope)


def main():
    before = read(WORK/'others/pre_run_evidence.json')['materials']
    for relative, ref in before.items():
        if digest(ROOT/relative) != digest(authenticate(ref)):
            raise ValueError('Frozen source changed: '+relative)
    check, judgment = read(WORK/'others/result_validation.json'), read(WORK/'others/judgment.json')
    if check['status'] != 'PASS' or judgment['census_sha256'] != digest(WORK/'others/census.json'):
        raise ValueError('Source-bound results and judgment required')
    research = context()
    paths = [*sorted((WORK/'src').glob('*.py')), *sorted((WORK/'protocols').glob('*.*')),
             *sorted(p for p in (WORK/'others').glob('*.*') if p.name not in ('publication.json', 'pre_run_evidence.json'))]
    refs = {str(p.relative_to(WORK)).replace('\\', '/'): material(research, 'result-'+str(j), p).to_dict()
            for j, p in enumerate(paths)}
    accounts = read(WORK/'others/accounts.json') if (WORK/'others/accounts.json').exists() else {}
    associated = tuple(EvidenceRef.from_dict(v) for v in
        [*before.values(), *refs.values(), *[a['evidence'] for a in accounts.values()]])
    report = publish_evidence(research, ExperimentReportWrite(EXPERIMENT, digest(WORK/'report.md'),
        ExperimentOutcome.COMPLETED, associated))
    checked = validate_experiment(REPOSITORY, ExperimentValidationRequest(EXPERIMENT,
        ExperimentValidationScope.REPORT_PUBLICATION))
    save(WORK/'others/publication.json', {'report': report.to_dict(), 'materials': refs, 'validation': checked.to_dict()})
    if checked.status.value != 'PASS':
        raise ValueError('Report publication validation failed')
    print('REPORT_PUBLICATION_PASS', flush=True)


if __name__ == '__main__':
    main()
