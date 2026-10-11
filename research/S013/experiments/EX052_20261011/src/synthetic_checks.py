"""Authenticate two independently completed pure prototypes before native evaluation."""
import ast
from common import ROOT, SRC, read, file_hash


def synthetic(plan, source):
    runtime = ROOT / '.tmp/ex052-consensus-acf-prototype'
    oracle = ROOT / '.tmp/ex052-consensus-acf-oracle'
    proofs = [read(runtime / 'focused.json'), read(oracle / 'focused.json')]
    assert all(item['status'] == 'PURE_PASS' for item in proofs)
    assert file_hash(runtime / 'focused.json') == '1010dd6eedc3c705a32ce432f1a1b01e9bbbee3246278481c097c86d338c3324'
    assert file_hash(oracle / 'focused.json') == '0bbbfa60299bfd9548dafe47c28c14f5bb52a039743b89256f0e18eae274e44a'
    for path in (runtime / 'strategy_runtime').rglob('*.py'):
        assert path.read_bytes() == (source / path.relative_to(runtime / 'strategy_runtime')).read_bytes()
    assert file_hash(runtime / 'strategy_runtime/strategies/bear_consensus_range.py') == 'adace832ee744b6a08bc2c31ac52bce6269f19b9179386d35152efb1e026485c'
    original = ast.parse((oracle / 'consensus_oracle.py').read_text(encoding='utf-8'))
    formal = ast.parse((SRC / 'consensus_oracle.py').read_text(encoding='utf-8'))
    before = {node.name: ast.dump(node, include_attributes=False) for node in original.body if isinstance(node, ast.FunctionDef)}
    after = {node.name: ast.dump(node, include_attributes=False) for node in formal.body if isinstance(node, ast.FunctionDef)}
    assert before == after, 'Only provider-audit import binding adapted; all independent formulas exact'
    parameter = ROOT / '.tmp/ex052-param-checks/focused.json'
    assert file_hash(parameter) == '1c0600b75c4735a9e6d1abd8b1bc3c827a7d2175849b24a210fa9ca73f108449'
    proof = read(parameter)
    assert proof['status'] == 'PURE_PASS' and proof['financial_calls'] == []
    assert proof['new_account_preparations'] == proof['new_account_evaluations'] == proof['native_account_reads'] == 0
    proofs.append(proof)
    for path in (ROOT / '.tmp/ex052-param-prototype').glob('*.py'):
        assert path.read_bytes() == (SRC / path.name).read_bytes()
    cfg = plan['configurations'][0]
    assert len(plan['configurations']) == 1 and cfg['mechanism'] == 'BEAR_CONSENSUS_ACF20'
    assert cfg['parent_control'] == 'B0-TIME'
    expected = next(row for row in plan['controls'] if row['label'] == 'B0-TIME')['payload']['parameters']
    actual = dict(cfg['payload']['parameters'])
    assert actual.pop('mechanism') == 'BEAR_CONSENSUS_ACF20' and actual == expected
    return {'status': 'PURE_PASS', 'runtime_and_independent_oracle': proofs,
        'original_numeric_center_exact': True, 'original_full13_domains_32_coordinates': True,
        'new_account_evaluations': 0, 'adaptation': 'Independent oracle SOURCE_CALLS bound to EX052 forbidden-provider context; formulas/functions unchanged'}
