"""Authenticate independently frozen pure proofs and unchanged original numeric contract."""
from common import ROOT, SRC, read, file_hash

def synthetic(plan, source):
    proofs = []
    for folder, expected in (
        (ROOT / '.tmp/ex053-raw-below-prototype', '0317345e6b103bf657d28c085e5836b112b78284d883531ca54d57df108e3b1b'),
        (ROOT / '.tmp/ex053-raw-below-oracle', '0ac711dae6043f258f862d8dc77ef4663b0e49d56c115f7e1672460c72e3c532'),
        (ROOT / '.tmp/ex053-param-checks', 'd10a873696580ffac548ea3a745e7808ee2d94a8e1a9f5594a08be75ddfc7c33')):
        assert file_hash(folder / 'focused.json') == expected
        proof = read(folder / 'focused.json')
        assert proof['status'] == ('PASS' if folder.name == 'ex053-raw-below-oracle' else 'PURE_PASS')
        proofs.append(proof)
    runtime = ROOT / '.tmp/ex053-raw-below-prototype/strategy_runtime'
    for path in runtime.rglob('*.py'):
        assert path.read_bytes() == (source / path.relative_to(runtime)).read_bytes()
    assert file_hash(source / 'strategies/bear_time_below_range.py') == 'fdaaf0f19095cceb6349678be15c0722f3a683be0d585f289b88412f294eb02f'
    import ast
    pure_path = ROOT / '.tmp/ex053-raw-below-oracle/raw_below_oracle.py'
    formal_path = SRC / 'raw_below_oracle.py'
    assert file_hash(pure_path) == '922865b5bfb4ca429f09344857a51e15c7c742538a05ac4702c56025a5e9132a'
    assert formal_path.read_bytes() == pure_path.read_bytes().replace(b'\r\n', b'\n')
    assert ast.dump(ast.parse(formal_path.read_text(encoding='utf-8')), include_attributes=False) == ast.dump(ast.parse(pure_path.read_text(encoding='utf-8')), include_attributes=False)
    for path in (ROOT / '.tmp/ex053-param-prototype').glob('*.py'):
        assert path.read_bytes() == (SRC / path.name).read_bytes()
    cross = ROOT / '.tmp/ex053-crosschecks/result.json'
    assert file_hash(cross) == '52add7d44a5aaeb35058e8f33044701923f3cceb9a7b0655f1fc725034d42f3b'
    cross = read(cross)
    assert cross['status'] == 'PURE_PASS' and len(cross['synthetic_paths']) == 33
    assert cross['new_account_preparations'] == cross['new_account_evaluations'] == 0
    assert not cross['provider_calls']
    assert len(plan['configurations']) == 1 and len(plan['controls']) == 2 and len(plan['diagnostic_controls']) == 1
    actual = dict(plan['configurations'][0]['payload']['parameters'])
    assert actual.pop('mechanism') == 'RAW_BEAR_TIME_BELOW_CLOSE'
    assert actual == next(row for row in plan['controls'] if row['label'] == 'B0-TIME')['payload']['parameters']
    assert plan['diagnostic_controls'][0]['candidate_id'] == 'C8701'
    return {'status': 'PURE_PASS', 'proofs': proofs, 'independent_33_synthetic_paths': cross,
        'original_numeric_center_exact': True, 'original_full13_domains_same32_and_parent_warmup': True,
        'new_account_evaluations': 0, 'adaptation': 'Runtime/formal helpers byteexact; oracle only exact CRLF-to-LF normalization and full AST equality to independently completed pure proofs; no financial account inputs.'}
