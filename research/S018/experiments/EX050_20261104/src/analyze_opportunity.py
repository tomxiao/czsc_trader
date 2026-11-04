"""Read-only C7502 opportunity conversion audit from immutable formal account."""
import importlib.util
import json
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path.cwd()
loader = importlib.util.spec_from_file_location('exits', ROOT/'research/S018/experiments/EX047_20261104/src/analyze_exits.py')
module = importlib.util.module_from_spec(loader)
loader.loader.exec_module(module)
record, run, closed = module.load('EX045_20261104', 'C7502')
orders = {}
for order in run['orders']:
    orders.setdefault(order['decision_id'], []).append(order)
rows = []
previous_quantity = 0
daily = {x['decision_id']: x for x in run['account_daily']}
for decision in run['decisions']:
    facts = {x['key']: x['text'] for x in decision['explanation']['basis']}
    signal = facts['observed_signal'] == 'True'
    own_orders = orders.get(decision['decision_id'], [])
    buys = [x for x in own_orders if x['side'] == 'BUY']
    sells = [x for x in own_orders if x['side'] == 'SELL']
    if signal:
        if previous_quantity > 0:
            classification = 'held_exit' if sells else 'held_continue'
        elif buys:
            classification = 'flat_filled' if buys[0]['status'] == 'FILLED' else 'flat_unfilled'
        else:
            classification = 'flat_no_order'
    else:
        classification = 'no_signal'
    row = dict(session=decision['execution_start'][:10], observed_date=decision['observed_through'][:10],
        signal=signal, previous_quantity=previous_quantity, classification=classification,
        orders=[{k:x[k] for k in ('side','status','reason','limit_price')} for x in own_orders])
    rows.append(row)
    previous_quantity = daily[decision['decision_id']]['quantity']

counts = run['metrics']['rolling_60_closed_cycle_counts']
assert len(counts) == len(rows) - 59
exits = Counter(x['exit_at'][:10] for x in run['trades'] if x['status'] == 'CLOSED')
windows = []
for i in range(59, len(rows)):
    window = rows[i-59:i+1]
    actual = sum(exits[x['session']] for x in window)
    assert actual == counts[i-59]
    classes = Counter(x['classification'] for x in window if x['signal'])
    windows.append(dict(start=window[0]['session'], end=window[-1]['session'],
        signals=sum(x['signal'] for x in window), closed=actual, **dict(classes)))

all_classes = Counter(x['classification'] for x in rows if x['signal'])
signals = [x['signals'] for x in windows]
signal_runs = []
streak = []
for row in rows + [dict(signal=False)]:
    if row['signal']:
        streak.append(row['session'])
    elif streak:
        signal_runs.append(dict(start=streak[0], end=streak[-1], length=len(streak)))
        streak = []

def summary(window_set):
    return dict(windows=len(window_set), signal_median=float(np.median([x['signals'] for x in window_set])),
        closed_median=float(np.median([x['closed'] for x in window_set])),
        signal_below_three=sum(x['signals'] < 3 for x in window_set),
        signal_at_least_six=sum(x['signals'] >= 6 for x in window_set),
        held_signal_median=float(np.median([x.get('held_continue', 0)+x.get('held_exit', 0) for x in window_set])))

output = dict(candidate='C7502', account_ref=record['account_ref'],
    definitions=['Signal counted on execution session and computed from previous completed daily observations.',
        'Flat/held uses previous execution session closing actual quantity; no intraday adjustments inferred.',
        'Held exit means an entry-eligible observation coincides with an already held account issuing an exit.',
        'Rolling windows align exactly to published account closed-cycle windows; observed signal windows use the same execution-session alignment.',
        'Signal counts include overlap and do not imply feasible independent round trips.'],
    decisions=len(rows), signals=sum(x['signal'] for x in rows), classification=dict(all_classes),
    unfilled_reasons=dict(Counter(x['orders'][0]['reason'] for x in rows if x['classification']=='flat_unfilled')),
    signal_runs=len(signal_runs), signal_run_lengths=dict(Counter(x['length'] for x in signal_runs)),
    windows=summary(windows), frequency_fail_windows=summary([x for x in windows if x['closed'] < 3]),
    median_fail_windows=summary([x for x in windows if x['closed'] < 6]),
    signal_coverage_three=sum(x>=3 for x in signals)/len(signals),
    signal_coverage_six=sum(x>=6 for x in signals)/len(signals),
    closed_coverage_three=sum(x['closed']>=3 for x in windows)/len(windows),
    lowest_closed_windows=sorted(windows, key=lambda x:(x['closed'],x['signals']))[:15],
    per_year={year:dict(Counter(x['classification'] for x in rows if x['signal'] and x['session'].startswith(year))) for year in ('2023','2024','2025','2026')},
    signal_details=[x for x in rows if x['signal']], rolling_details=windows)
path = Path(__file__).resolve().parents[1]/'others/analysis_opportunity.json'
path.write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps({k:v for k,v in output.items() if k not in ('signal_details','rolling_details')}, ensure_ascii=False, indent=2))
