"""Minimal EX050 delta oracle on pure fixtures; no actual strategy replay."""
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
from strategy_runtime import ParameterSet

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / 'research/S014/experiments/EX050_20261020/src/strategy_runtime/strategies/shock_state_policy.py'
OLD = ROOT / 'research/S014/experiments/EX046_20261020/src/strategy_runtime/strategies/completed_pause_review.py'
SOURCE_SHA = 'ac4fcdbdc5c46b1d43f31f53dda2de0635fea8f4f0cff8889a083a86f87e76f3'
PROFILES = ['ORIGINAL_C9461_CONTROL', 'FIRST_SHOCK_NON_FINAL_DAY_DOMINATED_HOLD', 'FIRST_SHOCK_AFTER_ENTRY_DAY_HOLD']
COUNTS = Counter()


def check(name, value):
    assert value, name
    COUNTS[name] += 1


def deny(*args, **kwargs):
    raise RuntimeError('Pure delta review forbids network')


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
    check('exact fixed source', ref(SOURCE)['sha256'] == SOURCE_SHA)
    new, old = module('a_policy_new', SOURCE), module('a_policy_original', OLD)
    fixture = module('a_policy_fixture', ROOT / 'research/S014/experiments/EX043_20261019/src/precheck.py')
    previous = old.CompletedPauseStrategy(ParameterSet({'pause_profile': 'AFTER_NET_LOSS_SKIP1'})).definition
    for profile in PROFILES:
        config = new.PolicyConfig.parse({'policy_profile': profile})
        check('fixed original roles', config.pause_profile.value == 'AFTER_NET_LOSS_SKIP1' and config.entry_guard.value == 'BASE' and config.exit_domain.value == 'POSITIVE_P' and config.cost_stop.value == 'NET_LOSS_1ATR')
        definition = new.ShockStateStrategy(ParameterSet({'policy_profile': profile})).definition
        for key in ['inputs', 'decision', 'execution', 'monitoring', 'capabilities']:
            check('original contract ' + key, getattr(definition, key) == getattr(previous, key))
    for value in ({}, {'policy_profile': True}, {'policy_profile': 'S2'}, {'policy_profile': PROFILES[0], 'pause_profile': 'BASE'}):
        try:
            new.PolicyConfig.parse(value)
        except ValueError:
            check('strong canonical enum', True)
        else:
            raise AssertionError('invalid parameter accepted')
    trees = [ast.parse(path.read_text(encoding='utf-8')) for path in [OLD, SOURCE]]
    for name in ['completed_sign', 'causal_features', 'tick', 'buy_limit', 'calendar_request', 'derive_calculation_scope']:
        functions = [next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name) for tree in trees]
        check('no repeated feature redesign ' + name, ast.dump(functions[0], include_attributes=False) == ast.dump(functions[1], include_attributes=False))
    for current, prior, fifth in [(11., 10., 8.), (11., 10., 10.), (9., 10., 8.), (1., 1., 1.)]:
        check('exact prescribed S2 expression', new.non_final_day_dominated(current, prior, fifth) == bool(np.log(current / prior) <= np.log(prior / fifth)))
    for values in [(np.inf, 1., 1.), (1., np.nan, 1.), (0., 1., 1.), (1e308, 1e-308, 1.)]:
        check('unknown not imputed', new.non_final_day_dominated(*values) is None)
    args = fixture.fixture()
    original = old.history(*args, old.PauseConfig.parse({'pause_profile': 'AFTER_NET_LOSS_SKIP1'}))
    for profile in PROFILES:
        config = new.PolicyConfig.parse({'policy_profile': profile})
        full = new.history(*args, config)
        if profile == PROFILES[0]:
            pd.testing.assert_frame_equal(full[list(original)], original, check_exact=True)
            check('control all old columns exact pure fixture', True)
        assessed = latch = known = hold = False
        age = -1
        firsts = 0
        records = full.to_dict('records')
        for i, row in enumerate(records):
            if row['buy_filled_today'] or row['sell_filled_today']:
                assessed = latch = known = hold = False
                age = -1
            inherited = bool(row['held_at_close'] and i and records[i - 1]['exit_pending'] and not row['sell_filled_today'])
            expiry = bool(row['held_at_close'] and row['warmup_sessions'] >= row['deadline_index'])
            eligible = bool(row['held_at_close'] and not inherited and not expiry)
            raw = bool(eligible and row['shock_known'] and row['net_profit'] > 0 and row['z5'] > 2)
            first = raw and not assessed
            if first:
                firsts += 1
                assessed = known = True
                age = int(row['holding_age'])
                hold = bool(np.log(float(args[0].Close.iloc[i]) / float(args[0].Close.iloc[i - 1])) <= np.log(float(args[0].Close.iloc[i - 1]) / float(args[0].Close.iloc[i - 5]))) if profile == PROFILES[1] else age >= 1 if profile == PROFILES[2] else False
                latch = hold
            expected = {'shock_state_assessed': assessed, 'shock_disable_latched': latch, 'first_shock_today': first,
                        'first_shock_state_known': known, 'first_shock_hold_decision': hold, 'first_shock_age': age,
                        'shock_action_suppressed': raw and latch, 'selected_shock_exit': raw and not latch,
                        'selected_profit_exit': raw, 'shock_condition': raw}
            for key, value in expected.items():
                check('independent first own cycle ' + key, row[key] == value)
            check('other protections retain priority', bool(row['exit_pending']) == bool(inherited or expiry or row['selected_cost_exit'] or row['selected_shock_exit'] or row['ordinary_support_exit']))
        check('fixture exercises actual first SHOCK', firsts > 0)
        for stop in (65, 76, 85):
            prefix = new.history(*(frame.iloc[:stop].copy(deep=True) for frame in args), config)
            pd.testing.assert_frame_equal(prefix, full.iloc[:stop], check_exact=True)
            check('causal first state/latch prefix', True)
    report = {'status': 'PASS', 'source_sha256': SOURCE_SHA, 'source': ref(SOURCE), 'prior_source': ref(OLD),
              'implementation': ref(Path(__file__).resolve()), 'check_count': sum(COUNTS.values()), 'checks': dict(COUNTS),
              'minimal_delta': 'Strong profile wrapper plus first-own-eligible-SHOCK single assessment and cycle latch only; raw legacy condition preserved. Same other protection priority and own loss-pause history.',
              'actual_new_source_control': 'NOT_EXECUTED_REQUIRED_NEXT', 'new_accounts': 0, 'new_fits': 0, 'new_supplier_calls': 0,
              'limits': ['Pure fixture only; actual positive-funded held/fills/completion and original seven-year goals require separate actual ledger audits.', 'Do not transplant original21 component dates or count new constant metadata as economic divergence.']}
    path = OUT / 'policy_source_review.json'
    with path.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'review': ref(path), 'checks': report['check_count']}))


if __name__ == '__main__':
    main()
