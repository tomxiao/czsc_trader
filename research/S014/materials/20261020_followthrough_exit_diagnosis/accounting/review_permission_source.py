"""Minimal EX052 D0 permission delta and declared numeric observation audit."""
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
SOURCE = ROOT / 'research/S014/experiments/EX052_20261020/src/strategy_runtime/strategies/trend_permission.py'
OLD = ROOT / 'research/S014/experiments/EX050_20261020/src/strategy_runtime/strategies/shock_state_policy.py'
SOURCE_SHA = 'ba01530dc434d32a540ba0a8e6ec9078a638137dcbaf683eb366171291ee67f2'
PROFILES = ['ORIGINAL_C9502_CONTROL', 'AGE_PRIOR_TREND_PERMISSION']
COUNTS = Counter()


def check(name, value):
    assert value, name
    COUNTS[name] += 1


def deny(*args, **kwargs):
    raise RuntimeError('Pure source/observation review, no network')


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
    check('final source exact byte', ref(SOURCE)['sha256'] == SOURCE_SHA)
    new, old = module('a_permission_new', SOURCE), module('a_permission_old', OLD)
    fixture = module('a_permission_fixture', ROOT / 'research/S014/experiments/EX043_20261019/src/precheck.py')
    prior = old.ShockStateStrategy(ParameterSet({'policy_profile': 'FIRST_SHOCK_AFTER_ENTRY_DAY_HOLD'})).definition
    for profile in PROFILES:
        strategy = new.TrendPermissionStrategy(ParameterSet({'permission_profile': profile}))
        for key in ['inputs', 'decision', 'execution', 'monitoring', 'capabilities']:
            check('original contract exact ' + key, getattr(strategy.definition, key) == getattr(prior, key))
        check('all new observations declared numeric', set(new.PERMISSION_DIAGNOSTIC) <= set(strategy._observed))
    for values in ({}, {'permission_profile': True}, {'permission_profile': 'S1'}, {'permission_profile': PROFILES[0], 'policy_profile': 'BASE'}):
        try:
            new.PermissionConfig.parse(values)
        except ValueError:
            check('canonical enum rejects invalid', True)
        else:
            raise AssertionError('invalid permission configuration')
    trees = [ast.parse(path.read_text(encoding='utf-8')) for path in [OLD, SOURCE]]
    for name in ['completed_sign', 'causal_features', 'tick', 'buy_limit', 'calendar_request', 'derive_calculation_scope', 'non_final_day_dominated']:
        funcs = [next(n for n in ast.walk(t) if isinstance(n, ast.FunctionDef) and n.name == name) for t in trees]
        check('unchanged original helper ' + name, ast.dump(funcs[0], include_attributes=False) == ast.dump(funcs[1], include_attributes=False))
    for operands, expected in [((11., 10., 9.), True), ((10., 10., 9.), True), ((11., 10., 10.), False), ((9., 10., 9.), False), ((np.inf, 10., 9.), None), ((10., np.nan, 9.), None)]:
        check('exact S1 inequalities/unknown boundary', new.prior_trend_permission(*operands) is expected)
    args = fixture.fixture()
    original = old.history(*args, old.PolicyConfig.parse({'policy_profile': 'FIRST_SHOCK_AFTER_ENTRY_DAY_HOLD'}))
    for profile in PROFILES:
        config = new.PermissionConfig.parse({'permission_profile': profile})
        full = new.history(*args, config)
        check('all new formal flags/index finite on fullfixture', np.isfinite(full[list(new.PERMISSION_DIAGNOSTIC)].to_numpy(dtype=float)).all())
        if profile == PROFILES[0]:
            pd.testing.assert_frame_equal(full[list(original)], original, check_exact=True)
            check('fresh C9502 pure every old column exact', True)
        assessed = latched = known = hold = evaluated = s1true = False
        age, index, firsts = -1, -1, 0
        records = full.to_dict('records')
        for i, row in enumerate(records):
            if row['buy_filled_today'] or row['sell_filled_today']:
                assessed = latched = known = hold = evaluated = s1true = False
                age = index = -1
            inherited = bool(row['held_at_close'] and i and records[i - 1]['exit_pending'] and not row['sell_filled_today'])
            expiry = bool(row['held_at_close'] and row['warmup_sessions'] >= row['deadline_index'])
            raw = bool(row['held_at_close'] and not inherited and not expiry and row['shock_known'] and row['net_profit'] > 0 and row['z5'] > 2)
            first = raw and not assessed
            required = False
            if first:
                assessed = known = True
                age, index = int(row['holding_age']), i
                firsts += 1
                hold = age >= 1
                if profile == PROFILES[1] and hold:
                    required = evaluated = True
                    s1true = bool(row['ma20_prior'] > row['ma20_prior_lag5'] and float(args[0].Close.iloc[i - 1]) >= row['ma20_prior'])
                    hold = s1true
                latched = hold
            expected = {'first_shock_today': first, 'first_shock_state_known': known, 'first_shock_hold_decision': hold,
                        'shock_state_assessed': assessed, 'shock_disable_latched': latched,
                        'permission_required_today': required, 'permission_s1_evaluated': evaluated, 'permission_s1_known': evaluated,
                        'permission_s1_true': s1true, 'permission_granted': assessed and hold,
                        'permission_refused': assessed and not hold, 'permission_age_qualified': assessed and age >= 1,
                        'permission_first_index': index, 'selected_shock_exit': raw and not latched}
            for key, value in expected.items():
                check('independent own firstD0 state ' + key, row[key] == value)
            check('original priority and nextE target', not row['held_at_close'] or bool(row['exit_pending']) == bool(inherited or expiry or row['selected_shock_exit'] or row['selected_cost_exit'] or row['ordinary_support_exit']))
        check('fixture exercises firstSHOCK', firsts > 0)
        for stop in [65, 76, 85]:
            prefix = new.history(*(a.iloc[:stop].copy(deep=True) for a in args), config)
            pd.testing.assert_frame_equal(prefix, full.iloc[:stop], check_exact=True)
            check('D0 frozenpermission causal prefix', True)
    report = {'status': 'PASS', 'reviewer': 'A', 'source_sha256': SOURCE_SHA, 'source': ref(SOURCE), 'prior_source': ref(OLD),
              'check_count': sum(COUNTS.values()), 'checks': dict(COUNTS), 'implementation': ref(Path(__file__).resolve()),
              'formal_observability_contract': {'required_new_fields': list(new.PERMISSION_DIAGNOSTIC), 'raw_columns_assumed': [],
                                                'actual_control_gate_required': 'Each declared new field must exist and be finite in formal actual decisions before treatment.'},
              'diagnostic_semantics': 'permission_granted/refused and first_index describe final firstSHOCK hold/exit state including age0/control. Count S1-specific grants/refusals only within permission_s1_evaluated and permission_age_qualified; raw refusals alone are not S1 refusals.',
              'manual_review': ['No EX051 anchor/ATR exit carried. New action is original positive direction S1 within age>=1 at first ownSHOCKD0 only.',
                                'Control/age0 no S1 input dependency. Required-domain UNKNOWN raises rather than FALSE; no rawprice projection assumption.',
                                'Old price/fees/support/cost/GRACE/H10/reservation and strict completed-loss pause unchanged. Actual funded control and sacrificed opportunities remain required.',
                                'Prior S1 negative/combination exclusions are preserved; current posthoc interaction is a separate explicit successor, not independent new information.'],
              'new_actual_input_fetches': 0, 'new_hit_counts': 0, 'new_accounts': 0, 'new_fits': 0, 'new_supplier_calls': 0}
    path = OUT / 'permission_source_review.json'
    with path.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'review': ref(path), 'checks': report['check_count']}))


if __name__ == '__main__':
    main()
