"""Minimal EX051 runner/source lock review, no actual data/account execution."""
import ast
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path.cwd()
BASE = Path('research/S014/materials/20261020_followthrough_exit_diagnosis')
EX = Path('research/S014/experiments/EX051_20261020')

def digest(path):
    return sha256((ROOT / path).read_bytes()).hexdigest()

expected = {
    (EX / 'protocols/design.json').as_posix(): 'e61c74fe0993df89885b8af29f2072a0ad6b1d1701a0c9e0365a710c35fb7b59',
    (EX / 'src/run_accounts.py').as_posix(): '83090d4c8055a4b0b8a29408e007e9e6573665cf9fa67100b56ba3043a5288ba',
    (EX / 'src/audit_accounts.py').as_posix(): 'd97af4461b24ab3171c8e067abb9db9b848265f00f754f8e6334df2eeb8bc271',
    (EX / 'src/offline_inputs.py').as_posix(): '731e8fd0cb14859789f54083298b9140e12d1e50be5d71bb1093ab7f5313b380',
    (EX / 'src/strategy_runtime/strategies/followthrough_anchor.py').as_posix(): 'a97a53b0d277ef4ee5702cc3b846ce8831fd8b182c2afca83159f31f0458f670',
}
design = json.loads((ROOT / EX / 'protocols/design.json').read_bytes())
upstream = {value['path']: value['sha256'] for value in design.values()
            if isinstance(value, dict) and set(value) == {'path', 'sha256'}}
assert len(upstream) == 19
expected.update(upstream)
for path, sha in expected.items():
    assert digest(path) == sha, path
method = json.loads((ROOT / BASE / 'method_decision.json').read_bytes())
assert design['fixed_parameters'] == [{'anchor_profile': row['profile']} for row in method['runs']]
assert design['candidate_ids'] == [row['diagnostic_id'] for row in method['runs']]
assert design['planned_account_count'] == 3
assert design['baseline_account_ref']['sha256'] == '83327564961b13c1bc8e36cdf4e5c78ad35896a7e26f8595b6c3215889533ac9'
assert design['baseline_result_hash'] == '63b4ce767292ebdfaa71e23f56981eda61e08f5bbf2e6de6c8814bd6da5a2757'
for name, count in (('synthetic_precheck.json', 76), ('audit_prefix_precheck.json', 7)):
    path = EX / 'others' / name
    receipt = json.loads((ROOT / path).read_bytes())
    assert receipt['status'] == 'PASS_PURE_SYNTHETIC_ONLY' and receipt['checks_count'] == count
    expected[path.as_posix()] = digest(path)
    if count == 76:
        assert receipt['actual_SRT_observation_materializations'] == 666
        assert receipt['source_sha256'] == expected[(EX / 'src/strategy_runtime/strategies/followthrough_anchor.py').as_posix()]
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
    'for index in range(1, 3):',
):
    assert clause in text, clause
assert (ROOT / EX / 'src/offline_inputs.py').read_bytes() == (ROOT / 'research/S014/experiments/EX050_20261020/src/offline_inputs.py').read_bytes()
for path in (old_runner_path, EX / 'src/precheck.py', EX / 'src/prefix_precheck.py',
             BASE / 'review/source_focused_review.json'):
    expected[path.as_posix()] = digest(path)
expected[Path(__file__).resolve().relative_to(ROOT).as_posix()] = digest(Path(__file__).resolve().relative_to(ROOT))
value = {
    'status': 'PASS', 'reviewer': 'B', 'blocking_findings': [], 'reviewed_hashes': expected,
    'scope': 'Minimal final source/runner/design delta and focused synthetic receipts, no repeat of old full feature/contract oracle or actual accounts.',
    'source_review': '34 independent pure checks and seven inherited helper AST exact. ZERO strict< and1ATR original difference>= inclusive equality/adjacent floats, creation only first ownAGE continuation, persistent later clock, frozenATR, no currentP gate, protection overlaps/pending/expiry and realBUYSELL resets all verified.',
    'runner_delta': 'Only EX/source/class/parameter/ID/upstream identities adapt from reviewedEX050. Entire EvaluationRequest AST remains exact, explicit offline helper byteexact, original prepare content/fingerprint/clock assertions and no-network local publication retained.',
    'actual_control_gate': 'Fresh baseline now explicitly original EX050002 C9502 account833275... with result63b4ce.... Complete old observations and funded ledgers must match before either treatment. Independent current-lock/control-ref PASS and original no-blind-retry receipts remain.',
    'internal_audit_boundary': 'Internal audit independently tracks own actual entry/completion/loss pause and frozen lifecycle/targets/old protective overlap. Its raw anchor price creation/condition is still independently recomputed by A in original sourceHFQ, not accepted merely from its own observed raw fields.',
    'release_scope': 'With A current-source/runner PASS, allow publicimmutable lock and fresh control. Two fixed treatments remain dependent on complete control exact and independent actual audit. This review executes none.',
    'new_funded_accounts': 0, 'new_market_calls': 0, 'new_prepared_fetches': 0, 'new_labels': 0,
}
out = ROOT / BASE / 'review/runner_review.json'
with out.open('x', encoding='utf-8', newline='\n') as handle:
    json.dump(value, handle, ensure_ascii=False, indent=2)
    handle.write('\n')
print(json.dumps({'path': out.relative_to(ROOT).as_posix(), 'sha256': digest(out.relative_to(ROOT)), 'status': 'PASS', 'bindings': len(expected)}))
