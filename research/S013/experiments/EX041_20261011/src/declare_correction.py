"""Retain the original nullable-category audit failure and declare an exact successor."""
from common import ROOT, SRC, PROTOCOLS, RUNS, EXPERIMENT, context, read, write, file_hash
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite


def main():
    assert not (PROTOCOLS / 'technical_correction_reference.json').exists()
    assert not (RUNS / 'analysis.json').exists()
    plan, geometry = read(PROTOCOLS / 'plan.json'), read(PROTOCOLS / 'geometry.json')
    original = {**plan['source_files'], **geometry['helper_source_files'],
                **{name: file_hash(SRC / name) for name in ('analyze.py', 'publish_accounts.py')}}
    for name, digest in original.items():
        assert file_hash(SRC / name) == digest
    failure = {'status': 'FAILED', 'phase': 'original-analysis', 'source': 'direction_oracle.py:198',
               'exception': 'AssertionError', 'field': 'last_exit_reason',
               'first_native_account': 'N0', 'mismatched_elements': 493, 'signal_days': 1636,
               'actual_absence': 'float NaN in execution categorical column',
               'desired_absence': 'None in independently reconstructed categorical column',
               'new_native_accounts_succeeded': 2, 'actual_evaluations': 3,
               'original_program_sha256': file_hash(SRC / 'analyze.py'),
               'original_oracle_sha256': file_hash(SRC / 'direction_oracle.py'),
               'matrix_sha256': file_hash(RUNS / 'matrix.json')}
    write(PROTOCOLS / 'analysis_failure.json', failure)
    proof = read(ROOT / '.tmp/ex041-null-v2/focused.json')
    assert proof['status'] == 'PURE_PASS' and proof['new_account_evaluations'] == 0
    method = {'name': 'S013-EX041-nullable-exit-metadata-audit-v2',
        'new_account_evaluations': 0, 'runtime_changed': False,
        'change': 'Compare absence only for last_exit_reason and last_exit_route: reconstructed None matches native None or floating NaN only at exactly the independently reconstructed absent positions. At every present position require exact valid category string; mismatched category, invented absence/presence, empty string, numeric value/infinity and any other field are rejected. No blanket NaN replacement or relaxed financial checks.',
        'original_failure': failure,
        'failure_sha256': file_hash(PROTOCOLS / 'analysis_failure.json'),
        'original_plan_sha256': file_hash(PROTOCOLS / 'plan.json'),
        'original_geometry_sha256': file_hash(PROTOCOLS / 'geometry.json'),
        'native_matrix_sha256': file_hash(RUNS / 'matrix.json'),
        'source_files': {name: file_hash(SRC / name) for name in ('direction_oracle_v2.py', 'analyze_v2.py',
            'run_parameters_v2.py', 'parameter_analysis_v2.py', 'pair_parameters_v2.py',
            'technical_validation.py', 'declare_correction.py')},
        'original_source_files': original, 'external_source_files': {}, 'focused_proof': proof,
        'pure_checks_source': {'path': '.tmp/ex041-null-v2/focused_checks.py',
            'sha256': file_hash(ROOT / '.tmp/ex041-null-v2/focused_checks.py'),
            'source': (ROOT / '.tmp/ex041-null-v2/focused_checks.py').read_text(encoding='utf-8')},
        'unchanged': 'All feature/state reconstruction and calendar functions AST identical; runtime/numeric parameters/four gates/13-domain geometry/signal dates/economic accounts and caches unchanged. Full both native signals audited and 17 illegal representation/state drifts rejected before declaration.',
        'limits': 'Diagnostic metadata representation correction only. Original frozen method and failure retained. No new economic account, independent validation, or economic success inferred.'}
    write(PROTOCOLS / 'technical_correction.json', method)
    ctx = context(1)
    refs = {}
    for name, path in (('original-analysis-failure', PROTOCOLS / 'analysis_failure.json'),
                       ('focused-nullable-correction', ROOT / '.tmp/ex041-null-v2/focused.json'),
                       ('explicit-technical-correction', PROTOCOLS / 'technical_correction.json')):
        refs[name] = publish_evidence(ctx, MaterialEvidenceWrite(EXPERIMENT, name, path.read_bytes(), 'application/json', 'json')).to_dict()
    write(PROTOCOLS / 'technical_correction_reference.json', refs['explicit-technical-correction'])
    write(PROTOCOLS / 'technical_proof_references.json', refs)
    print({'technical_correction': 'DECLARED', 'new_evaluations': 0}, flush=True)


if __name__ == '__main__':
    main()
