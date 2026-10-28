"""Describe actual closed-cycle exits in authenticated, published EX011 accounts.

Use analyze.load_accounts/EvidenceRef to authenticate retained account bytes.
Join fills -> orders.order_id -> decisions.decision_id, then group fills by the
closed trade's cycle_id. Classification uses explicit English-keyed structured
facts, not guessed meanings from timestamps, PnL, or free-form reason strings.
Unknown/missing explanation facts remain UNKNOWN; invalid ledger joins fail.

SESSION_END means the recorded last-interval branch caused the actual sell. That
branch has priority over stop calculation: it DOES NOT establish that the same
completed close could not also trigger a stop. STOP_TRIGGERED means the recorded
stop_hit/first_trigger_at facts explicitly establish the latched stop branch.
OVERNIGHT_RESIDUAL means the explicit overnight_residual fact and actual entry
date establish delayed liquidation, not voluntary overnight holding.

Cycle net_pnl is copied from closed trades; cycle fees are both entry and exit
fees from their actual fills. Partition sums reconcile to all closed trades and
fill fees, reported metrics, and terminal flat equity. Per-year groups use the
actual exit interval's local date. This is a descriptive ledger partition, not a
new economic audit, public diagnosis, account replay, return forecast, causal
claim, zero-fee reconstruction or counterfactual overnight strategy. No private
checkpoint, market-price read, fee addback, or modification of frozen rules.
"""
from collections import Counter, defaultdict
from datetime import datetime
from hashlib import sha256
import math
from pathlib import Path
from zoneinfo import ZoneInfo

from analyze import load_accounts
from run import WORK, EXPERIMENT, save


CATEGORIES = ('SESSION_END', 'STOP_TRIGGERED', 'OVERNIGHT_RESIDUAL', 'UNKNOWN')
ZONE = ZoneInfo('America/New_York')


def at(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def index_unique(rows, key):
    indexed = {row[key]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError('duplicate ledger identity: ' + key)
    return indexed


def equal(left, right, label):
    if not math.isclose(left, right, rel_tol=1e-10, abs_tol=1e-5):
        raise ValueError('ledger partition does not reconcile: ' + label)
    return left-right


def classify(decision):
    explanation = decision.get('explanation')
    if not isinstance(explanation, dict):
        return 'UNKNOWN', {}, 'MISSING_EXPLANATION'
    basis = explanation.get('basis', [])
    facts = {row['key']: row['text'] for row in basis}
    if len(facts) != len(basis):
        return 'UNKNOWN', facts, 'DUPLICATE_FACT_KEYS'
    if (decision['side'] != 'SELL' or decision['target'] != 0
            or explanation.get('case_key') != 'flat' or facts.get('held') != 'True'):
        return 'UNKNOWN', facts, 'NO_EXPLICIT_HELD_TO_FLAT_FACT'
    try:
        entry = at(facts['actual_entry']).astimezone(ZONE).date()
        session_date = at(decision['execution_start']).astimezone(ZONE).date()
        if facts['session_date'] != session_date.isoformat():
            return 'UNKNOWN', facts, 'SESSION_FACT_DISAGREES_WITH_EXECUTION'
        if facts.get('overnight_residual') == 'True':
            if entry < session_date:
                return 'OVERNIGHT_RESIDUAL', facts, 'EXPLICIT_OVERNIGHT_RESIDUAL_TRUE_AND_PRIOR_ENTRY'
            return 'UNKNOWN', facts, 'OVERNIGHT_FACT_DISAGREES_WITH_ENTRY'
        if (facts.get('last_execution_interval') == 'True' and entry == session_date
                and at(facts['session_end']) == at(decision['execution_end'])):
            return 'SESSION_END', facts, 'EXPLICIT_LAST_INTERVAL_HELD_TO_FLAT'
        if (facts.get('stop_hit') == 'True' and facts.get('first_trigger_at') not in (None, 'None', '')
                and facts.get('last_execution_interval') == 'False' and entry == session_date
                and at(facts['first_trigger_at']) <= at(decision['observed_through'])):
            return 'STOP_TRIGGERED', facts, 'EXPLICIT_STOP_HIT_TRUE_AND_OBSERVED_TRIGGER'
    except (ValueError, KeyError, TypeError):
        return 'UNKNOWN', facts, 'INCOMPLETE_OR_INVALID_TIME_FACTS'
    return 'UNKNOWN', facts, 'NO_UNAMBIGUOUS_RECORDED_BRANCH'


def aggregate(rows):
    return {'closed_cycles': len(rows),
            'net_pnl': math.fsum(row['net_pnl'] for row in rows),
            'fees': math.fsum(row['fees'] for row in rows),
            'positive_cycles': sum(row['net_pnl'] > 0 for row in rows),
            'negative_cycles': sum(row['net_pnl'] < 0 for row in rows),
            'zero_cycles': sum(row['net_pnl'] == 0 for row in rows)}


def describe(payload):
    run = payload['runs']['candidate']
    decisions = index_unique(run['decisions'], 'decision_id')
    orders = index_unique(run['orders'], 'order_id')
    fills = index_unique(run['fills'], 'fill_id')
    trades = index_unique(run['trades'], 'cycle_id')
    grouped = defaultdict(list)
    for fill in fills.values():
        order = orders[fill['order_id']]
        decision = decisions[order['decision_id']]
        if (order['status'] != 'FILLED' or fill['side'] != order['side']
                or order['side'] != decision['side'] or fill['quantity'] != order['quantity']
                or at(fill['interval_start']) != at(order['valid_start'])
                or at(fill['interval_end']) != at(order['valid_end'])
                or at(fill['interval_start']) != at(decision['execution_start'])
                or at(fill['interval_end']) != at(decision['execution_end'])):
            raise ValueError('actual fill/order/decision relationship differs')
        grouped[fill['cycle_id']].append((fill, order, decision))
    if set(grouped) != set(trades) or any(row['status'] != 'CLOSED' for row in trades.values()):
        raise ValueError('this description requires all actual cycles to be closed')
    rows = []
    for cycle_id, trade in trades.items():
        entries = [item for item in grouped[cycle_id] if item[0]['side'] == 'BUY']
        exits = [item for item in grouped[cycle_id] if item[0]['side'] == 'SELL']
        if len(entries) != 1 or len(exits) != 1 or entries[0][0]['quantity'] != exits[0][0]['quantity']:
            raise ValueError('this fixed BAR_RANGE description requires one whole entry and exit')
        entry_fill, _, _ = entries[0]
        exit_fill, order, decision = exits[0]
        if at(trade['entry_at']) != at(entry_fill['interval_start']) or at(trade['exit_at']) != at(exit_fill['interval_end']):
            raise ValueError('closed trade times differ from actual fills')
        equal(trade['income']-trade['cost'], trade['net_pnl'], 'recorded cycle net pnl')
        category, facts, basis = classify(decision)
        rows.append({'cycle_id': cycle_id, 'category': category, 'classification_basis': basis,
                     'entry_at': trade['entry_at'], 'exit_at': trade['exit_at'],
                     'exit_session': at(exit_fill['interval_start']).astimezone(ZONE).date().isoformat(),
                     'exit_order_id': order['order_id'], 'exit_decision_id': order['decision_id'],
                     'exit_fill_id': exit_fill['fill_id'], 'entry_fill_id': entry_fill['fill_id'],
                     'net_pnl': trade['net_pnl'],
                     'fees': math.fsum(fill['fees'] for fill, _, _ in grouped[cycle_id]),
                     'recorded_exit_facts': facts,
                     'recorded_judgment': (decision.get('explanation') or {}).get('judgment')})
    totals = aggregate(rows)
    categories = {name: aggregate([row for row in rows if row['category'] == name]) for name in CATEGORIES}
    by_year = {str(year): {name: aggregate([row for row in rows if row['category'] == name
               and row['exit_session'].startswith(str(year))]) for name in CATEGORIES}
               for year in range(2019, 2026)}
    final = run['account_points'][-1]
    if final['quantity'] != 0 or final['receivable'] != 0:
        raise ValueError('terminal account is not fully flat and settled')
    if totals['closed_cycles'] != run['metrics']['closed_cycles']:
        raise ValueError('cycle count differs from published account metric')
    residuals = {
        'class_count_minus_closed_cycles': sum(row['closed_cycles'] for row in categories.values())-totals['closed_cycles'],
        'classes_pnl_minus_trade_pnl': equal(math.fsum(row['net_pnl'] for row in categories.values()),
            math.fsum(row['net_pnl'] for row in run['trades']), 'classes vs trades pnl'),
        'classes_fees_minus_fill_fees': equal(math.fsum(row['fees'] for row in categories.values()),
            math.fsum(row['fees'] for row in run['fills']), 'classes vs fills fees'),
        'fill_fees_minus_metric_fees': equal(totals['fees'], run['metrics']['fees'], 'fills vs reported fees'),
        'trade_pnl_minus_final_equity_change': equal(totals['net_pnl'],
            final['equity']-payload['request']['initial_cash'], 'closed pnl vs terminal flat equity'),
    }
    return {'status': 'PASS', 'classification_complete': categories['UNKNOWN']['closed_cycles'] == 0,
            'totals': totals, 'by_exit_purpose': categories, 'by_exit_year': by_year,
            'actual_order_statuses': dict(Counter(row['status'] for row in run['orders'])),
            'terminal_equity': final['equity'], 'terminal_quantity': final['quantity'],
            'reconciliation': residuals, 'closed_cycles': rows}


def main():
    keys = ('C0036', 'C0037')
    payloads, references = load_accounts(WORK, EXPERIMENT, keys, exact=True)
    report = {'schema': 'S017_ACTUAL_EXIT_PURPOSE_DESCRIPTION_V1',
              'script_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'source_accounts': {key: ref.to_dict() for key, ref in references.items()},
              'account_identity_verification': 'PUBLIC_EVIDENCEREF_BYTES_AND_RECORDED_IDENTITIES_BOUND',
              'scope': 'PUBLISHED_CANDIDATE_ACCOUNTS_2019_2025_ONLY',
              'limitations': ['DESCRIPTIVE_PARTITION_NOT_PUBLIC_ECONOMIC_AUDIT',
                  'SESSION_END_DOES_NOT_ASSERT_STOP_WOULD_NOT_ALSO_TRIGGER',
                  'NET_PNL_COPIED_FROM_CLOSED_TRADES_FEES_FROM_ACTUAL_FILLS',
                  'NO_FEE_ADDBACK_NO_COUNTERFACTUAL_NO_CAUSAL_CLAIM',
                  'NO_PRIVATE_CHECKPOINT_NO_NEW_DIAGNOSIS_NO_2026_PRICE'],
              'accounts': {key: describe(payloads[key]) for key in keys}}
    save(WORK/'others/exit_purpose_description.json', report)
    for key, value in report['accounts'].items():
        print(key, value['by_exit_purpose'], value['reconciliation'], flush=True)


if __name__ == '__main__':
    main()
