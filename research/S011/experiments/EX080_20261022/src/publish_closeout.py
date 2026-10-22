"""Preserve comparison artifacts and publish the final technical report."""
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from repair import ROOT, EROOT, RESULTS, EXPERIMENT_ID, read, save
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef, EvaluationResources,
    MaterialEvidenceWrite, ExperimentReportWrite, ExperimentOutcome, EvidenceRef)
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence


def main():
    ctx = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S011'),
                                 resources=EvaluationResources(1, 1, 13))
    exp = ExperimentRef('S011', EXPERIMENT_ID)
    old = ROOT / 'strategies/S011/releases/v1/src/strategy_runtime'
    new = EROOT / 'src/strategy_runtime'
    assert (old / 'calculation.py').read_bytes() == (new / 'calculation.py').read_bytes()
    expected = (old / 'strategies/s011_reversal.py').read_text(encoding='utf-8')
    for a, b in [("'159326.SZ', 'daily', 30", "'159326.SZ', 'daily', 20"),
                 ("'159326.SZ', '30m', 30", "'159326.SZ', '30m', 20"),
                 ("'000300.SH', 'daily', 30", "'000300.SH', 'daily', 21")]:
        assert expected.count(a) == 1
        expected = expected.replace(a, b)
    assert expected == (new / 'strategies/s011_reversal.py').read_text(encoding='utf-8')
    legacy = []
    for digest in ('802a3968df9ac7cfc42d283033b4d1d594b5be7ca1fd9b8fef9bf897e0e6c28a',
                   '5cc2362d4a859bf0d3bb8e5386049b69328cd19b8aac7b9a93ebc8110490030a'):
        path = ROOT / 'experiments/S011/EX078_20261003/objects/inspection' / digest
        assert sha256(path.read_bytes()).hexdigest() == digest
        value = read(path)
        errors = []
        for candidate in (value, value['result']):
            try:
                validate_evaluation_evidence(candidate)
            except ValueError as exc:
                errors.append(str(exc))
            else:
                raise AssertionError('legacy authentication unexpectedly supported')
        legacy.append({'path': path.relative_to(ROOT).as_posix(), 'sha256': digest,
                       'result_schema_version': value['result']['schema_version'],
                       'current_authentication': 'UNSUPPORTED_CONTRACT', 'errors': errors})
    save(EROOT / 'others/legacy_evidence_limit.json', {'source_diff_only_three_minima': True, 'legacy': legacy})
    comparison = read(RESULTS / 'verification.json')
    folders = {x[k] for x in comparison['comparisons'] for k in ('old', 'new')}
    folders.add(read(RESULTS / 'backtest_2025-02-06.json')['data']['output_dir'])
    buffer = BytesIO()
    with ZipFile(buffer, 'w', compression=ZIP_DEFLATED) as bundle:
        for folder in sorted(folders):
            for path in sorted((ROOT / folder).iterdir()):
                if path.suffix in ('.csv', '.json', '.md'):
                    bundle.writestr(path.relative_to(ROOT).as_posix(), path.read_bytes())
        for path in sorted(RESULTS.glob('*.json')):
            bundle.writestr(path.relative_to(ROOT).as_posix(), path.read_bytes())
        path = EROOT / 'others/legacy_evidence_limit.json'
        bundle.writestr(path.relative_to(ROOT).as_posix(), path.read_bytes())
    bundle_ref = publish_evidence(ctx, MaterialEvidenceWrite(exp, 'comparison_accounts',
        buffer.getvalue(), 'application/zip', 'zip'))
    save(EROOT / 'others/comparison_accounts_evidence.json', bundle_ref.to_dict())
    refs = tuple(EvidenceRef.from_dict(read(EROOT / 'others' / name)) for name in
                 ('account_evidence.json', 'verification_evidence.json', 'comparison_accounts_evidence.json'))
    report = EROOT / 'report.md'
    ref = publish_evidence(ctx, ExperimentReportWrite(exp, sha256(report.read_bytes()).hexdigest(),
                          ExperimentOutcome.COMPLETED, refs))
    print('PUBLISHED', ref.repository_path, flush=True)


if __name__ == '__main__':
    main()
