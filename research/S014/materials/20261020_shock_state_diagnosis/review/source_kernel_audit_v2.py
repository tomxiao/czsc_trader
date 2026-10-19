"""Independent synthetic-only boundary audit; never calls prepared reader fetch."""
from dataclasses import replace
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import socket
import sys

import numpy as np

ROOT = Path.cwd()
BASE = Path('research/S014/materials/20261020_shock_state_diagnosis')
EX = Path('research/S014/experiments/EX049_20261020')
CHECKS = []

def digest(path):
    return sha256((ROOT / path).read_bytes()).hexdigest()

def check(name, value):
    if not value:
        raise AssertionError(name)
    CHECKS.append(name)

def deny(*args, **kwargs):
    raise RuntimeError('B source audit is synthetic-only; network forbidden')

socket.socket.connect = deny
socket.create_connection = deny
expected = {
    (EX / 'src/local_cycle.py').as_posix(): '58827ad8d59e4b3ebd99f250a25a05f8a1f552a9ebf8626ed1fef027f9134f6b',
    (EX / 'src/prepared_reader.py').as_posix(): '078c5d78033f40e2c73767b6ac92f1f36dbc296282ff0b00e8159bf68d2952a7',
    (EX / 'src/precheck.py').as_posix(): '74277aacf810152efc390d7e469e62b79395968070ed66e4b26bdd6b14ea3eda',
}
for path, value in expected.items():
    check('stable SHA ' + path, digest(path) == value)
sys.path.insert(0, str(ROOT / EX / 'src'))
K = importlib.import_module('local_cycle')

spec = importlib.util.spec_from_file_location('ex049_pure_fixture', ROOT / EX / 'src/precheck.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
seed, inputs, dates = fixture.fixture()
on = K.simulate(seed, inputs, K.Action.ON)
off = K.simulate(seed, inputs, K.Action.OFF_LOCAL_CYCLE)
check('ON first SHOCK D and next valid E', on['trace'][-1]['D'] == seed.first_shock_D and on['exit_E'] == inputs.clock[seed.first_shock_D])
check('OFF original deadline plus next E', off['trace'][-1]['market_index'] == seed.deadline_index and off['exit_E'] == inputs.clock[off['trace'][-1]['D']])
check('cycle latch persists independent support protection', all(r['shock_disable_latched'] for r in off['trace'] if r['D'] >= seed.first_shock_D))
check('no aftersale source D', all(r['D'] < off['exit_E'] for r in off['trace']))
check('source/execution units separated', inputs.source_market.loc[dates[4], 'Close'] != inputs.projected_execution.loc[dates[4], 'Close'])

row_D = dates[8]
for prior, last, first, expected_state in [(10., 12., 10., False), (12., 11., 10., True), (10., 10., 10., True)]:
    market = inputs.source_market.copy(deep=True)
    i = market.index.get_loc(row_D)
    market.loc[dates[i - 5], 'Close'] = first
    market.loc[dates[i - 1], 'Close'] = prior
    market.loc[row_D, 'Close'] = last
    current = replace(inputs, source_market=market)
    state = K.state_at_D(current, str(row_D.date()))
    check('S2 fixed <= ratio definition ' + str((prior, last, first)), state['NON_FINAL_DAY_DOMINATED'] is expected_state)
    check('S2 raw r1 expression ' + str(last), state['r1_log'] == float(np.log(last / prior)))
    check('S2 raw r4 expression ' + str(first), state['r4_log'] == float(np.log(prior / first)))
    market.loc[market.index > row_D, 'Close'] *= 19
    check('S2 future perturbation inert ' + str(last), K.state_at_D(replace(current, source_market=market), str(row_D.date())) == state)

feature = inputs.source_features.copy(deep=True)
feature.loc[row_D, 'ma20_prior'] = float('nan')
check('S1 unknown explicit', K.state_at_D(replace(inputs, source_features=feature), str(row_D.date()))['PRIOR_TREND_ESTABLISHED'] is None)
feature.loc[row_D, 'ma20_prior'] = feature.loc[row_D, 'ma20_prior_lag5']
check('S1 strict slope equality false', K.state_at_D(replace(inputs, source_features=feature), str(row_D.date()))['PRIOR_TREND_ESTABLISHED'] is False)

changed = inputs.source_features.copy(deep=True)
changed.loc[dates[6], 'support_floor'] = 1000
support_exit = K.simulate(seed, replace(inputs, source_features=changed), K.Action.OFF_LOCAL_CYCLE)
check('OFF support after ON closed rebuilt locally', support_exit['exit_E'] == str(dates[7].date()) and support_exit['trace'][-1]['ordinary_support_exit'])
changed = inputs.source_features.copy(deep=True)
market = inputs.source_market.copy(deep=True)
market.loc[dates[6], 'Close'] = 50.
loss = seed.runtime_entry_price * 1.001 - 50. * .999
changed.loc[dates[6], 'atr20_prior'] = loss
cost_exit = K.simulate(seed, replace(inputs, source_features=changed, source_market=market), K.Action.OFF_LOCAL_CYCLE)
check('NET cost >= includes exact equality', cost_exit['trace'][-1]['selected_cost_exit'] and cost_exit['exit_E'] == str(dates[7].date()))
status = inputs.trading_status.copy(deep=True)
status.loc[dates[4], 'Status'] = 'SUSPENDED'
pending = K.simulate(seed, replace(inputs, trading_status=status), K.Action.ON)
check('blocked SELL inherits and excludes discretionary SHOCK', pending['trace'][-1]['pending_inherited'] and not pending['trace'][-1]['profit_exit_eligible'])
check('pending intent E follows authoritative clock', all(inputs.clock[r['D']] == r['E'] for r in pending['attempts']))
censored = K.simulate(seed, replace(inputs, cutoff=str(dates[7].date())), K.Action.OFF_LOCAL_CYCLE)
check('right censor not forced exit', censored['status'] == 'CENSORED' and K.label(seed, on['exit_price_ledger'], on['exit_fee'], censored)['advantage'] is None)

label = K.label(seed, on['exit_price_ledger'], on['exit_fee'], off)
numerator = off['exit_price_ledger'] * seed.quantity - off['exit_fee'] - (on['exit_price_ledger'] * seed.quantity - on['exit_fee'])
check('strict total proceeds normalized total cost', label['advantage'] == numerator / (seed.ledger_entry_price * seed.quantity + seed.actual_buy_fee))
check('equivalent actual sign', label['sign'] == (1 if numerator > 0 else -1 if numerator < 0 else 0))
same = dict(off, exit_price_ledger=on['exit_price_ledger'], exit_fee=on['exit_fee'])
check('ties exact no epsilon', K.label(seed, on['exit_price_ledger'], on['exit_fee'], same)['sign'] == 0)

for bad in (float('inf'), float('-inf'), float('nan'), 0., -1.):
    market = inputs.source_market.copy(deep=True)
    market.loc[row_D, 'Close'] = bad
    check('nonfinite or nonpositive S2 unknown ' + str(bad), K.state_at_D(replace(inputs, source_market=market), str(row_D.date()))['NON_FINAL_DAY_DOMINATED'] is None)
market = inputs.source_market.copy(deep=True)
i = market.index.get_loc(row_D)
market.loc[row_D, 'Close'] = 1e308
market.loc[dates[i-1], 'Close'] = 1e-308
check('finite operands overflow ratio unknown', K.state_at_D(replace(inputs, source_market=market), str(row_D.date()))['NON_FINAL_DAY_DOMINATED'] is None)

for path in ('method_decision.json', 'method_state_boundary_clarification.json',
             'execution_precision_clarification.json', 'review/locked_method_review.json',
             'review/locked_method_semantics_addendum.json', 'review/source_kernel_finite_boundary_notice.json', 'review/source_kernel_review.json'):
    rel = (BASE / path).as_posix()
    expected[rel] = digest(rel)
expected[Path(__file__).resolve().relative_to(ROOT).as_posix()] = digest(Path(__file__).resolve().relative_to(ROOT))
result = {
    'status': 'PASS_KERNEL_READER_REVIEW_PENDING_RUNNER_LOCK',
    'blocking_findings': [], 'reviewed_hashes': expected, 'supersedes_prelock_review': 'review/source_kernel_review.json', 'finite_boundary_resolved': True,
    'synthetic_checks_count': len(CHECKS), 'synthetic_checks': CHECKS,
    'manual_reader_findings': [
        'Original account hash/result and independent population binding authenticated; explicit originalPreparedDataRef only, emptyProviderConfig and network denial. No prepare/evaluate/export.',
        'Source runtime market/raw/limits/status and projected account execution inputs remain separate; original runtime BUY basis authenticated using public resolver in original operation order.',
        'Original causal_features reused, support uses original in-window shifted5close floor. No original future held/exit/pause data supplied to simulator after seeding.',
        'Own local pending/cost/age/deadline/grace and first-SHOCK latch; originalabsolute entry+9 deadline and entry+10 reservation; no reentry or post-sale close.',
        'Original public SELL resolver preserves trigger/filled_at/time_precision. No OPEN-only shortcut or extra epsilon. Label uses actual Q and entry fee denominator.',
    ],
    'pending_gates': [
        'Final runner/design/source lock review must enforce exactly21 ON first, no alternate computation before independent A+B controls PASS.',
        'Reader future real identities and all21 ON exact unit/order/fee/control verification remain unexecuted by this review.',
        'Output fields must distinguish original_actual observations from alternative_POSTHOC modeled fills; local labels are not funded returns.',
    ],
    'real_prepared_fetches': 0, 'real_state_values': 0, 'real_ON_controls': 0,
    'real_OFF_labels': 0, 'new_funded_accounts': 0, 'new_market_calls': 0,
}
out = ROOT / BASE / 'review/source_kernel_review_v2.json'
with out.open('x', encoding='utf-8', newline='\n') as handle:
    json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
    handle.write('\n')
print(json.dumps({'status': result['status'], 'checks': len(CHECKS), 'path': out.relative_to(ROOT).as_posix(), 'sha256': digest(out.relative_to(ROOT))}))
