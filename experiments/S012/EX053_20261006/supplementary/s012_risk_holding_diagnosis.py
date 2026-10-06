"""Read existing ledger/state intersections; descriptive, no shadow portfolio or account run."""
from collections import defaultdict
import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
from research_experiment import load_experiment_input

root = Path.cwd()
task = root / '.tmp/s012-stage3-native-20261006'
read = lambda path: json.loads(path.read_text(encoding='utf-8'))
def ref(path):
    return {'path': path.relative_to(root).as_posix(), 'sha256': sha256(path.read_bytes()).hexdigest()}
features_path = root / 'experiments/S012/EX050_20261006/strategy_runtime/resources/features.csv'
assert ref(features_path)['sha256'] == '8ed38c5eb10fd15d112500b90b8871403554b41a77a9f1d71c9e897b24864192'
with features_path.open(encoding='utf-8', newline='') as stream:
    features = {row['Date']: row for row in csv.DictReader(stream)}
groups, evidence = [], [ref(features_path)]
parser = argparse.ArgumentParser()
parser.add_argument('--baseline-only', action='store_true')
args = parser.parse_args()
controls = [('EX050_20261006', 'C4603'), ('EX052_20261006', 'C4704')]
if not args.baseline_only:
    controls += [('EX053_20261006', 'C4800'), ('EX053_20261006', 'C4801')]
for eid, cid in controls:
    rex = root / 'experiments/S012' / eid / 'artifacts/rex'
    receipt = read(rex / 'execution_receipt.json')
    load_experiment_input(rex, expected_receipt_sha256=receipt['receipt_sha256'])
    trial = next(row for row in read(rex / 'trials.json') if row['candidate_id'] == cid)
    assert trial['record']['status'] == 'SUCCEEDED'
    item = trial['record']['result_artifact']
    path = rex / item['path']
    assert ref(path)['sha256'] == item['sha256']
    run = read(path)['runs'][0]
    account = run['ledgers']['account_daily']['data']
    decisions = run['ledgers']['decisions']['data']
    assert len(account) == len(decisions) == 1534
    fills = {row['fill_time'][:10] for row in run['ledgers']['fills']['data']}
    gate_rows = []
    for gate in ('vol', 'kurt'):
        bins = defaultdict(lambda: {'sessions': 0, 'sum_account_net_daily_return': 0., 'equity_increment': 0., 'loss_sessions': 0})
        exit_events = []
        for index, (row, decision) in enumerate(zip(account, decisions)):
            assert row['signal_date'] == decision['signal_date']
            f = features[row['signal_date'][:10]]
            state = 'UNKNOWN' if f[gate+'_valid'] == '0' else 'KNOWN_HIGH' if f[gate+'_high'] == '1' else 'KNOWN_LOW'
            if row['quantity_before'] <= 0 or index == 0:
                continue
            if state == 'KNOWN_HIGH' and decision['planned_target'] > 0:
                # Intraday execution has not yet occurred at the prior T17 signal.
                exit_events.append({'signal_date': row['signal_date'][:10], 'execution_date': row['date'][:10],
                    'planned_age': decision['planned_age'], 'actual_quantity_before': row['quantity_before']})
            if row['date'][:10] in fills:
                continue
            prior_equity = account[index-1]['equity']
            daily_return = row['equity']/prior_equity-1
            b = bins[state]
            b['sessions'] += 1
            b['sum_account_net_daily_return'] += daily_return
            b['equity_increment'] += row['equity']-prior_equity
            b['loss_sessions'] += daily_return < 0
        for b in bins.values():
            b['average_account_net_daily_return'] = b['sum_account_net_daily_return']/b['sessions']
        gate_rows.append({'gate': gate, 'held_no_fill_session_bins': dict(bins),
            'causal_high_state_while_actual_held_and_plan_continues': len(exit_events), 'events': exit_events})
    groups.append({'experiment_id': eid, 'candidate_id': cid, 'parameters': trial['parameters'], 'metrics': trial['metrics'], 'risk_states': gate_rows})
    evidence.append(ref(path))
target = task / ('risk_holding_baseline_diagnosis.json' if args.baseline_only else 'risk_holding_diagnosis.json')
with target.open('x', encoding='utf-8', newline='\n') as stream:
    json.dump({'status': 'PASS', 'groups': groups, 'evidence': evidence, 'new_accounts': 0,
        'interpretation': 'Observed full-development-pool association only. Existing account returns on held/no-fill sessions grouped by prior causal state; not an exit backtest, not a reconstructed portfolio, not a new economic acceptance gate.',
        'selection_disclosed': True}, stream, ensure_ascii=False, indent=2, allow_nan=False)
    stream.write('\n')
print(json.dumps({'status': 'PASS', 'groups': len(groups), 'output': ref(target)}))
