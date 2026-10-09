"""Audit every successful EX007 account, decision gate and actual fill path.

Cycle groups describe entry/exit cohorts. Calendar-year price and fee attribution
uses continuous marked account equity, including open tails. Diagnostics do not
add acceptance gates; no execution, source acquisition or registry writes occur.
"""
import numpy as np
import pandas as pd

from common import CACHE, RUNS, cache_read, read, write
from diagnose import rows, verify_account
from trade_attribution import describe, inspect_run, plain


CONTROLS = {'C2308': 'C3000', 'C2132': 'C3001'}


def summarize_decisions(execution, parameters):
    """Keep internal opportunity/entry signals distinct from execution actions."""
    frame = execution.decisions.copy()
    settings, confirmation = parameters['context'], parameters['confirmation']
    extra = parameters.get('opportunity_confirmation')
    enabled = extra is not None and extra['enabled']
    opportunity = frame.confirmation_opportunity.astype(bool)
    base_applies = pd.Series(confirmation['enabled'], index=frame.index)
    if confirmation['scope'] != 'both':
        base_applies &= frame.regime.eq(confirmation['scope'])
    if settings['entry_gate'] != 'all':
        base_applies &= frame.confirmation_exit_context.eq('regime')
    base_pass = ~base_applies | frame.confirmation_score.ge(confirmation['threshold'])
    if enabled:
        expected_applies = pd.Series(True, index=frame.index)
        if extra['route_scope'] != 'both':
            expected_applies &= frame.regime.eq(extra['route_scope'])
        if extra['application'] == 'ordinary_entries':
            expected_applies &= ~frame.confirmation_exit_context.eq('regime')
        actual_applies = frame.opportunity_confirmation_applies.astype(bool)
        extra_pass = frame.opportunity_confirmation_pass.astype(bool)
        assert actual_applies.equals(expected_applies)
        assert extra_pass.equals(~actual_applies | frame.opportunity_confirmation_score.ge(extra['threshold']))
    else:
        actual_applies = pd.Series(False, index=frame.index)
        extra_pass = pd.Series(True, index=frame.index)
    combined_pass = base_pass & extra_pass
    assert np.array_equal(combined_pass, frame.confirmation_pass.astype(bool))
    assert np.array_equal(opportunity & ~combined_pass, frame.signal_reason.eq('confirmation_rejected'))
    assert np.array_equal(opportunity & combined_pass, frame.signal_reason.eq('entry'))
    frame['signal_year'] = pd.to_datetime(frame.signal_date).dt.year
    frame['next_valid_session_year'] = pd.to_datetime(frame.valid_session).dt.year
    masks = {'base_opportunities': opportunity,
             'base_gate_applied_opportunities': opportunity & base_applies,
             'base_gate_failed_opportunities': opportunity & ~base_pass,
             'extra_gate_applied_opportunities': opportunity & actual_applies,
             'extra_gate_failed_opportunities': opportunity & ~extra_pass,
             'both_gates_failed_opportunities': opportunity & ~base_pass & ~extra_pass,
             'only_base_gate_failed_opportunities': opportunity & ~base_pass & extra_pass,
             'only_extra_gate_failed_opportunities': opportunity & base_pass & ~extra_pass,
             'confirmation_rejected_signals': frame.signal_reason.eq('confirmation_rejected'),
             'entry_signals': frame.signal_reason.eq('entry'),
             'execution_buy_decisions': frame.action.eq('BUY')}
    for name, mask in masks.items():
        frame[name] = mask.astype(int)
    orders = execution.orders.loc[execution.orders.side.eq('BUY')]
    fills = execution.fills.loc[execution.fills.side.eq('BUY')]
    frame['actual_buy_orders'] = frame.decision_id.map(orders.groupby('decision_id').size()).fillna(0).astype(int)
    frame['actual_buy_fills'] = frame.decision_id.map(fills.groupby('decision_id').size()).fillna(0).astype(int)
    frame['actual_buy_order_decisions'] = frame.actual_buy_orders.gt(0).astype(int)
    frame['actual_buy_fill_decisions'] = frame.actual_buy_fills.gt(0).astype(int)
    counts = list(masks) + ['actual_buy_orders', 'actual_buy_fills',
                           'actual_buy_order_decisions', 'actual_buy_fill_decisions']
    groups = frame.groupby(['signal_year', 'next_valid_session_year', 'regime',
                            'confirmation_exit_context'], dropna=False)[counts].sum().reset_index()
    buy_fill_years = []
    dated_fills = fills.assign(fill_year=pd.to_datetime(fills.fill_time).dt.year)
    lookup = frame.set_index('decision_id')
    dated_fills = dated_fills.assign(
        entry_route=dated_fills.decision_id.map(lookup.regime),
        signal_exit_context=dated_fills.decision_id.map(lookup.confirmation_exit_context))
    for keys, subset in dated_fills.groupby(['fill_year', 'entry_route', 'signal_exit_context'], dropna=False):
        buy_fill_years.append({'fill_year': int(keys[0]), 'entry_route': keys[1],
                              'signal_exit_context': keys[2], 'buy_fills': len(subset),
                              'distinct_buy_decisions': int(subset.decision_id.nunique()),
                              'distinct_cycles': int(subset.cycle_id.nunique()),
                              'purchased_quantity': int(subset.quantity.sum()),
                              'buy_notional': float((subset.quantity * subset.price).sum()),
                              'buy_fees': float(subset.fees.sum())})
    return {'extra_gate_enabled': enabled, 'gate_masks': 'EXACT_EQUAL',
            'totals': {name: int(frame[name].sum()) for name in counts},
            'signal_year_route_exit_context_groups': plain(groups.to_dict('records')),
            'actual_buy_fill_year_route_exit_context_groups': plain(buy_fill_years),
            'buy_order_status_counts': {str(key): int(value) for key, value in orders.status.value_counts().items()},
            'reason_action_counts': plain(frame.groupby(['signal_reason', 'action']).size()
                                         .rename('decisions').reset_index().to_dict('records'))}


def year_cycle_groups(cycles):
    closed = [row for row in cycles if row['status'] == 'CLOSED']
    for row in closed:
        row['short_holding_le_3_sessions'] = row['holding_sessions'] <= 3
    negative_years = [row for row in closed if row['exit_fill_year'] in (2022, 2023)]
    return {'short_holding_definition': 'actual fill session difference <= 3; diagnostic only',
            'all_exit_year_route_short_groups': (describe(closed, ['exit_fill_year', 'entry_route',
                                                                  'short_holding_le_3_sessions']) if closed else []),
            '2022_2023_exit_year_route_reason_short_groups': describe(
                negative_years, ['exit_fill_year', 'entry_route', 'exit_reason', 'short_holding_le_3_sessions'])
                if negative_years else []}


def comparison(account, control):
    original = {row['year']: row for row in control['path']['annual_account']}
    annual = []
    for row in account['path']['annual_account']:
        parent = original[row['year']]
        annual.append({'year': row['year'], **{
            field + '_difference': row[field] - parent[field]
            for field in ('account_return', 'price_contribution', 'fee_contribution',
                          'price_pnl', 'fees', 'net_pnl', 'opening_equity', 'closing_equity')}})
    return {'control_id': control['candidate_id'],
            'closed_cycle_difference': account['path']['closed_cycles'] - control['path']['closed_cycles'],
            'net_cagr_difference': account['net_cagr'] - control['net_cagr'],
            'annual_continuous_account_differences': annual,
            'interpretation': 'Full-path differences against exact disabled controls; groups are descriptive, not isolated causal effects.'}


def main():
    for path in RUNS.glob('cost_confirmation_*.json'):
        content = read(path)
        if 'rows' in content:
            assert content['status'] == 'COMPLETE', f'Search not complete: {path.name}'
    records = rows()
    assert len({row['candidate_id'] for row in records}) == len(records)
    accounts, unsuccessful = [], []
    for row in records:
        if row['status'] != 'SUCCEEDED':
            unsuccessful.append(row)
            continue
        bound, result = cache_read(CACHE / f'{row["candidate_id"]}.pkl.gz')
        assert result.result_hash == row['result_hash']
        assert len(result.runs) == 1 and result.runs[0].scenario_id == 'baseline'
        proof = verify_account(bound, result)
        for year, values in proof['annual'].items():
            assert abs(values['net_return'] - row['annual'][year]['return']) < 1e-12
            assert abs(values['drawdown_magnitude'] - row['annual'][year]['max_drawdown_magnitude']) < 1e-12
        path = inspect_run(result.runs[0])
        assert path['closed_cycles'] == row['closed_trades']
        accounts.append({'candidate_id': row['candidate_id'], 'parent': row['parent'],
                         'label': row['label'], 'search': row['search'],
                         'result_hash': result.result_hash, 'qualified': row['qualified'],
                         'gates': row['gates'], 'net_cagr': row['net_cagr'],
                         'parameters': row['parameters'], 'full_account_checks': proof,
                         'path': path, 'cycle_groups': year_cycle_groups(path['cycles']),
                         'decisions': summarize_decisions(result.runs[0].execution, row['parameters'])})
    lookup = {account['candidate_id']: account for account in accounts}
    assert set(CONTROLS.values()) <= lookup.keys()
    for account in accounts:
        assert account['parent'] in CONTROLS, account['parent']
        account['parent_control_comparison'] = comparison(account, lookup[CONTROLS[account['parent']]])
    write(RUNS / 'path_attribution.json', {
        'status': 'PASS', 'candidate_count': len(records), 'successful_accounts': len(accounts),
        'unsuccessful_configurations': unsuccessful,
        'coverage': 'All declared successful EX007 configurations, irrespective of qualification.',
        'controls': CONTROLS, 'diagnostic_only': True,
        'limits': ['Only the authorized, previously seen S013 developer pool is reused.',
                   'Opportunity and entry signals describe internal strategy state; BUY decisions, orders and actual fills are counted separately.',
                   'Signal-year and next-valid-session-year counts can differ at year boundaries; actual-fill-year groups use fills.',
                   'Cycle entry/exit-year groups are descriptive and cannot replace continuous annual account returns.',
                   'Route, short holding and profit concentration diagnostics add no acceptance gate.',
                   'Existing minute Low/High discrepancy limitations are retained in full account checks.'],
        'accounts': accounts})
    print({'status': 'PASS', 'successful_accounts': len(accounts),
           'unsuccessful_configurations': len(unsuccessful), 'candidate_count': len(records)})


if __name__ == '__main__':
    main()
