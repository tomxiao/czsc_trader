"""Describe authenticated EX004 accounts without executing accounts or fetching data.

Intent ages and targets come directly from each published decision ledger.  Cash
flow concentration uses all actual fills in completed cycles, including partial
sells; it does not reconstruct PnL from a single trade entry/exit average.
"""
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[5]
WORK = ROOT / 'research/S015/assets/runs/EX004_20261022/range_weights'
OLD_WORK = ROOT / 'research/S015/assets/runs/EX003_20261021/strategy_study'


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
                    encoding='utf-8', newline='\n')


def load_evidence(row, experiment='EX004_20261022'):
    ref = row['evidence']
    if ref['experiment'] != {'type': 'ExperimentRef', 'strategy_id': 'S015',
                             'experiment_id': experiment}:
        raise ValueError('evidence is outside the declared S015 experiment')
    folder = ROOT / 'research/S015/assets/evidence' / experiment
    path = (folder / ref['evidence_id']).resolve()
    if path.parent != folder.resolve():
        raise ValueError('evidence path escapes its experiment')
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != ref['sha256']:
        raise ValueError(f"evidence bytes changed: {row['candidate_id']}")
    payload = json.loads(raw)
    for key in ('request_hash', 'result_hash', 'input_bindings'):
        if payload[key] != row[key]:
            raise ValueError(f'{key} differs from authenticated evidence')
    if len(payload['runs']) != 1:
        raise ValueError('exactly one standard full-window account is required')
    run = payload['runs'][0]
    if run['candidate_id'] != row['candidate_id'] or run['observation'] != row['observation']:
        raise ValueError('candidate or metrics differ from authenticated account')
    if payload['request_identity']['initial_cash'] != 100000:
        raise ValueError('unexpected initial account cash')
    return run


def table(run, name):
    encoded = run['ledgers'][name]
    return pd.DataFrame(encoded['data'], columns=[f['name'] for f in encoded['schema']['fields']])


def frontier(rows):
    return [r for r in rows if not any(
        s['observation']['net_cagr'] >= r['observation']['net_cagr']
        and abs(s['observation']['max_drawdown']) <= abs(r['observation']['max_drawdown'])
        and (s['observation']['net_cagr'] > r['observation']['net_cagr']
             or abs(s['observation']['max_drawdown']) < abs(r['observation']['max_drawdown']))
        for s in rows)]


def anchor(row):
    p = row['parameters']
    return (float(p['entry']), float(p['exit']), int(p['max_days']))


def anchor_name(key):
    return f'entry={key[0]:g};exit={key[1]:g};max_days={key[2]}'


def details(row, run):
    account, decisions, fills, trades = (table(run, name) for name in
                                         ('account_daily', 'decisions', 'fills', 'trades'))
    account['date'] = pd.to_datetime(account['date'])
    account['signal_date'] = pd.to_datetime(account['signal_date'])
    decisions['valid_session'] = pd.to_datetime(decisions['valid_session'])
    decisions['signal_date'] = pd.to_datetime(decisions['signal_date'])
    if (len(account) != 434 or len(decisions) != 434
            or not account['date'].is_unique or not decisions['valid_session'].is_unique
            or account['date'].iloc[0] != pd.Timestamp('2025-01-02')
            or account['date'].iloc[-1] != pd.Timestamp('2026-10-21')):
        raise ValueError('account/decision development-window identity mismatch')
    decisions = decisions.set_index('valid_session').loc[account['date']].reset_index()
    np.testing.assert_array_equal(decisions.signal_date.to_numpy(), account.signal_date.to_numpy())
    np.testing.assert_array_equal(decisions.target_position.to_numpy(float), account.target_position.to_numpy(float))
    ages = decisions.intent_age.to_numpy(float)
    if not np.isfinite(ages).all() or (ages < 0).any() or (ages != np.floor(ages)).any():
        raise ValueError('invalid published intent ages')
    active = ages > 0
    target = decisions.target_position.to_numpy(float)
    if ((target < 0) | (target > 1)).any() or (target[~active] != 0).any():
        raise ValueError('target is outside its intent or long-only domain')
    # Independently reconstruct ONLY the existing market-intent state transition,
    # never the account. This is independent of target weights and actual fills.
    age = 0
    expected = []
    p = row['parameters']
    for pressure in decisions.pressure.to_numpy(float):
        if age:
            age = 0 if age >= p['max_days'] or pressure >= p['exit'] else age + 1
        elif pressure <= -p['entry']:
            age = 1
        expected.append(age)
    np.testing.assert_array_equal(ages, np.asarray(expected))
    eq = account.equity.to_numpy(float)
    benchmark = pd.DataFrame(run['buyhold']['account_daily']['data'])
    beq = benchmark.equity.to_numpy(float)
    np.testing.assert_array_equal(pd.to_datetime(benchmark.date).to_numpy(), account.date.to_numpy())
    before = np.r_[100000., eq[:-1]]
    bbefore = np.r_[100000., beq[:-1]]
    drawdown = eq / np.maximum.accumulate(np.r_[100000., eq])[1:] - 1
    bdrawdown = beq / np.maximum.accumulate(np.r_[100000., beq])[1:] - 1

    def interval(lo, hi):
        return {'start': str(account.date.iloc[lo].date()), 'end': str(account.date.iloc[hi].date()),
                'days': hi - lo + 1, 'strategy_return': float(eq[hi] / before[lo] - 1),
                'benchmark_return': float(beq[hi] / bbefore[lo] - 1),
                'strategy_drawdown': float(drawdown[lo:hi + 1].min()),
                'benchmark_drawdown': float(bdrawdown[lo:hi + 1].min()),
                'drawdown_basis': 'inherited full-account high-water mark'}

    annual = []
    for year in sorted(account.date.dt.year.unique()):
        indices = np.flatnonzero(account.date.dt.year.to_numpy() == year)
        annual.append({'year': int(year), 'partial': bool(year == 2026),
                       **interval(int(indices[0]), int(indices[-1]))})
    rolling = []
    longest, current = 0, 0
    for start in range(0, len(account) - 251, 21):
        record = interval(start, start + 251)
        record['excess'] = record['strategy_return'] - record['benchmark_return']
        current = current + 1 if record['excess'] < 0 else 0
        longest = max(longest, current)
        rolling.append(record)
    quantity = account.quantity.to_numpy(float)
    exposure = quantity * account.close.to_numpy(float) / eq
    buy = fills.side == 'BUY'
    sell = fills.side == 'SELL'
    if not (buy | sell).all():
        raise ValueError('unexpected fill side')
    amounts = fills.quantity.astype(float) * fills.price.astype(float)
    fees = fills.fees.astype(float)
    cashflows = amounts.where(sell, -amounts) - fees
    total_cash = 100000 + float(cashflows.sum())
    np.testing.assert_allclose(total_cash, account.cash.iloc[-1], rtol=1e-12, atol=1e-7)
    np.testing.assert_allclose(total_cash + quantity[-1] * float(account.close.iloc[-1]),
                               eq[-1], rtol=1e-12, atol=1e-7)
    closed = trades[trades.status == 'CLOSED']
    if not closed.cycle_id.is_unique:
        raise ValueError('multiple closed rows per actual account cycle')
    completed_cashflows = []
    for cycle in closed.cycle_id:
        mask = fills.cycle_id == cycle
        bought = int(fills.loc[mask & buy, 'quantity'].sum())
        sold = int(fills.loc[mask & sell, 'quantity'].sum())
        if bought <= 0 or bought != sold:
            raise ValueError('closed cycle fill quantities do not balance')
        completed_cashflows.append({'cycle_id': cycle, 'net_cashflow': float(cashflows[mask].sum()),
                                   'bought_quantity': bought, 'sold_quantity': sold,
                                   'fills_count': int(mask.sum()), 'fees': float(fees[mask].sum())})
    cycle_pnl = pd.Series([c['net_cashflow'] for c in completed_cashflows], dtype=float)
    positive = float(cycle_pnl[cycle_pnl > 0].sum())
    range_values = decisions.range_ratio.to_numpy(float) if p['sizing'] == 'relative' else decisions.range5.to_numpy(float)
    high = range_values > p['threshold'] if p['sizing'] in ('relative', 'absolute') else np.zeros(len(account), dtype=bool)
    return {'candidate_id': row['candidate_id'], 'evidence': row['evidence'],
            'parameters': p, 'annual': annual, 'rolling252': rolling,
            'longest_underperforming_rolling_run': int(longest),
            'fees': float(fees.sum()), 'buy_gross': float(amounts[buy].sum()),
            'sell_gross': float(amounts[sell].sum()), 'fills_count': len(fills),
            'orders_count': len(table(run, 'orders')), 'closed_trades': len(closed),
            'open_tail_quantity': int(quantity[-1]),
            'time_in_market_fraction': float((quantity > 0).mean()),
            'mean_realized_weight': float(exposure.mean()), 'max_realized_weight': float(exposure.max()),
            'mean_realized_weight_on_intent_active_execution_days': float(exposure[active].mean()) if active.any() else None,
            'target_mean_all_days': float(target.mean()),
            'target_mean_intent_active_days': float(target[active].mean()) if active.any() else None,
            'intent_active_days': int(active.sum()), 'intent_episode_count': int((ages == 1).sum()),
            'intent_zero_target_days': int((active & (target == 0)).sum()),
            'target_changed_days': int((np.diff(np.r_[0., target]) != 0).sum()),
            'target_zero_crossings': int(((np.r_[0., target[:-1]] > 0) & (target == 0)).sum()),
            'actual_flat_crossings': int(((account.quantity_before.to_numpy(float) > 0) & (quantity == 0)).sum()),
            'high_amplitude_active_days': int((high & active).sum()) if p['sizing'] in ('relative', 'absolute') else None,
            'signal_age_independent_of_target_check': 'PASS',
            'completed_cycle_cashflows': completed_cashflows,
            'realized_closed_cycle_net_cashflow': float(cycle_pnl.sum()),
            'largest_winner_share_of_positive_closed_cashflow': float(cycle_pnl.clip(lower=0).max() / positive) if positive else None,
            'top5_share_of_positive_closed_cashflow': float(cycle_pnl.nlargest(5).clip(lower=0).sum() / positive) if positive else None,
            'cashflow_reconciliation': 'PASS',
            'pnl_scope': 'Actual fills of CLOSED cycles; partial sells included, open-cycle flows excluded from concentration; no phase attribution'}


def compare(row, control, diagnostics):
    current, base = diagnostics[row['candidate_id']], diagnostics[control['candidate_id']]
    return {'candidate_id': row['candidate_id'], 'control_id': control['candidate_id'],
            'control_parameters': control['parameters'],
            'net_cagr_difference': row['observation']['net_cagr'] - control['observation']['net_cagr'],
            'drawdown_magnitude_difference': abs(row['observation']['max_drawdown']) - abs(control['observation']['max_drawdown']),
            'closed_trades_difference': current['closed_trades'] - base['closed_trades'],
            'fees_difference': current['fees'] - base['fees'],
            'mean_realized_weight_difference': current['mean_realized_weight'] - base['mean_realized_weight'],
            'active_target_weight_difference': current['target_mean_intent_active_days'] - base['target_mean_intent_active_days']}


def main():
    rows = []
    source_counts = {}
    protocol_root = Path(__file__).resolve().parents[1] / 'protocols'
    initial_protocol = json.loads((protocol_root / 'supplement_search.json').read_text(encoding='utf-8'))
    expected_counts = {'initial': len(initial_protocol['initial_configurations'])}
    for phase in ('followup','boundary'):
        followup_path = protocol_root / f'{phase}.json'
        if followup_path.exists():
            expected_counts[phase] = len(json.loads(followup_path.read_text(encoding='utf-8'))['configurations'])
    for stage in ('initial', 'followup', 'boundary'):
        path = WORK / f'{stage}_results.json'
        if path.exists():
            part = json.loads(path.read_text(encoding='utf-8'))
            rows.extend(part)
            source_counts[stage] = len(part)
    if not rows or len({r['candidate_id'] for r in rows}) != len(rows):
        raise ValueError('missing results or duplicate candidate identities')
    runs, diagnostics = {}, {}
    for row in rows:
        run = load_evidence(row)
        runs[row['candidate_id']] = run
        diagnostics[row['candidate_id']] = details(row, run)
    old_rows = json.loads((OLD_WORK / 'grid_results.json').read_text(encoding='utf-8'))
    old_by_id = {r['candidate_id']: r for r in old_rows}
    continuity = []
    for row in rows:
        if row['parameters']['sizing'] != 'cycle':
            continue
        old_id = {0.: 'C0031', .0025: 'C0026'}[row['parameters']['entry']]
        old_run = load_evidence(old_by_id[old_id], 'EX003_20261021')
        columns = ['date', 'cash', 'quantity', 'equity']
        left, right = (table(run, 'account_daily')[columns].copy().reset_index(drop=True)
                       for run in (runs[row['candidate_id']], old_run))
        for frame in (left, right):
            frame['date'] = pd.to_datetime(frame['date'])
        pd.testing.assert_frame_equal(left, right, check_dtype=False, check_exact=True)
        continuity.append({'candidate_id': row['candidate_id'], 'original_candidate_id': old_id,
                           'status': 'PASS', 'rows': len(left), 'comparison': 'exact date/cash/quantity/equity',
                           'original_evidence': old_by_id[old_id]['evidence']})
    by_anchor = {}
    comparisons = []
    for key in sorted({anchor(r) for r in rows}):
        group = [r for r in rows if anchor(r) == key]
        controls = [r for r in group if r['parameters']['sizing'] in ('cycle', 'constant')]
        for row in group:
            for control in controls:
                if row['candidate_id'] != control['candidate_id']:
                    comparisons.append(compare(row, control, diagnostics))
        types = {}
        for sizing in sorted({r['parameters']['sizing'] for r in group}):
            subset = [r for r in group if r['parameters']['sizing'] == sizing]
            types[sizing] = {'count': len(subset), 'passed': sum(r['passed'] for r in subset),
                             'frontier': [r['candidate_id'] for r in frontier(subset)],
                             'best_cagr': max(subset, key=lambda r: r['observation']['net_cagr'])['candidate_id']}
        by_anchor[anchor_name(key)] = {'count': len(group), 'passed': sum(r['passed'] for r in group),
                                     'frontier': [r['candidate_id'] for r in frontier(group)], 'types': types}
    groups = {}
    for row in rows:
        account = table(runs[row['candidate_id']], 'account_daily')
        digest = sha256(account[['date', 'cash', 'quantity', 'equity']].to_csv(index=False, float_format='%.9f').encode()).hexdigest()
        groups.setdefault(digest, []).append(row['candidate_id'])
    result = {'count': len(rows), 'source_counts': source_counts, 'expected_counts': expected_counts,
              'published_snapshot_complete': all(source_counts.get(key, 0) == count for key, count in expected_counts.items()),
              'succeeded': len(rows),
              'passed': sum(r['passed'] for r in rows), 'passed_ids': [r['candidate_id'] for r in rows if r['passed']],
              'frontier': [r['candidate_id'] for r in frontier(rows)], 'by_anchor': by_anchor,
              'control_comparisons': comparisons, 'economic_path_groups': groups,
              'cycle_control_continuity': continuity,
              'best_return': max(rows, key=lambda r: r['observation']['net_cagr'])['candidate_id'],
              'scope': 'Published S015 EX004 accounts and two EX003 control accounts only; no account execution or provider access',
              'limits': ['All results are already-seen development evidence, not independent validation.',
                         'Mean active target matching does not guarantee identical realized exposure or turnover.',
                         'Closed-cycle cashflows are actual accounting facts, not independent causal or phase attribution.',
                         'Economic path fingerprints are descriptive 9-decimal CSV groups, not exact equivalence certification.']}
    save(WORK / 'analysis.json', result)
    save(WORK / 'account_diagnostics.json', diagnostics)
    print(json.dumps({key: result[key] for key in ('count', 'passed', 'frontier', 'best_return', 'cycle_control_continuity')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
