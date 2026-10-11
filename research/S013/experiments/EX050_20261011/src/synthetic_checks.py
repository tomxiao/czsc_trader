"""Authenticate two independently completed pure prototypes before native evaluation."""
import ast
from common import ROOT, SRC, read, file_hash


def synthetic(plan, source):
    runtime = ROOT / '.tmp/ex050-rank-acf-prototype'
    oracle = ROOT / '.tmp/ex050-rank-acf-oracle'
    proofs = [read(runtime / 'focused.json'), read(oracle / 'focused.json')]
    assert all(item['status'] == 'PURE_PASS' for item in proofs)
    assert file_hash(runtime / 'focused.json') == 'ddb77cd469cee8d5a25632466b1275277420a90f7c676bf8dd3280be2e775ef5'
    assert file_hash(oracle / 'focused.json') == 'df0a7ef55f78c10124a32455d4f3b856ccd752fc86d3775f55e9e8355f5be8a9'
    for path in (runtime / 'strategy_runtime').rglob('*.py'):
        assert path.read_bytes() == (source / path.relative_to(runtime / 'strategy_runtime')).read_bytes()
    assert file_hash(runtime / 'strategy_runtime/strategies/bear_rank_range.py') == 'f5c2d6cf756b2b33332f0dc25a5b5e148fcc6ba3a1060fa45be40eb10f5147cc'
    original = ast.parse((oracle / 'rank_oracle.py').read_text(encoding='utf-8'))
    formal = ast.parse((SRC / 'rank_oracle.py').read_text(encoding='utf-8'))
    before = {node.name: ast.dump(node, include_attributes=False) for node in original.body if isinstance(node, ast.FunctionDef)}
    after = {node.name: ast.dump(node, include_attributes=False) for node in formal.body if isinstance(node, ast.FunctionDef)}
    assert before == after, 'Only provider-audit import binding adapted; all independent formulas exact'
    parameter = ROOT / '.tmp/ex050-param-checks/focused.json'
    assert file_hash(parameter) == '92ec554f322064fcdf4ff4e1b750ad0305e1721dae38393b85853c15309b5155'
    proof = read(parameter)
    assert proof['status'] == 'PURE_PASS' and proof['financial_calls'] == []
    assert proof['new_account_preparations'] == proof['new_account_evaluations'] == proof['native_account_reads'] == 0
    proofs.append(proof)
    for path in (ROOT / '.tmp/ex050-param-prototype').glob('*.py'):
        assert path.read_bytes() == (SRC / path.name).read_bytes()
    cfg = plan['configurations'][0]
    assert len(plan['configurations']) == 1 and cfg['mechanism'] == 'BEAR_RANK_ACF20'
    assert cfg['parent_control'] == 'B0-TIME'
    expected = next(row for row in plan['controls'] if row['label'] == 'B0-TIME')['payload']['parameters']
    actual = dict(cfg['payload']['parameters'])
    assert actual.pop('mechanism') == 'BEAR_RANK_ACF20' and actual == expected
    return {'status': 'PURE_PASS', 'runtime_and_independent_oracle': proofs,
        'original_numeric_center_exact': True, 'original_full13_domains_32_coordinates': True,
        'new_account_evaluations': 0, 'adaptation': 'Independent oracle SOURCE_CALLS bound to EX050 forbidden-provider context; formulas/functions unchanged'}
