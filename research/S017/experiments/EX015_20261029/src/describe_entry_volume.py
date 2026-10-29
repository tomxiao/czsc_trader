"""Describe C0044's realized entry-volume groups; never construct a filtered account.

Classify actual BUY decisions by opening_volume > prior_opening_mean_volume
(14 previous session openings). Unknown facts remain UNKNOWN. Reconcile every
closed cycle, both fill fees, trade cash flow and the terminal flat account.
Read only published accounts and already retained public diagnoses. No new replay,
diagnosis, price request, fee addback, trade deletion or causal-return estimate.
"""
from collections import Counter, defaultdict
from dataclasses import asdict
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

from czsc_trader.research_tools import EvidenceRef, ExperimentRef
from analyze import load_accounts, summarize_run, ECONOMIC_FIELDS
from run import ROOT, WORK, EXPERIMENT, save

GROUPS = ('TRUE', 'FALSE', 'UNKNOWN')
ZONE = ZoneInfo('America/New_York')
HELPER_PATH = ROOT / 'research/S017/experiments/EX011_20261029/src/describe_exits.py'
spec = spec_from_file_location('_s017_retained_ledger_description', HELPER_PATH)
ledger = module_from_spec(spec)
spec.loader.exec_module(ledger)


def classify_entry(decision):
    """Use recorded entry facts, never the disabled gate's volume_allowed=True."""
    basis = (decision.get('explanation') or {}).get('basis', [])
    facts = {row['key']: row['text'] for row in basis}
    if len(facts) != len(basis):
        return 'UNKNOWN', 'DUPLICATE_FACT_KEYS', facts, None
    if decision.get('side') != 'BUY' or decision.get('target') != 1 or facts.get('held') != 'False':
        return 'UNKNOWN', 'NO_EXPLICIT_FLAT_TO_LONG_BUY', facts, None
    if facts.get('opening_observed') != 'True' or facts.get('relative_volume_sessions') != '14':
        return 'UNKNOWN', 'MISSING_COMPLETE_14_SESSION_OPENING_BASIS', facts, None
    try:
        opening, prior = (float(facts[name]) for name in ('opening_volume', 'prior_opening_mean_volume'))
    except (KeyError, TypeError, ValueError):
        return 'UNKNOWN', 'MISSING_OR_NONNUMERIC_VOLUME_FACT', facts, None
    if not math.isfinite(opening) or not math.isfinite(prior) or opening <= 0 or prior <= 0:
        return 'UNKNOWN', 'NONFINITE_OR_NONPOSITIVE_VOLUME_FACT', facts, None
    return ('TRUE' if opening > prior else 'FALSE'), 'STRICT_RECORDED_OPENING_VOLUME_GT_PRIOR14_MEAN', facts, opening / prior


def distribution(values):
    values = sorted(values)
    if not values:
        return {'count': 0, 'min': None, 'q25': None, 'median': None, 'q75': None,
                'q95': None, 'max': None, 'mean': None}

    def quantile(q):
        position = q * (len(values) - 1)
        low, high = math.floor(position), math.ceil(position)
        return values[low] + (values[high] - values[low]) * (position - low)

    return {'count': len(values), 'min': values[0], 'q25': quantile(.25), 'median': quantile(.5),
            'q75': quantile(.75), 'q95': quantile(.95), 'max': values[-1],
            'mean': math.fsum(values) / len(values)}


def aggregate(rows):
    values = ledger.aggregate(rows)
    positive = sorted((row['net_pnl'] for row in rows if row['net_pnl'] > 0), reverse=True)
    losses = math.fsum(row['net_pnl'] for row in rows if row['net_pnl'] < 0)
    gains = math.fsum(positive)
    values.update(positive_net_pnl_sum=gains, negative_net_pnl_sum=losses,
        positive_cycle_fraction=values['positive_cycles'] / len(rows) if rows else None,
        profit_factor=gains / -losses if losses < 0 else None,
        net_pnl_distribution=distribution([row['net_pnl'] for row in rows]),
        recorded_net_return_distribution=distribution([row['net_return'] for row in rows]),
        holding_calendar_days_distribution=distribution([row['holding_calendar_days'] for row in rows]),
        top_1_positive_pnl=math.fsum(positive[:1]), top_3_positive_pnl=math.fsum(positive[:3]),
        top_5_positive_pnl=math.fsum(positive[:5]),
        top_3_share_of_positive_pnl=math.fsum(positive[:3]) / gains if gains > 0 else None)
    return values


def describe(payload):
    account = payload['runs']['candidate']
    decisions = ledger.index_unique(account['decisions'], 'decision_id')
    orders = ledger.index_unique(account['orders'], 'order_id')
    fills = ledger.index_unique(account['fills'], 'fill_id')
    trades = ledger.index_unique(account['trades'], 'cycle_id')
    grouped = defaultdict(list)
    for fill in fills.values():
        order = orders[fill['order_id']]
        decision = decisions[order['decision_id']]
        if (order['status'] != 'FILLED' or fill['side'] != order['side']
                or order['side'] != decision['side'] or fill['quantity'] != order['quantity']
                or ledger.at(fill['interval_start']) != ledger.at(order['valid_start'])
                or ledger.at(fill['interval_end']) != ledger.at(order['valid_end'])
                or ledger.at(fill['interval_start']) != ledger.at(decision['execution_start'])
                or ledger.at(fill['interval_end']) != ledger.at(decision['execution_end'])):
            raise ValueError('actual fill/order/decision identity or execution interval differs')
        ledger.equal(fill['fees'], fill['quantity'] * fill['price'] * payload['request']['fee_rate'],
                     'actual fee versus unchanged per-side fee contract')
        grouped[fill['cycle_id']].append((fill, order, decision))
    if set(grouped) != set(trades) or any(row['status'] != 'CLOSED' for row in trades.values()):
        raise ValueError('description requires every actual cycle to be closed')
    rows = []
    for cycle_id, trade in trades.items():
        entries = [item for item in grouped[cycle_id] if item[0]['side'] == 'BUY']
        exits = [item for item in grouped[cycle_id] if item[0]['side'] == 'SELL']
        if len(entries) != 1 or len(exits) != 1 or entries[0][0]['quantity'] != exits[0][0]['quantity']:
            raise ValueError('one whole entry and exit required for each realized cycle')
        entry, entry_order, entry_decision = entries[0]
        exit_fill, exit_order, _ = exits[0]
        if (ledger.at(trade['entry_at']) != ledger.at(entry['interval_start'])
                or ledger.at(trade['exit_at']) != ledger.at(exit_fill['interval_end'])):
            raise ValueError('trade times differ from original fills')
        ledger.equal(trade['cost'], entry['quantity'] * entry['price'] + entry['fees'], 'entry cash cost')
        ledger.equal(trade['income'], exit_fill['quantity'] * exit_fill['price'] - exit_fill['fees'], 'exit cash income')
        ledger.equal(trade['net_pnl'], trade['income'] - trade['cost'], 'recorded net cycle pnl')
        if not math.isclose(trade['net_return'], trade['net_pnl'] / trade['cost'], rel_tol=1e-8, abs_tol=5e-10):
            raise ValueError('recorded cycle net return differs from cash flow')
        category, reason, facts, ratio = classify_entry(entry_decision)
        entry_session = ledger.at(entry['interval_start']).astimezone(ZONE).date()
        if facts.get('session_date') not in (None, entry_session.isoformat()):
            raise ValueError('entry session fact differs from actual entry time')
        rows.append({'cycle_id': cycle_id, 'group': category, 'classification_basis': reason,
            'entry_at': trade['entry_at'], 'exit_at': trade['exit_at'], 'entry_session': entry_session.isoformat(),
            'entry_year': entry_session.year, 'entry_fill_id': entry['fill_id'],
            'entry_order_id': entry_order['order_id'], 'entry_decision_id': entry_order['decision_id'],
            'exit_fill_id': exit_fill['fill_id'], 'exit_order_id': exit_order['order_id'],
            'exit_decision_id': exit_order['decision_id'], 'opening_relative_volume': ratio,
            'recorded_entry_facts': facts, 'net_pnl': trade['net_pnl'], 'net_return': trade['net_return'],
            'entry_fee': entry['fees'], 'exit_fee': exit_fill['fees'],
            'fees': math.fsum(item[0]['fees'] for item in grouped[cycle_id]),
            'holding_calendar_days': (ledger.at(trade['exit_at']) - ledger.at(trade['entry_at'])).total_seconds() / 86400.})
    if any(row['entry_year'] not in range(2019, 2026) for row in rows):
        raise ValueError('entry cohort outside the authorized development window')
    totals = aggregate(rows)
    groups = {name: aggregate([row for row in rows if row['group'] == name]) for name in GROUPS}
    years = {str(year): {name: aggregate([row for row in rows if row['entry_year'] == year
                                       and row['group'] == name]) for name in GROUPS}
             for year in range(2019, 2026)}
    final = account['account_points'][-1]
    if final['quantity'] != 0 or final['receivable'] != 0:
        raise ValueError('terminal account must be flat and settled for whole-account pnl reconciliation')
    if totals['closed_cycles'] != 368 or totals['closed_cycles'] != account['metrics']['closed_cycles']:
        raise ValueError('description must cover the exact 368 published C0044 closed cycles')
    if sum(item['closed_cycles'] for item in groups.values()) != totals['closed_cycles']:
        raise ValueError('group counts do not partition all actual cycles')
    residuals = {
        'groups_pnl_minus_trades': ledger.equal(math.fsum(item['net_pnl'] for item in groups.values()),
            math.fsum(row['net_pnl'] for row in account['trades']), 'group pnl versus all trades'),
        'groups_fees_minus_fills': ledger.equal(math.fsum(item['fees'] for item in groups.values()),
            math.fsum(row['fees'] for row in account['fills']), 'group fees versus all fills'),
        'fees_minus_metrics': ledger.equal(totals['fees'], account['metrics']['fees'], 'actual versus published fees'),
        'pnl_minus_terminal_equity': ledger.equal(totals['net_pnl'], final['equity'] - payload['request']['initial_cash'],
            'actual closed pnl versus terminal flat equity'),
    }
    for group in GROUPS:
        if sum(year[group]['closed_cycles'] for year in years.values()) != groups[group]['closed_cycles']:
            raise ValueError('entry-year counts do not partition group: ' + group)
        residuals[group + '_years_pnl'] = ledger.equal(
            math.fsum(year[group]['net_pnl'] for year in years.values()), groups[group]['net_pnl'], 'entry-year group pnl')
        residuals[group + '_years_fees'] = ledger.equal(
            math.fsum(year[group]['fees'] for year in years.values()), groups[group]['fees'], 'entry-year group fees')
    return {'status': 'PASS', 'classification_complete': groups['UNKNOWN']['closed_cycles'] == 0,
        'totals': totals, 'groups': groups, 'by_entry_year': years, 'reconciliation': residuals,
        'terminal_equity': final['equity'], 'actual_order_statuses': dict(Counter(row['status'] for row in orders.values())),
        'closed_cycles': rows}


def retained_diagnosis(experiment, name, references):
    analysis_path = experiment.resolve(ROOT) / 'others/analysis.json'
    if not analysis_path.is_file():
        return {'status': 'NOT_AVAILABLE_AT_DESCRIPTION', 'experiment': experiment.to_dict(),
                'name': name, 'new_diagnosis_requested': False}
    analysis_bytes = analysis_path.read_bytes()
    analysis = json.loads(analysis_bytes)
    item = analysis['diagnostics'][name]
    reference = EvidenceRef.from_dict(item['evidence'])
    data = reference.resolve(ROOT).read_bytes()
    if sha256(data).hexdigest() != reference.sha256:
        raise ValueError('retained public diagnosis changed after authentication')
    diagnosis = json.loads(data)
    subject, control = name.split('_vs_')
    if (reference.experiment != experiment or diagnosis['status'] != 'COMPUTED'
            or item['status'] != 'COMPUTED'
            or diagnosis['sources'] != [asdict(references[control]), asdict(references[subject])]):
        raise ValueError('retained diagnosis is not computed on the exact original account pair')
    return {'status': diagnosis['status'], 'evidence': reference.to_dict(), 'issues': diagnosis['issues'],
        'protocol': diagnosis['protocol'], 'sources': diagnosis['sources'], 'reconciliation': diagnosis['reconciliation'],
        'analysis_path': analysis_path.relative_to(ROOT).as_posix(), 'analysis_sha256': sha256(analysis_bytes).hexdigest()}


def main():
    values, references = load_accounts(WORK, EXPERIMENT, ('C0044',), exact=True)
    payload = values['C0044']
    description = describe(payload)
    primary = {'request': {field: payload['request'][field] for field in ECONOMIC_FIELDS}, 'data': payload['data']}
    contexts = {'C0044': summarize_run(payload['runs']['candidate'], payload['request']['initial_cash'])}
    del payload, values
    earlier = ExperimentRef('S017', 'EX011_20261029')
    for key in ('C0036', 'C0037'):
        values, refs = load_accounts(earlier.resolve(ROOT), earlier, (key,))
        payload = values[key]
        if ({field: payload['request'][field] for field in ECONOMIC_FIELDS} != primary['request']
                or payload['data'] != primary['data']):
            raise ValueError('original ORB comparison economic contract or source data differs')
        contexts[key] = summarize_run(payload['runs']['candidate'], payload['request']['initial_cash'])
        references.update(refs)
        del payload, values
    diagnoses = {'C0037_vs_C0036': retained_diagnosis(earlier, 'C0037_vs_C0036', references),
                 'C0044_vs_C0036': retained_diagnosis(EXPERIMENT, 'C0044_vs_C0036', references)}
    if diagnoses['C0037_vs_C0036']['status'] != 'COMPUTED':
        raise ValueError('the existing volume-gate public comparison must already be completed')
    report = {'schema': 'S017_C0044_ACTUAL_ENTRY_VOLUME_DESCRIPTION_V1', 'status': 'PASS',
        'source_accounts': {key: reference.to_dict() for key, reference in references.items()},
        'script_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
        'helper_sources': {path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()).hexdigest()
                           for path in (HELPER_PATH, WORK / 'src/analyze.py', WORK / 'src/run.py')},
        'scope': 'PUBLISHED_S017_C0044_ACTUAL_BUY_FACTS_AND_C0036_C0037_ORIGINAL_ACCOUNTS_ONLY',
        'classification': 'opening_volume > prior_opening_mean_volume at the actual BUY decision; 14 prior session openings; equality is FALSE; unknown facts remain UNKNOWN.',
        'distribution_method': 'Recorded cycle net_pnl/net_return; linear quantiles over sorted realized cycles. Undefined statistics are null.',
        'year_basis': 'ACTUAL_ENTRY_YEAR_AMERICA_NEW_YORK; whole cycle pnl attributed to its entry cohort, not calendar-year account return.',
        'description': description, 'original_account_summaries': contexts, 'retained_public_diagnoses': diagnoses,
        'limitations': ['DESCRIPTIVE_REALIZED_CYCLE_PARTITION_NOT_NEW_ECONOMIC_AUDIT',
            'UNKNOWN_NOT_FALSE; volume_allowed is ignored because C44 disables the actual volume gate.',
            'Dollar pnl uses each original cycle capital; group totals/means are not a filtered or equally funded account.',
            'Removing entries changes available cash, later entry opportunities, holding, fees and cycles; no trade-deletion counterfactual.',
            'C37/C36 diagnoses the volume gate only under original intraday holding; C44/C36 changes holding policy. Their interaction is not tested by this partition.',
            'Repeatedly observed development data and post-result grouping; no independence, causal or adoption claim.',
            'NO_PRIVATE_CHECKPOINT_NO_NEW_REPLAY_NO_NEW_DIAGNOSIS_NO_2026_PRICE']}
    save(WORK / 'others/entry_volume_description.json', report)
    print(json.dumps({'status': report['status'], 'totals': description['totals'],
        'groups': description['groups'], 'diagnoses': {key: value['status'] for key, value in diagnoses.items()}},
        ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
