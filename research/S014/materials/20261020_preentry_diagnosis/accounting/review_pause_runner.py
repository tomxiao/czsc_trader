"""Short immutable EX046 final runner/design/control audit before public lock."""
import ast
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

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
    expected = {'src/run_accounts.py': 'c4f90ffba71c9c16450b064bd2991cdcf0055b77f44704ee9574afb11f664f08',
                'src/audit_accounts.py': 'a4bc7f8be15c955ef02c452a86e07444b5d961a10d786bb9ec626c1d3b3ee601',
                'protocols/design.json': 'f447784ad9f6d431b45c478f2ffd0d088d1e43ab61ea1c9cf0f0c00df1ee57cc'}
    for path, digest in expected.items():
        check('exact reviewed final bytes ' + path, ref(EX / path)['sha256'] == digest)
        if path.endswith('.py'):
            ast.parse((EX / path).read_text(encoding='utf-8'))
    design = json.loads((EX / 'protocols/design.json').read_bytes())
    for value in design.values():
        if isinstance(value, dict) and {'path', 'sha256'} <= value.keys():
            check('upstream byte identity ' + value['path'], ref(ROOT / value['path'])['sha256'] == value['sha256'])
    check('fixed three profiles and IDs', design['fixed_parameters'] == [{'pause_profile': p} for p in ('BASE', 'AFTER_NET_LOSS_SKIP1', 'AFTER_NET_PROFIT_SKIP1')] and design['candidate_ids'] == ['S014-C9460', 'S014-C9461', 'S014-C9462'])
    check('correct frozen cost baseline', design['baseline_account_ref']['sha256'] == '29782a9c53c1d4624b39aab6ae31bf2069a79a5747bccb7af56139e0dcf81f9b' and design['baseline_result_hash'] == 'a784d786c0fae2f64651275a653f8cdfc28c28e53048431f4d9151d2ffe07f05')
    synthetic = json.loads((EX / 'others/synthetic_precheck.json').read_bytes())
    prefix = json.loads((EX / 'others/audit_prefix_precheck.json').read_bytes())
    check('source toy and actual SRT receipt bound', synthetic['source_sha256'] == '5e775c5b27bfd7b1ac5bec9c2839ce24ae62f32f1829c21a13091868a174b846' and synthetic['checks_count'] == 97 and synthetic['actual_SRT_observation_materializations'] == 666)
    check('source precheck exact receipt', ref(EX / 'src/precheck.py')['sha256'] == synthetic['precheck_source_sha256'])
    check('final six audit boundaries bind final internal', prefix['checks_count'] == 6 and prefix['audit_source_sha256'] == expected['src/audit_accounts.py'] and prefix['precheck_source_sha256'] == ref(EX / 'src/prefix_precheck.py')['sha256'])
    spec = importlib.util.spec_from_file_location('a_pause_prefix_internal', EX / 'src/audit_accounts.py')
    internal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(internal)
    old = [{'signal_date': f'2020-01-0{i}', 'target_position': 0., 'reservation_index': -1.} for i in range(1, 5)]
    daily = [{'date': f'2020-01-0{i}', 'cash': 100., 'cash_before': 100., 'quantity': 0, 'quantity_before': 0, 'equity': 100.} for i in range(1, 5)]
    new = [{**r, 'completed_net_known': False, 'pause_armed_before_candidate': False} for r in old]
    new[1]['completed_net_known'] = True
    check('new completion memory does not imply original or funded divergence', internal.divergence_dates(new, old, daily, daily) == ('2020-01-02', None, None, None))
    new[2]['reservation_index'] = 14.
    check('reservation changes before target or money', internal.divergence_dates(new, old, daily, daily) == ('2020-01-02', '2020-01-03', None, None))
    new[3]['target_position'] = 1.
    wealth = deepcopy(daily)
    wealth[3].update(cash=90., quantity=1)
    check('four independent dates retained', internal.divergence_dates(new, old, wealth, daily) == ('2020-01-02', '2020-01-03', '2020-01-04', '2020-01-04'))
    result = {'status': 'PASS', 'source_sha256': synthetic['source_sha256'], 'implementation': ref(Path(__file__).resolve()),
              'reviewed_files': [ref(EX / p) for p in expected], 'checks': CHECKS, 'check_count': len(CHECKS),
              'manual_boundary_review': ['All dispatches validate immutable source/parameter/upstream byte hashes and public source-review gate first.',
                                         'Active profiles require independently published current-lock fresh BASE and exact current account-ref gate before dispatch; no blind retry.',
                                         'Original prepared data fingerprint/strategy causal plan except new strategy identity checked before evaluation; network blocked.',
                                         'All UNKNOWN/FAILED/SUCCEEDED receipts retained, internal technical error blocks dependent evaluation, both fixed active profiles run irrespective economics.',
                                         'Original 1% LIMIT BUY/market SELL, initial100000, .001 one-way, limits/lot/H10/HFQ anchor and original2026 tail unchanged.',
                                         'First feedback enters new known memory even in BASE; first selected arm separate; original-prefix uses first original state not first target.',
                                         'Internal actual-funded net sign and one-shot state checks do not replace independent exact fresh BASE/full-account review.'],
              'new_accounts': 0, 'fits': 0, 'new_market_calls': 0, 'real_control_gate': 'NOT_YET_EXECUTED'}
    destination = OUT / 'pause_runner_pre_review.json'
    with destination.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'review': ref(destination), 'checks': len(CHECKS)}))


if __name__ == '__main__':
    main()
