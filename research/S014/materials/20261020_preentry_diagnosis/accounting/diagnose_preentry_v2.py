"""Preserve first extraction; missing outcomes stay null also in empty groups.

The original attempt rows already leave failed-BUY outcomes blank. This adapter
also leaves aggregate outcome fields null when no actual filled/closed cycle
exists, instead of interpreting an empty sum as an observed zero return.
"""
import importlib.util
from pathlib import Path


PATH = Path(__file__).resolve().with_name('diagnose_preentry.py')
SPEC = importlib.util.spec_from_file_location('account_only_preentry', PATH)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
ORIGINAL_AGGREGATE = M.aggregate
ORIGINAL_OUTPUT = M.output


def aggregate(rows, keynames):
    groups = ORIGINAL_AGGREGATE(rows, keynames)
    for group in groups:
        if group['filled_entries'] == 0:
            for key in ['entryday_negative_net_count', 'entryday_gross_pnl', 'actual_buy_fees',
                        'entryday_net_pnl', 'entryday_net_annual_contribution_pp',
                        'Dclose_to_fill_price_bridge_money_NOT_account_pnl']:
                group[key] = None
        if group['closed_next_cycles'] == 0:
            group['closed_next_cycle_negative_count'] = None
            group['closed_next_cycle_net_pnl'] = None
    return groups


def output(name, value, is_csv=False):
    revised_name = name.replace('.csv', '_v2.csv').replace('.json', '_v2.json')
    if name == 'preentry_accounting_summary.json':
        value['base_implementation'] = value['implementation']
        value['implementation'] = M.digest(Path(__file__).resolve())
        value['supersedes_preliminary'] = M.digest(PATH.with_name('preentry_accounting_summary.json'))
        value['empty_group_rule'] = 'No actual fills => aggregate entry outcomes null; no closed cycles => aggregate closed-cycle outcomes null. Counts of observations remain counts.'
    return ORIGINAL_OUTPUT(revised_name, value, is_csv)


M.aggregate = aggregate
M.output = output

if __name__ == '__main__':
    M.main()
