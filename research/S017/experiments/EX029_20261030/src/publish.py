"""Publish the checked event/account result and exact report predecessor."""
from common import (ROOT, WORK, EXPERIMENT, REPOSITORY, context, read, save, digest, authenticate, material)
from czsc_trader.application import publish_evidence, validate_experiment
from czsc_trader.research_tools import (EvidenceRef, ExperimentReportWrite, ExperimentOutcome,
    ExperimentValidationRequest, ExperimentValidationScope)


def main():
    pre = read(WORK/'others/pre_run_evidence.json')
    for relative, ref in pre['materials'].items():
        if digest(ROOT/relative) != digest(authenticate(ref)):
            raise ValueError('Frozen event source changed: '+relative)
    events = read(WORK/'others/result_validation.json')
    accounts = read(WORK/'others/account_result_validation.json')
    judgment = read(WORK/'others/judgment.json')
    if (events['status'] != 'PASS' or events['analysis_sha256'] != digest(WORK/'others/census.json')
            or judgment['census_sha256'] != digest(WORK/'others/census.json')
            or accounts['status'] != 'PASS' or judgment['account_analysis_sha256'] != digest(WORK/'others/account_analysis.json')):
        raise ValueError('Source-bound current event, account and judgment checks required')
    research = context()
    paths = [*sorted((WORK/'src').glob('*.py')), *sorted((WORK/'protocols').glob('*.*')),
             *sorted(p for p in (WORK/'others').rglob('*') if p.is_file() and p.name != 'publication.json')]
    refs = {str(p.relative_to(WORK)).replace('\\', '/'): material(research, 'result-'+str(j), p).to_dict()
            for j, p in enumerate(paths)}
    formal = [v['evidence'] for v in read(WORK/'others/accounts_v3.json').values()]
    formal += [v['evidence'] for v in read(WORK/'others/account_analysis.json')['diagnostics'].values()]
    associated = tuple(EvidenceRef.from_dict(v) for v in [*pre['materials'].values(),
        pre['retained_report'], pre['retained_events'], pre['retained_census'], *refs.values(), *formal])
    pointer = WORK/'report_ref.json'
    previous = EvidenceRef.from_dict(read(pointer)['report']) if pointer.exists() else None
    report = publish_evidence(research, ExperimentReportWrite(EXPERIMENT, digest(WORK/'report.md'),
        ExperimentOutcome.COMPLETED, associated, previous))
    checked = validate_experiment(REPOSITORY, ExperimentValidationRequest(EXPERIMENT,
        ExperimentValidationScope.REPORT_PUBLICATION))
    save(WORK/'others/publication.json', {'report': report.to_dict(), 'materials': refs, 'validation': checked.to_dict()})
    if checked.status.value != 'PASS':
        raise ValueError('Report publication validation failed')
    print('REPORT_PUBLICATION_PASS', flush=True)


if __name__ == '__main__':
    main()
