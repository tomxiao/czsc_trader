"""EX035 synthetic boundaries only: no historical account dispatch or supplier calls."""
import ast
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from strategy_runtime import ParameterSet, implementation_sha256

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
PACKAGE = EX / 'src/strategy_runtime'
FROZEN = ROOT / 'research/S014/assets/candidates/C0011/source/4fa691aaf4107e7dd3d3a1decfabe5f8920926d7b9155f926f335f35bb760141/strategy_runtime'
SOURCE = PACKAGE / 'strategies/repair_e9.py'
AUDIT = ['intervention_today', 'intervention_done']


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    out = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(out)
    return out


def fixture(failed_buy=False, blocked_sell=None, reentry=False):
    """Adapted EX019 synthetic fixture: one entry at index 23; no historical input."""
    dates = pd.bdate_range('2020-01-01', periods=40)
    close = 10 + .02 * np.sin(np.arange(40))
    close[22] = 10.
    close[23] = 10.02
    close[24:26] = [10.25, 10.3]
    raw = pd.DataFrame({'Date': dates, 'Open': close + .02, 'High': close + .12,
                        'Low': close - .1, 'Close': close, 'Volume': 100000., 'Amount': 1000000.})
    raw.loc[22, ['Open', 'High', 'Low']] = [9.9, 10.1, 9.8]
    raw.loc[23, ['Open', 'High', 'Low']] = [10., 10.2, 9.9]
    if failed_buy:
        raw.loc[23, ['Open', 'High', 'Low', 'Close']] = [10.25, 10.4, 10.2, 10.3]
    limits = pd.DataFrame({'Date': dates, 'DownLimit': 5., 'UpLimit': 20.})
    if blocked_sell is not None:
        raw.loc[blocked_sell, ['Open', 'High', 'Low', 'Close']] = 9.
        limits.loc[blocked_sell, 'DownLimit'] = 9.
        raw.loc[blocked_sell + 1, ['Open', 'High', 'Low', 'Close']] = [9., 9.01, 9., 9.]
        limits.loc[blocked_sell + 1, 'DownLimit'] = 9.
    if reentry:
        raw.loc[29, ['Open', 'High', 'Low', 'Close']] = [9.7, 10.1, 9.6, 10.]
        raw.loc[30, ['Open', 'High', 'Low', 'Close']] = [9.9, 10.1, 9.8, 10.]
    status = pd.DataFrame({'Date': dates, 'Status': 'TRADING'})
    samples = pd.DataFrame({'maturity_date': pd.bdate_range('2019-01-01', periods=60), 'gap_autocorr': -1.})
    return [raw.copy(), raw, limits, status], samples


def main():
    destination = EX / 'others/precheck.json'
    if destination.exists():
        raise RuntimeError('Existing precheck evidence must not be overwritten')
    attempts = []
    def prohibited(*args, **kwargs):
        attempts.append('ATTEMPTED')
        raise RuntimeError('No network permitted in synthetic precheck')
    requests.sessions.Session.request = prohibited
    current = module('ex035_precheck_runtime', SOURCE)
    old = module('c0011_precheck_runtime', FROZEN / 'strategies/repair_v3.py')
    checks = []
    def check(name, truth):
        if not bool(truth):
            raise AssertionError(name)
        checks.append(name)
    def equal(name, left, right):
        pd.testing.assert_frame_equal(left, right, check_exact=True)
        check(name, True)
    def run(inputs, samples, entry=''):
        return current.history(*inputs, samples, 'high_H3', entry)
    def day(inputs, index):
        return inputs[0].Date.iloc[index].date().isoformat()
    check('frozen C0011 source identity', implementation_sha256(
        ('strategies/repair_v3.py', 'strategies/calibration_samples.csv'), source_root=FROZEN)
        == '4fa691aaf4107e7dd3d3a1decfabe5f8920926d7b9155f926f335f35bb760141')
    check('byte-identical frozen calibration', (PACKAGE / 'strategies/calibration_samples.csv').read_bytes()
          == (FROZEN / 'strategies/calibration_samples.csv').read_bytes())
    trees = [ast.parse(p.read_text(encoding='utf-8')) for p in (SOURCE, FROZEN / 'strategies/repair_v3.py')]
    for name in ('tick', 'buy_limit'):
        definitions = [next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name) for tree in trees]
        check('unchanged helper ' + name, ast.dump(definitions[0]) == ast.dump(definitions[1]))
    for name in ('calendar_request', 'derive_calculation_scope'):
        definitions = [next(n for n in next(c for c in t.body if isinstance(c, ast.ClassDef)).body
                            if isinstance(n, ast.FunctionDef) and n.name == name) for t in trees]
        check('unchanged input scope ' + name, ast.dump(definitions[0]) == ast.dump(definitions[1]))
    new_definition = current.RepairStrategy.from_parameters(ParameterSet({'variant': 'high_H3', 'intervention_entry_date': ''})).definition
    old_definition = old.RepairStrategy.from_parameters(ParameterSet({'variant': 'high_H3'})).definition
    for name in ('tradable_symbol', 'inputs', 'decision', 'execution', 'monitoring', 'capabilities', 'observation'):
        check('unchanged contract ' + name, getattr(new_definition, name) == getattr(old_definition, name))
    for kwargs in ({}, {'failed_buy': True}, {'blocked_sell': 26}, {'blocked_sell': 29}, {'reentry': True}):
        inputs, samples = fixture(**kwargs)
        noop = run(inputs, samples)
        equal('no-op exact original fields ' + str(kwargs), noop.drop(columns=AUDIT), old.history(*inputs, samples, 'high_H3'))
        check('no-op audit flags ' + str(kwargs), not noop[AUDIT].any().any())
    inputs, samples = fixture(reentry=True)
    chosen = day(inputs, 23)
    extended = run(inputs, samples, chosen)
    original = old.history(*inputs, samples, 'high_H3')
    equal('original fields unchanged before D', extended.iloc[:25].drop(columns=AUDIT), original.iloc[:25])
    check('actual E+2 one-time intervention', extended.intervention_today.sum() == 1
          and extended.intervention_today.iloc[25] and extended.intervention_done.iloc[25:].all()
          and not extended.intervention_done.iloc[:25].any())
    check('horizon stays H3 until decision and then H6', extended.holding_horizon.iloc[23:25].eq(3).all()
          and extended.holding_horizon.iloc[25:29].eq(6).all())
    check('E6 sale and same-close eligibility retained', extended.sell_filled_today.iloc[29]
          and extended.entry_signal.iloc[29] and extended.target_position.iloc[29] == 1.)
    check('next trade resumes original H3', extended.buy_filled_today.iloc[30]
          and extended.holding_horizon.iloc[30:33].eq(3).all() and extended.sell_filled_today.iloc[33])
    check('no second intervention after reentry', not extended.intervention_today.iloc[26:].any())
    wrong_clock = run(inputs, samples, day(inputs, 22))
    equal('entry signal date cannot select actual entry', wrong_clock.drop(columns=AUDIT), original)
    check('entry signal date has no intervention', not wrong_clock.intervention_today.any())
    for stop in (23, 24, 25, 26, 29, 30, 33, 40):
        equal('causal truncated prefix ' + str(stop), run([f.iloc[:stop].copy() for f in inputs], samples, chosen), extended.iloc[:stop])
    future = [f.copy() for f in inputs]
    for frame in future[:2]:
        frame.loc[26:, ['Open', 'High', 'Low', 'Close']] *= 1.1
    equal('future prices cannot change D', run(future, samples, chosen).iloc[:26], extended.iloc[:26])
    future_samples = pd.concat([samples, pd.DataFrame({'maturity_date': [pd.Timestamp('2030-01-01')] * 100, 'gap_autocorr': [1.] * 100})])
    equal('unavailable calibration cannot change decisions', run(inputs, future_samples, chosen), extended)
    scaled = [f.copy() for f in inputs]
    scaled[0][['Open', 'High', 'Low', 'Close']] *= 5.892
    scaled_history = run(scaled, samples, chosen)
    columns = ['target_position', 'held_at_close', 'buy_filled_today', 'sell_filled_today', 'entry_signal', 'holding_horizon', *AUDIT]
    equal('HFQ scale leaves execution state invariant', scaled_history[columns], extended[columns])
    failed, samples = fixture(failed_buy=True)
    h = run(failed, samples, day(failed, 23))
    check('unfilled limit buy consumes no intervention', h.failed_buy_reset.iloc[23] and not h.buy_filled_today.any()
          and not h.intervention_today.any() and h.target_position.iloc[23] == 0.)
    suspended_buy, samples = fixture()
    suspended_buy[3].loc[23, 'Status'] = 'SUSPENDED'
    h = run(suspended_buy, samples, day(suspended_buy, 23))
    check('suspended buy resets instead of hypothetical holding', h.failed_buy_reset.iloc[23]
          and not h.buy_filled_today.any() and not h.intervention_today.any())
    later, samples = fixture(failed_buy=True)
    for frame in later[:2]:
        frame.loc[24, ['Open', 'High', 'Low', 'Close']] = [9.7, 10.1, 9.6, 10.]
        frame.loc[25, ['Open', 'High', 'Low', 'Close']] = [9.9, 10.1, 9.8, 10.]
    h = run(later, samples, day(later, 25))
    check('clock follows later actual fill after failed attempt', h.failed_buy_reset.iloc[23]
          and h.buy_filled_today.iloc[25] and h.intervention_today.iloc[27] and h.intervention_today.sum() == 1)
    for kind in ('lower_limit', 'suspended'):
        blocked, samples = fixture(blocked_sell=29 if kind == 'lower_limit' else None)
        if kind == 'suspended':
            blocked[3].loc[29, 'Status'] = 'SUSPENDED'
        h = run(blocked, samples, day(blocked, 23))
        check(kind + ' delays sale and preserves one intervention', h.held_at_close.iloc[29]
              and h.target_position.iloc[29] == 0. and not h.sell_filled_today.iloc[29]
              and h.sell_filled_today.iloc[30] and h.intervention_today.sum() == 1)
        prefix = [f.iloc[:30].copy() for f in blocked]
        terminal = run(prefix, samples, day(blocked, 23))
        equal(kind + ' terminal prefix retains pending exit', terminal, h.iloc[:30])
        check(kind + ' terminal holding has observable mark and no forced sale', terminal.held_at_close.iloc[-1]
              and not terminal.sell_filled_today.iloc[-1] and terminal.target_position.iloc[-1] == 0.
              and np.isfinite(prefix[0].Close.iloc[-1]) and prefix[0].Close.iloc[-1] > 0)
    for value in (None, 20200101, '20200101', '2020-1-01', '2020-02-30'):
        try:
            current.RepairStrategy.from_parameters(ParameterSet({'variant': 'high_H3', 'intervention_entry_date': value}))
        except (ValueError, TypeError):
            pass
        else:
            raise AssertionError('invalid date accepted ' + str(value))
    for values in ({'variant': 'high_H3'}, {'variant': 'parent_H3', 'intervention_entry_date': ''},
                   {'variant': 'high_H3', 'intervention_entry_date': '', 'extra': True}):
        try:
            current.RepairStrategy.from_parameters(ParameterSet(values))
        except (ValueError, TypeError):
            pass
        else:
            raise AssertionError('invalid parameter schema accepted')
    check('strict schema and canonical date rejection', True)
    check('no network attempts', not attempts)
    source_files = ('strategies/repair_e9.py', 'strategies/calibration_samples.csv')
    result = {'status': 'PASS', 'check_count': len(checks), 'checks': checks,
              'implementation_sha256': implementation_sha256(source_files, source_root=PACKAGE),
              'source_files': list(source_files),
              'source_sha256': sha256(SOURCE.read_bytes()).hexdigest(),
              'calibration_sha256': sha256((PACKAGE / source_files[1]).read_bytes()).hexdigest(),
              'precheck_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'synthetic_only': True, 'account_runs': 0, 'supplier_calls': 0, 'network_attempts': len(attempts),
              'scope_note': 'Synthetic runtime tests verify pending terminal holding and observable close; real account terminal equity and pending orders require authorized control/pilot/account reconciliation.'}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print('EX035_SYNTHETIC_PRECHECK_PASS', len(checks), result['implementation_sha256'])


if __name__ == '__main__':
    main()
