import hashlib
import json
from pathlib import Path

import numpy as np

base = Path('research/S019/experiments/EX039_20261110')
def read(name):
    return json.loads((base / name).read_text(encoding='utf-8'))
def digest(name):
    return hashlib.sha256((base / name).read_bytes()).hexdigest()

done = read('others/statistics_completion.json')
assert done['status'] == 'COMPLETE'
assert done['source_sha256'] == digest('src/statistics_analysis.py')
assert done['protocol_sha256'] == digest('protocols/statistics_protocol.json')
protocol = read('protocols/statistics_protocol.json')
assert protocol['inventory_sha256'] == digest('others/statistics_inventory.json')
inventory = read('others/statistics_inventory.json')
returns = read('others/statistics_returns.json')
members = returns['members']
assert len(members) == len(inventory['rows']) == 236
assert sum(1 + len(r['aliases']) for r in inventory['rows']) == 238
assert len({r['reference']['sha256'] for r in members}) == 236
ref = members[0]
for member in members:
    assert len(member['returns']) == 1212
    assert member['sessions'] == ref['sessions']
    assert member['benchmark_returns'] == ref['benchmark_returns']
    assert np.isfinite(member['returns']).all()
    assert member['protocol_sha256'] == done['protocol_sha256']
for center in read('protocols/centers.json'):
    found, = [m for m in members if m['candidate_id'] == center['id']]
    assert found['reference'] == center['account_ref']
selection = read('others/statistics_selection.json')
assert len(selection['groups']) == 1
s = selection['groups'][0]['result']
assert len(selection['groups'][0]['members']) == 236
assert s['status'] == 'COMPLETE' and s['planned_windows'] == 4
proxy = read('others/statistics_search_bias.json')
assert proxy['actual_nar_gated_adaptive_selection_bias'] == 'NOT_ESTIMATED'
assert len(proxy['groups']) == 1
p = proxy['groups'][0]['diagnostics']['PBO_SHARPE_PROXY']
if p['status'] == 'AVAILABLE':
    assert len(p['splits']) == 252
    assert all(x['validation_candidate_count'] == 236 for x in p['splits'])
bootstrap = read('others/statistics_bootstrap.json')
assert len(bootstrap['comparisons']) == 3
pair = bootstrap['comparisons'][2]
expected = {'cagr': .7714182197458601 - .6302208331124366,
            'max_drawdown': -.1737953661302548 + .12715840410856472,
            'calmar': 4.438658158283136 - 4.956187029324225}
for key, value in expected.items():
    assert abs(pair[key]['point_difference'] - value) < 1e-10
summary = {
    'verification': 'PASSED',
    'checks': ['source/protocol/inventory hash bindings', 'all 238 published accounts represented',
               '236 unique implementations share 1212-session calendar and identical benchmark returns',
               'center account refs exactly match approved centers', 'all 252 Sharpe proxy splits retain 236 candidates',
               'bootstrap point differences match published center metrics'],
    'completion': done,
    'exact_repeats': {r['candidate_id']: [a['candidate_id'] for a in r['aliases']] for r in inventory['rows'] if r['aliases']},
    'selection_summary': {k: v for k, v in s.items() if k not in ('decisions', 'candidates', 'observations')},
    'selection_windows': [{k: v for k, v in w.items() if k != 'checks'} for w in s['decisions']],
    'selection_observations': [{k: v for k, v in w.items() if k != 'checks'} | {
        'failed_targets': [c['target']['target_id'] for c in w['checks'] if c['status'] == 'FAILED']
    } for w in s['observations']],
    'bootstrap_comparisons': bootstrap['comparisons'],
    'sharpe_proxy': {k: ({a: b for a, b in v.items() if a not in ('splits', 'selection_frequency')} if k == 'PBO_SHARPE_PROXY' else v)
                    for k, v in proxy['groups'][0]['diagnostics'].items()},
    'actual_nar_gated_adaptive_selection_bias': 'NOT_ESTIMATED',
    'limitations': protocol['limitations'],
}
(base / 'others/statistics_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps(summary['sharpe_proxy'], ensure_ascii=False))
print('STATISTICS_VERIFICATION_PASSED', done['elapsed_seconds'])
