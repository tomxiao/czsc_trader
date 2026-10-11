"""Authenticate frozen pure proofs before any EX058 account."""
from common import ROOT, SRC, read, file_hash

def synthetic(plan, source):
    proofs = []
    for folder, expected, status in [('ex058-boundary-recovery-prototype', '2fe37290a5c0c153425a5edc75e6020f5554bdc203cc3695f078aac4e84df293', 'PURE_PASS'), ('ex058-boundary-recovery-oracle', '611d964301803a775a7a4a1f33cf7039e05f472f8f5a7ee66592016ec1e02fdc', 'PASS'), ('ex058-param-checks-v2', 'abaa96a3584b561d5fb6dffac50bf0fe0e0ccae21a58e615bc184d4b9b05d0c4', 'PURE_PASS')]:
        path = ROOT / '.tmp' / folder / 'focused.json'
        assert file_hash(path) == expected
        proof = read(path)
        assert proof['status'] == status
        proofs.append(proof)
    for name, expected in {'strategies/adaptive_range.py': 'f3a8a9e8a69cb61b326c1702bf8b471fa49105fd91cc58ec9d09dc27492669e4', 'strategies/boundary_bear_recovery_range.py': '3fc44c4bfe601b26a43cee533303d41e54db365f98c526ccfcf004a9b8afdce8', 'strategies/confirmed_range.py': 'b1e6b77bd0983791550106c7e468f396371381f58f828cdcaf2c47ce1abf8a4a', 'strategies/range_reversion.py': '899522b56a578190c1f254e21c2babc1fdce6ece58cc3f947cd5e76065d78dd3', 'strategies/reentry_confirmed_range.py': '6dfa9c7d37d8eef604a0dfccb82ebc37ff4e87b44fff04686a27ad8bb7da518c', 'strategies/__init__.py': '4f2a781378f173bbfdf43029a57d62a6b009893d2d7c84615d9638956819fbb1'}.items():
        assert file_hash(source / name) == expected
    for name, expected in {'boundary_recovery_oracle.py': '5ca97aedd56918b190e697fbf47b1f0b622cfb7b865b9559c10b5ac16a368a22', 'analysis_reference.py': '7e9e8c16c74421dc40cd10ce2cf2e16e1ccc922f899762ca5cea5f0f165ccb67'}.items():
        assert file_hash(SRC / name) == expected
    for path in (ROOT / '.tmp/ex058-param-prototype-v2').glob('*.py'):
        assert path.read_bytes() == (SRC / path.name).read_bytes()
    helper = ROOT / '.tmp/ex058-boundary-recovery-oracle/analysis_focused.json'
    assert file_hash(helper) == '2854f4a2b1edc6b48474eef0c75e9bfe93d4e08583b443b31bbd316edd1ecb5d'
    cross = ROOT / '.tmp/ex058-crosschecks/result.json'
    assert file_hash(cross) == '456bc73bc5ffe0d728862e0e233df31541ec0f4f9323f1220a7f55eec0db7164'
    cross = read(cross)
    assert cross['status'] == 'PURE_PASS' and len(cross['synthetic_paths']) == 33
    assert cross['new_account_preparations'] == cross['new_account_evaluations'] == 0 and not cross['provider_calls']
    assert len(plan['configurations']) == 1 and len(plan['controls']) == len(plan['diagnostic_controls']) == 2
    actual = dict(plan['configurations'][0]['payload']['parameters'])
    assert actual.pop('mechanism') == 'RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY'
    assert actual == next(row for row in plan['controls'] if row['label'] == 'B0-TIME')['payload']['parameters']
    assert [row['candidate_id'] for row in plan['diagnostic_controls']] == ['C7980', 'C9102']
    return {'status': 'PURE_PASS', 'proofs': proofs, 'analysis_helper': read(helper), 'independent_33_synthetic_paths': cross,
        'original_numeric_center_exact': True, 'original_full13_domains_same32': True, 'warmup_disclosure': 'max(parent,regimeW+2), center32 original actual; full13 extreme62vs61 causal history',
        'new_account_evaluations': 0, 'adaptation': 'Exact20 boundaryBODY plus exact55 localbearBODY recovery; no EX058 financial inputs.'}
