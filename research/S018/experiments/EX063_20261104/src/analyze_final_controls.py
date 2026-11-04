"""Read-only exact controls and actual exit-margin effects for EX063."""
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader import research_tools as d
from czsc_trader.research_tools.equity_replay import materialize_equity

ROOT = Path.cwd()
EXPERIMENT = Path(__file__).resolve().parent.parent


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def load(record):
    ref = d.EvidenceRef.from_dict(record['account_ref'])
    path = ref.resolve(ROOT)
    data = path.read_bytes()
    assert sha256(data).hexdigest() == ref.sha256

    def artifact(value):
        content = (path.parent / (value['sha256'] + '.json')).read_bytes()
        assert sha256(content).hexdigest() == value['sha256']
        return content

    return materialize_equity(data, artifact).payload['runs']['candidate']


def economics(rows):
    return [{k: v for k, v in row.items() if not k.endswith('_id')} for row in rows]


def cycles(run):
    fills = defaultdict(list)
    for fill in run['fills']:
        fills[fill['cycle_id']].append({k: fill[k] for k in
            ('interval_start', 'interval_end', 'side', 'price', 'quantity', 'fees')})
    assert all(t['status'] == 'CLOSED' for t in run['trades'])
    assert run['account_daily'][-1]['quantity'] == 0
    return {t['entry_at']: dict(trade=t, fills=fills[t['cycle_id']]) for t in run['trades']}


def path(cycle):
    return [(f['interval_start'], f['side'], f['price']) for f in cycle['fills']]


def write(name, value):
    (EXPERIMENT / 'others' / name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def main():
    all_records = read(EXPERIMENT / 'others/results.json')['accounts']
    ids = ['C9301', 'C9380', 'C9381', 'C9387']
    records = {c: all_records[c] for c in ids}
    records['C8214'] = read(ROOT / 'research/S018/experiments/EX052_20261104/others/results.json')['accounts']['C8214']
    runs = {c: load(r) for c, r in records.items()}
    controls = []
    for left, right in [('C9387', 'C8214'), ('C9380', 'C9381')]:
        fields = {field: economics(runs[left][field]) == economics(runs[right][field])
            for field in ('fills', 'account_daily', 'trades', 'actions')}
        metrics = records[left]['candidate'] == records[right]['candidate']
        assert all(fields.values()) and metrics, (left, right, fields, metrics)
        controls.append(dict(left=left, right=right, fields_equal=fields, metrics_equal=metrics,
            rows={field: len(runs[left][field]) for field in fields}, status='EXACT_MATCH'))
    write('analysis_final_controls.json', dict(status='PASS', comparisons=controls,
        evidence={c: records[c]['account_ref'] for c in records},
        method='SHA-authenticated formal account materialization. Exact economic row list equality after dropping identity-only _id fields; no numeric rounding or tolerance. Full metric dictionary equality.', account_runs=0))
    baseline, changed = [cycles(runs[c]) for c in ('C9301', 'C9380')]
    left_only = [baseline[e] for e in baseline if e not in changed]
    right_only = [changed[e] for e in changed if e not in baseline]
    path_changes, size_changes, same = [], [], 0
    for entry in baseline.keys() & changed.keys():
        a, b = baseline[entry], changed[entry]
        row = dict(entry_at=entry, original=a, margin=b,
            exit_changed=a['trade']['exit_at'] != b['trade']['exit_at'],
            buy_path_changed=[f for f in path(a) if f[1] == 'BUY'] != [f for f in path(b) if f[1] == 'BUY'],
            net_pnl_delta=b['trade']['net_pnl']-a['trade']['net_pnl'],
            net_return_delta=b['trade']['net_return']-a['trade']['net_return'])
        if path(a) != path(b):
            path_changes.append(row)
        elif a['fills'] != b['fills']:
            size_changes.append(row)
        else:
            same += 1
    path_changes.sort(key=lambda v: v['entry_at'])
    size_changes.sort(key=lambda v: v['entry_at'])
    equity_delta = runs['C9380']['account_daily'][-1]['equity']-runs['C9301']['account_daily'][-1]['equity']
    groups = dict(common_entry_path_changed=sum(v['net_pnl_delta'] for v in path_changes),
        common_entry_path_unchanged=sum(v['net_pnl_delta'] for v in size_changes),
        new_entries=sum(v['trade']['net_pnl'] for v in right_only),
        removed_entries=-sum(v['trade']['net_pnl'] for v in left_only))
    assert abs(equity_delta-sum(groups.values())) < 1e-6
    result = dict(status='PASS', accounts={c: dict(config=records[c]['config'],
        metrics=records[c]['candidate'], account_ref=records[c]['account_ref']) for c in ('C9301', 'C9380')},
        counts=dict(original_cycles=len(baseline), margin_cycles=len(changed),
            removed_entries=len(left_only), new_entries=len(right_only),
            common_entry_changed_execution_path=len(path_changes),
            common_entry_only_size_fee_changes=len(size_changes), exact_unchanged_cycles=same,
            original_successful_adds=sum(sum(f['side']=='BUY' for f in v['fills'])-1 for v in baseline.values()),
            margin_successful_adds=sum(sum(f['side']=='BUY' for f in v['fills'])-1 for v in changed.values())),
        final_equity_delta=equity_delta, net_pnl_delta_by_actual_path_group=groups,
        changed_execution_paths=path_changes, same_path_size_changes=size_changes,
        removed_entry_cycles=left_only, new_entry_cycles=right_only,
        interpretation='Actual ledger comparisons only. Groups reconcile final wealth exactly but include downstream reinvestment and integer sizing, so grouped PnL is not an isolated causal counterfactual. Earlier exit may enable later entries. Terminal positions are zero in both accounts.', account_runs=0)
    write('analysis_exit_margin_effect.json', result)
    print(json.dumps(dict(controls=controls, counts=result['counts'], final_equity_delta=equity_delta, pnl_groups=groups), ensure_ascii=False, indent=2))
    for row in path_changes:
        print(row['entry_at'], 'original', path(row['original']), 'margin', path(row['margin']), 'pnl_delta', row['net_pnl_delta'])
    for row in right_only:
        print('NEW_ENTRY', row['trade'], row['fills'])
    for row in left_only:
        print('REMOVED_ENTRY', row['trade'], row['fills'])


if __name__ == '__main__':
    main()
