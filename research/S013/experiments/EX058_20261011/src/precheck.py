"""Public serial/spawn preflight for one raw-ACF BELOW reentry direction center only."""
# ruff: noqa: E402
import os
for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[variable] = '1'
import pandas as pd
from synthetic_checks import synthetic
from common import SRC, PROTOCOLS, RUNS, CACHE, SOURCE_CALLS, read, write, request, context, cache_write, file_hash


def source_check():
    plan = read(PROTOCOLS / 'plan.json')
    for name, digest in plan['source_files'].items():
        assert file_hash(SRC / name) == digest
    for name, digest in plan['external_source_files'].items():
        from common import ROOT
        assert file_hash(ROOT / name) == digest
    return plan


def main():
    assert not (RUNS / 'precheck.json').exists()
    plan = source_check()
    write(RUNS / 'synthetic_check.json', synthetic(plan, SRC / 'strategy_runtime'))
    from common import ROOT
    previous = ROOT / 'research/S013/experiments/EX057_20261011/protocols'
    assert read(ROOT / 'research/S013/assets/runs/EX057_20261011/delivery_validation.json')['status'] == 'PASS'
    assert read(previous / 'delivery_reference.json') == plan['previous_delivery']
    config = plan['configurations'][0]
    assert len(plan['configurations']) == 1 and config['label'] == 'N0'
    from common import EXPERIMENT
    from czsc_trader.research_tools.evidence import EvidenceRef
    screen_refs = [EvidenceRef.from_dict(read(PROTOCOLS / name)) for name in ('center_screen_method_reference.json', 'center_screen_reference.json')]
    for ref in screen_refs:
        assert ref.experiment == EXPERIMENT and file_hash(ref.resolve(ROOT)) == ref.sha256
    screen = read(screen_refs[1].resolve(ROOT))
    assert screen['status'] == 'PASS_INCREMENTAL' and screen['signal_days'] == 1636
    assert screen['target_different_days'] > 0
    assert screen['new_content_sha256'] == config['content_sha256']
    assert screen['old_candidate'] == 'C7980' and screen['new_candidate'] == config['candidate_id'] == 'C8880'
    assert screen['method_sha256'] == screen_refs[0].sha256
    assert screen['new_account_preparations'] == screen['new_account_evaluations'] == 0 and not screen['provider_calls']
    bound = context(1).evaluation.prepare(request(config))
    print({'prepared': 'N0'}, flush=True)
    serial = context(1).evaluation.evaluate(bound)
    cache_write(CACHE / 'preflight-serial.pkl.gz', (bound, serial))
    print({'serial': 'SUCCEEDED'}, flush=True)
    outcome = context(2).evaluation.evaluate_many((bound,))[0]
    assert outcome.status.value == 'SUCCEEDED', outcome.error
    parallel = outcome.result
    cache_write(CACHE / 'preflight-spawn.pkl.gz', (bound, parallel))
    a, b = serial.runs[0], parallel.runs[0]
    pd.testing.assert_frame_equal(a.signals.decisions, b.signals.decisions, check_exact=True)
    for kind in ('execution', 'buyhold'):
        left, right = getattr(a, kind), getattr(b, kind)
        if kind == 'buyhold':
            left, right = left.execution, right.execution
        for field in ('decisions', 'orders', 'fills', 'account_daily', 'trades'):
            pd.testing.assert_frame_equal(getattr(left, field), getattr(right, field), check_exact=True)
    assert serial.result_hash == parallel.result_hash and not SOURCE_CALLS
    assert serial.runs[0].identity.content_sha256 == config['content_sha256']
    cache_write(CACHE / 'N0.pkl.gz', (bound, serial))
    write(RUNS / 'precheck.json', {'status': 'PASS', 'serial_spawn': 'EXACT_EQUAL signals and5ledgers on both accounts',
        'result_hash': serial.result_hash, 'configuration': 'N0', 'actual_evaluations': 2,
        'new_business_configurations': 1, 'provider_calls': SOURCE_CALLS})
    write(RUNS / 'matrix.json', {'status': 'COMPLETE', 'rows': [{'label': 'N0', 'index': 0,
        'candidate_id': config['candidate_id'], 'content_sha256': config['content_sha256'], 'status': 'SUCCEEDED',
        'request_hash': serial.request_hash, 'result_hash': serial.result_hash}],
        'new_account_evaluations': 2, 'new_business_configurations': 1, 'historical_controls': 4,
        'provider_calls': SOURCE_CALLS})
    print({'precheck': 'PASS', 'new_business': 1, 'actual': 2}, flush=True)


if __name__ == '__main__':
    main()
