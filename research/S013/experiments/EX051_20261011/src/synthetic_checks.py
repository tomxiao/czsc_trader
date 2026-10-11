"""Authenticate two independently completed pure prototypes before native evaluation."""
import ast
from common import ROOT, SRC, read, file_hash


def synthetic(plan, source):
    runtime = ROOT / '.tmp/ex051-winsor-acf-prototype'
    oracle = ROOT / '.tmp/ex051-winsor-acf-oracle'
    proofs = [read(runtime / 'focused.json'), read(oracle / 'focused.json')]
    assert all(item['status'] == 'PURE_PASS' for item in proofs)
    assert file_hash(runtime / 'focused.json') == '830da86355e545ea0d6cf77c3d133e7e0f1626fbc44e54a58197452987a6bf23'
    assert file_hash(oracle / 'focused.json') == 'e971604495a3b3ae5864f64370cbb9bdfd23cde030e37c524084a399ee740c75'
    for path in (runtime / 'strategy_runtime').rglob('*.py'):
        assert path.read_bytes() == (source / path.relative_to(runtime / 'strategy_runtime')).read_bytes()
    assert file_hash(runtime / 'strategy_runtime/strategies/bear_winsor_range.py') == 'f445aed8116c9e0d058ff21f4e9086c95bdeb0736424e524de62cb7421153eef'
    original = ast.parse((oracle / 'winsor_oracle.py').read_text(encoding='utf-8'))
    formal = ast.parse((SRC / 'winsor_oracle.py').read_text(encoding='utf-8'))
    before = {node.name: ast.dump(node, include_attributes=False) for node in original.body if isinstance(node, ast.FunctionDef)}
    after = {node.name: ast.dump(node, include_attributes=False) for node in formal.body if isinstance(node, ast.FunctionDef)}
    assert before == after, 'Only provider-audit import binding adapted; all independent formulas exact'
    parameter = ROOT / '.tmp/ex051-param-checks/focused.json'
    assert file_hash(parameter) == 'b060736da2c73bbcf47452499c56a0cb56c276431884a86bcaad894690cf406b'
    proof = read(parameter)
    assert proof['status'] == 'PURE_PASS' and proof['financial_calls'] == []
    assert proof['new_account_preparations'] == proof['new_account_evaluations'] == proof['native_account_reads'] == 0
    proofs.append(proof)
    for path in (ROOT / '.tmp/ex051-param-prototype').glob('*.py'):
        assert path.read_bytes() == (SRC / path.name).read_bytes()
    cfg = plan['configurations'][0]
    assert len(plan['configurations']) == 1 and cfg['mechanism'] == 'BEAR_WINSOR_ACF20'
    assert cfg['parent_control'] == 'B0-TIME'
    expected = next(row for row in plan['controls'] if row['label'] == 'B0-TIME')['payload']['parameters']
    actual = dict(cfg['payload']['parameters'])
    assert actual.pop('mechanism') == 'BEAR_WINSOR_ACF20' and actual == expected
    return {'status': 'PURE_PASS', 'runtime_and_independent_oracle': proofs,
        'original_numeric_center_exact': True, 'original_full13_domains_32_coordinates': True,
        'new_account_evaluations': 0, 'adaptation': 'Independent oracle SOURCE_CALLS bound to EX051 forbidden-provider context; formulas/functions unchanged'}
