"""Retain the original failed diagnostic and declare a date-only successor."""
from common import ROOT, SRC, PROTOCOLS, RUNS, EXPERIMENT, context, read, write, file_hash
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite


def main():
    assert not (PROTOCOLS / 'technical_correction_reference.json').exists()
    assert not (RUNS / 'analysis.json').exists()
    old = read(PROTOCOLS / 'plan.json')
    geometry = read(PROTOCOLS / 'geometry.json')
    original = {**old['source_files'], **geometry['helper_source_files'],
                **{name: file_hash(SRC / name) for name in ('analyze.py', 'publish_accounts.py')}}
    for name, digest in original.items():
        assert file_hash(SRC / name) == digest
    proof = read(ROOT / '.tmp/ex040-calendar-v2/focused.json')
    assert proof['status'] == 'PURE_PASS' and proof['new_account_evaluations'] == 0
    method = {'name': 'S013-EX040-independent-date-boundary-audit-correction-v2',
        'new_account_evaluations': 0, 'runtime_changed': False,
        'change': 'Replace only invalid T+1-from-signal-OHLC coverage assumption. Original signal OHLC ends09-29 while last valid execution is09-30. Authenticate same prepared public trading-calendar open dates/content hash/PreviousTradingDate and full native signal_dates mapping; independently verify bound execution daily session dates/evaluation_sessions and exact adjacent T-to-valid dates. No later price read into signal feature calculation, date drop, fallback, extra data or account rerun.',
        'original_failure': 'Original analyze.py failed in direction_oracle.py line152 after all4business/5actual accounts succeeded. Original source/geometry/plan/results and failure remain immutable.',
        'failure_sha256': file_hash(PROTOCOLS / 'analysis_failure.json'),
        'original_plan_sha256': file_hash(PROTOCOLS / 'plan.json'),
        'original_geometry_sha256': file_hash(PROTOCOLS / 'geometry.json'),
        'native_matrix_sha256': file_hash(RUNS / 'matrix.json'),
        'source_files': {name: file_hash(SRC / name) for name in ('direction_oracle_v2.py', 'analyze_v2.py',
            'run_parameters_v2.py', 'parameter_analysis_v2.py', 'technical_validation.py', 'declare_correction.py')},
        'original_source_files': original, 'external_source_files': {},
        'focused_proof': proof,
        'pure_checks_source': {'path': '.tmp/ex040-calendar-v2/focused_checks.py',
            'sha256': file_hash(ROOT / '.tmp/ex040-calendar-v2/focused_checks.py'),
            'source': (ROOT / '.tmp/ex040-calendar-v2/focused_checks.py').read_text(encoding='utf-8')},
        'unchanged': 'Same runtime/source/content identities, public native accounts, cash/quantity/fees, all1636signal dates, economic thresholds,13coordinate full domain/32points/geometry. V1 _reconstruct exact AST equality required; only date validation differs.',
        'limits': 'Technical diagnostic correction, not an economic change or second experiment outcome. Failure retained. FULL remains evidence integrity only.'}
    write(PROTOCOLS / 'technical_correction.json', method)
    ctx = context(1)
    refs = {}
    for name, path in (('original-analysis-failure', PROTOCOLS / 'analysis_failure.json'),
                       ('focused-calendar-correction', ROOT / '.tmp/ex040-calendar-v2/focused.json'),
                       ('explicit-technical-correction', PROTOCOLS / 'technical_correction.json')):
        refs[name] = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, name, path.read_bytes(), 'application/json', 'json')).to_dict()
    write(PROTOCOLS / 'technical_correction_reference.json', refs['explicit-technical-correction'])
    write(PROTOCOLS / 'technical_proof_references.json', refs)
    print({'technical_correction': 'DECLARED', 'new_evaluations': 0, 'original_evidence': 'UNCHANGED'}, flush=True)


if __name__ == '__main__':
    main()
