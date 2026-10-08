"""S013 researcher diagnostic; read existing accounts, never evaluate anew."""
from pathlib import Path
from types import MappingProxyType, ModuleType
import gzip
import hashlib
import json
import pickle
import sys

import numpy as np
import pandas as pd

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[4]
# The known same-S013 caches used this mapping reducer. Avoid importing mutable
# research helpers or reading any other batch/source during this diagnostic.
mapping_module = ModuleType('common')
mapping_module._mapping = lambda value: MappingProxyType(value)
sys.modules.setdefault('common', mapping_module)


def load_result(identifier):
    path = ROOT / f'.tmp/s013-stage3-hfq/{identifier}.pkl.gz'
    raw = path.read_bytes()
    with gzip.open(path, 'rb') as handle:
        result = pickle.load(handle)
    return result, hashlib.sha256(raw).hexdigest()


def json_safe(value):
    if isinstance(value, (dict, MappingProxyType)):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_safe(v) for v in value]
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if hasattr(value, 'to_dict'):
        return json_safe(value.to_dict())
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def analyse(identifier):
    result, cache_hash = load_result(identifier)
    run = result.runs[0]
    acc = run.execution.account_daily.copy()
    fills = run.execution.fills.copy()
    trades = run.execution.trades.copy()
    acc['date'] = pd.to_datetime(acc.date).dt.normalize()
    fills['date'] = pd.to_datetime(fills.fill_time).dt.normalize()
    trades['entry_date'] = pd.to_datetime(trades.entry_date)
    trades['exit_date'] = pd.to_datetime(trades.exit_date)
    assert len(acc) == 1636 and acc.date.is_unique
    previous_equity = np.r_[1_000_000, acc.equity.to_numpy()[:-1]]
    acc['net_pnl'] = acc.equity.to_numpy() - previous_equity
    acc['fees'] = acc.date.map(fills.groupby('date').fees.sum()).fillna(0)
    acc['gross_price_pnl'] = acc.net_pnl + acc.fees
    active, previous_close, previous_quantity = None, None, 0
    cycles, max_error = [], 0.0
    for a in acc.itertuples():
        parts = {}
        if previous_quantity:
            parts[active] = {'gross': previous_quantity * (a.close - previous_close), 'fees': 0.0}
        for f in fills[fills.date.eq(a.date)].itertuples():
            parts.setdefault(f.cycle_id, {'gross': 0.0, 'fees': 0.0})
            sign = 1 if f.side == 'BUY' else -1
            parts[f.cycle_id]['gross'] += sign * f.quantity * (a.close - f.price)
            parts[f.cycle_id]['fees'] += f.fees
            if f.side == 'BUY':
                active = f.cycle_id
            elif a.quantity == 0:
                active = None
        total = sum(p['gross'] - p['fees'] for p in parts.values())
        max_error = max(max_error, abs(total - a.net_pnl))
        assert abs(total - a.net_pnl) < 1e-6
        for cycle, part in parts.items():
            cycles.append({'date': a.date, 'year': int(a.date.year), 'cycle_id': cycle,
                           'gross': part['gross'], 'fees': part['fees'],
                           'net': part['gross'] - part['fees']})
        previous_close, previous_quantity = a.close, a.quantity
    cycle_frame = pd.DataFrame(cycles)
    years, anchor = {}, 1_000_000.0
    for year, segment in acc.groupby(acc.date.dt.year):
        values = np.r_[anchor, segment.equity.to_numpy()]
        year_return = float(values[-1] / anchor - 1)
        maximum_dd = float(np.max(1 - values / np.maximum.accumulate(values)))
        monthly, month_anchor = [], anchor
        for month, month_account in segment.groupby(segment.date.dt.month):
            month_return = float(month_account.equity.iloc[-1] / month_anchor - 1)
            monthly.append({'month': int(month), 'opening_equity': month_anchor,
                            'closing_equity': float(month_account.equity.iloc[-1]),
                            'actual_net_return': month_return,
                            'gross_price_pnl': float(month_account.gross_price_pnl.sum()),
                            'fees': float(month_account.fees.sum()),
                            'net_pnl': float(month_account.net_pnl.sum()),
                            'net_contribution_fraction_year_opening': float(month_account.net_pnl.sum() / anchor),
                            'held_close_sessions': int(month_account.quantity.gt(0).sum())})
            month_anchor = float(month_account.equity.iloc[-1])
        year_cycles = cycle_frame[cycle_frame.year.eq(year)].groupby('cycle_id')[['gross', 'fees', 'net']].sum()
        cycle_records = []
        for cycle_id, pnl in year_cycles.iterrows():
            trade = trades[trades.cycle_id.eq(cycle_id)].iloc[0]
            cross_year = trade.entry_date.year != trade.exit_date.year if pd.notna(trade.exit_date) else None
            cycle_records.append({'cycle_id': cycle_id, 'entry_date': trade.entry_date.isoformat(),
                                  'exit_date': trade.exit_date.isoformat() if pd.notna(trade.exit_date) else None,
                                  'whole_trade_status': trade.status, 'cross_year': cross_year,
                                  'gross_price_pnl': float(pnl.gross), 'fees': float(pnl.fees),
                                  'year_segment_net_pnl': float(pnl.net),
                                  'net_contribution_fraction_year_opening': float(pnl.net / anchor)})
        sorted_cycles = sorted(cycle_records, key=lambda c: c['year_segment_net_pnl'], reverse=True)
        net_pnl = float(segment.net_pnl.sum())
        positive_sum = sum(max(c['year_segment_net_pnl'], 0.0) for c in cycle_records)
        largest = sorted_cycles[0]['year_segment_net_pnl'] if sorted_cycles else 0.0
        largest3 = sum(c['year_segment_net_pnl'] for c in sorted_cycles[:3])
        sorted_days = segment.sort_values('net_pnl', ascending=False)
        year_fills = fills[fills.date.dt.year.eq(year)]
        years[str(year)] = {'sessions': len(segment), 'opening_equity': anchor,
                           'closing_equity': float(values[-1]), 'actual_net_return': year_return,
                           'maximum_drawdown_magnitude': maximum_dd,
                           'gross_price_pnl': float(segment.gross_price_pnl.sum()),
                           'fees': float(segment.fees.sum()), 'net_pnl': net_pnl,
                           'gross_contribution_fraction_opening': float(segment.gross_price_pnl.sum() / anchor),
                           'fee_contribution_fraction_opening': float(segment.fees.sum() / anchor),
                           'held_close_sessions': int(segment.quantity.gt(0).sum()),
                           'buy_fills': int(year_fills.side.eq('BUY').sum()),
                           'sell_fills': int(year_fills.side.eq('SELL').sum()),
                           'months': monthly, 'cycle_year_segments': sorted_cycles,
                           'concentration_diagnostics': {
                               'positive_cycle_segments': sum(c['year_segment_net_pnl'] > 0 for c in cycle_records),
                               'negative_cycle_segments': sum(c['year_segment_net_pnl'] < 0 for c in cycle_records),
                               'positive_cycle_segment_pnl_sum': positive_sum,
                               'top1_cycle_segment_net_pnl': largest,
                               'top3_cycle_segment_net_pnl': largest3,
                               'top1_fraction_total_year_net_pnl': largest / net_pnl if net_pnl else None,
                               'top3_fraction_total_year_net_pnl': largest3 / net_pnl if net_pnl else None,
                               'top1_fraction_positive_cycle_segment_sum': largest / positive_sum if positive_sum else None,
                               'top3_fraction_positive_cycle_segment_sum': largest3 / positive_sum if positive_sum else None,
                               'arithmetic_return_without_top1_segment': (net_pnl - largest) / anchor,
                               'arithmetic_return_without_top3_segments': (net_pnl - largest3) / anchor,
                               'top1_positive_daily_pnl': float(sorted_days.net_pnl.iloc[0]),
                               'arithmetic_return_without_top1_day': float((net_pnl - sorted_days.net_pnl.iloc[0]) / anchor),
                               'top_positive_days': [{'date': d.date.isoformat(), 'net_pnl': float(d.net_pnl)}
                                                     for d in sorted_days.head(5).itertuples()],
                           }}
        assert abs(sum(m['net_pnl'] for m in monthly) - net_pnl) < 1e-6
        assert abs(sum(c['year_segment_net_pnl'] for c in cycle_records) - net_pnl) < 1e-6
        assert abs(net_pnl / anchor - year_return) < 1e-12
        anchor = float(values[-1])
    parameters = json_safe(run.signals.snapshot.strategy_payload['parameters'])
    plan = json_safe(run.signals.support_data['input_binding']['plan'])
    plan.pop('strategy')
    signal_plan_hash = hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    out = {'candidate_id': identifier, 'parameters': parameters, 'cache_sha256': cache_hash,
           'request_hash': result.request_hash, 'result_hash': result.result_hash,
           'runtime': json_safe(run.signals.snapshot.strategy_payload['runtime']),
           'prepared_data_identity': json_safe(run.signals.support_data.get('prepared_data_identity')),
           'execution_input_identities': json_safe(run.signals.support_data.get('execution_input_identities')),
           'signal_input_plan_without_strategy_sha256': signal_plan_hash,
           'data_identity': json_safe(run.signals.data_identity), 'daily_attribution_max_abs_error_yuan': max_error,
           'net_cagr': float((acc.equity.iloc[-1] / 1_000_000) ** (252 / len(acc)) - 1),
           'closed_trades': int(trades.status.eq('CLOSED').sum()), 'years': years}
    return out


def finish_findings(out):
    accounts = out['accounts']
    own, control = accounts['C0440'], accounts['C0439']
    y23, y24 = own['years']['2023'], own['years']['2024']
    january = next(m for m in y23['months'] if m['month'] == 1)
    september_october = sum(m['net_pnl'] for m in y24['months'] if m['month'] in (9, 10))
    cross_year23 = sum(c['year_segment_net_pnl'] for c in y23['cycle_year_segments'] if c['cross_year'])
    entered_earlier23 = sum(c['year_segment_net_pnl'] for c in y23['cycle_year_segments'] if c['entry_date'][:4] < '2023')
    exits_later23 = sum(c['year_segment_net_pnl'] for c in y23['cycle_year_segments'] if c['exit_date'] is None or c['exit_date'][:4] > '2023')
    out['key_diagnostics'] = {
        '2023_small_positive': {
            'actual_net_return': y23['actual_net_return'], 'net_pnl_yuan': y23['net_pnl'],
            'january_net_pnl_yuan': january['net_pnl'],
            'rest_of_year_net_pnl_yuan': y23['net_pnl'] - january['net_pnl'],
            'cross_year_cycle_2023_marked_pnl_yuan': cross_year23,
            'entered_2022_cycle_2023_marked_pnl_yuan': entered_earlier23,
            'exits_2024_cycle_2023_marked_pnl_yuan': exits_later23,
            'arithmetic_return_without_entered_2022_cycle_2023_segment': (y23['net_pnl'] - entered_earlier23) / y23['opening_equity'],
            'arithmetic_return_without_cross_year_cycle_2023_segments': (y23['net_pnl'] - cross_year23) / y23['opening_equity'],
            'cash_february_march': all(m['held_close_sessions'] == 0 and m['net_pnl'] == 0 for m in y23['months'] if m['month'] in (2, 3)),
            'negative_month_count': sum(m['actual_net_return'] < 0 for m in y23['months']),
            'positive_cycle_segment_sum': y23['concentration_diagnostics']['positive_cycle_segment_pnl_sum'],
            'negative_cycle_segment_sum': sum(min(c['year_segment_net_pnl'], 0) for c in y23['cycle_year_segments']),
        },
        '2024_concentration': {
            'calendar_net_return': y24['actual_net_return'], 'net_pnl_yuan': y24['net_pnl'],
            'share_full_pool_net_profit_yuan': y24['net_pnl'] / (own['years']['2026']['closing_equity'] - 1_000_000),
            'september_october_net_pnl_yuan': september_october,
            'september_october_fraction_year_net_profit': september_october / y24['net_pnl'],
            'largest_year_cycle_segment': y24['cycle_year_segments'][0],
            'top1_fraction_year_net_profit': y24['concentration_diagnostics']['top1_fraction_total_year_net_pnl'],
            'top3_fraction_year_net_profit': y24['concentration_diagnostics']['top3_fraction_total_year_net_pnl'],
            'without_state_exit_2024_return': control['years']['2024']['actual_net_return'],
            'september_october_actual_monthly_return_differences': [{
                'month': m['month'],
                'with_exit': m['actual_net_return'], 'without_exit': n['actual_net_return'],
                'difference': m['actual_net_return'] - n['actual_net_return']}
                for m, n in zip(y24['months'], control['years']['2024']['months'], strict=True) if m['month'] in (9, 10)],
        },
    }
    out['negative_evidence'] = [
        {'finding': 'State exit increases actual turnover costs rather than reducing them;2023gross-price advantage is outweighed by extra fees.',
         '2023_gross_contribution_difference': y23['gross_contribution_fraction_opening'] - control['years']['2023']['gross_contribution_fraction_opening'],
         '2023_fee_contribution_difference': y23['fee_contribution_fraction_opening'] - control['years']['2023']['fee_contribution_fraction_opening'],
         '2023_net_return_difference': y23['actual_net_return'] - control['years']['2023']['actual_net_return']},
        {'finding': 'Strictly positive2023net return has a small cushion relative to individual profitable days/cycles. Arithmetic removal diagnoses dependence only.',
         'net_pnl_yuan': y23['net_pnl'],
         'top1_cycle_segment_yuan': y23['concentration_diagnostics']['top1_cycle_segment_net_pnl'],
         'arithmetic_return_without_top1_segment': y23['concentration_diagnostics']['arithmetic_return_without_top1_segment'],
         'arithmetic_return_without_top1_day': y23['concentration_diagnostics']['arithmetic_return_without_top1_day']},
        {'finding': '2024profit is concentrated in the lateSeptember/earlyOctober rally. The no-state-exit control also captures it at almost identical monthly percentage returns; the exit policy cannot be credited with independently creating that market opportunity.',
         'top1_share_calendar_year_profit': y24['concentration_diagnostics']['top1_fraction_total_year_net_pnl'],
         'top3_share_calendar_year_profit': y24['concentration_diagnostics']['top3_fraction_total_year_net_pnl']},
        {'finding': 'The policy has adverse annual effects in2021and2023;2026remains negative, while2025underperformsBuyHold. Fourth gate does not trigger in benchmark-positive2026.',
         'adverse_annual_effect_years': [c['year'] for c in out['controlled_exit_contrast']['calendar_comparison'] if c['return_difference'] < 0],
         '2026_strategy_return': own['years']['2026']['actual_net_return'],
         '2025_strategy_return': own['years']['2025']['actual_net_return'],
         '2025_buyhold_return': out['benchmark_calendar_returns']['2025'],
         '2026_buyhold_return': out['benchmark_calendar_returns']['2026']},
        {'finding': 'Different prior-year account capital affects absolute PnL; normalized annual/monthly returns compare policy outcomes. Added profit includes changed entries/exits and compounding, not solely avoiding individual losing positions.'},
    ]
    out['analysis_source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return out


def main():
    source = WORK / 'search_results_r4.json'
    raw = source.read_bytes()
    rows = json.loads(raw)['rows']
    by_id = {r['candidate_id']: r for r in rows if r['status'] == 'SUCCEEDED'}
    results = {}
    for identifier in ('C0440', 'C0439', 'C0385', 'C0315'):
        results[identifier] = analyse(identifier)
        a = results[identifier]
        if identifier in by_id:
            expected = by_id[identifier]
            assert abs(expected['net_cagr'] - a['net_cagr']) < 1e-12
            assert expected['closed_trades'] == a['closed_trades']
            for year in a['years']:
                assert abs(expected['annual'][year]['return'] - a['years'][year]['actual_net_return']) < 1e-12
        print('analysed', identifier, flush=True)
    controlled, control = results['C0440'], results['C0439']
    cp = dict(controlled['parameters'])
    bp = dict(control['parameters'])
    assert cp.pop('exit_on_regime_change') is True
    assert bp.pop('exit_on_regime_change') is False
    assert cp == bp
    assert controlled['runtime'] == control['runtime']
    assert controlled['execution_input_identities'] == control['execution_input_identities']
    assert controlled['signal_input_plan_without_strategy_sha256'] == control['signal_input_plan_without_strategy_sha256']
    comparison = []
    for year in controlled['years']:
        x, y = controlled['years'][year], control['years'][year]
        comparison.append({'year': year, 'with_exit_actual_return': x['actual_net_return'],
                           'without_exit_actual_return': y['actual_net_return'],
                           'return_difference': x['actual_net_return'] - y['actual_net_return'],
                           'gross_contribution_difference': x['gross_contribution_fraction_opening'] - y['gross_contribution_fraction_opening'],
                           'fee_contribution_difference': x['fee_contribution_fraction_opening'] - y['fee_contribution_fraction_opening'],
                           'held_close_session_difference': x['held_close_sessions'] - y['held_close_sessions'],
                           'months': [{'month': m['month'],
                                       'with_exit_actual_return': m['actual_net_return'],
                                       'without_exit_actual_return': n['actual_net_return'],
                                       'return_difference': m['actual_net_return'] - n['actual_net_return'],
                                       'with_exit_net_pnl': m['net_pnl'], 'without_exit_net_pnl': n['net_pnl']}
                                      for m, n in zip(x['months'], y['months'], strict=True)]})
    out = {'scope': 'S013/510500.SH only; no new evaluation, source/platform modification, or refreshed data',
           'source_search_path': 'research/S013/experiments/EX004_20261007/work/search_results_r4.json',
           'source_search_sha256_snapshot': hashlib.sha256(raw).hexdigest(),
           'selected_source_rows_snapshot': {i: by_id[i] for i in results if i in by_id},
           'benchmark_calendar_returns': {y: s['return'] for y, s in by_id['C0440']['buyhold_annual'].items()},
           'methods': {
               'annual': 'Continuous daily account, calendar year return final equity / prior year final equity -1; initial2020cash1m.2026through09/30.',
               'daily_price_attribution': 'prior quantity*(current close-prior close) + bought quantity*(close-fill price) - sold quantity*(close-fill price); net subtracts actual daily fees. Each day reconciles equity change to tolerance1e-6yuan.',
               'cycle_attribution': 'Actual daily mark-to-market contribution by cycle_id, split across calendar boundaries, includes open cycles. Whole-trade realized PnL is never assigned wholesale to exit year.',
               'fees': 'Gross contribution arithmetic adds back paid fees at actual account quantities. This does not reproduce fee-free sizing or a zero-fee strategy.',
               'concentration': 'Calendar-year monthly/day/cycle-segment contributions are diagnostics only, distinct from stage-four mandated whole-research maximum profitable-trade metric.',
               'removal': 'Contribution subtraction is arithmetic evidence of dependence. Does not evaluate a strategy skipping that trade/day or propagate re-sizing/compounding.'},
           'accounts': results, 'controlled_exit_contrast': {
               'sole_parameter_change': 'exit_on_regime_change False to True',
               'runtime_source_and_execution_input_identities_and_signal_request_plans_match': True,
               'prepared_strategy_data_identities_match': controlled['prepared_data_identity'] == control['prepared_data_identity'],
               'signal_input_comparison_limit': 'Independent strategy preparations have different overall data_identity hashes. Same signal request/date/calendar plan excluding strategy and identical execution input hashes including2020-2026adjusted_daily are verified from caches. Exact earlier2019warmup frame bytes are not contained in these inspected caches and should be checked by the primary session from existing preparation manifests before claiming all signal bytes match.',
               'net_cagr_difference': controlled['net_cagr'] - control['net_cagr'],
               'closed_trade_difference': controlled['closed_trades'] - control['closed_trades'],
               'calendar_comparison': comparison,
               'causal_boundary': 'Same implementation, execution input identities and requested signal windows, only state-exit Boolean changes. Conditional on equal prepared warmup signal values, supports an in-sample controlled causal effect of the complete exit policy on the simulated account. Includes consequent changes to re-entry, exposure, lot-rounded quantities, compounding and costs; does not isolate a pure per-order exit-price effect, prove a universal mechanism or provide an independent out-of-sample estimate. C0385/C0315 differ in several policy elements and are contextual, not single-variable controls.'},
           'negative_evidence': [],
           'selection_limits': ['Whole development pool and loss years already viewed repeatedly; C0440 is selected following adaptive search, no independent sample.',
                                'No future BuyHold sign is used in this diagnostic or as an authorized decision rule; regime is a historical price feature.',
                                '2023 strict positive return must be judged at unrounded full value; concentrated profits do not create additional user gates.',
                                'Do not extrapolate research-unit simulated outcomes to physical-share PTE returns.']}
    finish_findings(out)
    path = WORK / 'adaptive_attribution_20261008.json'
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf8')
    for identifier, result in results.items():
        print(identifier, [(year, round(s['actual_net_return'] * 100, 5), round(s['gross_contribution_fraction_opening'] * 100, 5), round(s['fee_contribution_fraction_opening'] * 100, 5))
                           for year, s in result['years'].items()], flush=True)
    print('saved', path, flush=True)


if __name__ == '__main__':
    main()
