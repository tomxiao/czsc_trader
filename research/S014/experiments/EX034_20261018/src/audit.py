"""Independent Decimal arithmetic audit of the already-produced EX034 nodes.

This program never imports the primary calculator, matches an order, or creates
an additional sample. It only verifies the fixed result file against old public
evidence. Run only after the primary result exists.
"""
from collections import Counter
import csv
from decimal import Decimal
from hashlib import sha256
import io
import json
from pathlib import Path
import socket

from czsc_trader.research_tools import EvidenceRef

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
METHOD = ROOT / 'research/S014/materials/20261018_action_value_method_review'
MONEY_TOL = Decimal('0.0000001')
RETURN_TOL = Decimal('0.0000000001')


def dec(value):
    return Decimal(str(value))


def date(value):
    return str(value)[:10] if value else None


def sign(value):
    return int(value > RETURN_TOL) - int(value < -RETURN_TOL)


def terminal_value(cash, quantity, mark, sale_day, sale_price, sale_fee, terminal):
    if sale_day is not None and sale_day <= terminal:
        return cash + quantity * sale_price - sale_fee
    return cash + quantity * mark


def main():
    def blocked(*args, **kwargs):
        raise RuntimeError('Independent offline audit: network forbidden')
    socket.socket.connect = blocked
    socket.create_connection = blocked
    sources, checks = {}, []

    def check(name, condition):
        checks.append({'name': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)

    def read(path):
        raw = path.read_bytes()
        sources[path.relative_to(ROOT).as_posix()] = sha256(raw).hexdigest()
        return raw

    # The existence of main results is an execution boundary, not a source of
    # sample eligibility or the independently reconstructed reference values.
    actual = list(csv.DictReader(io.StringIO(read(EX / 'others/events.csv').decode())))
    summary = json.loads(read(EX / 'others/summary.json'))
    precheck = json.loads(read(EX / 'others/precheck.json'))
    budget_attempts = json.loads(read(EX / 'others/attempts.json'))
    main_source = read(EX / 'src/analyze.py')
    design = json.loads(read(EX / 'protocols/design.json'))
    inventory = json.loads(read(METHOD / 'inventory.json'))
    check('Fixed approved caps', design['execution_authorized'] and design['proposed_caps']['decision_node_groups'] == 146)
    check('Declared numeric tolerances', dec(design['sign_zero_tolerance']) == RETURN_TOL and dec(design['monetary_comparison_absolute_tolerance']) == MONEY_TOL)
    check('Primary source linked to synthetic precheck and results', precheck['status'] == 'PASS' and sha256(main_source).hexdigest() == precheck['source_sha256'] == summary['source_sha256'])
    check('Main event hash', summary['events_sha256'] == sources[(EX / 'others/events.csv').relative_to(ROOT).as_posix()])
    for source_path, identity in inventory['sources'].items():
        if source_path == 'public_account_C0011':
            continue
        raw = read(ROOT / source_path)
        check('Source hash ' + source_path, sha256(raw).hexdigest() == identity['sha256'])
        if 'public_ref' in identity:
            ref = EvidenceRef.from_dict(identity['public_ref'])
            check('Published identity ' + source_path, ref.resolve(ROOT).read_bytes() == raw and ref.sha256 == sha256(raw).hexdigest())
    account_ref = EvidenceRef.from_dict(inventory['sources']['public_account_C0011']['public_ref'])
    account_raw = account_ref.resolve(ROOT).read_bytes()
    check('Public C0011 account identity', sha256(account_raw).hexdigest() == account_ref.sha256)
    account = json.loads(account_raw)
    check('C0011 result identity', account['result_hash'] == inventory['sources']['public_account_C0011']['result_hash'])
    ledger = account['runs'][0]['ledgers']
    daily = {date(r['date']): r for r in ledger['account_daily']['data']}
    trades = ledger['trades']['data']
    fills = ledger['fills']['data']
    dates = [r['date'] for r in csv.DictReader(io.StringIO((ROOT / 'research/S014/experiments/EX033_20261018/others/calendar.csv').read_text()))]
    members = {r['cycle_id']: r for r in csv.DictReader(io.StringIO((ROOT / 'research/S014/experiments/EX019_20261017/others/state_diagnostics_v2_members.csv').read_text()))}
    attempts = list(csv.DictReader(io.StringIO((ROOT / 'research/S014/experiments/EX019_20261017/others/state_diagnostics_v2_fill_attempts.csv').read_text())))
    check('Original inventory conserved', len(trades) == len(members) == 147 and len(dates) == len(daily) == 1642)

    expected, censored = {}, []
    for trade in trades:
        cycle = trade['cycle_id']
        entry = date(trade['entry_date'])
        pos = dates.index(entry)
        if pos + 6 >= len(dates):
            censored.append(cycle)
            continue
        decision, terminal = dates[pos + 2], dates[pos + 6]
        d, t, member = daily[decision], daily[terminal], members[cycle]
        quantity, cash, wealth = dec(trade['quantity']), dec(d['cash']), dec(d['equity'])
        check(cycle + ' D holdings and equity', dec(d['quantity']) == quantity and abs(wealth-cash-quantity*dec(d['close'])) <= MONEY_TOL)
        check(cycle + ' Dates and old quantity', member['decision_date'] == decision and member['extended_target_exit'] == terminal and dec(member['quantity']) == quantity)
        event_fills = [r for r in fills if r['cycle_id'] == cycle]
        buy = [r for r in event_fills if r['side'] == 'BUY']
        sale = [r for r in event_fills if r['side'] == 'SELL']
        h6 = [r for r in attempts if r['cycle_id'] == cycle and r['horizon'] == '6' and r['filled'] == 'True']
        check(cycle + ' Unique original fills', len(buy) == 1 and len(sale) <= 1 and len(h6) <= 1)
        outlay = quantity * dec(buy[0]['price']) + dec(buy[0]['fees'])
        check(cycle + ' Original entry cost', abs(outlay-dec(member['entry_outlay'])) <= MONEY_TOL)
        check(cycle + ' Buy fee', abs(dec(buy[0]['fees'])-quantity*dec(buy[0]['price'])*Decimal('.001')) <= MONEY_TOL)
        sale_day = date(sale[0]['fill_time']) if sale else None
        sale_price = dec(sale[0]['price']) if sale else Decimal(0)
        sale_fee = dec(sale[0]['fees']) if sale else Decimal(0)
        if sale:
            check(cycle + ' Original sell fee', abs(sale_fee-quantity*sale_price*Decimal('.001')) <= MONEY_TOL)
        h6_day = h6[0]['day'] if h6 else None
        h6_price = dec(h6[0]['price']) if h6 else Decimal(0)
        H = terminal_value(cash, quantity, dec(t['close']), h6_day, h6_price, quantity*h6_price*Decimal('.001'), terminal)
        C = terminal_value(cash, quantity, dec(t['close']), sale_day, sale_price, sale_fee, terminal)
        X = dec(t['equity'])
        check(cycle + ' Actual endpoint NAV', abs(X-dec(t['cash'])-dec(t['quantity'])*dec(t['close'])) <= MONEY_TOL)
        action, holding, opportunity = (H-X)/wealth, (H-C)/wealth, (X-C)/wealth
        old = dec(member['extension_increment'])*outlay/wealth
        check(cycle + ' Old label common denominator', abs(holding-old) <= RETURN_TOL)
        rebuys = [r for r in fills if r['side'] == 'BUY' and sale_day is not None and sale_day <= date(r['fill_time']) <= terminal and r['cycle_id'] != cycle]
        expected[cycle] = {'cycle_id': cycle, 'entry_date': entry, 'decision_date': decision, 'terminal_date': terminal,
                           'W_D': wealth, 'D_cash': cash, 'D_quantity': quantity,
                           'X_T': X, 'H_T': H, 'C_T': C, 'A': action, 'L': holding, 'O': opportunity,
                           'old_common': old, 'reentry_count': len(rebuys),
                           'terminal_quantity': dec(t['quantity']), 'sign_flip': sign(action)*sign(holding) == -1}
    check('Eligible set based only on observable D/T', len(expected) == 146 and len(censored) == 1 and {r['cycle_id'] for r in actual} == set(expected))
    check('Every eligible node counted once', len(actual) == 146 and budget_attempts['attempted'] == budget_attempts['succeeded'] == 146 and budget_attempts['failed'] == 0 and not budget_attempts['retry'])

    # Main schema comparison is deliberately explicit, avoiding an import of
    # the implementation being audited. Populated once the main output exists.
    aliases = {
        'decision_date': 'decision_date', 'terminal_date': 'terminal_date',
        'W_D': 'W_D', 'D_cash': 'D_cash', 'D_quantity': 'D_quantity',
        'X_T': 'X_T', 'H_T': 'H_T', 'C_T': 'C_T',
        'A': 'A', 'L': 'L', 'O': 'O',
        'old_common': 'old_increment_W_D',
    }
    maximum_money_error, maximum_return_error = Decimal(0), Decimal(0)
    for row in actual:
        ref = expected[row['cycle_id']]
        for key, column in aliases.items():
            if key.endswith('_date'):
                check(row['cycle_id'] + ' ' + key, row[column] == ref[key])
            else:
                error = abs(dec(row[column])-ref[key])
                is_return = key in ('A', 'L', 'O', 'old_common')
                check(row['cycle_id'] + ' ' + key, error <= (RETURN_TOL if is_return else MONEY_TOL))
                if is_return:
                    maximum_return_error = max(maximum_return_error, error)
                else:
                    maximum_money_error = max(maximum_money_error, error)
        check(row['cycle_id'] + ' Sign and reentry fields', int(row['sign_A']) == sign(ref['A']) and int(row['sign_L']) == sign(ref['L']) and (row['sign_flip'] == 'True') == ref['sign_flip'] and int(row['reentry_n']) == ref['reentry_count'])
        check(row['cycle_id'] + ' Terminal states', dec(row['X_quantity']) == ref['terminal_quantity'] and row['X_state'] == ('HOLDING' if ref['terminal_quantity'] else 'CASH') and row['H_state'] == row['C_state'] == 'CASH')

    rows = sorted(expected.values(), key=lambda r: (r['decision_date'], r['cycle_id']))
    clusters, end = [], ''
    for row in rows:
        if row['decision_date'] > end:
            clusters.append([])
        clusters[-1].append(row)
        end = max(end, row['terminal_date'])

    def stats(group):
        size = len(group)
        return {'count': size, **{f'mean_{k}': float(sum((r[k] for r in group), Decimal(0))/size) if size else None for k in ('A', 'L', 'O')},
                'sign_flips': sum(r['sign_flip'] for r in group)}

    abs_o = sorted(rows, key=lambda r: (-abs(r['O']), r['decision_date'], r['cycle_id']))
    diagnostics = {
        'all': stats(rows),
        'decision_year_counts': dict(sorted(Counter(r['decision_date'][:4] for r in rows).items())),
        'without2026': stats([r for r in rows if r['decision_date'] <= '2025-12-31' and r['terminal_date'] <= '2025-12-31']),
        'clusters': [[r['cycle_id'] for r in group] for group in clusters],
        'cluster_equal_means': {k: float(sum((sum((r[k] for r in group), Decimal(0))/len(group) for group in clusters), Decimal(0))/len(clusters)) for k in ('A', 'L', 'O')},
        'leave_one_cluster_out': [stats([r for r in rows if r['cycle_id'] not in {q['cycle_id'] for q in group}]) for group in clusters],
        'remove_top_absolute_O': {str(n): {'removed_cycles': [r['cycle_id'] for r in abs_o[:n]], **stats([r for r in rows if r['cycle_id'] not in {q['cycle_id'] for q in abs_o[:n]}])} for n in (1, 3, 5)},
    }

    def audit_summary(name, actual_summary, group):
        ref = stats(group)
        check(name + ' node count', actual_summary['n'] == ref['count'])
        if not group:
            return
        for key in ('A', 'L', 'O'):
            independent_mean = sum((r[key] for r in group), Decimal(0))/len(group)
            check(name + ' mean ' + key, abs(dec(actual_summary['means_pp'][key])/100-independent_mean) <= RETURN_TOL)
        check(name + ' direction reversals', actual_summary['opposite_sign_n'] == ref['sign_flips'])
        counts = {
            'same_sign_n': sum(sign(r['A']) == sign(r['L']) for r in group),
            'zero_boundary_difference_n': sum(sign(r['A']) != sign(r['L']) and (sign(r['A']) == 0 or sign(r['L']) == 0) for r in group),
            'nonzero_O_n': sum(sign(r['O']) != 0 for r in group),
            'old_extend_new_exit_n': sum(sign(r['L']) == 1 and sign(r['A']) == -1 for r in group),
            'old_exit_new_extend_n': sum(sign(r['L']) == -1 and sign(r['A']) == 1 for r in group),
        }
        for key, val in counts.items():
            check(name + ' ' + key, actual_summary[key] == val)

    audit_summary('All nodes', summary['all'], rows)
    audit_summary('No 2026 D or T', summary['without2026'], [r for r in rows if r['decision_date'] <= '2025-12-31' and r['terminal_date'] <= '2025-12-31'])
    for year in range(2020, 2027):
        audit_summary('Decision year ' + str(year), summary['by_decision_year'][str(year)], [r for r in rows if r['decision_date'].startswith(str(year))])
        audit_summary('Entry year ' + str(year), summary['by_entry_year'][str(year)], [r for r in rows if r['entry_date'].startswith(str(year))])
    for truth in (True, False):
        audit_summary('Reentry ' + str(truth), summary['by_reentry'][str(truth)], [r for r in rows if bool(r['reentry_count']) == truth])
    for state in ('CASH', 'HOLDING'):
        audit_summary('Terminal ' + state, summary['by_X_terminal_state'][state], [r for r in rows if ('HOLDING' if r['terminal_quantity'] else 'CASH') == state])
    check('Independent inclusive transitive cluster count', summary['cluster_count'] == len(clusters))
    actual_by_cycle = {r['cycle_id']: r for r in actual}
    for i, group in enumerate(clusters, 1):
        check('Cluster membership ' + str(i), all(int(actual_by_cycle[r['cycle_id']]['cluster_id']) == i for r in group))
        audit_summary('Cluster ' + str(i), summary['clusters'][str(i)], group)
        ids = {r['cycle_id'] for r in group}
        audit_summary('Leave cluster out ' + str(i), summary['leave_one_cluster_out'][str(i)], [r for r in rows if r['cycle_id'] not in ids])
    for key in ('A', 'L', 'O'):
        check('Equal cluster mean ' + key, abs(dec(summary['cluster_equal_means_pp'][key])/100-dec(diagnostics['cluster_equal_means'][key])) <= RETURN_TOL)
    for n in (1, 3, 5):
        removed = [r['cycle_id'] for r in abs_o[:n]]
        check('Absolute O removal ranking ' + str(n), summary['delete_top_abs_O'][str(n)]['removed'] == removed)
        audit_summary('Absolute O remaining ' + str(n), summary['delete_top_abs_O'][str(n)]['remaining'], [r for r in rows if r['cycle_id'] not in removed])
    check('No extra model data account or matching', all(summary['actual_budget'][k] == 0 for k in ('new_upstream_calls', 'model_fits', 'new_complete_accounts', 'new_matching_calls', 'alternate_endpoints')))
    # Pure synthetic arithmetic boundaries do not create historical labels.
    check('Future exit price not used at T', terminal_value(dec(10), dec(2), dec(30), '2026-01-03', dec(999), dec(1), '2026-01-02') == dec(70))
    check('Unfilled terminal has no sell fee', terminal_value(dec(10), dec(2), dec(30), None, dec(999), dec(1), '2026-01-02') == dec(70))
    check('Executed terminal uses net cash', terminal_value(dec(10), dec(2), dec(30), '2026-01-02', dec(40), dec('.08'), '2026-01-02') == dec('89.92'))
    check('Sign tolerance is numerical only', sign(RETURN_TOL) == 0 and sign(-RETURN_TOL) == 0 and sign(RETURN_TOL*2) == 1)
    result = {'status': 'PASS', 'scope': 'Independent verification of the same 146 already-produced nodes; no additional samples or experiments',
              'source_hashes': sources, 'audit_source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'verified_nodes': len(expected), 'censored_cycles': censored,
              'maximum_money_error': float(maximum_money_error), 'maximum_return_error': float(maximum_return_error),
              'checks': checks, 'independent_diagnostics': diagnostics,
              'new_upstream_calls': 0, 'new_model_fits': 0, 'new_account_runs': 0, 'new_matching_calls': 0,
              'additional_sample_groups': 0, 'primary_summary_fields_seen': sorted(summary)}
    output = EX / 'others/independent_audit.json'
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status': result['status'], 'verified_nodes': len(expected), 'checks': len(checks), 'maximum_money_error': float(maximum_money_error), 'maximum_return_error': float(maximum_return_error), 'diagnostics': diagnostics['all']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
