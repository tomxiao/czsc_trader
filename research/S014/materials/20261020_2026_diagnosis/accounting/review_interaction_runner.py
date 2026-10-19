"""Final fixed EX048 runner/internal/design byte and control-boundary review."""
import ast
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
EX = ROOT / 'research/S014/experiments/EX048_20261020'
CHECKS = []


def check(name, value):
    assert value, name
    CHECKS.append(name)


def ref(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest()}


def main():
    expected = {'src/run_accounts.py': 'cfb87b8043882a108161a8ad4006fe9ff9e64038dccaa176a75a76a1482c97d6',
                'src/audit_accounts.py': 'ef00279cf757e3d5da32ea12a15bd7d0f09d8df3121c2b6e0b01c303c4c3ce91',
                'protocols/design.json': 'c1dab953e4fcd09f4d37aa18c370093c2e8868b0d6f134c3346091fd169c5b41'}
    for path, digest in expected.items():
        check('final exact source bytes ' + path, ref(EX / path)['sha256'] == digest)
        if path.endswith('.py'):
            ast.parse((EX / path).read_text(encoding='utf-8'))
    design = json.loads((EX / 'protocols/design.json').read_bytes())
    for value in design.values():
        if isinstance(value, dict) and {'path', 'sha256'} <= value.keys():
            check('upstream exact byte ' + value['path'], ref(ROOT / value['path'])['sha256'] == value['sha256'])
    check('fixed pair and identities', design['fixed_parameters'] == [{'pause_profile': p} for p in ('AFTER_NET_LOSS_SKIP1', 'BASE')] and design['candidate_ids'] == ['S014-C9480', 'S014-C9481'])
    check('correct C9471 formal control', design['baseline_account_ref']['sha256'] == '3c9ca87b2cec20e4bfb793c68df7d438862da67b8f6533348ac2f7f39df62bf9' and design['baseline_result_hash'] == '030016c1a2438d26c3aa94a9dfbb455697b8b739d6240548430d7186295f61d8')
    check('all seven original gates retained', design['original_annual_acceptance_years'] == list(range(2020, 2027)))
    toy = json.loads((EX / 'others/synthetic_precheck.json').read_bytes())
    prefix = json.loads((EX / 'others/audit_prefix_precheck.json').read_bytes())
    check('87toy666actual observation source proof', toy['checks_count'] == 87 and toy['actual_SRT_observation_materializations'] == 666 and toy['source_sha256'] == '5a4347527aad29cb647d9c44a26cf1b970dda471af9d1419f817b39e4476a66b')
    check('current toy implementation receipt', toy['precheck_source_sha256'] == ref(EX / 'src/precheck.py')['sha256'])
    check('7prefix bound exact final internal', prefix['checks_count'] == 7 and prefix['audit_source_sha256'] == expected['src/audit_accounts.py'] and prefix['precheck_source_sha256'] == ref(EX / 'src/prefix_precheck.py')['sha256'])
    spec = importlib.util.spec_from_file_location('a_shock_internal', EX / 'src/audit_accounts.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old = [{'signal_date': f'2020-01-0{i}', 'target_position': 0., 'reservation_index': -1.} for i in range(1, 5)]
    daily = [{'date': f'2020-01-0{i}', 'cash': 100., 'cash_before': 100., 'quantity': 0, 'quantity_before': 0, 'equity': 100.} for i in range(1, 5)]
    rows = [{**r, 'completed_net_known': False, 'pause_armed_before_candidate': False, 'shock_action_enabled': 0.} for r in old]
    check('new OFF constant is not old-state or wealth difference', module.divergence_dates(rows, old, daily, daily) == (None, None, None, None))
    rows[0]['pause_loss_profile'] = 0.
    old[0]['pause_loss_profile'] = 1.
    check('changed constant pause profile not mutable original state', module.divergence_dates(rows, old, daily, daily) == (None, None, None, None))
    rows[1]['completed_net_known'] = True
    rows[2]['reservation_index'] = 14.
    check('memory and old reservation separated', module.divergence_dates(rows, old, daily, daily) == ('2020-01-02', '2020-01-03', None, None))
    rows[3]['target_position'] = 1.
    wealth = deepcopy(daily)
    wealth[3].update(cash=90., quantity=1)
    check('four source/funded boundary dates explicit', module.divergence_dates(rows, old, wealth, daily) == ('2020-01-02', '2020-01-03', '2020-01-04', '2020-01-04'))
    review = {'status': 'PASS', 'source_sha256': toy['source_sha256'], 'implementation': ref(Path(__file__).resolve()),
              'reviewed_files': [ref(EX / p) for p in expected], 'check_count': len(CHECKS), 'checks': CHECKS,
              'manual_review': ['Independent control gate and exact public source/currentlock bound before active BASE; refuse dispatched index retries.',
                                'Original offline prepared identities/causal clock/fingerprint verified before evaluation, UNKNOWN/FAILED preserved and dependent arm stops.',
                                'Original EX046 corrected D/E state mapping and explicit prewindow100000/0 are retained.',
                                'Each profile own actual cycle net signs/armed/pause/actual orders; fixedOFF and onlyBASE disables arming. Profile constants not mutable-state divergence.',
                                'All2020-2026 original goals, own year opening, fullfrequency and partial2026 nonannualized preserved.',
                                'Publication is repository-local evidence API with empty-provider publication context and networking disabled; no registration or remote action.'],
              'new_actual_accounts': 0, 'fits': 0, 'real_LOSS_control': 'NOT_EXECUTED'}
    destination = OUT / 'interaction_runner_pre_review.json'
    with destination.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(review, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'review': ref(destination), 'checks': len(CHECKS)}))


if __name__ == '__main__':
    main()
