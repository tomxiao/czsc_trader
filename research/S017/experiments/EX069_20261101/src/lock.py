"""Publish exact previous-session range definitions before any new group returns."""
from common import ROOT, WORK, EXPERIMENT, LABEL_SHA, checked_bytes, digest, material, read, save


def main():
    if (WORK / 'others/census_pre_run.json').exists():
        raise ValueError('Existing immutable pre-label lock; inspect rather than overwrite')
    checks = read(WORK / 'others/precheck.json')
    if checks['status'] != 'PASS' or checks['feature_source_sha256'] != digest(WORK / 'src/features.py'):
        raise ValueError('Current causal feature checks required')
    old = read(ROOT / 'research/S017/experiments/EX061_20261101/others/census_pre_run.json')['execution_labels']
    if old['sha256'] != LABEL_SHA:
        raise ValueError('Wrong original label reference')
    paths = {'common_source': 'src/common.py', 'feature_source': 'src/features.py',
        'census_source': 'src/census.py', 'precheck_source': 'src/precheck.py',
        'lock_source': 'src/lock.py', 'design': 'protocols/design.md',
        'contract': 'protocols/census_contract.json', 'features': 'others/features.json',
        'precheck_result': 'others/precheck.json'}
    refs = {key: material('pre-label-' + key, WORK / path).to_dict() for key, path in paths.items()}
    # Do not resolve or open the return-label blob during lock publication.
    proof = {'status': 'LOCKED_PRE_LABEL', 'experiment': EXPERIMENT.to_dict(), **refs,
        'execution_labels': old, 'new_label_reads': 0, 'new_account_compute': 0}
    path = WORK / 'others/census_pre_run.json'
    save(path, proof)
    public = material('session-range-pre-label-lock', path)
    if checked_bytes(public) != path.read_bytes():
        raise ValueError('Published pre-label proof mismatch')
    save(WORK / 'others/pre_label_publication.json', {'status': 'PUBLISHED_PRE_LABEL', 'lock': public.to_dict()})
    print('PUBLIC_SESSION_RANGE_LOCK_PUBLISHED', public.sha256, flush=True)


if __name__ == '__main__':
    main()
