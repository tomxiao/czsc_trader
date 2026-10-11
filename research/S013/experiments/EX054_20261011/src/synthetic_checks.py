"""Authenticate pure proofs frozen before any EX054 account evaluation."""
from common import ROOT, SRC, read, file_hash

def synthetic(plan, source):
    proofs = []
    for folder, expected, status in [('ex054-raw-body-prototype', 'd05bffd944ed249b1847aac44feb5b1051f8d2e171c6b3a40ddb6901a08b220a', 'PURE_PASS'), ('ex054-raw-body-oracle', '4ce1f792dbc97d8f1e16e48040cc285c7068533faa1a2e93fc7e36f17c52815c', 'PASS'), ('ex054-param-checks', '1fbfd96b76efe08f28058138f8e699e9ae9fb3b40f0ef3a11ac735ca86bfb484', 'PURE_PASS')]:
        path = ROOT / '.tmp' / folder / 'focused.json'
        assert file_hash(path) == expected
        proof = read(path)
        assert proof['status'] == status
        proofs.append(proof)
    for name, expected in {'strategies/adaptive_range.py': 'f3a8a9e8a69cb61b326c1702bf8b471fa49105fd91cc58ec9d09dc27492669e4', 'strategies/bear_time_below_body_range.py': 'c92e8387bb1a81feb8777cadde01d7903a644b402093ff3b4d5ddac1cad8920b', 'strategies/confirmed_range.py': 'b1e6b77bd0983791550106c7e468f396371381f58f828cdcaf2c47ce1abf8a4a', 'strategies/range_reversion.py': '899522b56a578190c1f254e21c2babc1fdce6ece58cc3f947cd5e76065d78dd3', 'strategies/reentry_confirmed_range.py': '6dfa9c7d37d8eef604a0dfccb82ebc37ff4e87b44fff04686a27ad8bb7da518c', 'strategies/__init__.py': 'a4ea34f3027f0896c2cace440a6e20bdb784790bcf9fd4951506556a2c6ff0fc'}.items():
        assert file_hash(source / name) == expected
    for name, expected in {'raw_body_oracle.py': 'd5984e4fcbd2377c9014b3deae08be51db3f9a7063fb8ff7ac213bd5bdde72d6', 'analysis_reference.py': '11845befa9db40dd26df7f8351a5b79e1e2c6d5e9d61a48166c245c822f7686c'}.items():
        assert file_hash(SRC / name) == expected
    for path in (ROOT / '.tmp/ex054-param-prototype').glob('*.py'):
        assert path.read_bytes() == (SRC / path.name).read_bytes()
    helper = ROOT / '.tmp/ex054-raw-body-oracle/analysis_focused.json'
    assert file_hash(helper) == '35edb9672e0ec598fd045396830ec0677e33d4a5ae03357b5dd9c4d25c9a4dc2'
    cross = ROOT / '.tmp/ex054-crosschecks/result.json'
    assert file_hash(cross) == '1b72a3905b83acf6e9366e907ce9ad182cfda2b8a38598750e64e69197767f34'
    cross = read(cross)
    assert cross['status'] == 'PURE_PASS' and len(cross['synthetic_paths']) == 33
    assert cross['new_account_preparations'] == cross['new_account_evaluations'] == 0
    assert not cross['provider_calls']
    assert len(plan['configurations']) == 1 and len(plan['controls']) == 2 and len(plan['diagnostic_controls']) == 3
    actual = dict(plan['configurations'][0]['payload']['parameters'])
    assert actual.pop('mechanism') == 'RAW_BEAR_TIME_BELOW_BODY'
    assert actual == next(row for row in plan['controls'] if row['label'] == 'B0-TIME')['payload']['parameters']
    assert set(row['candidate_id'] for row in plan['diagnostic_controls']) == {'C8701', 'C7580', 'C4901'}
    return {'status': 'PURE_PASS', 'proofs': proofs, 'analysis_helper': read(helper), 'independent_33_synthetic_paths': cross,
        'original_numeric_center_exact': True, 'original_full13_domains_same32_and_parent_warmup': True,
        'new_account_evaluations': 0, 'adaptation': 'Prospective frozen runtime/oracle/helper/pure sources; no EX054 financial inputs.'}
