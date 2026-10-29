"""Publish the integrated result only after source-bound checks and diagnosis."""
from czsc_trader.application import publish_evidence, validate_experiment
from czsc_trader.research_tools import (EvidenceRef, ExperimentReportWrite, ExperimentOutcome,
    ExperimentValidationRequest, ExperimentValidationScope)
from run import ROOT, WORK, REPOSITORY, EXPERIMENT, context, read, save, digest, material

def main():
    research = context()
    before = read(WORK/'others/pre_run_evidence.json')
    files = [(p.stem+'-source', p) for p in sorted((WORK/'src').glob('*.py'))
             if p.stem in ('run', 'strategy', 'precheck', 'check_mechanism', 'analyze')]
    files += [(p.stem.replace('_', '-'), p) for p in sorted((WORK/'protocols').iterdir()) if p.is_file()]
    files += [('precheck', WORK/'others/precheck.json'),
        ('precheck-mechanism', WORK/'others/precheck_mechanism.json'),
        ('entry-reproduction', WORK/'others/entry_reproduction.json')]
    for name, path in files:
        ref = EvidenceRef.from_dict(before[name])
        if digest(ref.resolve(ROOT)) != digest(path):
            raise ValueError('Published pre-run evidence changed: '+name)
    analysis = read(WORK/'others/analysis.json')
    verified, judgment = read(WORK/'others/result_validation.json'), read(WORK/'others/judgment.json')
    if (analysis['status'] != 'PASS' or verified['status'] != 'PASS'
            or verified['analysis_sha256'] != digest(WORK/'others/analysis.json')
            or verified['verification_source_sha256'] != digest(WORK/'src/verify.py')
            or judgment['analysis_sha256'] != digest(WORK/'others/analysis.json')):
        raise ValueError('Result checks or judgment do not bind the analyzed result')
    extras = [('analysis', WORK/'others/analysis.json'), ('verification', WORK/'others/result_validation.json'),
        ('analysis-revision', WORK/'others/analysis_revision.json'),
        ('judgment', WORK/'others/judgment.json'), ('account-manifest', WORK/'others/accounts.json'),
        ('execution-status', WORK/'others/execution_status.json'), ('execution-stats', WORK/'others/execution_stats.json'),
        ('publication-status', WORK/'others/publication_status.json')]
    extras += [(p.stem+'-source', p) for p in sorted((WORK/'src').glob('*.py'))
               if p.stem not in ('run', 'strategy', 'precheck', 'check_mechanism', 'analyze')]
    published = {name: material(research, name, path).to_dict() for name, path in extras}
    account_refs = [item['evidence'] for item in read(WORK/'others/accounts.json').values()]
    diagnostic_refs = [item['evidence'] for item in analysis['diagnostics'].values()]
    references = tuple(EvidenceRef.from_dict(v) for v in
        [*before.values(), *published.values(), *account_refs, *diagnostic_refs])
    report = publish_evidence(research, ExperimentReportWrite(EXPERIMENT, digest(WORK/'report.md'),
        ExperimentOutcome.COMPLETED, references))
    validation = validate_experiment(REPOSITORY, ExperimentValidationRequest(EXPERIMENT,
        ExperimentValidationScope.REPORT_PUBLICATION))
    save(WORK/'others/publication.json', {'report': report.to_dict(), 'materials': published,
        'validation': validation.to_dict()})
    if validation.status.value != 'PASS':
        raise ValueError('Report publication failed validation')
    print('REPORT_PUBLICATION_PASS', flush=True)

if __name__ == '__main__':
    main()
