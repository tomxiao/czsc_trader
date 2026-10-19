"""Final fixed EX047 runner/internal/design byte and control-boundary review."""
import ast
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
EX = ROOT / 'research/S014/experiments/EX047_20261020'
CHECKS = []


def check(name, value):
    assert value, name
    CHECKS.append(name)


def ref(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest()}


def main():
    expected = {'src/run_accounts.py': '5a683c4579cc1c280535a6f9099023926d4c4fab1451981f37ec5f960850db3d',
                'src/audit_accounts.py': '2cdc8704da12ebbed757cc2d82d92f2284b48e9196fc9234f1c6490ae657e471',
                'protocols/design.json': 'e62e08a4555d1957b869aee867fb7a0bb4d01fb803e9ee3e24486ee1666783aa'}
    for path, digest in expected.items():
        check('final exact source bytes ' + path, ref(EX / path)['sha256'] == digest)
        if path.endswith('.py'):
            ast.parse((EX / path).read_text(encoding='utf-8'))
    design = json.loads((EX / 'protocols/design.json').read_bytes())
    for value in design.values():
        if isinstance(value, dict) and {'path', 'sha256'} <= value.keys():
            check('upstream exact byte ' + value['path'], ref(ROOT / value['path'])['sha256'] == value['sha256'])
    check('fixed pair and identities', design['fixed_parameters'] == [{'shock_profile': p} for p in ('SHOCK_ON', 'SHOCK_OFF')] and design['candidate_ids'] == ['S014-C9470', 'S014-C9471'])
    check('correct C9461 formal control', design['baseline_account_ref']['sha256'] == '935b74f311a04b11e494d7adea80c7c9d1badb7776706e0761a77679dc8751e0' and design['baseline_result_hash'] == 'a3c398bd3f3259bbf8e46a6339a36a8bd83b2ccd924526240b0ca604b0f21bcb')
    check('all seven original gates retained', design['original_annual_acceptance_years'] == list(range(2020, 2027)))
    toy = json.loads((EX / 'others/synthetic_precheck.json').read_bytes())
    prefix = json.loads((EX / 'others/audit_prefix_precheck.json').read_bytes())
    check('80toy666actual observation source proof', toy['checks_count'] == 80 and toy['actual_SRT_observation_materializations'] == 666 and toy['source_sha256'] == 'ea8f6c82dc7901b12edd00fe13cf1db6ed6d274563ac65479bf06058ed11bf4b')
    check('current toy implementation receipt', toy['precheck_source_sha256'] == ref(EX / 'src/precheck.py')['sha256'])
    check('7prefix bound exact final internal', prefix['checks_count'] == 7 and prefix['audit_source_sha256'] == expected['src/audit_accounts.py'] and prefix['precheck_source_sha256'] == ref(EX / 'src/prefix_precheck.py')['sha256'])
    spec = importlib.util.spec_from_file_location('a_shock_internal', EX / 'src/audit_accounts.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old = [{'signal_date': f'2020-01-0{i}', 'target_position': 0., 'reservation_index': -1.} for i in range(1, 5)]
    daily = [{'date': f'2020-01-0{i}', 'cash': 100., 'cash_before': 100., 'quantity': 0, 'quantity_before': 0, 'equity': 100.} for i in range(1, 5)]
    rows = [{**r, 'completed_net_known': False, 'pause_armed_before_candidate': False, 'shock_action_enabled': 0.} for r in old]
    check('new OFF constant is not old-state or wealth difference', module.divergence_dates(rows, old, daily, daily) == (None, None, None, None))
    rows[1]['completed_net_known'] = True
    rows[2]['reservation_index'] = 14.
    check('memory and old reservation separated', module.divergence_dates(rows, old, daily, daily) == ('2020-01-02', '2020-01-03', None, None))
    rows[3]['target_position'] = 1.
    wealth = deepcopy(daily)
    wealth[3].update(cash=90., quantity=1)
    check('four source/funded boundary dates explicit', module.divergence_dates(rows, old, wealth, daily) == ('2020-01-02', '2020-01-03', '2020-01-04', '2020-01-04'))
    review = {'status': 'PASS', 'source_sha256': toy['source_sha256'], 'implementation': ref(Path(__file__).resolve()),
              'reviewed_files': [ref(EX / p) for p in expected], 'check_count': len(CHECKS), 'checks': CHECKS,
              'manual_review': ['Independent control gate and exact public source/currentlock bound before any OFF; refuse dispatched index retries.',
                                'Original offline prepared identities/causal clock/fingerprint verified before evaluation, UNKNOWN/FAILED preserved and dependent arm stops.',
                                'Original EX046 corrected D/E state mapping and explicit prewindow100000/0 are retained.',
                                'Each profile own actual cycle net signs/armed/pause/actual orders; OFF only gates actual selectedSHOCK, not raw legacy condition.',
                                'All2020-2026 original goals, own year opening, fullfrequency and partial2026 nonannualized preserved.',
                                'Publication is repository-local evidence API with empty-provider publication context and networking disabled; no registration or remote action.'],
              'new_actual_accounts': 0, 'fits': 0, 'real_ON_control': 'NOT_EXECUTED'}
    destination = OUT / 'shock_runner_pre_review.json'
    with destination.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(review, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'review': ref(destination), 'checks': len(CHECKS)}))


if __name__ == '__main__':
    main()
