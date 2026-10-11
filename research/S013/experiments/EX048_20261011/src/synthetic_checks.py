"""Authenticate two independently completed pure prototypes before native evaluation."""
import ast
from common import ROOT, SRC, read, file_hash


def synthetic(plan, source):
    runtime = ROOT / '.tmp/ex048-bear-exit-prototype'
    oracle = ROOT / '.tmp/ex048-bear-exit-oracle'
    proofs = [read(runtime / 'focused.json'), read(oracle / 'focused.json')]
    assert all(item['status'] == 'PURE_PASS' for item in proofs)
    assert file_hash(runtime / 'focused.json') == '5005abd6ca1c5ed0fa7131cdd6529ca83ed9e1425e59821f16adacec7c6163f3'
    assert file_hash(oracle / 'focused.json') == 'e92d6d42d94c4621fe304733a9c263120a8202f84ed378abb37edb58c8d0351a'
    for path in (runtime / 'strategy_runtime').rglob('*.py'):
        assert path.read_bytes() == (source / path.relative_to(runtime / 'strategy_runtime')).read_bytes()
    assert file_hash(runtime / 'strategy_runtime/strategies/exit_confirmed_range.py') == 'f623e4fdff5b43dddf9c5aefb599f3eadaa56b91374740fc22f0a252ec7fd58d'
    original = ast.parse((oracle / 'exit_oracle.py').read_text(encoding='utf-8'))
    formal = ast.parse((SRC / 'exit_oracle.py').read_text(encoding='utf-8'))
    before = {node.name: ast.dump(node, include_attributes=False) for node in original.body if isinstance(node, ast.FunctionDef)}
    after = {node.name: ast.dump(node, include_attributes=False) for node in formal.body if isinstance(node, ast.FunctionDef)}
    assert before == after, 'Only provider-audit import binding adapted; all independent formulas exact'
    cfg = plan['configurations'][0]
    assert len(plan['configurations']) == 1 and cfg['mechanism'] == 'BEAR_EXIT_BULL2'
    assert cfg['parent_control'] == 'B0-TIME'
    expected = next(row for row in plan['controls'] if row['label'] == 'B0-TIME')['payload']['parameters']
    actual = dict(cfg['payload']['parameters'])
    assert actual.pop('mechanism') == 'BEAR_EXIT_BULL2' and actual == expected
    return {'status': 'PURE_PASS', 'runtime_and_independent_oracle': proofs,
        'original_numeric_center_exact': True, 'original_full13_domains_32_coordinates': True,
        'new_account_evaluations': 0, 'adaptation': 'Independent oracle SOURCE_CALLS bound to EX048 forbidden-provider context; formulas/functions unchanged'}
