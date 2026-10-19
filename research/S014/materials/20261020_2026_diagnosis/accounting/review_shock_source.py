"""Independent small source/toy ON-OFF gate review, no actual account replay."""
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
EX = ROOT / 'research/S014/experiments/EX047_20261020'
SOURCE = EX / 'src/strategy_runtime/strategies/shock_action_review.py'
OLD = ROOT / 'research/S014/experiments/EX046_20261020/src/strategy_runtime/strategies/completed_pause_review.py'
COUNTS = Counter()


def check(name, condition):
    assert condition, name
    COUNTS[name] += 1


def deny(*args, **kwargs):
    raise RuntimeError('Pure source only; network forbidden')


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
    check('frozen new source', ref(SOURCE)['sha256'] == 'ea8f6c82dc7901b12edd00fe13cf1db6ed6d274563ac65479bf06058ed11bf4b')
    new, old = module('a_shock_new', SOURCE), module('a_shock_prior', OLD)
    fixture = module('a_shock_fixture', ROOT / 'research/S014/experiments/EX043_20261019/src/precheck.py')
    config = old.PauseConfig.parse({'pause_profile': 'AFTER_NET_LOSS_SKIP1'})
    for profile in ('SHOCK_ON', 'SHOCK_OFF'):
        typed = new.ShockConfig.parse({'shock_profile': profile})
        check('fixed loss/cost/S5 roles', typed.pause_profile.value == 'AFTER_NET_LOSS_SKIP1' and typed.cost_stop.value == 'NET_LOSS_1ATR' and typed.entry_guard.value == 'BASE' and typed.exit_domain.value == 'POSITIVE_P')
        definition = new.ShockActionStrategy(ParameterSet({'shock_profile': profile})).definition
        previous = old.CompletedPauseStrategy(ParameterSet({'pause_profile': 'AFTER_NET_LOSS_SKIP1'})).definition
        for key in ['inputs', 'decision', 'execution', 'monitoring', 'capabilities']:
            check('original contract exact ' + key, getattr(definition, key) == getattr(previous, key))
    for value in ({}, {'shock_profile': True}, {'shock_profile': 'ON'}, {'shock_profile': 'SHOCK_OFF', 'pause_profile': 'BASE'}):
        try:
            new.ShockConfig.parse(value)
        except ValueError:
            check('canonical enum rejected', True)
        else:
            raise AssertionError('invalid configuration accepted')
    trees = [ast.parse(p.read_text(encoding='utf-8')) for p in (OLD, SOURCE)]
    for name in ['completed_sign', 'causal_features', 'tick', 'buy_limit', 'calendar_request', 'derive_calculation_scope']:
        functions = [next(n for n in ast.walk(t) if isinstance(n, ast.FunctionDef) and n.name == name) for t in trees]
        check('inherited helper AST exact ' + name, ast.dump(functions[0], include_attributes=False) == ast.dump(functions[1], include_attributes=False))
    rising, flat = fixture.fixture(), fixture.fixture()
    for i in range(len(flat[0])):
        fixture.change(flat, i, close=10., open_=10.)
    for label, args in [('rising', rising), ('flat_fee_loss', flat)]:
        reference = old.history(*args, config)
        for profile in ('SHOCK_ON', 'SHOCK_OFF'):
            full = new.history(*args, new.ShockConfig.parse({'shock_profile': profile}))
            if profile == 'SHOCK_ON':
                pd.testing.assert_frame_equal(full[list(reference)], reference, check_exact=True)
                check('ON all original observations exact ' + label, True)
            for i, row in enumerate(full.to_dict('records')):
                held = bool(row['held_at_close'])
                inherited = bool(held and i and full.iloc[i - 1].exit_pending and not row['sell_filled_today'])
                deadline = bool(held and row['warmup_sessions'] >= row['deadline_index'])
                eligible = bool(held and not inherited and not deadline)
                raw = bool(eligible and row['shock_known'] and row['net_profit'] > 0 and row['z5'] > 2)
                selected = raw and profile == 'SHOCK_ON'
                check('raw and legacy positive condition retained', bool(row['shock_condition']) == raw and bool(row['selected_profit_exit']) == raw)
                check('actual SHOCK solely gated', bool(row['selected_shock_exit']) == selected and bool(row['shock_action_suppressed']) == bool(raw and not selected))
                check('profile finite bool diagnostic', row['shock_action_enabled'] == (profile == 'SHOCK_ON'))
                if held:
                    risk = selected or bool(row['selected_cost_exit'])
                    check('risk gate leaves cost and support', bool(row['selected_risk_exit']) == risk and bool(row['exit_pending']) == bool(inherited or deadline or risk or row['ordinary_support_exit']))
            for stop in (62, 72, 85):
                prefix = new.history(*(a.iloc[:stop].copy(deep=True) for a in args), new.ShockConfig.parse({'shock_profile': profile}))
                pd.testing.assert_frame_equal(prefix, full.iloc[:stop], check_exact=True)
                check('causal synthetic prefix', True)
    receipt = EX / 'others/synthetic_precheck.json'
    proof = json.loads(receipt.read_bytes())
    check('C pure synthetic/SRT bound exact', proof['source_sha256'] == ref(SOURCE)['sha256'] and proof['checks_count'] == 80 and proof['actual_SRT_observation_materializations'] == 666)
    result = {'status': 'PASS', 'source_sha256': ref(SOURCE)['sha256'], 'implementation': ref(Path(__file__).resolve()), 'source': ref(SOURCE), 'prior_source': ref(OLD),
              'synthetic_receipt': ref(receipt), 'check_count': sum(COUNTS.values()), 'checks': dict(COUNTS),
              'manual_review': ['Diff changes only canonical wrapper and actual selectedSHOCK gate; raw positiveP observations are preserved.',
                                'Date-free own loss pause and net-cost/support/H10/pending/entrygrace left identical.',
                                'Suppression diagnostics can overlap another still-active exit; target/funded changes require actual account verification.',
                                'All seven original annual gates include partial2026, no annualization or goal amendment.',
                                'Actual new-source ON exactC9461 and actual funded/strictsign gates remain NOT_EXECUTED.'],
              'new_accounts': 0, 'new_data_calls': 0, 'fits': 0}
    destination = OUT / 'shock_source_review.json'
    with destination.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'source_review': ref(destination), 'checks': result['check_count']}))


if __name__ == '__main__':
    main()
