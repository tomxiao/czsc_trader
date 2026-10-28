"""Independent consistency check for endpoint-state attribution on retained fills."""
from hashlib import sha256
import json
from math import fsum, isclose, log
from pathlib import Path

from czsc_trader.research_tools import EvidenceRef

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]


def main():
    path = WORK/'others/numeric_analysis.json'
    content = path.read_bytes()
    result = json.loads(content)
    assert result['status'] == 'PASS'
    assert result['source_sha256'] == sha256((WORK/'src/diagnose.py').read_bytes()).hexdigest()
    runs, checks = {}, {}
    for key, record in result['accounts'].items():
        ref = EvidenceRef.from_dict(record['source'])
        raw = ref.resolve(ROOT).read_bytes()
        assert sha256(raw).hexdigest() == ref.sha256
        payload = json.loads(raw)
        assert payload['evaluation_id'] == record['evaluation_id']
        run = payload['runs']['candidate']
        assert not run['actions']
        points = run['account_points']
        assert all('2019-01-02' <= p['session'] <= '2025-12-31' for p in points)
        quantities = [0, *(p['quantity'] for p in points)]
        transitions = sum(a != b for a, b in zip(quantities, quantities[1:]))
        assert transitions == len(run['fills'])
        checks[key] = {'status': 'PASS', 'quantity_changes': transitions, 'fills': len(run['fills']),
                       'note': 'Every fill has an endpoint quantity change; no hidden same-bar roundtrip or refill is omitted by this partition.'}
        runs[key] = run
    annual_checks = []
    flat_partition_checks = []
    for pair, value in result['exposure_decomposition'].items():
        subject, baseline = pair.split('_vs_')
        a = runs[subject]['account_points']
        b = runs[baseline]['account_points']
        for label, win in value['windows'].items():
            if label == 'FULL':
                indices = list(range(len(a)))
            elif label == 'PRE_2025':
                indices = [i for i,p in enumerate(a) if p['session'] < '2025-01-01']
            elif label == 'YEAR_2025':
                indices = [i for i,p in enumerate(a) if p['session'] >= '2025-01-01']
            else:
                indices = [i for i,p in enumerate(a) if p['session'].startswith(label+'-')]
            left, right = indices[0], indices[-1]
            pa = a[left-1]['equity'] if left else 100000.
            pb = b[left-1]['equity'] if left else 100000.
            direct = log((a[right]['equity']/pa)/(b[right]['equity']/pb))
            assert isclose(direct, win['totals']['relative_log_return'], abs_tol=1e-10)
            detail = win['flat_breakdown']
            expected_keys = {(phase, sign) for phase in ('BEFORE_FIRST_ENTRY', 'AFTER_PRIOR_HOLDING')
                             for sign in ('UP', 'DOWN', 'ZERO')}
            assert len(detail) == 6
            assert {(r['phase'], r['baseline_sign']) for r in detail} == expected_keys
            whole = win['states']['BASELINE_ONLY_HELD']
            assert sum(r['intervals'] for r in detail) == whole['intervals']
            residuals = {}
            for field in ('subject_log_return', 'baseline_log_return', 'relative_log_return'):
                combined = fsum(r[field] for r in detail)
                assert isclose(combined, whole[field], abs_tol=1e-10)
                residuals[field] = combined-whole[field]
            flat_partition_checks.append({'pair': pair, 'window': label,
                                          'phase_sign_members': len(detail), 'intervals': whole['intervals'],
                                          'log_sum_residuals': residuals})
            annual_checks.append({'pair': pair, 'window': label,
                                  'direct_log_wealth_gap': direct,
                                  'residual': win['totals']['relative_log_return']-direct})
    output = {'status': 'PASS', 'numeric_analysis_sha256': sha256(content).hexdigest(),
              'validation_source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'fill_endpoint_checks': checks, 'window_telescoping_checks': annual_checks,
              'flat_phase_sign_partition_checks': flat_partition_checks}
    (WORK/'others/partition_validation.json').write_bytes(json.dumps(output, ensure_ascii=False, indent=2).encode())
    print('PARTITION_VALIDATION PASS', checks, 'windows', len(annual_checks))


if __name__ == '__main__':
    main()
