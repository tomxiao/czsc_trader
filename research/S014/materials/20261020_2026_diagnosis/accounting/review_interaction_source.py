"""Independent minimal fixed-OFF completed-loss interaction source review."""
import ast
from collections import Counter
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import socket
import sys

import pandas as pd
from strategy_runtime import ParameterSet

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
EX = ROOT / 'research/S014/experiments/EX048_20261020'
SOURCE = EX / 'src/strategy_runtime/strategies/loss_interaction_review.py'
OLD = ROOT / 'research/S014/experiments/EX047_20261020/src/strategy_runtime/strategies/shock_action_review.py'
COUNTS = Counter()


def check(name, condition):
    assert condition, name
    COUNTS[name] += 1


def deny(*args, **kwargs):
    raise RuntimeError('Pure source review forbids network')


socket.socket.connect = deny
socket.create_connection = deny


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def ref(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest()}


def main():
    check('fixed new source bytes', ref(SOURCE)['sha256'] == '5a4347527aad29cb647d9c44a26cf1b970dda471af9d1419f817b39e4476a66b')
    check('prior frozen source bytes', ref(OLD)['sha256'] == 'ea8f6c82dc7901b12edd00fe13cf1db6ed6d274563ac65479bf06058ed11bf4b')
    new, old = module('a_interaction_new', SOURCE), module('a_interaction_old', OLD)
    fixture = module('a_interaction_fixture', ROOT / 'research/S014/experiments/EX043_20261019/src/precheck.py')
    for profile in ('AFTER_NET_LOSS_SKIP1', 'BASE'):
        typed = new.InteractionConfig.parse({'pause_profile': profile})
        check('canonical fixed roles', typed.pause_profile.value == profile and typed.shock_profile.value == 'SHOCK_OFF' and typed.cost_stop.value == 'NET_LOSS_1ATR' and typed.entry_guard.value == 'BASE' and typed.exit_domain.value == 'POSITIVE_P')
        definition = new.LossInteractionStrategy(ParameterSet({'pause_profile': profile})).definition
        previous = old.ShockActionStrategy(ParameterSet({'shock_profile': 'SHOCK_OFF'})).definition
        for key in ['inputs', 'decision', 'execution', 'monitoring', 'capabilities']:
            check('original public contract exact ' + key, getattr(definition, key) == getattr(previous, key))
    for value in ({}, {'pause_profile': True}, {'pause_profile': 'LOSS'}, {'pause_profile': 'AFTER_NET_PROFIT_SKIP1'}, {'pause_profile': 'BASE', 'shock_profile': 'SHOCK_OFF'}):
        try:
            new.InteractionConfig.parse(value)
        except ValueError:
            check('illegal payload blocked', True)
        else:
            raise AssertionError('Invalid configuration accepted')
    trees = [ast.parse(p.read_text(encoding='utf-8')) for p in (OLD, SOURCE)]
    for name in ['completed_sign', 'causal_features', 'tick', 'buy_limit', 'calendar_request', 'derive_calculation_scope']:
        nodes = [next(n for n in ast.walk(t) if isinstance(n, ast.FunctionDef) and n.name == name) for t in trees]
        check('inherited helper exact ' + name, ast.dump(nodes[0], include_attributes=False) == ast.dump(nodes[1], include_attributes=False))
    old_text = OLD.read_text(encoding='utf-8').replace('ShockConfig', 'InteractionConfig')
    old_history = next(n for n in ast.parse(old_text).body if isinstance(n, ast.FunctionDef) and n.name == 'history')
    new_history = next(n for n in trees[1].body if isinstance(n, ast.FunctionDef) and n.name == 'history')
    check('whole history unchanged except typed config name', ast.dump(old_history, include_attributes=False) == ast.dump(new_history, include_attributes=False))
    rising, flat = fixture.fixture(), fixture.fixture()
    for i in range(len(flat[0])):
        fixture.change(flat, i, close=10., open_=10.)
    for name, args in [('rising', rising), ('fee_loss', flat)]:
        reference = old.history(*args, old.ShockConfig.parse({'shock_profile': 'SHOCK_OFF'}))
        for profile in ('AFTER_NET_LOSS_SKIP1', 'BASE'):
            full = new.history(*args, new.InteractionConfig.parse({'pause_profile': profile}))
            if profile == 'AFTER_NET_LOSS_SKIP1':
                pd.testing.assert_frame_equal(reference, full, check_exact=True)
                check('fresh source LOSS exact old OFF all columns ' + name, True)
            for row in full.to_dict('records'):
                check('SHOCK always truly disabled', row['shock_action_enabled'] == row['selected_shock_exit'] == 0.)
                check('constant profile certification', bool(row['pause_loss_profile']) == (profile == 'AFTER_NET_LOSS_SKIP1') and not row['pause_profit_profile'])
                if profile == 'BASE':
                    check('BASE never arms or consumes', not row['pause_armed_before_candidate'] and not row['pause_armed'] and not row['pause_slot_consumed'] and not row['planned_slot_active'] and row['planned_slot_until'] == -1)
                check('completion observed iff real toy SELL', bool(row['completed_cycle_today']) == bool(row['sell_filled_today']))
                if row['sell_filled_today']:
                    check('truthful strict completed sign', row['last_completed_sign'] == (1 if row['completed_net_unit'] > 0 else -1 if row['completed_net_unit'] < 0 else 0))
                if row['held_at_close']:
                    check('cost and original support remain', bool(row['selected_risk_exit']) == bool(row['selected_cost_exit']) and bool(row['exit_pending']) == bool(row['pending_inherited'] or row['deadline_exit'] or row['selected_cost_exit'] or row['ordinary_support_exit']))
            for stop in (62, 72, 85):
                prefix = new.history(*(a.iloc[:stop].copy(deep=True) for a in args), new.InteractionConfig.parse({'pause_profile': profile}))
                pd.testing.assert_frame_equal(prefix, full.iloc[:stop], check_exact=True)
                check('no future-dependent prefix', True)
    result = {'status': 'PASS', 'source_sha256': ref(SOURCE)['sha256'], 'source': ref(SOURCE), 'prior_source': ref(OLD),
              'implementation': ref(Path(__file__).resolve()), 'check_count': sum(COUNTS.values()), 'checks': dict(COUNTS),
              'scope': 'Pure source/contracts/synthetic; fresh real LOSS and funded BASE not executed by auditor.',
              'manual_review': ['Only strong enum config exposes original pause_profile at fixedOFF; history AST exact after config-type rename.',
                                'BASE completion history remains observable; never interpreted as no completed losses.',
                                'Constant pause_loss/profit profile flags are not mutable old-state or wealth divergence.',
                                'All seven original annual goals and unchanged fullfrequency; no new acceptance gate.'],
              'new_accounts': 0, 'new_data_calls': 0, 'fits': 0}
    path = OUT / 'interaction_source_review.json'
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'review': ref(path), 'checks': result['check_count']}))


if __name__ == '__main__':
    main()
