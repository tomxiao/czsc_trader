"""Read-only review of saved S014 accounts; no replay, fitting, or new labels."""
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from czsc_trader.research_tools import EvidenceRef

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
EX = ROOT / 'research/S014/experiments'


def main():
    requests.sessions.Session.request = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('Offline review'))
    assert not (OUT / 'account_review.json').exists()
    sources = {}

    def read(path):
        raw = path.read_bytes()
        sources[path.relative_to(ROOT).as_posix()] = sha256(raw).hexdigest()
        return json.loads(raw)

    records = read(EX / 'EX023_20261018/others/comparison_accounts.json')['records']
    record = next(r for r in records if r['candidate'] == 'S014-C0056')
    ref = EvidenceRef.from_dict(record['evidence'])
    raw = ref.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest() == ref.sha256
    account = json.loads(raw)
    assert account['result_hash'] == record['result_hash'] and len(account['runs']) == 1
    ledgers = {k: pd.DataFrame(v['data']) for k, v in account['runs'][0]['ledgers'].items()}
    d = ledgers['account_daily'].copy()
    d['date'] = pd.to_datetime(d.date).dt.normalize()
    d = d.sort_values('date').set_index('date')
    f = ledgers['fills'].copy()
    f['date'] = pd.to_datetime(f.fill_time).dt.normalize()
    assert len(d) == 1642 and not d.index.has_duplicates
    assert f.groupby('date').size().max() == 1
    fills = {r['date']: r for r in f.to_dict('records')}
    prev_close = d.close.shift()
    prev_equity = d.equity.shift(fill_value=100000.)
    d['entry_mark_pnl'] = 0.
    d['hold_mark_pnl'] = 0.
    d['exit_mark_pnl'] = 0.
    d['fees_pnl'] = 0.
    d['phase'] = 'FLAT'
    for day, row in d.iterrows():
        fill = fills.get(day)
        if fill is not None:
            assert abs(fill['fees'] - fill['quantity'] * fill['price'] * .001) < 1e-7
            d.loc[day, 'fees_pnl'] = -fill['fees']
            if fill['side'] == 'BUY':
                assert row.quantity_before == 0 and row.quantity == fill['quantity']
                d.loc[day, 'entry_mark_pnl'] = fill['quantity'] * (row.close - fill['price'])
                d.loc[day, 'phase'] = 'ENTRY'
            else:
                assert row.quantity_before == fill['quantity'] and row.quantity == 0
                d.loc[day, 'exit_mark_pnl'] = fill['quantity'] * (fill['price'] - prev_close.loc[day])
                d.loc[day, 'phase'] = 'EXIT'
        elif row.quantity_before:
            assert row.quantity_before == row.quantity
            d.loc[day, 'hold_mark_pnl'] = row.quantity * (row.close - prev_close.loc[day])
            d.loc[day, 'phase'] = 'HOLD'
    atoms = ['entry_mark_pnl', 'hold_mark_pnl', 'exit_mark_pnl', 'fees_pnl']
    d['actual_pnl'] = d.equity - prev_equity
    assert np.allclose(d[atoms].sum(axis=1), d.actual_pnl, atol=1e-7, rtol=0)
    summary = read(EX / 'EX029_20261018/others/budget_summary.json')
    candidate = next(r for r in summary['candidate_summaries'] if r['candidate'] == 'S014-C0056')
    annual = []
    for year, g in d.groupby(d.index.year):
        opening = float(prev_equity.loc[g.index[0]])
        a = next(a for a in candidate['annual'] if a['year'] == year)
        assert np.isclose(g.actual_pnl.sum() / opening, a['return'], atol=1e-12)
        assert np.isclose(g.equity.iloc[-1] / opening - 1, a['return'], atol=1e-12)
        annual.append({
            'year': int(year), 'opening_equity': opening,
            'net_pnl': float(g.actual_pnl.sum()), 'return': a['return'],
            'required_return': a['required_return'],
            'phases': {k: {'pnl': float(g[k].sum()), 'contribution_pp': float(100*g[k].sum()/opening)} for k in atoms},
            'phase_days': {str(k): int(v) for k, v in g.phase.value_counts().items()},
            'negative_mark_pnl': float(g[atoms[:3]].sum(axis=1).clip(upper=0).sum()),
            'positive_mark_pnl': float(g[atoms[:3]].sum(axis=1).clip(lower=0).sum()),
            'cash_fee_addback_same_path_pp': float(100*(g.actual_pnl.sum()-g.fees_pnl.sum())/opening),
        })
    diagnosis = read(EX / 'EX023_20261018/others/loss_state_diagnostics.json')
    episodes = pd.DataFrame(diagnosis['episodes'])
    episodes = episodes[episodes.window.eq('ALL')].copy()
    assert len(episodes) == 138
    cohort = []
    for year, g in episodes.groupby('entry_year'):
        early = g[g.early_break & g.both_closed]
        cohort.append({
            'entry_year': int(year), 'trades': len(g),
            'negative_trades': int(g.R_cycle_log.lt(0).sum()),
            'positive_trades': int(g.R_cycle_log.gt(0).sum()),
            'negative_log_sum': float(g.R_cycle_log.clip(upper=0).sum()),
            'positive_log_sum': float(g.R_cycle_log.clip(lower=0).sum()),
            'net_cycle_log': float(g.R_cycle_log.sum()),
            'matched_early_count': len(early),
            'matched_early_R_minus_B_log': float(early.actual_cycle_log_increment.sum()),
            'early_nonpositive_count': int(early.positive_mark.eq(False).sum()),
            'early_nonpositive_R_minus_B_log': float(early.loc[early.positive_mark.eq(False), 'actual_cycle_log_increment'].sum()),
            'negative_trades_without_early_exit': int((g.R_cycle_log.lt(0) & ~g.early_break).sum()),
        })
    b = next(r for r in summary['candidate_summaries'] if r['candidate'] == 'S014-C0034')
    p = next(r for r in summary['candidate_summaries'] if r['candidate'] == 'S014-C0057')
    comparisons = [{'year': y, **{name: next(a['return'] for a in row['annual'] if a['year'] == y) for name, row in [('C0034_B', b), ('C0056_R', candidate), ('C0057_P', p)]}} for y in range(2020, 2027)]
    result = {
        'status': 'PASS_EXISTING_LEDGER_RECONCILIATION', 'source_sha256': sources,
        'account_evidence': record['evidence'], 'account_result_hash': record['result_hash'],
        'annual': annual, 'entry_year_cohorts': cohort, 'existing_account_comparisons': comparisons,
        'checks': {'daily_reconciliations': len(d), 'annual_reconciliations': len(annual), 'fee_checks': len(f), 'source_hashes_recorded': len(sources)},
        'new_data_calls': 0, 'new_fits': 0, 'new_labels': 0, 'new_accounts': 0,
        'limits': [
            'Accounting allocation of actual NAV changes, not causal economic explanation or counterfactual strategy.',
            'Phase contributions use each calendar-year opening NAV and add exactly to annual return; fees are separate.',
            'Hold phase includes overnight and intraday changes. Exit phase is previous close to actual sell fill, not the whole trade loss.',
            'Fee addback holds actual position/capital path fixed; it is not a zero-fee replay and does not change the agreed fee.',
            'Entry-year trade cohorts may cross calendar years and cannot be added to annual phase PnL.',
            'All years are reported; no new signal, threshold, label, training or account replay.',
        ],
    }
    (OUT / 'account_review.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')
    d[atoms+['actual_pnl','phase']].to_csv(OUT / 'daily_reconciliation.csv', float_format='%.12g', lineterminator='\n')
    print(json.dumps({'annual': annual, 'cohorts': cohort}, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
