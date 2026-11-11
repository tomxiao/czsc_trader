"""Ledger arithmetic copied from EX047; fee contract explicit, performance formulas unchanged.
Original source SHA256: 1732a74f5e0ea3c40d32216995e875080f016656f9a311e911490e14ae811229.
"""
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path
import sys
import numpy as np

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
sys.path.insert(0,str(ROOT/'research/S019/experiments/EX013_20261110/src'))
from runner import metrics, read_account  # noqa: E402

def ledger(work, row, spec):
    ref, payload = read_account(work/spec['account_path'])
    assert ref.to_dict() == row['account_ref']
    request = payload['request']
    assert request['content_sha256'] == row['content_hash']
    assert request['candidate_definition'] == row['definition']
    assert request['initial_cash'] == 100000. and request['drawdown_basis'] == 'SESSION_CLOSE'
    fee = spec['fee_rate']
    assert fee in (.001,.002)
    assert request['fee_rate'] == fee
    assert request['scenario_id'] == ('STANDARD' if fee == .001 else 'STRESS')
    assert request['window_id'] == 'FULL'
    assert request['measurement_tier'] == ('FORMAL' if fee == .001 else 'STRESS')
    run, bh = payload['runs']['candidate'], payload['runs']['buy_hold']
    full_metrics = metrics(run, bh['metrics']['daily_max_drawdown'])
    allowed = set(full_metrics) if fee == .001 else set(full_metrics)-{'gates','eligible'}
    assert set(row['candidate']) == allowed
    measured = {key:full_metrics[key] for key in allowed}
    assert measured == row['candidate']
    daily = run['account_daily']
    sessions = [x['session'] for x in daily]
    assert len(sessions) == 1212 and sessions[0] == '2022-01-03' and sessions[-1] == '2026-10-30'
    equity = np.asarray([100000., *(x['equity'] for x in daily)], dtype=float)
    dd = 1-equity/np.maximum.accumulate(equity)
    trough = int(np.argmax(dd))
    peak = int(np.argmax(equity[:trough+1]))
    recovery = np.flatnonzero(equity[trough+1:] >= equity[peak])
    dates = ['INITIAL_CASH', *sessions]
    episode = {'peak': dates[peak], 'trough': dates[trough], 'magnitude': float(dd[trough]),
               'recovery': dates[trough+1+int(recovery[0])] if len(recovery) else None,
               'unrecovered_at_sample_end': len(recovery) == 0,
               'sample_end_drawdown_from_running_peak': float(dd[-1])}
    assert abs(episode['magnitude']-measured['drawdown']) < 1e-10
    by_cycle = defaultdict(list)
    for fill in run['fills']:
        by_cycle[fill['cycle_id']].append(fill)
    points = run['account_points']
    times = [p['time'] for p in points]
    assert times == sorted(times)
    closed, all_balances = [], {}
    closed_ids = {t['cycle_id'] for t in run['trades']}
    assert len(closed_ids) == len(run['trades']) and all(t['status'] == 'CLOSED' for t in run['trades'])
    for cid, fs in by_cycle.items():
        all_balances[cid] = sum(f['quantity']*(1 if f['side'] == 'BUY' else -1) for f in fs)
        assert all_balances[cid] >= 0
    for trade in run['trades']:
        cid = trade['cycle_id']
        fills = sorted(by_cycle[cid], key=lambda f: f['executed_at'])
        assert fills and fills[0]['side'] == 'BUY' and fills[-1]['side'] == 'SELL'
        assert all_balances[cid] == 0
        entry, exit_at = fills[0]['executed_at'], fills[-1]['executed_at']
        index = bisect_right(times, entry)-1
        capital = points[index]['equity'] if index >= 0 else 100000.
        assert capital > 0
        closed.append({'cycle_id': cid, 'entry_at': entry, 'exit_at': exit_at,
                       'entry_equity': capital, 'net_pnl': trade['net_pnl'],
                       'net_return': trade['net_return'],
                       'pnl_over_entry_equity': trade['net_pnl']/capital,
                       'fees_over_entry_equity': sum(f['fees'] for f in fills)/capital,
                       'gross_turnover_over_entry_equity': sum(f['quantity']*f['price'] for f in fills)/capital,
                       'actual_fill_count': len(fills)})
    open_ids = set(by_cycle)-closed_ids
    assert all(all_balances[cid] > 0 for cid in open_ids)
    terminal = points[-1]
    assert sum(all_balances.values()) == terminal['quantity']
    assert len(open_ids) == int(terminal['quantity'] > 0)
    if open_ids:
        assert open_ids == {terminal['cycle_id']}
    assert len(closed) == measured['closed_cycles']
    assert len({c['entry_at'] for c in closed}) == len(closed)
    fees = sum(f['fees'] for f in run['fills'])
    assert abs(fees-measured['fees']) < 1e-6
    return {'key': row['label'], 'candidate_id': row['candidate_id'], 'account_ref': ref.to_dict(),
            'metrics': measured, 'annual_returns': measured['year_returns'], 'mdd_episode': episode,
            'execution': {'actual_fills': len(run['fills']), 'buy_fills': sum(f['side']=='BUY' for f in run['fills']),
                          'sell_fills': sum(f['side']=='SELL' for f in run['fills']), 'fees': fees,
                          'gross_turnover': sum(f['quantity']*f['price'] for f in run['fills']),
                          'mean_closed_cycle_fees_over_entry_equity': float(np.mean([c['fees_over_entry_equity'] for c in closed])) if closed else None},
            'terminal': {'equity': terminal['equity'], 'cash': terminal['cash'], 'quantity': terminal['quantity'],
                         'confirmed_open_cycle_count': len(open_ids), 'open_cycle_ids': sorted(open_ids)},
            'largest_closed_losses': sorted([c for c in closed if c['net_pnl'] < 0], key=lambda c: c['pnl_over_entry_equity'])[:5],
            'largest_closed_gains': sorted([c for c in closed if c['net_pnl'] > 0], key=lambda c: -c['pnl_over_entry_equity'])[:5],
            'cycles': closed, 'sessions': sessions, 'daily_returns': (equity[1:]/equity[:-1]-1).tolist()}
