"""Minimal EX050 new-rule boundaries; reuse prior helpers and synthetic fixture."""
import ast
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import socket
import sys

import numpy as np
import pandas as pd

ROOT = Path.cwd()
BASE = Path('research/S014/materials/20261020_shock_state_diagnosis')
SOURCE = Path('research/S014/experiments/EX050_20261020/src/strategy_runtime/strategies/shock_state_policy.py')
OLD = Path('research/S014/experiments/EX046_20261020/src/strategy_runtime/strategies/completed_pause_review.py')
FIXTURE = Path('research/S014/experiments/EX043_20261019/src/precheck.py')
CHECKS = []
def digest(path):
    return sha256((ROOT / path).read_bytes()).hexdigest()

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

def check(name, value):
    if not value:
        raise AssertionError(name)
    CHECKS.append(name)

def deny(*args, **kwargs):
    raise RuntimeError('B EX050 pure focused audit forbids network')

socket.socket.connect = deny
socket.create_connection = deny
assert digest(SOURCE) == 'ac4fcdbdc5c46b1d43f31f53dda2de0635fea8f4f0cff8889a083a86f87e76f3'
assert digest(OLD) == '5e775c5b27bfd7b1ac5bec9c2839ce24ae62f32f1829c21a13091868a174b846'
new, old, toy = load('b_ex050', SOURCE), load('b_ex046', OLD), load('b_policy_fixture', FIXTURE)
profiles = [item.value for item in new.PolicyProfile]
trees = [ast.parse((ROOT / path).read_text(encoding='utf-8')) for path in (OLD, SOURCE)]
for name in ('causal_features', 'tick', 'buy_limit', 'completed_sign', 'calendar_request', 'derive_calculation_scope'):
    nodes = [next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name) for tree in trees]
    check('unchanged inherited helper AST ' + name, ast.dump(nodes[0]) == ast.dump(nodes[1]))
for args in ((10., 10., 10.), (11., 12., 10.), (12., 10., 10.), (np.inf, 10., 10.), (1e308, 1e-308, 10.)):
    a, b, c = args
    value = new.non_final_day_dominated(a, b, c)
    if all(np.isfinite(x) and x > 0 for x in args) and np.isfinite(a / b) and np.isfinite(b / c):
        check('exact scalar log <= ' + str(args), value == bool(float(np.log(a / b)) <= float(np.log(b / c))))
    else:
        check('UNKNOWN invalid ratio ' + str(args), value is None)

features = new.causal_features
def run(args, profile, shock_indices):
    f = features(args[0])
    f['z5'] = 0.
    f['shock_known'] = True
    f['atr20_prior'] = 100.
    f['atr_positive'] = True
    for index in shock_indices:
        f.iloc[index, f.columns.get_loc('z5')] = 3.
    new.causal_features = lambda market: f.loc[pd.to_datetime(market.Date)].copy()
    try:
        return new.history(*args, new.PolicyConfig.parse({'policy_profile': profile}))
    finally:
        new.causal_features = features

args = toy.fixture()
baseline = run(args, profiles[0], [])
entry = int(np.flatnonzero(baseline.buy_filled_today)[0])
control = run(args, profiles[0], [entry + 1, entry + 2])
s2 = run(args, profiles[1], [entry + 1, entry + 2])
age = run(args, profiles[2], [entry + 1, entry + 2])
check('control raw firstSHOCK sells next E', control.exit_pending.iloc[entry + 1] and control.sell_filled_today.iloc[entry + 2])
for label, result in (('S2', s2), ('AGE', age)):
    check(label + ' first own held node assessed once', result.first_shock_today.iloc[entry + 1] and result.first_shock_age.iloc[entry + 1] == 1)
    check(label + ' latch selectedSHOCK only', result.shock_condition.iloc[entry + 1] and result.shock_action_suppressed.iloc[entry + 1] and not result.selected_shock_exit.iloc[entry + 1])
    check(label + ' later SHOCK not reassessed', result.shock_condition.iloc[entry + 2] and not result.first_shock_today.iloc[entry + 2] and result.shock_disable_latched.iloc[entry + 2])
    check(label + ' original H10 not reset', result.deadline_index.iloc[entry + 1] == entry + 9 and result.deadline_exit.iloc[entry + 9] and result.sell_filled_today.iloc[entry + 10])
    check(label + ' actualSELL clears cycle latch', not result.shock_state_assessed.iloc[entry + 10] and not result.shock_disable_latched.iloc[entry + 10] and result.first_shock_age.iloc[entry + 10] == -1)

entryday = toy.fixture()
toy.change(entryday, entry, close=float(entryday[0].Close.iloc[entry]) + .5)
e = run(entryday, profiles[2], [entry])
check('AGE entryday rawSHOCK observed', e.buy_filled_today.iloc[entry] and e.shock_condition.iloc[entry])
check('AGE entryday follows original exit', e.first_shock_age.iloc[entry] == 0 and not e.first_shock_hold_decision.iloc[entry] and e.exit_pending.iloc[entry] and e.sell_filled_today.iloc[entry + 1])

changed = toy.fixture()
toy.change(changed, entry + 3, close=8.)
support = run(changed, profiles[2], [entry + 1])
check('AGE latch never protects support exit', support.shock_disable_latched.iloc[entry + 3] and support.ordinary_support_exit.iloc[entry + 3] and support.exit_pending.iloc[entry + 3])
failed = toy.fixture()
failed[3].loc[entry, 'Status'] = 'SUSPENDED'
failed_result = run(failed, profiles[2], [entry])
check('failedBUY creates no cycle latch', failed_result.failed_buy_reset.iloc[entry] and failed_result.entry_index.iloc[entry] == -1 and not failed_result.shock_state_assessed.iloc[entry])
pending = toy.fixture()
pending[3].loc[entry + 2, 'Status'] = 'SUSPENDED'
p = run(pending, profiles[0], [entry + 1, entry + 2])
check('original pending cannot reassess', p.pending_inherited.iloc[entry + 2] and not p.first_shock_today.iloc[entry + 2] and p.sell_filled_today.iloc[entry + 3])
for profile in profiles:
    full = run(args, profile, [entry + 1, entry + 2])
    stop = entry + 4
    prefix = [frame.iloc[:stop].copy(deep=True) for frame in args]
    actual = run(prefix, profile, [entry + 1, entry + 2])
    pd.testing.assert_frame_equal(actual, full.iloc[:stop], check_exact=True)
    CHECKS.append('new lifecycle prefix ' + profile)

plain = toy.fixture()
old_frame = old.history(*plain, old.PauseConfig.parse({'pause_profile': 'AFTER_NET_LOSS_SKIP1'}))
new_frame = new.history(*plain, new.PolicyConfig.parse({'policy_profile': profiles[0]}))
pd.testing.assert_frame_equal(new_frame[old_frame.columns], old_frame, check_exact=True)
CHECKS.append('control all inherited columns exact on toy')
bindings = {path.as_posix(): digest(path) for path in (SOURCE, OLD, FIXTURE, BASE / 'policy_decision.json', BASE / 'review/policy_locked_method_review.json')}
bindings[Path(__file__).resolve().relative_to(ROOT).as_posix()] = digest(Path(__file__).resolve().relative_to(ROOT))
result = {'status': 'PASS_FOCUSED_SOURCE_PENDING_RUNNER', 'reviewer': 'B', 'blocking_findings': [],
          'reviewed_hashes': bindings, 'checks_count': len(CHECKS), 'checks': CHECKS,
          'review': 'Only new policy enum/first-own-SHOCK assessment and independent latch were investigated. Original six helpers AST exact; unchanged prior contracts and all-profile SRT materialization remain C focused precheck responsibility. No repeated full feature oracle or real account replay.',
          'gate': 'Final runner/design review and immutable source lock still required; fresh exact C9461 control must independently PASS before either treatment.',
          'new_funded_accounts': 0, 'new_market_calls': 0, 'real_prepared_fetches': 0}
out = ROOT / BASE / 'review/policy_source_focused_review.json'
with out.open('x', encoding='utf-8', newline='\n') as handle:
    json.dump(result, handle, ensure_ascii=False, indent=2)
    handle.write('\n')
print(json.dumps({'status': result['status'], 'checks': len(CHECKS), 'path': out.relative_to(ROOT).as_posix(), 'sha256': digest(out.relative_to(ROOT))}))
