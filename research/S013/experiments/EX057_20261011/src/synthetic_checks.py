"""Authenticate pure proofs frozen before any EX057 account evaluation."""
from common import ROOT, SRC, read, file_hash

def synthetic(plan, source):
    proofs = []
    for folder, expected, status in [('ex057-supported-recovery-prototype', '5cd3ee8df9ace4073a3709720b885550e282609bc494d5ce699545275d86b528', 'PURE_PASS'), ('ex057-supported-recovery-oracle-v2', 'b13b2cb3c3914fa9e50e161b92be8314f0779a80e80b52b7a3965009a319ddc3', 'PASS'), ('ex057-param-checks', '00e7446a81641a47df1c358222690e22a70142009aef119ffa17ca9bd06c1b4d', 'PURE_PASS')]:
        path = ROOT / '.tmp' / folder / 'focused.json'
        assert file_hash(path) == expected
        proof = read(path)
        assert proof['status'] == status
        proofs.append(proof)
    for name, expected in {'strategies/adaptive_range.py': 'f3a8a9e8a69cb61b326c1702bf8b471fa49105fd91cc58ec9d09dc27492669e4', 'strategies/bear_time_below_supported_recovery_range.py': '20b24b84e17eaedb4288af8363c775b53ed119ed4743fd67c945a5ea74d21850', 'strategies/confirmed_range.py': 'b1e6b77bd0983791550106c7e468f396371381f58f828cdcaf2c47ce1abf8a4a', 'strategies/range_reversion.py': '899522b56a578190c1f254e21c2babc1fdce6ece58cc3f947cd5e76065d78dd3', 'strategies/reentry_confirmed_range.py': '6dfa9c7d37d8eef604a0dfccb82ebc37ff4e87b44fff04686a27ad8bb7da518c', 'strategies/__init__.py': '012dc455681d72bf476154139f394aab6ea01363be7bbb1fb2ee101aad5f5743'}.items():
        assert file_hash(source / name) == expected
    for name, expected in {'supported_recovery_oracle.py': 'a12b24616be3610b2f489a55c3852712f9b8342b96c67dc3d7c3a8df69bd042c', 'analysis_reference.py': '154620c1c9ad458ea12e847e8265598e4aac1b2229c03d23166947eb2ece2391'}.items():
        assert file_hash(SRC / name) == expected
    for path in (ROOT / '.tmp/ex057-param-prototype').glob('*.py'):
        assert path.read_bytes() == (SRC / path.name).read_bytes()
    helper = ROOT / '.tmp/ex057-supported-recovery-oracle-v2/analysis_focused.json'
    assert file_hash(helper) == '76326864c7dfa66e24d0bb270cf92a037da37ab5810b26899680b74b390dc9f9'
    cross = ROOT / '.tmp/ex057-crosschecks-v2/result.json'
    assert file_hash(cross) == 'b3b28c5631508de805226e033f8a21cfc4328321dc63be4cea2abcf57b370595'
    cross = read(cross)
    assert cross['status'] == 'PURE_PASS' and len(cross['synthetic_paths']) == 33
    assert cross['new_account_preparations'] == cross['new_account_evaluations'] == 0
    assert not cross['provider_calls']
    assert len(plan['configurations']) == 1 and len(plan['controls']) == 2 and len(plan['diagnostic_controls']) == 1
    actual = dict(plan['configurations'][0]['payload']['parameters'])
    assert actual.pop('mechanism') == 'RAW_BEAR_TIME_BELOW_BODY_SUPPORTED_ACF_RECOVERY'
    assert actual == next(row for row in plan['controls'] if row['label'] == 'B0-TIME')['payload']['parameters']
    assert plan['diagnostic_controls'][0]['candidate_id'] == 'C7980'
    return {'status': 'PURE_PASS', 'proofs': proofs, 'analysis_helper': read(helper), 'independent_33_synthetic_paths': cross,
        'original_numeric_center_exact': True, 'original_full13_domains_same32_and_parent_warmup': True,
        'new_account_evaluations': 0, 'adaptation': 'Only BODY and original neutral-score-supported local recovery, independently crosschecked; no EX057 financial inputs.'}
