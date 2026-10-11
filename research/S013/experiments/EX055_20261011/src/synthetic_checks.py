"""Authenticate pure proofs frozen before any EX055 account evaluation."""
from common import ROOT, SRC, read, file_hash

def synthetic(plan, source):
    proofs = []
    for folder, expected, status in [('ex055-raw-recovery-prototype', '11ed3bd8e6d8fa68d87221cb547bc44ce4b77a9b20ab63b4c3b36eb647533cb9', 'PURE_PASS'), ('ex055-raw-recovery-oracle', 'c648dae080ee5b7554b573f43bc33d259159e557081a3ec08c475f43e9e2c6b2', 'PASS'), ('ex055-param-checks', 'e4e8ff60bf4aa6986b95d888e9db720223956fceca01e0703fd2bb2ba2780cf6', 'PURE_PASS')]:
        path = ROOT / '.tmp' / folder / 'focused.json'
        assert file_hash(path) == expected
        proof = read(path)
        assert proof['status'] == status
        proofs.append(proof)
    for name, expected in {'strategies/adaptive_range.py': 'f3a8a9e8a69cb61b326c1702bf8b471fa49105fd91cc58ec9d09dc27492669e4', 'strategies/bear_time_below_recovery_range.py': '7d7ddb05d0e9c40ec7d8d194a02aaa8c8093f7d6546c71c2649f299bf15a4b28', 'strategies/confirmed_range.py': 'b1e6b77bd0983791550106c7e468f396371381f58f828cdcaf2c47ce1abf8a4a', 'strategies/range_reversion.py': '899522b56a578190c1f254e21c2babc1fdce6ece58cc3f947cd5e76065d78dd3', 'strategies/reentry_confirmed_range.py': '6dfa9c7d37d8eef604a0dfccb82ebc37ff4e87b44fff04686a27ad8bb7da518c', 'strategies/__init__.py': 'ac1fa511cf4d9619c0a28e400b16a7525c7525fa4e9a30361767b0888f19409c'}.items():
        assert file_hash(source / name) == expected
    for name, expected in {'raw_recovery_oracle.py': '18fbe8df583a8758fc674e829dfccd693a0f09e9bf956357e4743929631cce3b', 'analysis_reference.py': 'c6620ad4905a4b14694916213e019f1e991ff74fc22f6d70f64346ef5b0c5bdb'}.items():
        assert file_hash(SRC / name) == expected
    for path in (ROOT / '.tmp/ex055-param-prototype').glob('*.py'):
        assert path.read_bytes() == (SRC / path.name).read_bytes()
    helper = ROOT / '.tmp/ex055-raw-recovery-oracle/analysis_focused.json'
    assert file_hash(helper) == '9a95ea62bbcdf37e4d14ccd3454b8a282954cb299e87fb2a6448fefd81449fa1'
    cross = ROOT / '.tmp/ex055-crosschecks/result.json'
    assert file_hash(cross) == 'ee062f0ea526503c4319002cfbf1672436db43452cde3ad7b5e8ae3007dcd0b9'
    cross = read(cross)
    assert cross['status'] == 'PURE_PASS' and len(cross['synthetic_paths']) == 33
    assert cross['new_account_preparations'] == cross['new_account_evaluations'] == 0
    assert not cross['provider_calls']
    assert len(plan['configurations']) == 1 and len(plan['controls']) == 2 and len(plan['diagnostic_controls']) == 1
    actual = dict(plan['configurations'][0]['payload']['parameters'])
    assert actual.pop('mechanism') == 'RAW_BEAR_TIME_BELOW_BODY_ACF_RECOVERY'
    assert actual == next(row for row in plan['controls'] if row['label'] == 'B0-TIME')['payload']['parameters']
    assert plan['diagnostic_controls'][0]['candidate_id'] == 'C7880'
    return {'status': 'PURE_PASS', 'proofs': proofs, 'analysis_helper': read(helper), 'independent_33_synthetic_paths': cross,
        'original_numeric_center_exact': True, 'original_full13_domains_same32_and_parent_warmup': True,
        'new_account_evaluations': 0, 'adaptation': 'Prospective frozen runtime/oracle/helper/pure sources; no EX055 financial inputs.'}
