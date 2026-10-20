"""Minimal frozen-event anchor delta oracle on pure fixtures, not market data."""
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
SOURCE = ROOT / 'research/S014/experiments/EX051_20261020/src/strategy_runtime/strategies/followthrough_anchor.py'
OLD = ROOT / 'research/S014/experiments/EX050_20261020/src/strategy_runtime/strategies/shock_state_policy.py'
SOURCE_SHA = 'a97a53b0d277ef4ee5702cc3b846ce8831fd8b182c2afca83159f31f0458f670'
PROFILES = ['ORIGINAL_C9502_CONTROL', 'SHOCK_ANCHOR_ZERO', 'SHOCK_ANCHOR_FROZEN_1ATR']
COUNTS = Counter()


def check(name, condition):
    assert condition, name
    COUNTS[name] += 1


def deny(*args, **kwargs):
    raise RuntimeError('Pure anchor delta review forbids network')


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
    check('frozen source byte', ref(SOURCE)['sha256'] == SOURCE_SHA)
    new, old = module('a_anchor_new', SOURCE), module('a_anchor_original', OLD)
    fixture = module('a_anchor_fixture', ROOT / 'research/S014/experiments/EX043_20261019/src/precheck.py')
    previous = old.ShockStateStrategy(ParameterSet({'policy_profile': 'FIRST_SHOCK_AFTER_ENTRY_DAY_HOLD'})).definition
    for profile in PROFILES:
        config = new.AnchorConfig.parse({'anchor_profile': profile})
        check('fixed original AGE LOSS COST roles', config.policy_profile.value == 'FIRST_SHOCK_AFTER_ENTRY_DAY_HOLD' and config.pause_profile.value == 'AFTER_NET_LOSS_SKIP1' and config.cost_stop.value == 'NET_LOSS_1ATR')
        definition = new.FollowthroughStrategy(ParameterSet({'anchor_profile': profile})).definition
        for key in ['inputs', 'decision', 'execution', 'monitoring', 'capabilities']:
            check('original contract ' + key, getattr(definition, key) == getattr(previous, key))
    for values in ({}, {'anchor_profile': True}, {'anchor_profile': 'ZERO'}, {'anchor_profile': PROFILES[0], 'policy_profile': 'BASE'}):
        try:
            new.AnchorConfig.parse(values)
        except ValueError:
            check('strong canonical enum rejects extra configuration', True)
        else:
            raise AssertionError('invalid anchor configuration accepted')
    trees = [ast.parse(path.read_text(encoding='utf-8')) for path in (OLD, SOURCE)]
    for name in ['completed_sign', 'causal_features', 'tick', 'buy_limit', 'calendar_request', 'derive_calculation_scope', 'non_final_day_dominated']:
        functions = [next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name) for tree in trees]
        check('unchanged helper AST ' + name, ast.dump(functions[0], include_attributes=False) == ast.dump(functions[1], include_attributes=False))
    args = fixture.fixture()
    original = old.history(*args, old.PolicyConfig.parse({'policy_profile': 'FIRST_SHOCK_AFTER_ENTRY_DAY_HOLD'}))
    for profile in PROFILES:
        config = new.AnchorConfig.parse({'anchor_profile': profile})
        full = new.history(*args, config)
        if profile == PROFILES[0]:
            pd.testing.assert_frame_equal(full[list(original)], original, check_exact=True)
            check('control every original column exact', True)
        index, anchor, atr = -1, None, None
        created_n = 0
        for i, row in enumerate(full.to_dict('records')):
            if row['buy_filled_today'] or row['sell_filled_today']:
                index, anchor, atr = -1, None, None
            created = bool(row['first_shock_today'] and row['first_shock_hold_decision'] and profile != PROFILES[0])
            if created:
                created_n += 1
                index, anchor = i, float(args[0].Close.iloc[i])
                atr = float(row['atr20_prior']) if profile == PROFILES[2] else None
                check('positive finite required frozen input', np.isfinite(anchor) and anchor > 0 and (atr is None or np.isfinite(atr) and atr > 0))
            later = bool(row['held_at_close'] and index >= 0 and i > index)
            raw = bool(later and (float(args[0].Close.iloc[i]) < anchor if profile == PROFILES[1] else anchor - float(args[0].Close.iloc[i]) >= atr if profile == PROFILES[2] else False))
            eligible = bool(row['profit_exit_eligible'] and later)
            selected = eligible and raw
            expected = {'anchor_created_today': created, 'anchor_known': index >= 0, 'anchor_atr_known': atr is not None,
                        'anchor_index': index, 'anchor_later_session': later, 'anchor_raw_condition': raw,
                        'anchor_exit_eligible': eligible, 'selected_anchor_exit': selected,
                        'anchor_exit_added': selected and not (row['selected_risk_exit'] or row['ordinary_support_exit']),
                        'anchor_cost_overlap': selected and row['selected_cost_exit'],
                        'anchor_support_overlap': selected and row['original_support_exit'],
                        'anchor_deadline_overlap': raw and row['deadline_exit'], 'anchor_pending_overlap': raw and row['pending_inherited'],
                        'selected_combined_risk_exit': bool(row['selected_risk_exit'] or selected)}
            for key, value in expected.items():
                check('independent frozen own-cycle ' + key, row[key] == value)
            for key, value in [('shock_anchor_close_RUNTIME_HFQ', anchor), ('shock_anchor_ATR0_RUNTIME_HFQ', atr)]:
                check('frozen raw field known versus null', pd.isna(row[key]) if value is None else row[key] == value)
            check('legacy risk preserves original role', bool(row['selected_risk_exit']) == bool(row['selected_shock_exit'] or row['selected_cost_exit']))
            if row['held_at_close']:
                check('pending expiry combinedrisk S5 priority', bool(row['exit_pending']) == bool(row['pending_inherited'] or row['deadline_exit'] or row['selected_combined_risk_exit'] or row['ordinary_support_exit']))
        check('fixture has event creation or exact control', created_n > 0 or profile == PROFILES[0])
        for stop in (65, 76, 85):
            prefix = new.history(*(frame.iloc[:stop].copy(deep=True) for frame in args), config)
            pd.testing.assert_frame_equal(prefix, full.iloc[:stop], check_exact=True)
            check('frozen anchor causal prefix', True)
    report = {'status': 'PASS', 'reviewer': 'A', 'source_sha256': SOURCE_SHA, 'source': ref(SOURCE), 'prior_source': ref(OLD),
              'implementation': ref(Path(__file__).resolve()), 'check_count': sum(COUNTS.values()), 'checks': dict(COUNTS),
              'manual_review': ['ZERO and1ATR share all-later-D cycle clock; firstD0 excluded. Close/ATR freeze once and clear actualBUY/SELL only.',
                                'ZERO/control have no required frozenATR;1ATR requires finite positive originalATR0, never currentATR substitution.',
                                'Original AGE state, rawprofit/risk observations retained; selected_combined_risk_exit represents actual oldriskORanchor. Do not misread legacy selected_risk_exit as full current action.',
                                'Anchor exit no currentP>0 gate, preserves pending/expiry/S5/cost and loss-pause/reservation/publicfill; no source nextE lookahead.',
                                'Actual new-source control exactC9502 and three funded economics remain required after public lock.'],
              'new_accounts': 0, 'new_actual_input_fetches': 0, 'new_ATR_hit_inventory': 0, 'new_fits': 0, 'new_supplier_calls': 0}
    path = OUT / 'anchor_source_review.json'
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'review': ref(path), 'checks': report['check_count']}))


if __name__ == '__main__':
    main()
