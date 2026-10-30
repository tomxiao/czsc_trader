"""Authenticate V4 accounts, compare the old control, and audit actual economics."""
from collections import Counter
from datetime import date, datetime, timezone
import math
from statistics import mean, median
from zoneinfo import ZoneInfo

from common import (ROOT, WORK, REPOSITORY, PARAMETERS, context,
    read, save, digest, authenticate, material)
from czsc_trader.application import diagnose_accounts
from czsc_trader.research_tools import (EvidenceRef, AccountRunRef, AccountDiagnosisRequest,
    EvaluationIdentity, EvaluationWindow)
from czsc_trader.research_tools.equity_replay import materialize_equity
from strategy_manager import CandidateKey

MONEY_FIELDS = {
    'account_points': ('time', 'cash', 'quantity', 'receivable', 'equity', 'close', 'session', 'valuation_stale'),
    'account_daily': ('time', 'cash', 'quantity', 'receivable', 'equity', 'close', 'session', 'valuation_stale'),
    'decisions': ('observed_through', 'decision_at', 'execution_start', 'execution_end',
                  'target', 'reference_price', 'limit_price', 'quantity', 'side', 'signal_status'),
    'orders': ('valid_start', 'valid_end', 'side', 'quantity', 'limit_price', 'status', 'reason'),
    'fills': ('interval_start', 'interval_end', 'side', 'quantity', 'price', 'fees', 'time_precision'),
    'trades': ('entry_at', 'exit_at', 'cost', 'income', 'net_pnl', 'net_return', 'status'),
    'actions': (),
}
TIME_FIELDS = {'time', 'observed_through', 'decision_at', 'execution_start', 'execution_end',
               'valid_start', 'valid_end', 'interval_start', 'interval_end', 'entry_at', 'exit_at'}


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)


def near(left, right):
    if type(left) in (int, float) and type(right) in (int, float):
        return math.isclose(left, right, rel_tol=1e-11, abs_tol=1e-6)
    return left == right


def compare_paths(old, new):
    checks, differences = {}, []
    for table, fields in MONEY_FIELDS.items():
        a, b = old[table], new[table]
        count = 0
        if len(a) != len(b):
            differences.append({'table': table, 'old_rows': len(a), 'new_rows': len(b)})
            count += 1
        for i, (before, after) in enumerate(zip(a, b)):
            for field in fields:
                if field not in before or field not in after:
                    count += 1
                    if len(differences) < 15:
                        differences.append({'table': table, 'row': i, 'missing_field': field})
                    continue
                x, y = before[field], after[field]
                if field in TIME_FIELDS:
                    x, y = instant(x), instant(y)
                if not near(x, y):
                    count += 1
                    if len(differences) < 15:
                        differences.append({'table': table, 'row': i, 'field': field, 'old': x, 'new': y})
        if table == 'actions' and (a or b):
            raise ValueError('Unexpected nonempty corporate-action ledger in NONE study')
        checks[table] = {'old_rows': len(a), 'new_rows': len(b), 'differences': count}
    return {'status': 'PASS' if not any(c['differences'] for c in checks.values()) else 'DIFFERENT',
        'tables': checks, 'differences': differences,
        'scope': 'Declared complete economic projections, not identical IDs or explanatory schema. Monetary atol1e-6/rtol1e-11; no old schema recertification or re-signing.'}


def summary(run, initial):
    points, daily, trades = run['account_points'], run['account_daily'], run['trades']
    if len(points) != 22790 or len(daily) != 1760 or any(p['session'] > '2025-12-31' for p in daily):
        raise ValueError('Account population or authorized boundary differs')
    closed = [t for t in trades if t['status'] == 'CLOSED']
    sessions = [row['session'] for row in daily]
    counts = Counter(instant(t['exit_at']).astimezone(ZoneInfo('America/New_York')).date().isoformat() for t in closed)
    rolling = [sum(counts[s] for s in sessions[i-59:i+1]) for i in range(59, len(sessions))]
    peak, maximum, peak_at, trough_at, peak_time = initial, 0., None, None, None
    peak_value = initial
    for point in points:
        if point['equity'] > peak:
            peak, peak_time = point['equity'], point['time']
        loss = 1 - point['equity']/peak
        if loss > maximum:
            maximum, peak_at, trough_at, peak_value = loss, peak_time, point['time'], peak
    recovery = next((p['time'] for p in points if trough_at is not None
        and instant(p['time']) > instant(trough_at) and p['equity'] >= peak_value), None)
    fees = math.fsum(fill['fees'] for fill in run['fills'])
    ending = points[-1]['equity']
    actual = {'annualized_return': (ending/initial)**(252/len(daily))-1,
        'bar_max_drawdown': maximum, 'closed_cycles': len(closed), 'fees': fees,
        'rolling_60_closed_cycle_median': median(rolling), 'total_return': ending/initial-1}
    for field, value in actual.items():
        if not near(value, run['metrics'][field]):
            raise ValueError('Independent metric disagrees: ' + field)
    if rolling != run['metrics']['rolling_60_closed_cycle_counts']:
        raise ValueError('Actual-exit rolling frequency differs')
    positive = sorted((t['net_pnl'] for t in closed if t['net_pnl'] > 0), reverse=True)
    negative = [t['net_pnl'] for t in closed if t['net_pnl'] < 0]
    closed_pnl = math.fsum(t['net_pnl'] for t in closed)
    nonclosed = ending - initial - closed_pnl
    if points[-1]['quantity'] == 0 and not near(nonclosed, 0.):
        raise ValueError('Closed-cycle money does not reconcile to account equity')
    year_returns = {}
    opening = initial
    for year in range(2019, 2026):
        ending_year = [p for p in daily if p['session'].startswith(str(year))][-1]['equity']
        year_returns[str(year)] = ending_year/opening-1
        opening = ending_year
    signal_facts = [{f['key']: f['text'] for f in d['explanation']['basis']} for d in run['decisions']]
    return {**actual, 'ending_equity': ending, 'ending_quantity': points[-1]['quantity'],
        'coverage_at_least_three': mean(n >= 3 for n in rolling), 'frequency_windows': len(rolling),
        'holding_bar_fraction': mean(p['quantity'] > 0 for p in points),
        'mean_invested_equity_fraction': mean(p['quantity']*p['close']/p['equity'] for p in points),
        'year_returns': year_returns,
        'max_drawdown_path': {'peak': peak_at, 'trough': trough_at, 'recovery': recovery},
        'trade_pnl': {'closed_net_pnl': closed_pnl, 'positive_pnl': math.fsum(positive),
            'negative_pnl': math.fsum(negative), 'nonclosed_equity_change': nonclosed,
            'win_rate': mean(t['net_pnl'] > 0 for t in closed) if closed else None,
            'mean_cycle_net_return': mean(t['net_return'] for t in closed) if closed else None,
            'median_cycle_net_return': median(t['net_return'] for t in closed) if closed else None,
            'top_five_positive_pnl_share': math.fsum(positive[:5])/math.fsum(positive) if positive else None},
        'decision_counts': {'entry_signals': sum(f.get('entry_signal') == 'True' for f in signal_facts),
            'held_signals_ignored': sum(f.get('entry_signal') == 'True' and f.get('held') == 'True' for f in signal_facts),
            'flat_signals': sum(f.get('entry_signal') == 'True' and f.get('held') == 'False' for f in signal_facts),
            'buy_fills': sum(f['side'] == 'BUY' for f in run['fills']),
            'unfilled_orders': dict(Counter(o['reason'] for o in run['orders'] if o['status'] != 'FILLED'))}}


def run_ref(reference, payload):
    identity = dict(payload['evaluation_identity'])
    identity['candidate'] = CandidateKey(**identity['candidate'])
    result = AccountRunRef(EvidenceRef.from_dict(reference), EvaluationIdentity(**identity))
    if result.identity.evaluation_id != payload['evaluation_id']:
        raise ValueError('Evaluation identity does not bind its selected account')
    return result


def main():
    manifest = read(WORK/'others/accounts.json')
    if set(manifest) != set(PARAMETERS):
        raise ValueError('Unexpected account set')
    payloads, refs = {}, {}
    for key, record in manifest.items():
        ref = record['evidence']
        if ref['schema'] != 'equity_research' or ref['schema_version'] != 4:
            raise ValueError('Only current V4 accounts can be diagnosed')
        path = authenticate(ref)
        envelope = read(path)
        allowed = {(envelope[n]['kind'], envelope[n]['sha256']) for n in ('input_ref', 'candidate_ref', 'benchmark_ref')}

        def resolve(item):
            if set(item) != {'kind', 'sha256'} or (item['kind'], item['sha256']) not in allowed:
                raise ValueError('Unowned dependency refused')
            return (path.parent/(item['sha256']+'.json')).read_bytes()

        payload = materialize_equity(path.read_bytes(), resolve).payload
        if (payload['request']['candidate_id'] != key or payload['evaluation_id'] != record['evaluation_id']
                or payload['request_hash'] != record['request_hash']):
            raise ValueError('Formal manifest identity differs')
        payloads[key], refs[key] = payload, ref
    fields = ('initial_cash', 'fee_rate', 'window', 'history_start', 'specification', 'specification_hash',
        'sources', 'data_manifest', 'input_binding', 'benchmark', 'benchmark_sha256', 'engine_sources',
        'warmup_bars', 'drawdown_basis', 'concentration_basis', 'frequency_window_days', 'measurement_tier')
    for field in fields:
        if payloads['C0061']['request'][field] != payloads['C0062']['request'][field]:
            raise ValueError('New/control contract differs: ' + field)
    if payloads['C0061']['runs']['buy_hold'] != payloads['C0062']['runs']['buy_hold']:
        raise ValueError('Shared benchmark complete path differs')
    old_ref = read(ROOT/'research/S017/experiments/EX027_20261029/others/analysis.json')['source_accounts']['C0048']
    old = read(authenticate(old_ref))
    old_checks = {name: compare_paths(old['runs'][name], payloads['C0062']['runs'][name]) for name in ('candidate', 'buy_hold')}
    save(WORK/'others/control_equivalence.json', {'old_reference': old_ref, 'new_reference': refs['C0062'],
        'status': 'PASS' if all(v['status'] == 'PASS' for v in old_checks.values()) else 'DIFFERENT',
        'comparisons': old_checks})
    if not all(v['status'] == 'PASS' for v in old_checks.values()):
        raise ValueError('V4 control does not reproduce the old economic projections; inspect before interpretation')
    summaries = {}
    for key, payload in payloads.items():
        initial = payload['request']['initial_cash']
        cand, bench = summary(payload['runs']['candidate'], initial), summary(payload['runs']['buy_hold'], initial)
        goals = {'annualized_return': cand['annualized_return'] >= 1.5*bench['annualized_return'],
            'relative_drawdown': cand['bar_max_drawdown'] <= .8*bench['bar_max_drawdown'],
            'absolute_drawdown': cand['bar_max_drawdown'] <= .25,
            'frequency_median': cand['rolling_60_closed_cycle_median'] >= 6,
            'frequency_coverage': cand['coverage_at_least_three'] >= .9}
        summaries[key] = {'parameters': PARAMETERS[key], 'candidate': cand, 'benchmark': bench,
            'goals': goals, 'all_goals_met': all(goals.values())}
    diagnosis = diagnose_accounts(REPOSITORY, AccountDiagnosisRequest(
        run_ref(refs['C0062'], payloads['C0062']), run_ref(refs['C0061'], payloads['C0061']),
        EvaluationWindow('DEV_2019_2025', date(2019, 1, 2), date(2025, 12, 31))))
    save(WORK/'others/public_diagnosis.json', diagnosis.to_dict())
    if diagnosis.status.value != 'COMPUTED' or any(abs(r.residual) > 1e-6 for r in diagnosis.reconciliation):
        raise ValueError('Public diagnosis is not computed or failed reconciliation')
    diagnosis_ref = material(context(), 'm008-vs-m005-public-diagnosis', WORK/'others/public_diagnosis.json')
    save(WORK/'others/analysis.json', {'schema': 's017-m008-complete-account-comparison/v1', 'status': 'PASS',
        'analysis_source_sha256': digest(WORK/'src/analyze.py'), 'account_manifest_sha256': digest(WORK/'others/accounts.json'),
        'source_accounts': refs, 'contract_checks': {'status': 'PASS', 'equal_fields': fields,
            'complete_shared_benchmark_equal': True, 'control_equivalence': 'PASS'},
        'summaries': summaries, 'public_diagnosis': {'reference': diagnosis_ref.to_dict(), 'status': diagnosis.status.value,
            'path_comparison_counts': dict(Counter('both_enter' if p.baseline_cycle_id and p.alternative_cycle_id
                else 'baseline_only' if p.baseline_cycle_id else 'alternative_only' for p in diagnosis.path_comparison)),
            'reconciliation': [r.to_dict() for r in diagnosis.reconciliation]},
        'semantics': {'annual': 'Continuous account equity; no annual reset.',
            'comparison': 'Entry policies change future capital and opportunity sequences; no removed-trade counterfactual.',
            'open_positions': 'Reported separately without hypothetical liquidation.',
            'history': 'Repeatedly seen 2019-2025 development pool, not independent validation.'}})
    print('ACCOUNT_ANALYSIS_PASS', flush=True)
    for key, value in summaries.items():
        r = value['candidate']
        print(key, r['annualized_return'], r['bar_max_drawdown'], r['closed_cycles'],
              r['rolling_60_closed_cycle_median'], r['coverage_at_least_three'], flush=True)


if __name__ == '__main__':
    main()
