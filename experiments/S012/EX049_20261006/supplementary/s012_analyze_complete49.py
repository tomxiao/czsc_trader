from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from research_experiment import load_experiment_input

root = Path.cwd()
exp = root / 'experiments/S012/EX049_20261006'
rex = exp / 'artifacts/rex'
receipt_path = rex / 'execution_receipt.json'
receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
load_experiment_input(rex, expected_receipt_sha256=receipt['receipt_sha256'])
search_path = rex / 'search.json'
search = json.loads(search_path.read_text(encoding='utf-8'))
rows = search['proposals']
assert len(rows) == 1040 and all(row['status'] == 'COMPLETE' for row in rows)
assert len({row['proposal_id'] for row in rows}) == len({row['parameter_sha256'] for row in rows}) == 1040
assert {row['trial_number'] for row in rows} == set(range(1040))
assert not receipt['trace']['evaluations']
checks = 0
for row in rows:
    references = [row['raw_summary'], *row['raw_ledgers'].values()]
    for ref in references:
        path = (rex / ref['path']).resolve()
        path.relative_to(rex.resolve())
        assert sha256(path.read_bytes()).hexdigest() == ref['sha256'], path
        checks += 1
    assert row['candidate'] is None
    metrics = row['metrics']
    assert metrics['evaluation_sessions'] == 1534 and metrics['frequency_denominator'] == 1535
    assert metrics['frequency'] == metrics['closed_trades'] * 60 / 1535
    assert row['passed_all'] == (metrics['net_cagr'] >= 1.5 * metrics['benchmark']['cagr']
        and abs(metrics['max_drawdown']) < abs(metrics['benchmark']['max_drawdown'])
        and metrics['frequency'] >= 5)
ranking = sorted(rows, key=lambda row: (-row['metrics']['net_cagr'],
                 abs(row['metrics']['max_drawdown']), -row['metrics']['frequency'], row['proposal_id']))
feasible = [row for row in ranking if row['metrics']['frequency'] >= 5 and
            abs(row['metrics']['max_drawdown']) < abs(row['metrics']['benchmark']['max_drawdown'])]
assert search['frontier']['rank_primary'] == [row['proposal_id'] for row in ranking]
selected = [ranking[0]]
if feasible and feasible[0]['proposal_id'] != ranking[0]['proposal_id']:
    selected.append(feasible[0])
result = {'schema_version': 1, 'experiment_id': exp.name,
          'receipt_sha256': receipt['receipt_sha256'],
          'raw_search': {'path': search_path.relative_to(root).as_posix(),
                         'sha256': sha256(search_path.read_bytes()).hexdigest()},
          'unique_parameter_count': len({row['parameter_sha256'] for row in rows}),
          'unique_trade_behavior_count': len({row['behavior_sha256'] for row in rows}),
          'unique_signal_policy_count': len({row['signal_policy_sha256'] for row in rows}),
          'status_counts': dict(Counter(row['status'] for row in rows)),
          'verified_raw_files': checks,
          'qualified': [row['proposal_id'] for row in ranking if row['passed_all']],
          'best_return': ranking[0], 'best_frequency_drawdown_feasible': feasible[0] if feasible else None,
          'selected_for_actual_full': selected,
          'selection_reason': 'Retain return-priority first and highest-return simultaneous drawdown/frequency feasible frontier; both need actual FULL. This grid is a checkpoint, not stage-three closure.',
          'stage_three_complete': False, 'all_window_seen': True}
output = root / '.tmp/s012-stage3-native-20261006/complete49_analysis.json'
output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({key: result[key] for key in ('experiment_id', 'receipt_sha256', 'unique_parameter_count',
    'unique_trade_behavior_count', 'unique_signal_policy_count', 'status_counts', 'verified_raw_files', 'qualified')}))
for row in selected:
    print(json.dumps({'selected': row['proposal_id'], 'parameters': row['parameters'], 'metrics': row['metrics']}))
