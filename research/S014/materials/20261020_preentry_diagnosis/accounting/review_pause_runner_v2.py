"""Additive audit/runner correction review on the SAME successful BASE."""
import ast
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
EX = ROOT / 'research/S014/experiments/EX046_20261020'
CHECKS = []


def check(name, value):
    assert value, name
    CHECKS.append(name)


def ref(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest()}


def main():
    expected = {'src/audit_accounts_v2.py': 'b9f80bfc4f5757e00d4984a2bd7481f6835c4d4654b1b7121341851d26d47324',
                'src/run_accounts_v2.py': '64994e8c8a7dccf4192e820969acf68f0b10d472ca2c8d2f8ebf005f66efb0ab',
                'protocols/technical_revision.json': '56ebd15c618f786f91e2c81e8537cad31a78eaeaa655b1b790751dd9806cc7a9'}
    for path, digest in expected.items():
        check('exact final successor bytes ' + path, ref(EX / path)['sha256'] == digest)
    revision = json.loads((EX / 'protocols/technical_revision.json').read_bytes())
    for value in revision.values():
        if isinstance(value, dict) and {'path', 'sha256'} <= value.keys():
            check('revision exact linked bytes ' + value['path'], ref(ROOT / value['path'])['sha256'] == value['sha256'])
    parent = EvidenceRef.from_dict(revision['parent_lock_ref'])
    check('formal parent lock SHA and local preserved', sha256(parent.resolve(ROOT).read_bytes()).hexdigest() == parent.sha256 == ref(EX / 'protocols/execution_lock.json')['sha256'])
    lock = json.loads(parent.resolve(ROOT).read_bytes())
    for path, digest in lock['source_hashes'].items():
        check('all original locked bytes preserved ' + path, ref(EX / path)['sha256'] == digest)
    account_ref = EvidenceRef.from_dict(revision['same_successful_control_account_ref'])
    account_bytes = account_ref.resolve(ROOT).read_bytes()
    check('same actual successful BASE identity', sha256(account_bytes).hexdigest() == account_ref.sha256 == '174a4f8d4ca11ccd14a44f8cfb439e046123de4e3df67da065846e323ea36ab4')
    account = json.loads(account_bytes)
    spec = importlib.util.spec_from_file_location('a_internal_pause_corrected', EX / 'src/audit_accounts_v2.py')
    corrected = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(corrected)
    result = corrected.audit(account, {'pause_profile': 'BASE'})
    supplement = json.loads((EX / 'others/control_audit_correction_v2.json').read_bytes())
    check('independently rechecked same account internal successor425923 exact', result == supplement['audit'] and result['status'] == 'PASS' and result['checks'] == 425923)
    check('old receipt failure unchanged', json.loads((EX / 'others/accounts/run-000.json').read_bytes())['audit']['status'] == 'FAIL')
    previous = ast.parse((EX / 'src/audit_accounts.py').read_text(encoding='utf-8'))
    current = ast.parse((EX / 'src/audit_accounts_v2.py').read_text(encoding='utf-8'))
    for name in ['sign', 'frozen_baseline', 'divergence_dates']:
        functions = [next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name) for tree in [previous, current]]
        check('unchanged non-clock helper AST ' + name, ast.dump(functions[0], include_attributes=False) == ast.dump(functions[1], include_attributes=False))
    old_runner = ast.parse((EX / 'src/run_accounts.py').read_text(encoding='utf-8'))
    new_runner = ast.parse((EX / 'src/run_accounts_v2.py').read_text(encoding='utf-8'))
    for name in ['EvaluationRequest', 'StrategyCandidate']:
        calls = [[n for n in ast.walk(t) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name] for t in [old_runner, new_runner]]
        check('same exact actual request/candidate constructor ' + name, [ast.dump(n, include_attributes=False) for n in calls[0]] == [ast.dump(n, include_attributes=False) for n in calls[1]])
    independent = json.loads((OUT / 'pause_account_000_independent_review.json').read_bytes())
    check('A actual BASE already independently PASS on original v1', independent['status'] == 'PASS' and independent['account_ref'] == revision['same_successful_control_account_ref'] and independent['source_lock_sha256'] == parent.sha256)
    review = {'status': 'PASS', 'source_sha256': revision['strategy_source_unchanged']['sha256'],
              'implementation': ref(Path(__file__).resolve()), 'reviewed_files': [ref(EX / p) for p in expected],
              'same_account_supplement': ref(EX / 'others/control_audit_correction_v2.json'),
              'original_independent_BASE_review': ref(OUT / 'pause_account_000_independent_review.json'),
              'checks': CHECKS, 'check_count': len(CHECKS), 'same_account_internal_checks_reapplied': result['checks'],
              'manual_diff': ['Only internal clock comparison and D actual inventory selection corrected, explicit initial100000/zero state.',
                              'Source5e77, parameter payloads and execution/fee/price/lot/market/cutoff requests unchanged.',
                              'Original run000/auditFAIL and v1 immutable lock retain original bytes; supplemental PASS is same account, no new execution.',
                              'Runner uses successor audit and source/control gates, records active per-dispatch lockv2, only allows active indices1/2, no blind retry.',
                              'New locks and exact public corrected/independent gates still must be verified before active execution.'],
              'account_engine_failures': 0, 'retained_internal_audit_expression_incidents': 1,
              'new_accounts': 0, 'fits': 0, 'price_epsilon_changed': False}
    destination = OUT / 'pause_runner_v2_review.json'
    with destination.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(review, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'review': ref(destination), 'checks': len(CHECKS)}))


if __name__ == '__main__':
    main()
