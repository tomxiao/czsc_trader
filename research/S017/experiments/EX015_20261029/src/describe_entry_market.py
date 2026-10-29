"""Describe original C0044 cycles by the published C0043 SPY20 entry fact.

Read only public EvidenceRef-authenticated original accounts; bind immutable
strategy/definition materials, identical economic inputs/four main products/BH.
Reuse the retained whole-fill ledger join and market-fact classifier without
editing or executing either source's main(). Actual BUY fill -> order -> decision
must match the C0043 decision time and execution/observation boundaries exactly.
Absent, duplicate, stale or inconsistent context stays UNKNOWN, never False.

All original closed cycles retain ledger net_pnl/net_return and actual entry plus
exit fees. Quantiles describe cycle returns, not subgroup portfolios. Entry-year
tables use each original entry year and do not reset money or establish year
rules. Unclosed positions remain separate with null realized net_pnl/net_return;
terminal marked PnL is labelled and includes only fees actually paid. Original
whole-ledger identities reconcile, but no new public economic audit is invoked.

This post-result conditional description is subject to C0044's own capital,
holdings and opportunity selection. Deleting a group cannot estimate an SPY
filter or its interaction with overnight holding. No fee addback, synthetic
account, replay, public diagnosis, threshold search, other batch or 2026 prices.
"""
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path
import math
import sys

from czsc_trader.research_tools import ExperimentRef

from analyze import load_accounts, ECONOMIC_FIELDS, PRIMARY, economic
from run import ROOT, WORK, EXPERIMENT, save

sys.path.append(str(ROOT/'research/S017/experiments/EX011_20261029/src'))
sys.path.append(str(ROOT/'research/S017/experiments/EX014_20261029/src'))
from describe_entry_context import (bind_source, verify_market_source, classify_context,
                                    aggregate, groups, check_partition)
from describe_entry_difference import ledger
from describe_exits import at, equal


CONTEXT_EXPERIMENT = ExperimentRef('S017', 'EX014_20261029')


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def comparison_inputs(own, context):
    checks = []
    for field in ECONOMIC_FIELDS:
        if own['request'][field] != context['request'][field]:
            raise ValueError('entry description economic contract differs: '+field)
        checks.append('request.'+field)
    for product in PRIMARY:
        if own['data'][product] != context['data'][product]:
            raise ValueError('entry description main product identity differs: '+product)
        checks.append('primary.'+product)
    for field in ('account_points', 'account_daily', 'fills', 'trades', 'actions', 'metrics'):
        if economic(own['runs']['buy_hold'][field]) != economic(context['runs']['buy_hold'][field]):
            raise ValueError('entry description embedded BH economic path differs: '+field)
        checks.append('embedded_buy_hold.'+field)
    return {'status': 'PASS', 'checked_fields': checks,
            'note': 'Only implementation bookkeeping IDs excluded from BH path comparison.'}


def describe():
    """Return reproducible descriptive evidence without writes or account evaluation."""
    own, own_refs = load_accounts(WORK, EXPERIMENT, ('C0044',), exact=True)
    other, other_refs = load_accounts(CONTEXT_EXPERIMENT.resolve(ROOT), CONTEXT_EXPERIMENT,
                                     ('C0043',), exact=True)
    payload, context = own['C0044'], other['C0043']
    comparable = comparison_inputs(payload, context)
    definition, own_source = bind_source(WORK, EXPERIMENT, 'C0044', payload)
    context_definition, context_source = bind_source(CONTEXT_EXPERIMENT.resolve(ROOT),
                                                    CONTEXT_EXPERIMENT, 'C0043', context)
    if (definition.parameters != {'allow_overnight': True} or definition.auxiliary_inputs
            or definition.warmup_bars != 261 or not definition.session_context
            or definition.feedback_mode != 'CONFIRMED_CLOSED_CYCLE_V1'):
        raise ValueError('description requires the original fixed crossday C0044 input/holding policy')
    context_binding = verify_market_source(context, context_definition)
    cycles, reconciliation, decisions, _ = ledger(payload)
    by_time = defaultdict(list)
    for decision in context['runs']['candidate']['decisions']:
        by_time[at(decision['decision_at'])].append(decision)
    rows, open_rows = [], []
    for cycle in cycles:
        if not '2019-01-02' <= cycle['entry_session'] <= '2025-12-31':
            raise ValueError('cycle entry lies outside the fixed development window')
        origin = decisions[cycle['entry_decision_id']]
        if origin['side'] != 'BUY':
            raise ValueError('cycle entry is not an actual BUY decision')
        group, facts, basis = classify_context(origin, by_time[at(origin['decision_at'])], 432000)
        row = {**cycle, 'entry_market': group, 'market_facts': facts,
               'market_classification_basis': basis}
        (rows if cycle['status'] == 'CLOSED' else open_rows).append(row)
    if len(rows) != 368 or len(rows) != payload['runs']['candidate']['metrics']['closed_cycles']:
        raise ValueError('all original 368 C0044 closed cycles must be retained')
    total, grouped = aggregate(rows), groups(rows)
    years = {str(year): {
        'total': aggregate([row for row in rows if row['entry_session'].startswith(str(year))]),
        'market_groups': groups([row for row in rows if row['entry_session'].startswith(str(year))])}
        for year in range(2019, 2026)}
    residuals = {'market': check_partition(list(grouped.values()), total, 'market'),
                'entry_year': check_partition([value['total'] for value in years.values()], total, 'entry years')}
    for year, value in years.items():
        residuals[year] = check_partition(list(value['market_groups'].values()), value['total'], year)
    unclosed = {key: {
        'cycles': sum(row['entry_market'] == key for row in open_rows),
        'actual_paid_entry_fees': math.fsum(row['fees'] for row in open_rows if row['entry_market'] == key),
        'terminal_mark_pnl_after_paid_entry_fee': math.fsum(row['terminal_mark_pnl_after_paid_entry_fee']
            for row in open_rows if row['entry_market'] == key)} for key in ('TRUE', 'FALSE', 'UNKNOWN')}
    equal(total['fees']+math.fsum(value['actual_paid_entry_fees'] for value in unclosed.values()),
          payload['runs']['candidate']['metrics']['fees'], 'closed plus open paid fees')
    return {'schema': 'S017_C0044_ORIGINAL_ENTRY_MARKET_DESCRIPTION_V1', 'status': 'PASS',
        'scope': 'ORIGINAL_C0044_ACTUAL_CYCLES_2019_2025',
        'script_sha256': digest(Path(__file__)),
        'source_accounts': {**{key: ref.to_dict() for key, ref in own_refs.items()},
                            **{key: ref.to_dict() for key, ref in other_refs.items()}},
        'frozen_sources': {'C0044': own_source, 'C0043': context_source},
        'same_economic_primary_and_bh': comparable,
        'market_source_and_holding_independence': context_binding,
        'closed_cycle_totals': total, 'by_entry_market': grouped, 'by_entry_year': years,
        'closed_cycles': rows, 'unclosed_cycles_separate': open_rows, 'unclosed_by_entry_market': unclosed,
        'unknown_reasons': dict(Counter(row['market_classification_basis']
            for row in (*rows, *open_rows) if row['entry_market'] == 'UNKNOWN')),
        'partition_reconciliation_residuals': residuals, 'original_ledger_reconciliation': reconciliation,
        'public_diagnosis_read_or_invoked': False,
        'method_sources': [{'path': path.relative_to(ROOT).as_posix(), 'sha256': digest(path)} for path in (
            WORK/'src/analyze.py',
            ROOT/'research/S017/experiments/EX014_20261029/src/describe_entry_difference.py',
            ROOT/'research/S017/experiments/EX011_20261029/src/describe_entry_context.py',
            ROOT/'research/S017/experiments/EX011_20261029/src/describe_exits.py')],
        'limitations': ['CONDITIONAL_ORIGINAL_EXECUTED_TRADES_NOT_FILTER_COUNTERFACTUAL',
            'OWN_HOLDINGS_CAPITAL_AND_OPPORTUNITY_SELECTION', 'UNKNOWN_RETAINED_NOT_FALSE',
            'CYCLE_RETURN_DISTRIBUTION_NOT_SUBGROUP_ACCOUNT_RETURN',
            'ENTRY_YEAR_DESCRIPTION_NOT_YEARLY_PORTFOLIO_PERFORMANCE_OR_RULE',
            'UNCLOSED_REALIZED_PNL_NULL_ACTUAL_TERMINAL_MARK_SEPARATE_NO_HYPOTHETICAL_SELL_FEE',
            'DESCRIPTIVE_RECONCILIATION_NOT_PUBLIC_ECONOMIC_DIAGNOSIS',
            'NO_FEE_ADDBACK_NO_REPLAY_NO_NEW_DIAGNOSIS_NO_NEW_THRESHOLD_NO_2026_PRICE']}


def main():
    report = describe()
    save(WORK/'others/entry_market_description.json', report)
    print('C0044_ENTRY_MARKET PASS', report['by_entry_market'], flush=True)
    print('UNCLOSED', report['unclosed_by_entry_market'], flush=True)
    for year, value in report['by_entry_year'].items():
        print(year, {key: {'cycles': item['cycles'], 'net_pnl': item['net_pnl'], 'fees': item['fees']}
                     for key, item in value['market_groups'].items()}, flush=True)


if __name__ == '__main__':
    main()
