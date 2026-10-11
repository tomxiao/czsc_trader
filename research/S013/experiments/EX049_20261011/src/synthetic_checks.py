"""Authenticate two independently completed pure prototypes before native evaluation."""
import ast
from common import ROOT, SRC, read, file_hash


def synthetic(plan, source):
    runtime = ROOT / '.tmp/ex049-mean-momentum-prototype'
    oracle = ROOT / '.tmp/ex049-mean-momentum-oracle'
    proofs = [read(runtime / 'focused.json'), read(oracle / 'focused.json')]
    assert all(item['status'] == 'PURE_PASS' for item in proofs)
    assert file_hash(runtime / 'focused.json') == '768a0fcd3dc822d15c80ffab9f0560af0e40cf20735b17f41c779bd1933803f5'
    assert file_hash(oracle / 'focused.json') == 'b6456f097a62461d44240b6e18ad043eb7db20dbac39ba8a0a4562c4c987eb68'
    for path in (runtime / 'strategy_runtime').rglob('*.py'):
        assert path.read_bytes() == (source / path.relative_to(runtime / 'strategy_runtime')).read_bytes()
    assert file_hash(runtime / 'strategy_runtime/strategies/mean_momentum_range.py') == '2c69aa871ff8a5a7fdc15bcd894e181eefb2856d5cb86cc61cef8e992a82f87c'
    original = ast.parse((oracle / 'regime_oracle.py').read_text(encoding='utf-8'))
    formal = ast.parse((SRC / 'regime_oracle.py').read_text(encoding='utf-8'))
    before = {node.name: ast.dump(node, include_attributes=False) for node in original.body if isinstance(node, ast.FunctionDef)}
    after = {node.name: ast.dump(node, include_attributes=False) for node in formal.body if isinstance(node, ast.FunctionDef)}
    assert before == after, 'Only provider-audit import binding adapted; all independent formulas exact'
    parameter = ROOT / '.tmp/ex049-param-checks/focused.json'
    assert file_hash(parameter) == 'c222c5f70f3016ca838b96ee8b676844e2fe3012da6560ce33c9c0ce2ceb6265'
    proof = read(parameter)
    assert proof['status'] == 'PURE_PASS' and proof['financial_calls'] == []
    assert proof['new_account_preparations'] == proof['new_account_evaluations'] == proof['native_account_reads'] == 0
    proofs.append(proof)
    for path in (ROOT / '.tmp/ex049-param-prototype').glob('*.py'):
        assert path.read_bytes() == (SRC / path.name).read_bytes()
    cfg = plan['configurations'][0]
    assert len(plan['configurations']) == 1 and cfg['mechanism'] == 'MEAN_MOMENTUM3'
    assert cfg['parent_control'] == 'B0-TIME'
    expected = next(row for row in plan['controls'] if row['label'] == 'B0-TIME')['payload']['parameters']
    actual = dict(cfg['payload']['parameters'])
    assert actual.pop('mechanism') == 'MEAN_MOMENTUM3' and actual == expected
    return {'status': 'PURE_PASS', 'runtime_and_independent_oracle': proofs,
        'original_numeric_center_exact': True, 'original_full13_domains_32_coordinates': True,
        'new_account_evaluations': 0, 'adaptation': 'Independent oracle SOURCE_CALLS bound to EX049 forbidden-provider context; formulas/functions unchanged'}
