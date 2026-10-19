"""EX050 minimal runner/offline-provider delta gate, no account computation."""
import ast
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path.cwd()
BASE = Path('research/S014/materials/20261020_shock_state_diagnosis')
EX = Path('research/S014/experiments/EX050_20261020')
def digest(path):
    return sha256((ROOT / path).read_bytes()).hexdigest()

expected = {
    (EX / 'protocols/design.json').as_posix(): '1845fea88102c01b84890b8571842731ad2b1722977e03bd7a2be113d76532b3',
    (EX / 'src/run_accounts.py').as_posix(): '3eea3fcd79b0bb80f4360de64b666b1745da52179a28a034d37d68e566180bcb',
    (EX / 'src/audit_accounts.py').as_posix(): '07a23131db5a81e726b3b53ac8e44bf4e9e6cfea190541a8e5534e84f72e4b78',
    (EX / 'src/offline_inputs.py').as_posix(): '731e8fd0cb14859789f54083298b9140e12d1e50be5d71bb1093ab7f5313b380',
    (EX / 'src/strategy_runtime/strategies/shock_state_policy.py').as_posix(): 'ac4fcdbdc5c46b1d43f31f53dda2de0635fea8f4f0cff8889a083a86f87e76f3',
}
design = json.loads((ROOT / EX / 'protocols/design.json').read_bytes())
upstream = {value['path']: value['sha256'] for value in design.values() if isinstance(value, dict) and set(value) == {'path', 'sha256'}}
assert len(upstream) == 19
expected.update(upstream)
for path, value in expected.items():
    assert digest(path) == value, path
root_design = json.loads((ROOT / BASE / 'policy_decision.json').read_bytes())
assert design['fixed_parameters'] == [{'policy_profile': row['policy']} for row in root_design['runs']]
assert design['planned_account_count'] == len(design['fixed_parameters']) == 3
assert design['baseline_account_ref']['sha256'] == '935b74f311a04b11e494d7adea80c7c9d1badb7776706e0761a77679dc8751e0'
for name in ('synthetic_precheck.json', 'audit_prefix_precheck.json'):
    rel = EX / 'others' / name
    value = json.loads((ROOT / rel).read_bytes())
    assert value['status'] == 'PASS_PURE_SYNTHETIC_ONLY'
    assert value['checks_count'] == (62 if name == 'synthetic_precheck.json' else 7)
    expected[rel.as_posix()] = digest(rel)
    if name == 'synthetic_precheck.json':
        assert value['actual_SRT_observation_materializations'] == 666
        assert value['source_sha256'] == expected[(EX / 'src/strategy_runtime/strategies/shock_state_policy.py').as_posix()]
        assert digest(EX / 'src/precheck.py') == value['precheck_source_sha256']

old_helper = ast.parse((ROOT / 'research/S014/experiments/EX017_20261017/src/pinned_inputs.py').read_text(encoding='utf-8'))
new_helper = ast.parse((ROOT / EX / 'src/offline_inputs.py').read_text(encoding='utf-8'))
def find(tree, name):
    return next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name)
for name in ('_json', '_original_receipt', '_request', '_cut', '_coverage', 'PinnedProvider', 'get_context'):
    assert ast.dump(find(old_helper, name)) == ast.dump(find(new_helper, name)), name
old_catalog, new_catalog = find(old_helper, '_catalog'), find(new_helper, '_catalog')
assert len(old_catalog.body) == len(new_catalog.body)
for old, new in zip(old_catalog.body, new_catalog.body, strict=True):
    if isinstance(old, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'ctx' for t in old.targets):
        assert 'providers=ProviderConfig(bindings={})' in ast.unparse(new)
    else:
        assert ast.dump(old) == ast.dump(new)
old_runner = ast.parse((ROOT / 'research/S014/experiments/EX048_20261020/src/run_accounts.py').read_text(encoding='utf-8'))
new_runner = ast.parse((ROOT / EX / 'src/run_accounts.py').read_text(encoding='utf-8'))
def request_node(tree):
    return next(node for node in ast.walk(find(tree, 'execute')) if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'request' for t in node.targets))
assert ast.dump(request_node(old_runner)) == ast.dump(request_node(new_runner))
text = ast.unparse(new_runner)
assert "independent['account_ref'] == read(EX / 'others/accounts/run-000.json')['evidence']" in text
assert "independent['source_lock_sha256'] == digest(EX / 'protocols/execution_lock.json')" in text
assert "binding['execution_identities'] == old['original_execution_identities']" in text
assert "binding['execution_fingerprint'] == old['original_execution_fingerprint']" in text
assert "providers=ProviderConfig(bindings={})" in text
assert 'socket.socket.connect = no_network' in text
assert 'for index in range(1, 3):' in text
assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {'register_candidate', 'freeze', 'push'} for node in ast.walk(new_runner))
for rel in (EX / 'src/precheck.py', EX / 'src/prefix_precheck.py', BASE / 'review/policy_source_focused_review.json'):
    expected[rel.as_posix()] = digest(rel)
expected[Path(__file__).resolve().relative_to(ROOT).as_posix()] = digest(Path(__file__).resolve().relative_to(ROOT))
result = {
    'status': 'PASS', 'reviewer': 'B', 'blocking_findings': [], 'reviewed_hashes': expected,
    'review_scope': 'Minimal source/runner/provider and focused pure checks only; no repeated old full-contract feature oracle or funded account replay.',
    'findings': [
        'Three canonical root-locked profiles and diagnostic IDs match. No dates/year/threshold parameters, S1 reversal or age-by-S2 combination.',
        'New first-own-SHOCK assessed/latch passes31 independent focused tests; old six helpers AST exact. C62 pure/666SRT and7prefix receipts bind current bytes.',
        'EvaluationRequest AST exactly matches prior EX048 request: original fullwindow100000, pinned1%LimitBuyHold/.001eachside and original date/cutoff. Fresh C9461 exact old-ledger and independent-currentcontrol gate precedes treatment dispatch.',
        'Runner delta changes source identities, explicit3 profiles and loops/upstreams only; original public prepare/execution content/fingerprint/clock assertions, immutable dispatch receipts and failure retention remain.',
        'Offline helper differs from original only fixed oldEX017 source/prewindow, revision hash anchored to old pinned source, and explicit emptyProviderConfig in prepared-only catalog fetch. Composition/quality/scope and original-period equality logic AST unchanged. New wrapper and old revision source are both explicitly locked.',
        'Internal new lifecycle audit uses actual own fills and corrected D->E mapping/initial100000 state, separately records firstassessment/oldstate/target/funded differences. S2 actual source-formula verification remains independent A audit responsibility rather than trusting its observed hold flag.',
    ],
    'release_scope': 'Immutable public source lock and fresh original control, after independent A source/runner review also PASS. Both treatments remain dependent on exact complete control and independent actual-account PASS. No execution performed by reviewer.',
    'new_funded_accounts': 0, 'new_market_calls': 0, 'new_fits': 0, 'real_prepared_fetches': 0,
}
out = ROOT / BASE / 'review/policy_runner_review.json'
with out.open('x', encoding='utf-8', newline='\n') as handle:
    json.dump(result, handle, ensure_ascii=False, indent=2)
    handle.write('\n')
print(json.dumps({'path': out.relative_to(ROOT).as_posix(), 'sha256': digest(out.relative_to(ROOT)), 'status': 'PASS', 'bindings': len(expected)}))
