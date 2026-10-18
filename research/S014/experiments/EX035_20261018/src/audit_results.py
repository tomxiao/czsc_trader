"""Independent Decimal reconstruction of EX035; reads evidence, never executes accounts."""
import csv
from collections import Counter
from decimal import Decimal, localcontext
from hashlib import sha256
import io
import json
from pathlib import Path
import socket

from czsc_trader.research_tools import EvidenceRef
from strategy_runtime import implementation_sha256
from audit_accounts import audit_control, audit_path, selfcheck as account_selfcheck
from audit_identity import audit_identity, selfcheck as identity_selfcheck

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
REVIEW = ROOT / 'research/S014/materials/20261018_e9_extension_review'
OLD = ROOT / 'research/S014/experiments/EX034_20261018'
EPS = Decimal('1e-10')
MONEY_EPS = Decimal('1e-7')
KEYS = ('A6', 'L6', 'O6', 'A9', 'L9', 'O9', 'J9', 'delta_A', 'delta_O')


def dec(value):
    return Decimal(str(value))


def sign(value):
    return 1 if value > EPS else -1 if value < -EPS else 0


def datepart(value):
    return value[:10]


def csv_rows(raw):
    return list(csv.DictReader(io.StringIO(raw.decode('utf-8'))))


def load_public(record, hashes):
    ref = EvidenceRef.from_dict(record)
    raw = ref.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest() == ref.sha256, ref
    hashes[ref.sha256] = ref.to_dict()
    return raw


def rows(account, name):
    assert len(account['runs']) == 1
    return account['runs'][0]['ledgers'][name]['data']


def indexed(account, name, key):
    source = rows(account, name)
    out = {datepart(row[key]): row for row in source}
    assert len(out) == len(source)
    return out


def distribution(data):
    if not data:
        return {'n': 0}
    def average(values):
        return sum(values, Decimal(0)) / len(values)
    def quantile(values, q):
        ordered = sorted(values)
        pos = (len(ordered) - 1) * dec(q)
        lower = int(pos)
        return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (pos - lower)
    def pairs(left, right):
        table = Counter((sign(r[left]), sign(r[right])) for r in data)
        return {
            'strict_opposite_n': table[(-1, 1)] + table[(1, -1)],
            'same_sign_n': sum(table[(i, i)] for i in (-1, 0, 1)),
            'zero_boundary_difference_n': sum(table[(a, b)] for a in (-1, 0, 1) for b in (-1, 0, 1) if a != b and 0 in (a, b)),
            'left_positive_right_negative_n': table[(1, -1)],
            'left_negative_right_positive_n': table[(-1, 1)],
            'transition_counts': {f'{a}:{b}': table[(a, b)] for a in (-1, 0, 1) for b in (-1, 0, 1)},
        }
    value = {'n': len(data),
             'means_pp': {k: 100 * average([r[k] for r in data]) for k in KEYS},
             'medians_pp': {k: 100 * quantile([r[k] for r in data], '.5') for k in KEYS},
             'mean_absolute_pp': {k: 100 * average([abs(r[k]) for r in data]) for k in KEYS},
             'quantiles_pp': {k: {q: 100 * quantile([r[k] for r in data], q) for q in ('0', '0.1', '0.25', '0.5', '0.75', '0.9', '1')} for k in KEYS},
             'sign_counts': {k: {str(s): sum(sign(r[k]) == s for r in data) for s in (-1, 0, 1)} for k in KEYS},
             'A6_to_A9': pairs('A6', 'A9'), 'L6_to_A9': pairs('L6', 'A9'),
             'L9_to_A9': pairs('L9', 'A9'), 'L6_to_A6': pairs('L6', 'A6'),
             'nonzero_delta_A_n': sum(abs(r['delta_A']) > EPS for r in data),
             'nonzero_J9_n': sum(abs(r['J9']) > EPS for r in data),
             'A9_abs_greater_than_A6_n': sum(abs(r['A9']) - abs(r['A6']) > EPS for r in data),
             'A9_abs_less_than_A6_n': sum(abs(r['A9']) - abs(r['A6']) < -EPS for r in data)}
    original = [r for r in data if r['original_E6_flip']]
    value['original_E6_flip_subset'] = {
        'n': len(original),
        'persists_opposite_L6_A9_n': sum(sign(r['L6']) * sign(r['A9']) == -1 for r in original),
        'same_L6_A9_sign_n': sum(sign(r['L6']) == sign(r['A9']) for r in original),
        'A9_zero_n': sum(sign(r['A9']) == 0 for r in original),
    }
    return value


def main():
    def blocked(*args, **kwargs):
        raise RuntimeError('Independent EX035 audit forbids network access')
    socket.socket.connect = blocked
    socket.create_connection = blocked
    output = EX / 'others/independent_audit.json'
    assert not output.exists(), 'Preserve immutable independent audit'
    checks = 0
    hashes = {}
    def require(truth, label):
        nonlocal checks
        checks += 1
        assert truth, label
    def near(actual, expected, label, tolerance=EPS):
        require(dec(actual).is_finite() and abs(dec(actual) - expected) <= tolerance, label)
    def compare(expected, actual, label):
        if isinstance(expected, dict):
            require(set(expected) == set(actual), label + ' keys')
            for k, value in expected.items():
                compare(value, actual[k], label + '/' + k)
        elif isinstance(expected, Decimal):
            near(actual, expected, label, Decimal('1e-8'))
        else:
            require(actual == expected, label)
    publication = json.loads((REVIEW / 'publication.json').read_bytes())
    inventory = json.loads(load_public(publication['evidence']['inventory.json'], hashes))
    original = json.loads(load_public(inventory['sources']['C0011'], hashes))
    require(original['result_hash'] == inventory['sources']['C0011_result_hash'], 'original result identity')
    calendar = [r['date'] for r in csv_rows(load_public(inventory['sources']['calendar'], hashes))]
    xdays = indexed(original, 'account_daily', 'date')
    xdecisions = indexed(original, 'decisions', 'signal_date')
    require(list(xdays) == calendar and len(calendar) == 1642, 'full original calendar')
    old_result = json.loads((OLD / 'others/result.json').read_bytes())
    old = {r['cycle_id']: r for r in csv_rows(load_public(old_result['evidence']['others/events.csv'], hashes))}
    require(len(old) == 146, 'EX034 fixed universe')
    design = (EX / 'protocols/design.json').read_bytes()
    require(load_public(json.loads((EX / 'protocols/published_design.json').read_bytes()), hashes) == design, 'published fixed design')
    lock = json.loads((EX / 'protocols/execution_lock.json').read_bytes())
    require(lock['status'] == 'LOCKED_BEFORE_ACCOUNTS' and lock['maximum_account_dispatches'] == 69 and lock['automatic_retries'] == 0, 'execution lock caps')
    for name, expected_hash in lock['source_hashes'].items():
        require(sha256((EX / name).read_bytes()).hexdigest() == expected_hash, 'locked source ' + name)
    precheck = json.loads((EX / 'others/precheck.json').read_bytes())
    require(precheck['status'] == 'PASS', 'synthetic precheck pass')
    implementation = implementation_sha256(tuple(precheck['source_files']), source_root=EX / 'src/strategy_runtime')
    require(implementation == precheck['implementation_sha256'] == lock['source_sha256'], 'precheck and runtime implementation identity')
    require(len(list((EX / 'others/dispatches').glob('*.json'))) == 69, 'exact69 dispatch files')
    require([r['index'] for r in lock['runs']] == list(range(69)), 'exact69 locked indices')
    nodes = sorted([n for n in inventory['events'] if n['eligible']], key=lambda n: (n['E2'], n['cycle_id']))
    replay = [n for n in nodes if n['route'] == 'PUBLIC_H_REPLAY_REQUIRED']
    require(len(inventory['events']) == 147 and len(nodes) == 145 and len(replay) == 68, 'fixed cohort 147/145/68')
    require(len(list((EX / 'others/accounts').glob('run-*.json'))) == 69, '69 account receipts, no missing paths')
    observed_raw = (EX / 'others/events.csv').read_bytes()
    observed = csv_rows(observed_raw)
    actual = json.loads((EX / 'others/summary.json').read_bytes())
    require(actual['status'] == 'PASS', 'analysis successful')
    compare({'inventory': 147, 'eligible': 145, 'censored': 2, 'cash_reuse': 77,
             'replay': 68, 'account_receipts': 69, 'account_success': 69, 'failed': 0}, actual['counts'], 'fixed counts')
    compare({'account_runs': 69, 'node_groups': 145, 'primary_A9_labels': 145,
             'fixed_attribution_values': 435, 'terminal_values': 435, 'new_upstream_calls': 0,
             'model_fits': 0, 'alternate_endpoints': 0, 'account_external_matching_trials': 0,
             'new_qualified_candidates': 0}, actual['actual_budget'], 'fixed budget claim')
    require(actual['censored_nodes'] == [n for n in inventory['events'] if not n['eligible']], 'two censored nodes disclosed')
    require(actual['events_sha256'] == sha256(observed_raw).hexdigest(), 'events summary hash')
    require([r['cycle_id'] for r in observed] == [n['cycle_id'] for n in nodes], 'same145 exact inclusion and order')
    recorded = {r['cycle_id']: r for r in observed}
    accounts = {}
    receipt_hashes = {}
    account_audits = []
    for i in range(69):
        dispatch = json.loads((EX / f'others/dispatches/{i:03d}.json').read_bytes())
        require(dispatch['index'] == i and dispatch['maximum'] == 69 and dispatch['state'] == 'DISPATCHED_COUNTS_EVEN_IF_UNKNOWN'
                and dispatch['automatic_retry_allowed'] is False, 'counted dispatch ' + str(i))
        payload_raw = (EX / f'protocols/payloads/{i:03d}.json').read_bytes()
        payload = json.loads(payload_raw)
        expected_node = None if i == 0 else replay[i - 1]
        require(payload['parameters'] == {'variant': 'high_H3', 'intervention_entry_date': '' if i == 0 else expected_node['entry_date']}, 'fixed payload parameters ' + str(i))
        require(payload['runtime']['source_sha256'] == implementation and payload['runtime']['source_files'] == precheck['source_files'], 'payload implementation ' + str(i))
        require(sha256(payload_raw).hexdigest() == lock['runs'][i]['payload_sha256'] and lock['runs'][i]['node'] == expected_node
                and lock['runs'][i]['candidate'] == f'S014-C{9000+i}', 'locked payload/node/technical identity ' + str(i))
        path = EX / f'others/accounts/run-{i:03d}.json'
        raw = path.read_bytes()
        receipt_hashes[path.relative_to(ROOT).as_posix()] = sha256(raw).hexdigest()
        receipt = json.loads(raw)
        require(receipt['index'] == i and receipt['status'] == 'SUCCEEDED' and receipt['audit']['status'] == 'PASS', 'successful audited receipt ' + str(i))
        require(receipt['candidate'] == f'S014-C{9000+i}', 'receipt technical identity ' + str(i))
        account = json.loads(load_public(receipt['evidence'], hashes))
        require(account['result_hash'] == receipt['result_hash'], 'receipt result hash ' + str(i))
        economic_audit = audit_control(account) if i == 0 else audit_path(account, expected_node)
        identity_audit = audit_identity(account)
        require(economic_audit['status'] == 'PASS', 'rerun economic audit ' + str(i) + repr(economic_audit['errors']))
        require(identity_audit['status'] == 'PASS', 'rerun identity audit ' + str(i) + repr(identity_audit['errors']))
        account_audits.append({'index': i, 'economic_status': economic_audit['status'], 'economic_checks': economic_audit['checks'],
                              'identity_status': identity_audit['status'], 'identity_checks': identity_audit['checks']})
        if i == 0:
            require(rows(account, 'account_daily') == rows(original, 'account_daily'), 'no-op exact economic series')
        else:
            node = replay[i - 1]
            require(receipt['node'] == node, 'receipt node assignment ' + str(i))
            accounts[node['cycle_id']] = account
    rebuilt = []
    for node in nodes:
        cycle = node['cycle_id']
        previous, stored = old[cycle], recorded[cycle]
        d, e6, e9 = node['E2'], node['E6'], node['E9']
        require(calendar[calendar.index(node['entry_date']) + 2] == d and calendar[calendar.index(node['entry_date']) + 9] == e9, cycle + ' original entry clock')
        wd = dec(xdays[d]['equity'])
        near(previous['W_D'], wd, cycle + ' WD', MONEY_EPS)
        h6, c6, x6 = dec(previous['H_T']), dec(previous['C_T']), dec(xdays[e6]['equity'])
        require(previous['H_actual_exit'] == e6 and previous['C_actual_exit'] <= e6 and previous['H_state'] == previous['C_state'] == 'CASH', cycle + ' original liquidation proof')
        eligible = [all(bool(xdecisions[t][k]) for k in ('ready', 'parent', 'high')) for t in (node['E6'], node['E7'], node['E8'])]
        route = 'PUBLIC_H_REPLAY_REQUIRED' if any(eligible) else 'EXACT_H_CASH_REUSE'
        require(route == node['route'] == stored['route'], cycle + ' independent state-free route proof')
        h_account = accounts.get(cycle)
        if h_account:
            hdays = indexed(h_account, 'account_daily', 'date')
            near(hdays[d]['equity'], wd, cycle + ' replay WD', MONEY_EPS)
            near(hdays[e6]['equity'], h6, cycle + ' replay H6', MONEY_EPS)
            require(hdays[e6]['quantity'] == 0, cycle + ' H6 flat')
            h9 = dec(hdays[e9]['equity'])
            hd = indexed(h_account, 'decisions', 'signal_date')
            for t in (node['E6'], node['E7'], node['E8'], node['E9']):
                require(all(hd[t][k] == xdecisions[t][k] for k in ('ready', 'parent', 'high')), cycle + ' market-only eligibility unchanged ' + t)
        else:
            h9 = h6
        x9, c9 = dec(xdays[e9]['equity']), c6
        values = {'A6': (h6 - x6) / wd, 'L6': (h6 - c6) / wd, 'O6': (x6 - c6) / wd,
                  'A9': (h9 - x9) / wd, 'L9': (h9 - c9) / wd, 'O9': (x9 - c9) / wd,
                  'J9': (h9 - h6) / wd}
        values.update(delta_A=values['A9'] - values['A6'], delta_O=values['O9'] - values['O6'])
        for key, expected in values.items():
            near(stored[key], expected, cycle + ' ' + key)
        for key, expected in {'W_D': wd, 'X6': x6, 'H6': h6, 'C6': c6, 'X9': x9, 'H9': h9, 'C9': c9}.items():
            near(stored[key], expected, cycle + ' ' + key, MONEY_EPS)
        for branch, source_account, wealth in (('X', original, x9), ('H', h_account, h9), ('C', None, c9)):
            if source_account is None:
                cash, quantity, plan = wealth, 0, None
                action = 'BUY' if branch == 'H' and all(bool(xdecisions[e9][k]) for k in ('ready', 'parent', 'high')) else 'HOLD'
            else:
                daily_row = indexed(source_account, 'account_daily', 'date')[e9]
                cash, quantity = dec(daily_row['cash']), int(daily_row['quantity'])
                near(wealth, cash + quantity * dec(daily_row['close']), cycle + ' ' + branch + ' mark identity', MONEY_EPS)
                action = indexed(source_account, 'decisions', 'signal_date')[e9]['action'].upper()
                plan = None
                if quantity:
                    buys = [f for f in rows(source_account, 'fills') if f['side'].upper() == 'BUY' and datepart(f['fill_time']) <= e9]
                    exit_index = calendar.index(datepart(buys[-1]['fill_time'])) + 3
                    plan = calendar[exit_index] if exit_index < len(calendar) else None
            near(stored[branch + '_cash'], cash, cycle + ' ' + branch + ' cash', MONEY_EPS)
            require(int(stored[branch + '_quantity']) == quantity, cycle + ' ' + branch + ' quantity')
            require(stored[branch + '_state'] == ('HOLDING' if quantity else 'CASH'), cycle + ' ' + branch + ' terminal state')
            require(stored[branch + '_next_action'] == action and stored[branch + '_pending'] == (action if action in ('BUY', 'SELL') else 'NONE'), cycle + ' ' + branch + ' pending action')
            require(stored[branch + '_planned_exit'] == (plan or '') and stored[branch + '_planned_exit_beyond_calendar'] == str(bool(quantity and plan is None))
                    and stored[branch + '_planned_exit_already_due'] == str(bool(plan is not None and plan <= e9)), cycle + ' ' + branch + ' planned exit')
        for key in ('A', 'L', 'O'):
            near(previous[key], values[key + '6'], cycle + ' old label ' + key)
        require(abs(values['A9'] - values['L9'] + values['O9']) < Decimal('1e-35'), cycle + ' A9 identity')
        require(abs(values['L9'] - values['L6'] - values['J9']) < Decimal('1e-35'), cycle + ' L9 identity')
        require(abs(values['delta_A'] - values['J9'] + values['delta_O']) < Decimal('1e-35'), cycle + ' endpoint-change identity')
        row = {**values, 'cycle_id': cycle, 'decision_date': d, 'terminal_date': e9,
               'entry_year': int(node['entry_date'][:4]), 'decision_year': int(d[:4]), 'route': route,
               'original_E6_flip': sign(values['A6']) * sign(values['L6']) == -1}
        require(stored['original_E6_flip'] == str(row['original_E6_flip']), cycle + ' original flip flag')
        for flag, left, right in (('A6_A9_strict_flip', 'A6', 'A9'), ('L6_A9_strict_flip', 'L6', 'A9'), ('L9_A9_strict_flip', 'L9', 'A9')):
            require(stored[flag] == str(sign(values[left]) * sign(values[right]) == -1), cycle + ' ' + flag)
        rebuilt.append(row)
    # Independently construct interval connected components by graph union, not an endpoint sweep.
    parents = list(range(len(rebuilt)))
    def find(i):
        while parents[i] != i:
            i = parents[i]
        return i
    for i, a in enumerate(rebuilt):
        for j in range(i):
            b = rebuilt[j]
            if max(a['decision_date'], b['decision_date']) <= min(a['terminal_date'], b['terminal_date']):
                parents[find(i)] = find(j)
    roots = []
    for i, row in enumerate(rebuilt):
        key = find(i)
        if key not in roots:
            roots.append(key)
        row['cluster_id'] = roots.index(key) + 1
        require(int(recorded[row['cycle_id']]['cluster_id']) == row['cluster_id'], row['cycle_id'] + ' inclusive transitive cluster')
    compare(distribution(rebuilt), actual['all'], 'all145 distribution')
    compare(distribution([r for r in rebuilt if r['decision_date'] <= '2025-12-31' and r['terminal_date'] <= '2025-12-31']), actual['without2026'], 'without2026')
    for key, report_key in (('route', 'by_route'), ('decision_year', 'by_decision_year'), ('entry_year', 'by_entry_year')):
        groups = sorted({r[key] for r in rebuilt})
        compare({str(k): distribution([r for r in rebuilt if r[key] == k]) for k in groups}, actual[report_key], report_key)
    cluster_groups = {str(i): [r for r in rebuilt if r['cluster_id'] == i] for i in range(1, len(roots) + 1)}
    require(actual['cluster_count'] == len(roots), 'cluster count')
    compare({k: distribution(v) for k, v in cluster_groups.items()}, actual['clusters'], 'cluster distributions')
    compare({k: distribution([r for r in rebuilt if str(r['cluster_id']) != k]) for k in cluster_groups}, actual['leave_one_cluster_out'], 'leave one cluster out')
    equal_means = {k: sum((sum(r[k] for r in group) / len(group) for group in cluster_groups.values()), Decimal(0)) * 100 / len(cluster_groups) for k in KEYS}
    compare(equal_means, actual['cluster_equal_means_pp'], 'cluster equal means')
    compare({str(k): v for k, v in Counter(len(g) for g in cluster_groups.values()).items()}, actual['cluster_sizes'], 'cluster size counts')
    ordered = sorted(rebuilt, key=lambda r: (-abs(r['delta_A']), r['decision_date'], r['cycle_id']))
    total_abs = sum(abs(r['delta_A']) for r in rebuilt)
    for n in (1, 3, 5):
        removed = [r['cycle_id'] for r in ordered[:n]]
        compare({'removed': removed,
                 'removed_absolute_change_share': sum(abs(r['delta_A']) for r in ordered[:n]) / total_abs if total_abs else Decimal(0),
                 'remaining': distribution([r for r in rebuilt if r['cycle_id'] not in removed])}, actual['delete_top_abs_delta_A'][str(n)], 'topdrop ' + str(n))
    flip_ids = {k for k, r in old.items() if sign(dec(r['A'])) * sign(dec(r['L'])) == -1}
    current_ids = {r['cycle_id'] for r in rebuilt}
    flip_report = actual['original_25_flips']
    require(len(flip_ids) == flip_report['original_n'] == 25, 'original25')
    require(flip_report['observable_n'] == len(flip_ids & current_ids) and flip_report['censored_cycle_ids'] == sorted(flip_ids - current_ids)
            and flip_report['censored_n'] == len(flip_ids - current_ids), 'original25 exact inclusion')
    compare(distribution([r for r in rebuilt if r['cycle_id'] in flip_ids]), flip_report['observable'], 'original25 observable distribution')
    require(flip_report['persisted_cycle_ids'] == [r['cycle_id'] for r in rebuilt if r['original_E6_flip'] and sign(r['L6']) * sign(r['A9']) == -1], 'original25 persisted IDs')
    require(flip_report['collapsed_cycle_ids'] == [r['cycle_id'] for r in rebuilt if r['original_E6_flip'] and sign(r['L6']) * sign(r['A9']) != -1], 'original25 collapsed IDs')
    for branch in ('X', 'H', 'C'):
        expected_terminal = {'state_counts': dict(Counter(r[branch + '_state'] for r in observed)),
                             'pending_counts': dict(Counter(r[branch + '_pending'] for r in observed)),
                             'planned_exit_already_due_n': sum(r[branch + '_planned_exit_already_due'] == 'True' for r in observed),
                             'planned_exit_beyond_calendar_n': sum(r[branch + '_planned_exit_beyond_calendar'] == 'True' for r in observed)}
        compare(expected_terminal, actual['terminal_states'][branch], branch + ' terminal summary')
    selfchecks = {'account': account_selfcheck(), 'identity': identity_selfcheck()}
    require(all(v['status'] == 'PASS' for v in selfchecks.values()), 'tamper detection selfchecks')
    result = {'status': 'PASS', 'method': 'Independent Decimal40 arithmetic and interval graph connected components; no analyze.py imports',
              'checked_nodes': len(rebuilt), 'checks': checks, 'authenticated_public_sources': list(hashes.values()),
              'receipt_sha256': receipt_hashes,
              'reperformed_account_audits': account_audits, 'audit_selfchecks': selfchecks,
              'execution_lock_sha256': sha256((EX / 'protocols/execution_lock.json').read_bytes()).hexdigest(),
              'account_audit_source_sha256': sha256((EX / 'src/audit_accounts.py').read_bytes()).hexdigest(),
              'identity_audit_source_sha256': sha256((EX / 'src/audit_identity.py').read_bytes()).hexdigest(),
              'events_sha256': sha256(observed_raw).hexdigest(), 'summary_sha256': sha256((EX / 'others/summary.json').read_bytes()).hexdigest(),
              'audit_source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'independent_all_means_pp': {k: float(v) for k, v in distribution(rebuilt)['means_pp'].items()},
              'independent_cluster_count': len(roots), 'independent_route_counts': dict(Counter(r['route'] for r in rebuilt)),
              'label_absolute_tolerance': float(EPS), 'money_absolute_tolerance': float(MONEY_EPS), 'summary_pp_absolute_tolerance': 1e-8,
              'account_evaluations': 0, 'model_fits': 0, 'supplier_calls': 0, 'matching_trials': 0,
              'scope': 'All145 wealth levels, nine label columns, route proof, cohort membership, distributions/signs, calendar groups, original25 subset, graph clusters, topdrop and terminal state; reperform69 economic and identity audits plus exact locked inputs/payload/dispatch validation.'}
    with output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'status': result['status'], 'checked_nodes': len(rebuilt), 'checks': checks, 'clusters': len(roots)}, ensure_ascii=False))


if __name__ == '__main__':
    with localcontext() as context:
        context.prec = 40
        main()
