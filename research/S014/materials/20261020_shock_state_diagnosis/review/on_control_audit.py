"""Original ON exact-control plus independent D-known formula audit; no OFF."""
from collections import Counter
from hashlib import sha256
import importlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
BASE = Path('research/S014/materials/20261020_shock_state_diagnosis')
EX = Path('research/S014/experiments/EX049_20261020')
COUNT = 0

def digest(path):
    return sha256((ROOT / path).read_bytes()).hexdigest()

def check(value, name):
    global COUNT
    if not value:
        raise AssertionError(name)
    COUNT += 1

def resolve(value):
    ref = EvidenceRef.from_dict(value)
    path = ref.resolve(ROOT)
    check(digest(path.relative_to(ROOT)) == ref.sha256, 'published byte identity')
    return json.loads(path.read_bytes()), path

on_ref = json.loads((ROOT / EX / 'others/on_controls_ref.json').read_bytes())
original, on_path = resolve(on_ref)
check(on_path.read_bytes() == (ROOT / EX / 'others/on_controls.json').read_bytes(), 'ON immutable local bytes')
lock_ref = json.loads((ROOT / EX / 'protocols/published_lock.json').read_bytes())
lock, lock_path = resolve(lock_ref)
check(lock_path.read_bytes() == (ROOT / EX / 'protocols/execution_lock.json').read_bytes(), 'locked source bytes')
lock_sha = digest(EX / 'protocols/execution_lock.json')
check(lock_sha == '3ce1292b28b7469a2332f268b573861f4f8364b97622d02bf6895c73b0317c90', 'current known lock')
check(original['source_lock_sha256'] == lock_sha, 'ON lock binding')
bindings = {}
for path, value in lock['source_hashes'].items():
    rel = (EX / path).as_posix()
    check(digest(rel) == value, rel)
    bindings[rel] = value
for path, value in lock['external_source_hashes'].items():
    check(digest(path) == value, path)
    bindings[path] = value
account, account_path = resolve(original['origin_actual_account_ref'])
check(account['result_hash'] == 'a3c398bd3f3259bbf8e46a6339a36a8bd83b2ccd924526240b0ca604b0f21bcb', 'original C9461 only')
ledgers = account['runs'][0]['ledgers']
decisions = {str(row['signal_date'])[:10]: row for row in ledgers['decisions']['data']}
selected = [row for row in decisions.values() if row['selected_shock_exit'] == 1]
check(len(selected) == len({row['entry_index'] for row in selected}) == 21, 'full21 first SHOCK cycles')
check([sum(str(row['signal_date']).startswith(str(year)) for row in selected) for year in range(2020, 2027)] == [2, 5, 0, 3, 3, 2, 6], 'original yearly inventory')
check(original['N'] == len(original['rows']) == 21, 'complete ON output')
check({row['origin_actual_event']['D'] for row in original['rows']} == {str(row['signal_date'])[:10] for row in selected}, 'not matched-OFF population')
fills = {row['fill_id']: row for row in ledgers['fills']['data']}
orders = ledgers['orders']['data']
fields = ('target_position', 'held_at_close', 'entry_index', 'deadline_index', 'reservation_index',
          'holding_age', 'pending_inherited', 'deadline_exit', 'profit_exit_eligible', 'shock_condition',
          'selected_shock_exit', 'selected_cost_exit', 'selected_risk_exit', 'ordinary_support_exit',
          'entry_grace_eligible', 'entry_grace_applied', 'support_exit_suppressed', 'support_break',
          'net_profit', 'cost_loss_price', 'exit_pending')
for row in original['rows']:
    event, seed, control = row['origin_actual_event'], row['seed'], row['original_ON_MODELLED_control']
    buy = fills[event['actual_entry_fill_id']]
    sell = fills[event['actual_exit_fill_id']]
    check(buy['side'] == 'BUY' and sell['side'] == 'SELL', 'observed fill roles')
    check(seed['quantity'] == buy['quantity'] == sell['quantity'] == control['quantity'], 'original fixed funded Q')
    check(seed['ledger_entry_price'] == buy['price'] and seed['actual_buy_fee'] == buy['fees'], 'original entry capital')
    check(seed['entry_E'] == str(buy['fill_time'])[:10] and seed['first_shock_D'] == event['D'], 'original event dates')
    check(seed['deadline_index'] == seed['entry_index'] + 9 and seed['reservation_index'] == seed['entry_index'] + 10, 'original absolute anchors')
    check(control['status'] == 'CLOSED' and control['exit_E'] == str(sell['fill_time'])[:10], 'observed ON exit')
    for output, field in (('exit_price_ledger', 'price'), ('exit_fee', 'fees'), ('exit_trigger', 'trigger'), ('exit_time_precision', 'time_precision')):
        check(control[output] == sell[field], output)
    check(pd.Timestamp(control['exit_fill_time']) == pd.Timestamp(sell['fill_time']), 'original fill timestamp')
    check(not control['post_sale_close_evaluated'], 'no next opportunity on SELL Eclose')
    days = sorted(day for day in decisions if seed['entry_E'] <= day < control['exit_E'])
    check([trace['D'] for trace in control['trace']] == days, 'full held interval through exit instruction')
    for trace in control['trace']:
        actual = decisions[trace['D']]
        check(trace['valid_E'] == str(actual['valid_session'])[:10], 'D->E')
        for field in fields:
            check(trace[field] == actual[field], field)
        check(trace['shock_disable_latched'] is False, 'ON cannot latch suppression')
    cycle_orders = sorted([order for order in orders if order['cycle_id'] == seed['cycle_id'] and order['side'] == 'SELL'], key=lambda order: order['execution_date'])
    check(len(cycle_orders) == len(control['attempts']), 'all SELL attempts')
    for attempt, order in zip(control['attempts'], cycle_orders, strict=True):
        check(attempt['D'] == str(order['signal_date'])[:10] and attempt['E'] == str(order['execution_date'])[:10], 'order link D/E')
        check(attempt['quantity'] == order['quantity'], 'SELL attempted Q')
        matched = [fill for fill in fills.values() if fill['order_id'] == order['order_id']]
        check(attempt['filled'] == bool(matched), 'filled/blocked exact')

# Reuse audited authenticated prepared-only reader; independently derive state formulas.
# No simulator, label or OFF result is called/read here; raw data remains memory-only.
sys.path.insert(0, str(ROOT / EX / 'src'))
reader = importlib.import_module('prepared_reader')
_, same_account, binding = reader.identities()
check(same_account == account, 'reader original identity')
inputs, manifest = reader.fetch_inputs(account, binding)
check(manifest == original['prepared_content_identities'], 'same prepared content identities')
close = inputs.source_market.Close
masked = close.where(close.index >= pd.Timestamp('2020-01-02'))
ma = masked.shift(1).rolling(20, min_periods=20).mean()
lag = ma.shift(5)
state_counts = {'PRIOR_TREND_ESTABLISHED': Counter(), 'NON_FINAL_DAY_DOMINATED': Counter()}
for row in original['rows']:
    day = pd.Timestamp(row['origin_actual_event']['D'])
    i = close.index.get_loc(day)
    current, prior, first = float(close.iloc[i]), float(close.iloc[i-1]), float(close.iloc[i-5])
    m, lagged = float(ma.loc[day]), float(lag.loc[day])
    trend = bool(m > lagged and prior >= m) if all(np.isfinite(value) for value in (m, lagged, prior)) else None
    r1 = float(np.log(current / prior))
    r4 = float(np.log(prior / first))
    shape = bool(r1 <= r4) if np.isfinite(r1) and np.isfinite(r4) else None
    state = row['D_known_states']
    for key, expected in {'PRIOR_TREND_ESTABLISHED': trend, 'NON_FINAL_DAY_DOMINATED': shape,
                          'r1_log': r1, 'r4_log': r4, 'r1_positive': r1 > 0,
                          'prior_close_RUNTIME_HFQ': prior, 'ma20_prior_RUNTIME_HFQ': m,
                          'ma20_prior_lag5_RUNTIME_HFQ': lagged}.items():
        check(state[key] == expected, 'independent D-known formula ' + key)
    for key in state_counts:
        state_counts[key][str(state[key])] += 1
    check(int(float(row['origin_actual_event']['holding_age_D'])) == i - row['seed']['entry_index'], 'original age index')
    check(int(float(row['origin_actual_event']['remaining_D_sessions_to_deadline'])) == row['seed']['deadline_index'] - i, 'original remaining horizon')

for path in (EX / 'protocols/execution_lock.json', EX / 'protocols/published_lock.json',
             EX / 'others/on_controls.json', EX / 'others/on_controls_ref.json',
             account_path.relative_to(ROOT), on_path.relative_to(ROOT)):
    bindings[path.as_posix()] = digest(path)
bindings[Path(__file__).resolve().relative_to(ROOT).as_posix()] = digest(Path(__file__).resolve().relative_to(ROOT))
result = {
    'status': 'PASS', 'reviewer': 'B', 'blocking_findings': [],
    'source_lock_sha256': lock_sha, 'ON_ref': on_ref, 'reviewed_hashes': bindings,
    'checks_count': COUNT, 'original_actual_cycles': 21,
    'annual_population_2020_2026': [2, 5, 0, 3, 3, 2, 6],
    'D_known_state_inventory': {key: dict(value) for key, value in state_counts.items()},
    'review': 'All21 local ON controls match original actual C9461 entry capital/Q, each held D target/exit/cost/profit/grace/pending state, original SELL attempt and final price/fee/trigger/time precision. D-known states independently derive from original source closes with original in-window MA masks and declared exact log ratios. No after-sale fullaccount decisions or new opportunities compared.',
    'release_scope': 'With A current-lock/full-ON-ref PASS, allow only frozen OFF local-cycle counterfactual labels. Modelled alternative fills are not funded trades or policy returns.',
    'prepared_only_fetches': 8, 'new_market_calls': 0, 'new_OFF_labels': 0,
    'new_funded_accounts': 0, 'new_fits': 0,
}
out = ROOT / BASE / 'review/on_control_review.json'
with out.open('x', encoding='utf-8', newline='\n') as handle:
    json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
    handle.write('\n')
print(json.dumps({'status': result['status'], 'checks': COUNT, 'path': out.relative_to(ROOT).as_posix(), 'sha256': digest(out.relative_to(ROOT))}))
