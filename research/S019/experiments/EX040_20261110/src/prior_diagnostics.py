"""Read-only path comparison of five existing S019 accounts; no replay."""
from pathlib import Path
import sys
import json
from hashlib import sha256
from collections import Counter
from time import perf_counter

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
PRIOR = WORK.parent / 'EX039_20261110'
sys.path.insert(0, str(WORK.parent / 'EX013_20261110/src'))
from runner import read_account, metrics  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def analyze(path, params):
    ref, payload = read_account(path)
    run = payload['runs']['candidate']
    daily = pd.DataFrame(run['account_daily'])
    equity = daily.equity.to_numpy()
    returns = equity / np.r_[100000., equity[:-1]] - 1
    dd = 1 - equity / np.maximum.accumulate(np.r_[100000., equity])[1:]
    trough = int(np.argmax(dd))
    peak = int(np.argmax(equity[:trough + 1]))
    recovered = np.flatnonzero(equity[trough + 1:] >= equity[peak])
    mdd = {'peak': daily.session.iloc[peak], 'trough': daily.session.iloc[trough],
           'recovery': daily.session.iloc[trough + 1 + int(recovered[0])] if len(recovered) else None,
           'magnitude': float(dd[trough])}
    decisions = {d['decision_id']: d for d in run['decisions']}
    orders = {o['order_id']: o for o in run['orders']}
    points = pd.DataFrame(run['account_points'])
    cycles = []
    for trade in run['trades']:
        if trade['status'] != 'CLOSED':
            continue
        fills = sorted([f for f in run['fills'] if f['cycle_id'] == trade['cycle_id']], key=lambda f: f['executed_at'])
        assert fills and fills[0]['side'] == 'BUY' and fills[-1]['side'] == 'SELL'
        entry, exit_ = fills[0]['executed_at'], fills[-1]['executed_at']
        decision = decisions[orders[fills[-1]['order_id']]['decision_id']]
        facts = {x['key']: x['text'] for x in decision['explanation']['basis']}
        prior = points.loc[points.time <= entry, 'equity']
        capital = float(prior.iloc[-1]) if len(prior) else 100000.
        cycles.append({**trade, 'recorded_entry_at': trade['entry_at'], 'recorded_exit_at': trade['exit_at'],
                       'entry_at': entry, 'exit_at': exit_, 'exit_order_id': fills[-1]['order_id'],
                       'entry_account_equity': capital,
                       'pnl_over_entry_equity': trade['net_pnl'] / capital,
                       'exit_reason': decision['explanation']['judgment'],
                       'exit_facts': facts})
    assert len(cycles) == run['metrics']['closed_cycles']
    yearly = {}
    for year, indices in daily.groupby(daily.session.str[:4]).groups.items():
        idx = np.asarray(list(indices))
        yearly[year] = {'return': float(np.prod(1 + returns[idx]) - 1),
                        'log_growth': float(np.log1p(returns[idx]).sum())}
    return {'reference': ref.to_dict(), 'parameters': params,
            'metrics': metrics(run, payload['runs']['buy_hold']['metrics']['daily_max_drawdown']),
            'mdd_episode': mdd, 'yearly': yearly, 'cycles': cycles,
            'exit_reason_counts': dict(Counter(x['exit_reason'] for x in cycles)),
            'sessions': daily.session.tolist(), 'daily_returns': returns.tolist(),
            'target_activity': [[d['execution_start'], float(d['target']) > 0] for d in run['decisions']]}


def compare(left, right):
    assert left['sessions'] == right['sessions']
    a = {c['entry_at']: c for c in left['cycles']}
    b = {c['entry_at']: c for c in right['cycles']}
    common = set(a) & set(b)
    timing = [{'entry_at': k, 'left': a[k], 'right': b[k]} for k in sorted(common) if a[k]['exit_at'] != b[k]['exit_at']]
    contribution = [{'entry_at': k, 'left_exit': a[k]['exit_at'], 'right_exit': b[k]['exit_at'],
                     'normalized_pnl_delta': a[k]['pnl_over_entry_equity'] - b[k]['pnl_over_entry_equity'],
                     'trade_return_delta': a[k]['net_return'] - b[k]['net_return']} for k in common]
    contribution.sort(key=lambda x: abs(x['normalized_pnl_delta']), reverse=True)
    delta = np.log1p(left['daily_returns']) - np.log1p(right['daily_returns'])
    ranked = np.argsort(np.abs(delta))[::-1]
    return {'identical_closed_timing': len(common) == len(a) == len(b) and not timing,
            'common_entries': len(common), 'changed_exit_count': len(timing), 'changed_exits': timing,
            'left_only_entries': [a[k] for k in sorted(set(a)-set(b))],
            'right_only_entries': [b[k] for k in sorted(set(b)-set(a))],
            'activity_state_changes': sum(x != y for x, y in zip(left['target_activity'], right['target_activity'], strict=True)),
            'largest_cycle_contribution_deltas': contribution[:12],
            'log_growth_difference': float(delta.sum()),
            'top10_days_absolute_log_difference_share': float(np.abs(delta[ranked[:10]]).sum()/np.abs(delta).sum()),
            'largest_daily_log_differences': [{'session': left['sessions'][i], 'difference': float(delta[i])} for i in ranked[:10]]}


def main():
    started = perf_counter()
    records = read(PRIOR/'others/account_results.json')['accounts']
    centers = read(PRIOR/'protocols/centers.json')
    c224 = next(c for c in centers if c['id'] == 'C0224')
    params = json.loads(c224['definition']['parameters_json'])
    chosen = [(c['id'], PRIOR/'others'/f"{c['id']}_center_prior_ref.json", json.loads(c['definition']['parameters_json']), c['account_ref']) for c in centers]
    # Shared center reference files are never written: use a task-owned temporary directory.
    scratch = ROOT/'.tmp/s019-stage3-prior'
    scratch.mkdir(parents=True, exist_ok=True)
    chosen = [(cid, scratch/f'{cid}.json', p, ref) for cid, _, p, ref in chosen]
    for cid, path, p, ref in chosen:
        path.write_text(json.dumps(ref), encoding='utf-8')
    for key, row in records.items():
        only_atr = {k:v for k,v in row['parameters'].items() if k != 'trail_atr'} == {k:v for k,v in params.items() if k != 'trail_atr'}
        if row['candidate_id'] == 'C0300' or (row['parent'] == 'C0224' and row['label'] != 'STRESS' and only_atr):
            chosen.append((row['candidate_id'], PRIOR/'others'/f'{key}_account.json', row['parameters'], row['account_ref']))
    assert {x[0] for x in chosen} == {'C0135', 'C0224', 'C0300', 'C0256', 'C0259'}
    accounts = {}
    for cid, path, p, ref in chosen:
        accounts[cid] = analyze(path, p)
        assert accounts[cid]['reference'] == ref
        print('READ', cid, flush=True)
    comparisons = {f'{a}-minus-{b}': compare(accounts[a], accounts[b]) for a,b in
                   [('C0300','C0224'),('C0224','C0135'),('C0256','C0224'),('C0259','C0224')]}
    warm = [{'candidate_id': r['candidate_id'], 'parameters': r['parameters'], 'reference': r['account_ref'],
             'content_hash': r['content_hash'], 'metrics': r['candidate']} for r in records.values()
            if r['parent'] == 'C0224' and r['label'] != 'STRESS']
    warm.append({'candidate_id': 'C0224', 'parameters': params, 'reference': c224['account_ref'],
                 'content_hash': c224['content_hash'], 'metrics': accounts['C0224']['metrics']})
    assert len(warm) == 81 and sum(w['metrics']['eligible'] for w in warm) == 9
    out = {'status': 'COMPLETE', 'new_accounts': 0, 'elapsed_seconds': perf_counter()-started,
           'source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
           'prior_account_results_sha256': sha256((PRIOR/'others/account_results.json').read_bytes()).hexdigest(),
           'accounts': accounts, 'comparisons': comparisons, 'warm_start_observations': warm,
           'limitations': ['Previously seen development sample; descriptive diagnosis.',
                           'Cycle timing uses actual filled entry/exit; share quantities excluded from timing comparisons.',
                           'Normalized cycle PnL divides ledger PnL by entry account equity; descriptive allocation contribution, not isolated causal effect.',
                           'Annual returns are actual calendar-period returns; 2026 ends October 30.',
                           'Daywise log-growth differences are additive; cycle cash PnL is affected by compounding and allocation.']}
    (WORK/'others/prior_diagnostics.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({k:{x:v[x] for x in ['identical_closed_timing','common_entries','changed_exit_count','activity_state_changes','log_growth_difference','top10_days_absolute_log_difference_share']} for k,v in comparisons.items()}))


if __name__ == '__main__':
    main()
