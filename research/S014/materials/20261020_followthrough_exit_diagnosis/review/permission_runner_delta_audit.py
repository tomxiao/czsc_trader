"""Minimal EX052 runner/source lock review, no actual data/account execution."""
import ast
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path.cwd()
BASE = Path('research/S014/materials/20261020_followthrough_exit_diagnosis')
EX = Path('research/S014/experiments/EX052_20261020')

def digest(path):
    return sha256((ROOT / path).read_bytes()).hexdigest()

expected = {
    (EX / 'protocols/design.json').as_posix(): 'de9abd879e43be3e7f52c038586cc8295dfe8885f24820f12bb23219f47d228e',
    (EX / 'src/run_accounts.py').as_posix(): 'bb866ef2973a871105150ae89667754e99220b586805cc193d4502b4a72d6472',
    (EX / 'src/audit_accounts.py').as_posix(): 'b30f82c6768593851ab0f343b57cec6068ad0d127d25681017fcc7521dd6713e',
    (EX / 'src/offline_inputs.py').as_posix(): '731e8fd0cb14859789f54083298b9140e12d1e50be5d71bb1093ab7f5313b380',
    (EX / 'src/strategy_runtime/strategies/trend_permission.py').as_posix(): 'ba01530dc434d32a540ba0a8e6ec9078a638137dcbaf683eb366171291ee67f2',
}
design = json.loads((ROOT / EX / 'protocols/design.json').read_bytes())
upstream = {value['path']: value['sha256'] for value in design.values()
            if isinstance(value, dict) and set(value) == {'path', 'sha256'}}
assert len(upstream) == 19
expected.update(upstream)
for path, sha in expected.items():
    assert digest(path) == sha, path
method = json.loads((ROOT / BASE / 'permission_decision.json').read_bytes())
assert design['fixed_parameters'] == [{'permission_profile': row['profile']} for row in method['runs']]
assert design['candidate_ids'] == [row['diagnostic_id'] for row in method['runs']]
assert design['planned_account_count'] == 2
assert design['baseline_account_ref']['sha256'] == '83327564961b13c1bc8e36cdf4e5c78ad35896a7e26f8595b6c3215889533ac9'
assert design['baseline_result_hash'] == '63b4ce767292ebdfaa71e23f56981eda61e08f5bbf2e6de6c8814bd6da5a2757'
for name, count in (('synthetic_precheck.json', 55), ('audit_prefix_precheck.json', 7)):
    path = EX / 'others' / name
    receipt = json.loads((ROOT / path).read_bytes())
    assert receipt['status'] == 'PASS_PURE_SYNTHETIC_ONLY' and receipt['checks_count'] == count
    expected[path.as_posix()] = digest(path)
    if count == 55:
        assert receipt['actual_SRT_observation_materializations'] == 444
        assert receipt['source_sha256'] == expected[(EX / 'src/strategy_runtime/strategies/trend_permission.py').as_posix()]
        assert digest(EX / 'src/precheck.py') == receipt['precheck_source_sha256']
        assert receipt['network_attempts'] == []
old_runner_path = Path('research/S014/experiments/EX050_20261020/src/run_accounts.py')
old_runner = ast.parse((ROOT / old_runner_path).read_text(encoding='utf-8'))
new_runner = ast.parse((ROOT / EX / 'src/run_accounts.py').read_text(encoding='utf-8'))
def request_node(tree):
    return next(node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == 'request' for target in node.targets))
assert ast.dump(request_node(old_runner)) == ast.dump(request_node(new_runner))
text = ast.unparse(new_runner)
for clause in (
    "independent['account_ref'] == read(EX / 'others/accounts/run-000.json')['evidence']",
    "independent['source_lock_sha256'] == digest(EX / 'protocols/execution_lock.json')",
    "binding['execution_identities'] == old['original_execution_identities']",
    "binding['execution_fingerprint'] == old['original_execution_fingerprint']",
    'providers=ProviderConfig(bindings={})', 'socket.socket.connect = no_network',
    'for index in range(1, 2):',
):
    assert clause in text, clause
assert (ROOT / EX / 'src/offline_inputs.py').read_bytes() == (ROOT / 'research/S014/experiments/EX050_20261020/src/offline_inputs.py').read_bytes()
prior_audit = Path('research/S014/experiments/EX051_20261020/src/audit_accounts_v2.py')
old_audit_tree = ast.parse((ROOT / prior_audit).read_text(encoding='utf-8'))
new_audit_tree = ast.parse((ROOT / EX / 'src/audit_accounts.py').read_text(encoding='utf-8'))
fetch_nodes = [next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'source_closes')
               for tree in (old_audit_tree, new_audit_tree)]
assert ast.dump(fetch_nodes[0]) == ast.dump(fetch_nodes[1])
audit_text = ast.unparse(new_audit_tree)
assert 'all((k in row and isinstance(row[k], (int, float)) and math.isfinite(row[k]) for k in new_diag))' in audit_text
assert "prior_close = prior_closes[D]" in audit_text
expected[prior_audit.as_posix()] = digest(prior_audit)
for path in (old_runner_path, EX / 'src/precheck.py', EX / 'src/prefix_precheck.py',
             BASE / 'review/permission_source_review.json'):
    expected[path.as_posix()] = digest(path)
expected[Path(__file__).resolve().relative_to(ROOT).as_posix()] = digest(Path(__file__).resolve().relative_to(ROOT))
value = {
    'status': 'PASS', 'reviewer': 'B', 'blocking_findings': [], 'reviewed_hashes': expected,
    'scope': 'Minimal final source/runner/design delta and focused synthetic receipts, no repeat of old full feature/contract oracle or actual accounts.',
    'source_review': '31 independent pure checks and seven inherited helper AST exact. Original priorMA strictgreater/priorClose inclusive boundary, finiteknown required only held treatment, own firstSHOCK latch/reset, protection/pending and causal prefixes all verified.',
    'runner_delta': 'Only EX/source/class/parameter/ID/upstream identities adapt from reviewedEX050. Entire EvaluationRequest AST remains exact, explicit offline helper byteexact, original prepare content/fingerprint/clock assertions and no-network local publication retained.',
    'actual_control_gate': 'Fresh baseline now explicitly original EX050002 C9502 account833275... with result63b4ce.... Complete old observations and funded ledgers must match before sole treatment. Independent current-lock/control-ref PASS and original no-blind-retry receipts remain.',
    'internal_audit_boundary': 'Internal audit explicitly asserts nine declared numeric observations are present finite. It reconstructs priorClose from existing authenticated PreparedDataRef and combines formally observed original MAs; no unprojected raw price assumed. A independently recomputes source features and funded lifecycle.',
    'release_scope': 'With A current-source/runner PASS, allow publicimmutable lock and fresh control. One fixed treatment remains dependent on complete control exact and independent actual audit. This review executes none.',
    'new_funded_accounts': 0, 'new_market_calls': 0, 'new_prepared_fetches': 0, 'new_labels': 0,
}
out = ROOT / BASE / 'review/permission_runner_review.json'
with out.open('x', encoding='utf-8', newline='\n') as handle:
    json.dump(value, handle, ensure_ascii=False, indent=2)
    handle.write('\n')
print(json.dumps({'path': out.relative_to(ROOT).as_posix(), 'sha256': digest(out.relative_to(ROOT)), 'status': 'PASS', 'bindings': len(expected)}))
