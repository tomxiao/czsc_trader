"""Independent fixed-source static and small synthetic audit; zero accounts."""
import ast
from collections import Counter
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import socket
import sys

import numpy as np
import pandas as pd
import requests
from strategy_runtime import ParameterSet

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / 'research/S014/experiments/EX046_20261020/src/strategy_runtime/strategies/completed_pause_review.py'
OLD = ROOT / 'research/S014/experiments/EX044_20261019/src/strategy_runtime/strategies/action_role_review.py'
DESIGN = OUT.parent / 'design_decision.json'
CHECKS = Counter()


def blocked(*args, **kwargs):
    raise RuntimeError('Pure source review: network prohibited')


socket.socket.connect = blocked
socket.create_connection = blocked
requests.sessions.Session.request = blocked


def check(name, value):
    assert value, name
    CHECKS[name] += 1


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def ref(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest()}


def main():
    check('exact frozen source', ref(SOURCE)['sha256'] == '5e775c5b27bfd7b1ac5bec9c2839ce24ae62f32f1829c21a13091868a174b846')
    new, old = module('a_pause_source', SOURCE), module('a_pause_prior', OLD)
    fixture = module('a_pause_fixture', ROOT / 'research/S014/experiments/EX043_20261019/src/precheck.py')
    previous_config = old.ActionRoleConfig.parse({'entry_guard': 'BASE', 'exit_domain': 'POSITIVE_P', 'cost_stop': 'NET_LOSS_1ATR'})
    profiles = ('BASE', 'AFTER_NET_LOSS_SKIP1', 'AFTER_NET_PROFIT_SKIP1')
    design = json.loads(DESIGN.read_bytes())
    check('exact fixed profiles', design['fixed_parameters'] == [{'pause_profile': p} for p in profiles])
    trees = [ast.parse(path.read_text(encoding='utf-8')) for path in (OLD, SOURCE)]
    for name in ('causal_features', 'tick', 'buy_limit', 'calendar_request', 'derive_calculation_scope'):
        nodes = [next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name) for tree in trees]
        check('original helper AST exact ' + name, ast.dump(nodes[0], include_attributes=False) == ast.dump(nodes[1], include_attributes=False))
    for value, expected in ((-1e-300, -1), (-0.0, 0), (0.0, 0), (1e-300, 1)):
        check('strict finite sign', new.completed_sign(value) == expected)
    for value in (np.nan, np.inf, -np.inf):
        try:
            new.completed_sign(value)
        except ValueError:
            check('invalid completed value rejected', True)
        else:
            raise AssertionError('nonfinite completion accepted')
    for value in ({}, {'pause_profile': True}, {'pause_profile': 'base'}, {'pause_profile': 'BASE', 'cost_stop': 'BASE'}):
        try:
            new.PauseConfig.parse(value)
        except ValueError:
            check('strict canonical schema rejected', True)
        else:
            raise AssertionError('invalid configuration accepted')
    old_definition = old.ActionRoleStrategy(ParameterSet({'entry_guard': 'BASE', 'exit_domain': 'POSITIVE_P', 'cost_stop': 'NET_LOSS_1ATR'})).definition
    for p in profiles:
        definition = new.CompletedPauseStrategy(ParameterSet({'pause_profile': p})).definition
        for name in ('inputs', 'decision', 'execution', 'monitoring', 'capabilities'):
            check('original execution/clock contract ' + name, getattr(definition, name) == getattr(old_definition, name))
    rising = fixture.fixture()
    flat = fixture.fixture()
    for i in range(len(flat[0])):
        fixture.change(flat, i, close=10., open_=10.)
    for label, args in [('rising', rising), ('flat_afterfee_loss', flat)]:
        reference = old.history(*args, previous_config)
        for p in profiles:
            history = new.history(*args, new.PauseConfig.parse({'pause_profile': p}))
            if p == 'BASE':
                pd.testing.assert_frame_equal(history[list(reference)], reference, check_exact=True)
                check('BASE all prior columns exact ' + label, True)
            expected_armed = False
            last_sign = 0
            for i, row in enumerate(history.to_dict('records')):
                check('completed only actual matched SELL', bool(row['completed_cycle_today']) == bool(row['sell_filled_today']))
                if row['completed_cycle_today']:
                    net = row['completed_net_unit']
                    sign = -1 if net < 0 else 1 if net > 0 else 0
                    last_sign = sign
                    expected_armed = bool((p == profiles[1] and sign < 0) or (p == profiles[2] and sign > 0))
                    check('completion finite and selected strict sign', np.isfinite(net))
                else:
                    check('no synthetic completion value', pd.isna(row['completed_net_unit']))
                check('stored last sign', row['last_completed_sign'] == last_sign)
                check('armed before eligibility includes sameD completion', bool(row['pause_armed_before_candidate']) == expected_armed)
                consumed = bool(expected_armed and row['original_entry_candidate'])
                check('one shot consume first eligible', bool(row['pause_slot_consumed']) == consumed)
                if consumed:
                    expected_armed = False
                    check('virtual slot exact original planned H10', row['reservation_index'] == i + 11 and row['planned_slot_until'] == i + 11)
                    check('virtual slot no buy or fake state', row['target_position'] == 0 and not row['entry_signal'] and row['entry_index'] == row['deadline_index'] == -1 and not row['held_at_close'] and not row['failed_buy_reset'])
                check('armed cleared once, no stale sign rearm', bool(row['pause_armed']) == expected_armed)
            for stop in (62, 72, 85):
                prefix = new.history(*(x.iloc[:stop].copy(deep=True) for x in args), new.PauseConfig.parse({'pause_profile': p}))
                pd.testing.assert_frame_equal(prefix, history.iloc[:stop], check_exact=True)
                check('own-feedback history synthetic prefix exact', True)
    receipt = ROOT / 'research/S014/experiments/EX046_20261020/others/synthetic_precheck.json'
    precheck = json.loads(receipt.read_bytes())
    check('C synthetic bound exact source and test', precheck['source_sha256'] == ref(SOURCE)['sha256'] and precheck['checks_count'] == 97 and precheck['actual_SRT_observation_materializations'] == 666)
    result = {'status': 'PASS', 'source_sha256': ref(SOURCE)['sha256'], 'source': ref(SOURCE), 'design': ref(DESIGN),
              'prior_source': ref(OLD), 'synthetic_receipt': ref(receipt), 'implementation': ref(Path(__file__).resolve()),
              'checks': dict(CHECKS), 'check_count': sum(CHECKS.values()),
              'review': ['Strict own completed history; actual SELL before D close may arm and consume at same D.',
                         'Cost/support/shock/entry grace and original 1% order/limits/fees unchanged.',
                         'Pause only eligible flat candidate; no E success lookahead, fake fill, position, fee, deadline or completed cycle.',
                         'BASE synthetic equality is not yet fresh funded NOOP; actual shadow/positive-funded matching and perunit net sign remain account gates.',
                         'Separate first feedback-state D, original-state D including reservation, target D, and funded-state E.'],
              'new_accounts': 0, 'new_market_data': 0, 'fits': 0, 'real_funded_control': 'NOT_YET_EXECUTED'}
    destination = OUT / 'pause_source_review.json'
    with destination.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'review': ref(destination), 'check_count': result['check_count']}))


if __name__ == '__main__':
    main()
