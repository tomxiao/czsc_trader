from collections import Counter
from datetime import datetime,timezone
from statistics import mean,median
from zoneinfo import ZoneInfo
import math
def instant(v): return datetime.fromisoformat(v.replace("Z","+00:00")).astimezone(timezone.utc)
def near(a,b): return math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-6)
def summary(run, initial):
    points, daily, trades = run['account_points'], run['account_daily'], run['trades']
    if len(points) != 22790 or len(daily) != 1760 or any(p['session'] > '2025-12-31' for p in daily):
        raise ValueError('Account population or authorized boundary differs')
    closed = [t for t in trades if t['status'] == 'CLOSED']
    sessions = [row['session'] for row in daily]
    counts = Counter(instant(t['exit_at']).astimezone(ZoneInfo('America/New_York')).date().isoformat() for t in closed)
    rolling = [sum(counts[s] for s in sessions[i-59:i+1]) for i in range(59, len(sessions))]
    peak, maximum, peak_at, trough_at, peak_time = initial, 0., None, None, None
    peak_value = initial
    for point in points:
        if point['equity'] > peak:
            peak, peak_time = point['equity'], point['time']
        loss = 1 - point['equity']/peak
        if loss > maximum:
            maximum, peak_at, trough_at, peak_value = loss, peak_time, point['time'], peak
    recovery = next((p['time'] for p in points if trough_at is not None
        and instant(p['time']) > instant(trough_at) and p['equity'] >= peak_value), None)
    fees = math.fsum(fill['fees'] for fill in run['fills'])
    ending = points[-1]['equity']
    actual = {'annualized_return': (ending/initial)**(252/len(daily))-1,
        'bar_max_drawdown': maximum, 'closed_cycles': len(closed), 'fees': fees,
        'rolling_60_closed_cycle_median': median(rolling), 'total_return': ending/initial-1}
    for field, value in actual.items():
        if not near(value, run['metrics'][field]):
            raise ValueError('Independent metric disagrees: ' + field)
    if rolling != run['metrics']['rolling_60_closed_cycle_counts']:
        raise ValueError('Actual-exit rolling frequency differs')
    positive = sorted((t['net_pnl'] for t in closed if t['net_pnl'] > 0), reverse=True)
    negative = [t['net_pnl'] for t in closed if t['net_pnl'] < 0]
    closed_pnl = math.fsum(t['net_pnl'] for t in closed)
    nonclosed = ending - initial - closed_pnl
    if points[-1]['quantity'] == 0 and not near(nonclosed, 0.):
        raise ValueError('Closed-cycle money does not reconcile to account equity')
    year_returns = {}
    opening = initial
    for year in range(2019, 2026):
        ending_year = [p for p in daily if p['session'].startswith(str(year))][-1]['equity']
        year_returns[str(year)] = ending_year/opening-1
        opening = ending_year
    signal_facts = [{f['key']: f['text'] for f in d['explanation']['basis']} for d in run['decisions']]
    return {**actual, 'ending_equity': ending, 'ending_quantity': points[-1]['quantity'],
        'coverage_at_least_three': mean(n >= 3 for n in rolling), 'frequency_windows': len(rolling),
        'holding_bar_fraction': mean(p['quantity'] > 0 for p in points),
        'mean_invested_equity_fraction': mean(p['quantity']*p['close']/p['equity'] for p in points),
        'year_returns': year_returns,
        'max_drawdown_path': {'peak': peak_at, 'trough': trough_at, 'recovery': recovery},
        'trade_pnl': {'closed_net_pnl': closed_pnl, 'positive_pnl': math.fsum(positive),
            'negative_pnl': math.fsum(negative), 'nonclosed_equity_change': nonclosed,
            'win_rate': mean(t['net_pnl'] > 0 for t in closed) if closed else None,
            'mean_cycle_net_return': mean(t['net_return'] for t in closed) if closed else None,
            'median_cycle_net_return': median(t['net_return'] for t in closed) if closed else None,
            'top_five_positive_pnl_share': math.fsum(positive[:5])/math.fsum(positive) if positive else None},
        'decision_counts': {'entry_signals': sum(f.get('entry_signal') == 'True' for f in signal_facts),
            'held_signals_ignored': sum(f.get('entry_signal') == 'True' and f.get('held') == 'True' for f in signal_facts),
            'flat_signals': sum(f.get('entry_signal') == 'True' and f.get('held') == 'False' for f in signal_facts),
            'buy_fills': sum(f['side'] == 'BUY' for f in run['fills']),
            'unfilled_orders': dict(Counter(o['reason'] for o in run['orders'] if o['status'] != 'FILLED'))}}
