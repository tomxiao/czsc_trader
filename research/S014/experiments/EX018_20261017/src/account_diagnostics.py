"""Offline attribution of authenticated accounts, without replay or upstream access."""
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from czsc_trader.research_tools import EvidenceRef

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
VARIANTS = ('parent_high_H3', 'parent_high_H6', 'up_candle_high_H3')


def table(value):
    return pd.DataFrame(value['data'], columns=[f['name'] for f in value['schema']['fields']])


def distribution(values):
    v = pd.Series(values, dtype=float).dropna()
    return dict(n=len(v), mean=float(v.mean()) if len(v) else None,
                median=float(v.median()) if len(v) else None,
                min=float(v.min()) if len(v) else None,
                max=float(v.max()) if len(v) else None,
                positive=int(v.gt(0).sum()), negative=int(v.lt(0).sum()), zero=int(v.eq(0).sum()),
                positive_sum=float(v.clip(lower=0).sum()), negative_sum=float(v.clip(upper=0).sum()),
                net_sum=float(v.sum()),
                mean_remove_top3=float(v.sort_values().iloc[:-3].mean()) if len(v) > 3 else None,
                mean_remove_top5=float(v.sort_values().iloc[:-5].mean()) if len(v) > 5 else None)


def load(record):
    ref = EvidenceRef.from_dict(record['evidence'])
    raw = ref.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest() == ref.sha256
    value = json.loads(raw)
    assert value['result_hash'] == record['result_hash'] and len(value['runs']) == 1
    tables = {k: table(v) for k, v in value['runs'][0]['ledgers'].items()}
    tables['account_daily']['date'] = pd.to_datetime(tables['account_daily'].date).dt.normalize()
    tables['account_daily'] = tables['account_daily'].sort_values('date').set_index('date')
    for field in ('entry_date', 'exit_date'):
        tables['trades'][field] = pd.to_datetime(tables['trades'][field])
    tables['fills']['fill_time'] = pd.to_datetime(tables['fills'].fill_time)
    assert len(tables['account_daily']) == 1642
    return tables


def cycles(tables, cutoff, variant):
    daily, fills, trades = (tables[k] for k in ('account_daily', 'fills', 'trades'))
    end = daily.loc[:cutoff].iloc[-1]
    rows = []
    for t in trades.sort_values('entry_date').itertuples():
        day = t.entry_date.normalize()
        if day > cutoff:
            continue
        f = fills.loc[fills.cycle_id.eq(t.cycle_id)]
        buys = f.loc[f.side.eq('BUY')]
        sells = f.loc[f.side.eq('SELL') & f.fill_time.dt.normalize().le(cutoff)]
        assert len(buys) == 1 and len(sells) <= 1
        b = buys.iloc[0]
        assert daily.loc[day, 'quantity_before'] == 0
        outlay = float(b.quantity * b.price + b.fees)
        starting = float(daily.loc[day, 'cash_before'])
        residual = starting - outlay
        assert residual >= -1e-8
        if len(sells):
            s = sells.iloc[0]
            assert s.quantity == b.quantity
            proceeds = float(s.quantity * s.price - s.fees)
            exit_day = s.fill_time.normalize()
            exit_price = float(s.price)
            status = 'CLOSED'
        else:
            assert end.quantity == b.quantity
            proceeds = float(b.quantity * end.close)
            exit_day = daily.loc[:cutoff].index[-1]
            exit_price = float(end.close)
            status = 'MARKED_OPEN_NO_EXIT_FEE'
        position_return = proceeds / outlay - 1
        cycle_return = (residual + proceeds) / starting - 1
        if status == 'CLOSED':
            assert np.isclose(position_return, t.net_return, atol=1e-12)
        rows.append(dict(variant=variant, cutoff=cutoff.date().isoformat(), cycle_id=t.cycle_id,
                         entry_date=day.date().isoformat(), entry_year=day.year,
                         exit_or_mark_date=exit_day.date().isoformat(), status=status,
                         entry_price=float(b.price), exit_or_mark_price=exit_price,
                         entry_precision=b.time_precision, quantity=int(b.quantity),
                         entry_outlay=outlay, starting_wealth=starting, residual_cash=residual,
                         residual_fraction=residual / starting, proceeds=proceeds,
                         position_return=position_return, position_log=float(np.log1p(position_return)),
                         cycle_return=cycle_return, cycle_log=float(np.log1p(cycle_return))))
    result = pd.DataFrame(rows)
    assert result.entry_date.is_unique
    actual_return = float(end.equity / 100000 - 1)
    cycle_log = float(result.cycle_log.sum())
    assert np.isclose(np.expm1(cycle_log), actual_return, atol=1e-10)
    reconciliation = dict(variant=variant, cutoff=cutoff.date().isoformat(), cycles=len(result),
                          closed=int(result.status.eq('CLOSED').sum()),
                          marked_open=int(result.status.ne('CLOSED').sum()), actual_return=actual_return,
                          cycle_compounded_return=float(np.expm1(cycle_log)),
                          position_compounded_return=float(np.expm1(result.position_log.sum())),
                          actual_log=float(np.log1p(actual_return)), cycle_log_sum=cycle_log,
                          position_log_sum=float(result.position_log.sum()),
                          cash_residual_log_effect=float(cycle_log-result.position_log.sum()),
                          absolute_reconciliation_error=float(abs(np.expm1(cycle_log)-actual_return)))
    return result, reconciliation


def scopes(df):
    return [('ALL', df), *[(str(y), df.loc[df.entry_year.eq(y)]) for y in range(2020, 2027)]]


def compare(left, right, comparison, window):
    joined = left.merge(right, on='entry_date', how='outer', suffixes=('_left', '_right'), indicator=True)
    joined['entry_year'] = pd.to_datetime(joined.entry_date).dt.year
    joined['category'] = joined['_merge'].map({'both': 'matched', 'left_only': 'left_only', 'right_only': 'right_only'}).astype(str)
    joined['comparison'] = comparison
    joined['window'] = window
    joined['both_closed'] = joined.status_left.eq('CLOSED') & joined.status_right.eq('CLOSED')
    joined['position_return_difference'] = joined.position_return_right - joined.position_return_left
    joined['position_log_difference'] = joined.position_log_right.fillna(0) - joined.position_log_left.fillna(0)
    joined['cycle_log_difference'] = joined.cycle_log_right.fillna(0) - joined.cycle_log_left.fillna(0)
    both = joined.category.eq('matched')
    assert np.allclose(joined.loc[both, 'entry_price_left'], joined.loc[both, 'entry_price_right'])
    summary = []
    for scope, part in scopes(joined):
        for category in ('matched', 'left_only', 'right_only'):
            p = part.loc[part.category.eq(category)]
            summary.append(dict(comparison=comparison, window=window, entry_cohort=scope,
                                category=category, n=len(p), both_closed=int(p.both_closed.sum()),
                                left_returns=distribution(p.position_return_left),
                                right_returns=distribution(p.position_return_right),
                                matched_return_difference=distribution(p.position_return_difference),
                                position_log_difference_sum=float(p.position_log_difference.sum()),
                                cycle_log_difference_sum=float(p.cycle_log_difference.sum())))
    assert np.isclose(joined.cycle_log_difference.sum(), right.cycle_log.sum()-left.cycle_log.sum(), atol=1e-12)
    return joined.drop(columns='_merge'), summary


def main():
    output = EX / 'others/account_diagnostics.json'
    if output.exists():
        raise RuntimeError('Preserve completed diagnostic evidence')
    requests.sessions.Session.request = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('Offline only'))
    source = EX / 'others/comparison_accounts.json'
    records = json.loads(source.read_text(encoding='utf-8'))['records']
    selected = {r['variant']: r for r in records if r['variant'] in VARIANTS}
    tables = {v: load(selected[v]) for v in VARIANTS}
    reconciliations, all_cycles, pairs, comparisons, trims, pnl_groups, annual = [], [], [], [], [], [], []
    for window, cutoff in [('ALL', pd.Timestamp('2026-10-15')), ('WITHOUT2026', pd.Timestamp('2025-12-31'))]:
        current = {}
        for variant in VARIANTS:
            c, check = cycles(tables[variant], cutoff, variant)
            c['window'] = window
            current[variant] = c
            all_cycles.append(c)
            reconciliations.append(check)
            for scope, part in scopes(c):
                closed = part.loc[part.status.eq('CLOSED')]
                trims.append(dict(variant=variant, window=window, entry_cohort=scope,
                                  closed_return_distribution=distribution(closed.position_return),
                                  marked_open_count=int(part.status.ne('CLOSED').sum())))
        for right, name in [('parent_high_H6', 'H6_minus_H3'), ('up_candle_high_H3', 'UP_CANDLE_H3_minus_PARENT_H3')]:
            joined, summaries = compare(current['parent_high_H3'], current[right], name, window)
            pairs.append(joined)
            comparisons.extend(summaries)
            if name == 'H6_minus_H3':
                closed = joined.loc[joined.both_closed].copy()
                closed['h3_realized_pnl_group'] = np.where(closed.position_return_left.gt(0), 'H3_POSITIVE', 'H3_NONPOSITIVE')
                for scope, part in scopes(closed):
                    for group in ('ALL', 'H3_POSITIVE', 'H3_NONPOSITIVE'):
                        p = part if group == 'ALL' else part.loc[part.h3_realized_pnl_group.eq(group)]
                        pnl_groups.append(dict(window=window, entry_cohort=scope, h3_realized_pnl_group=group,
                                               h6_minus_h3_return=distribution(p.position_return_difference),
                                               h6_minus_h3_position_log=distribution(p.position_log_difference)))
    for variant, t in tables.items():
        previous = 100000.
        for year, part in t['account_daily'].groupby(t['account_daily'].index.year):
            values = np.r_[previous, part.equity.to_numpy(float)]
            annual.append(dict(variant=variant, year=int(year), start_nav=previous, end_nav=float(values[-1]),
                               return_=float(values[-1]/previous-1),
                               maximum_drawdown=float(np.max(1-values/np.maximum.accumulate(values)))))
            previous = float(values[-1])
    result = dict(schema='s014_ex018_account_path_diagnostics_v1', upstream_calls=0, account_replays=0,
                  sources={v: selected[v] for v in VARIANTS}, comparison_manifest_sha256=sha256(source.read_bytes()).hexdigest(),
                  method={
                      'matching': 'Actual entry calendar date, unique per account; matched entry prices asserted identical.',
                      'windows': 'ALL ends 2026-10-15; WITHOUT2026 truly truncates at 2025-12-31, including open positions marked at that account close with no hypothetical exit fee.',
                      'cohorts': 'Year tables group by actual entry year, not natural-year account PnL. Annual NAV statistics are separate and include previous year last NAV in drawdown.',
                      'position_return': 'Actual sale net proceeds / actual purchase including fee - 1; open holdings marked at account closing price without sale fee.',
                      'cycle_return': 'Residual cash plus net sale/mark proceeds divided by pre-entry entire account cash - 1. Product exactly reconciles account NAV; residual-cash log difference can be positive or negative.',
                      'attribution': 'Matched and unmatched log terms describe realized paths; matched cycle log differences still depend on path-specific quantities/residual cash. Entry replacement terms are not independent causal effects.',
                      'no_additive_returns': 'Arithmetic trade percentages and positive/negative sums are distribution diagnostics, never additive account return. Only log wealth terms add in the explicitly reconciled decomposition.',
                      'trim': 'Remove highest individual closed trade returns or matched return differences, recompute arithmetic mean only; no tradable counterfactual account.',
                      'pnl_groups': 'H3 actual exit net PnL is known only after next-session execution, not at the prior evening exit decision. Grouping is retrospective, not an executable conditional switch.',
                      'same_entry_extension': 'Same entry matches compare actual H6/H3 exits, including genuine exit delays. They do not imply that the entire H6 account consists of simply extending every H3 trade.'},
                  reconciliation=reconciliations, comparisons=comparisons, closed_return_diagnostics=trims,
                  matched_h3_exit_pnl_groups=pnl_groups, annual_nav=annual)
    with output.open('w', encoding='utf-8', newline='\n') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')
    outputs = {'trades': pd.concat(all_cycles, ignore_index=True),
               'matches': pd.concat(pairs, ignore_index=True),
               'annual_nav': pd.DataFrame(annual),
               'reconciliation': pd.DataFrame(reconciliations),
               'comparison_summary': pd.json_normalize(comparisons),
               'closed_return_diagnostics': pd.json_normalize(trims),
               'matched_pnl_groups': pd.json_normalize(pnl_groups)}
    for name, frame in outputs.items():
        frame.to_csv(EX / f'others/account_diagnostics_{name}.csv', index=False, lineterminator='\n')
    print(json.dumps({'status': 'PASS', 'reconciliation': reconciliations,
                      'comparison_all': [r for r in comparisons if r['entry_cohort']=='ALL'],
                      'pnl_groups_all': [r for r in pnl_groups if r['entry_cohort']=='ALL']}, indent=2))


if __name__ == '__main__':
    main()
