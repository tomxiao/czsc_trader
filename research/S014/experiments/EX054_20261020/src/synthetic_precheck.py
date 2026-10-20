"""Offline synthetic equivalence and parameter-boundary checks; no accounts."""
import importlib.util
import json
import math
import socket
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet


ROOT = Path.cwd()


def no_network(*args, **kwargs):
    raise AssertionError('Network prohibited in synthetic parameter-adapter checks')


socket.create_connection = no_network
socket.socket.connect = no_network


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


old = load('c9523_parent_synthetic', ROOT / 'research/S014/experiments/EX053_20261020/work/c9522/strategy_runtime/strategies/trend_permission.py')
new = load('c9524_successor_synthetic', ROOT / 'research/S014/experiments/EX054_20261020/src/strategy_runtime/strategies/trend_permission.py')
builder = load('c9524_builder_synthetic', ROOT / 'research/S014/experiments/EX054_20261020/src/build_candidate.py')
values = dict(builder.CENTER_PARAMETERS)
prior = old.TrendPermissionStrategy(ParameterSet({'permission_profile': values['permission_profile']}))
current = new.TrendPermissionStrategy(ParameterSet(values))
candidate, description = builder.build()
assert candidate.reference_id == 'S014-C9524'
assert candidate.payload['decision_feedback'] == 'SIMULATED_FILL_FEEDBACK'
assert candidate.payload['runtime']['contract_version'] == 2
assert prior.definition.execution == current.definition.execution
assert prior.definition.inputs == current.definition.inputs
assert prior.definition.observation == current.definition.observation

cases = []
event_totals = {}
for seed in (13, 41, 173):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range('2019-12-31', periods=901)
    shocks = 0.004 * np.sin(np.arange(len(dates)) / 17) + rng.normal(0, .025, len(dates))
    close = np.round(10 * np.exp(np.cumsum(shocks)), 2)
    opening = np.round(np.r_[close[0], close[:-1]] * np.exp(rng.normal(0, .012, len(dates))), 2)
    high = np.round(np.maximum(opening, close) * (1 + rng.uniform(.002, .025, len(dates))), 2)
    low = np.round(np.minimum(opening, close) * (1 - rng.uniform(.002, .025, len(dates))), 2)
    market = pd.DataFrame({'Date': dates, 'Open': opening, 'High': high, 'Low': low, 'Close': close})
    raw = market.copy()
    prev = np.r_[close[0], close[:-1]]
    limits = pd.DataFrame({'Date': dates, 'DownLimit': np.round(prev * .9, 2), 'UpLimit': np.round(prev * 1.1, 2)})
    status = pd.DataFrame({'Date': dates, 'Status': ['SUSPENDED' if i % 37 == 0 else 'TRADING' for i in range(len(dates))]})
    inputs = dict(market=market, raw=raw, limits=limits, status=status)
    for offset in (0, 300):
        sessions = dates[offset:]
        before = old.history(market, raw, limits, status, prior._config, sessions)
        after = new.history(market, raw, limits, status, current._config, sessions)
        pd.testing.assert_frame_equal(before, after, check_exact=True)
        cases.append({'seed': seed, 'state_offset': offset, 'rows': len(after), 'columns': len(after.columns), 'exact': True})
        for name in ('buy_filled_today', 'sell_filled_today', 'failed_buy_reset', 'pause_slot_consumed', 'selected_shock_exit', 'selected_cost_exit', 'deadline_exit', 'permission_granted', 'permission_refused'):
            event_totals[name] = event_totals.get(name, 0) + int(after[name].sum())

# Every numerical coordinate is wired into its intended calculation or state
# path on a fixed synthetic sample. This is sensitivity plumbing, not a P&L test.
sensitivity = {}
for key in values:
    if key == 'permission_profile':
        continue
    point = dict(values)
    point[key] = point[key] + (1 if type(point[key]) is int else .25)
    changed = new.history(market, raw, limits, status, new.PermissionConfig.parse(point), dates)
    base = new.history(market, raw, limits, status, current._config, dates)
    assert not changed.equals(base), f'Unwired coordinate {key}'
    sensitivity[key] = True

bad = [dict(values, permission_profile='ORIGINAL_C9502_CONTROL'), dict(values, extra=1), {k:v for k,v in values.items() if k != 'support_window'}]
for key in values:
    if key == 'permission_profile':
        continue
    if type(values[key]) is int:
        for value in (True, 0, -1, 5.0, '5'):
            bad.append(dict(values, **{key: value}))
    else:
        for value in (True, 0.0, -1.0, 2, '2.0', math.nan, math.inf):
            bad.append(dict(values, **{key: value}))
bad.append(dict(values, volatility_window=1))
for point in bad:
    try:
        new.PermissionConfig.parse(point)
    except ValueError:
        pass
    else:
        raise AssertionError(f'Accepted illegal coordinates: {point}')
assert all(event_totals[key] > 0 for key in event_totals), event_totals
result = {'status': 'PASS', 'candidate': candidate.reference_id, 'synthetic_equivalence_cases': cases,
    'zero_tolerance': True, 'numeric_coordinate_sensitivity': sensitivity,
    'illegal_parameter_cases_rejected': len(bad), 'event_coverage': event_totals,
    'account_evaluations': 0, 'network_calls': 0,
    'source_files_changed': ['EX054/src/strategy_runtime/strategies/trend_permission.py', 'EX054/src/build_candidate.py']}
out = ROOT / '.tmp/stage4-parameter-adapter/result.json'
out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(result, ensure_ascii=False))
