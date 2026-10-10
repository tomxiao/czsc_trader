"""Retain prospective pure verification sources and results without account evaluation."""
from common import ROOT, RUNS, read, write, file_hash


def main():
    source = ROOT / '.tmp/ex041_parameters/focused_checks.py'
    result = read(ROOT / '.tmp/ex041_parameters/focused.json')
    assert result['status'] == 'PURE_PASS' and result['new_account_evaluations'] == 0
    assert result['native_synthetic_oracle_audits'] == 78
    assert result['original_calendar_oracle_AST_identical']
    assert not (RUNS / 'prospective_pure_verification.json').exists()
    write(RUNS / 'prospective_pure_verification.json', {
        'status': 'PURE_PASS', 'new_account_evaluations': 0,
        'parameter_helpers': result, 'parameter_check_source_sha256': file_hash(source),
        'parameter_check_source': source.read_text(encoding='utf-8'),
        'runtime_synthetic': read(ROOT / '.tmp/ex041-synthetic/result.json'),
        'scope': 'Synthetic causality/state/13-domain points and authenticated old native parents; no new complete economic account or parameter robustness claim.'})
    print({'prospective_pure_verification': 'RETAINED'}, flush=True)


if __name__ == '__main__':
    main()
