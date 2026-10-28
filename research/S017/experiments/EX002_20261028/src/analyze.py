"""Describe retained S017 accounts without rerunning strategies or reading holdout data."""
from datetime import date
from math import isclose
from collections import Counter

from czsc_trader.application import diagnose_accounts
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.account_diagnosis import AccountDiagnosisRequest, AccountRunRef
from czsc_trader.research_tools.equity_evaluation import EquityEvaluationResult
from czsc_trader.research_tools.evaluation import EvaluationIdentity, EvaluationWindow
from strategy_manager import CandidateKey

from run import ROOT, WORK, REPOSITORY, EXPERIMENT, configurations, read, save, context, material


def drawdown(values, opening):
    peak, worst = float(opening), 0.
    for value in values:
        peak = max(peak, float(value))
        worst = max(worst, 1. - float(value) / peak)
    return worst


def ratio_return(closing, opening):
    if opening <= 0:
        raise ValueError('nonpositive opening equity has no multiplicative return')
    return closing / opening - 1.


def _validate_run(run, initial):
    points, daily = run['account_points'], run['account_daily']
    if not points or not daily:
        raise ValueError('retained account has no observations')
    if any(not '2019-01-02' <= row['session'] <= '2025-12-31' for row in points):
        raise ValueError('account exceeds authorized development window')
    if [p['time'] for p in points] != sorted({p['time'] for p in points}):
        raise ValueError('account observations are not unique and ordered')
    ends = {}
    for point in points:
        ends[point['session']] = point
    if list(ends.values()) != daily:
        raise ValueError('daily observations are not session-end account points')
    metrics = run['metrics']
    expected = {
        'total_return': ratio_return(daily[-1]['equity'], initial),
        'bar_max_drawdown': drawdown((p['equity'] for p in points), initial),
        'daily_max_drawdown': drawdown((p['equity'] for p in daily), initial),
    }
    for name, value in expected.items():
        if not isclose(value, metrics[name], rel_tol=1e-10, abs_tol=1e-9):
            raise ValueError(f'{name} differs from audited metric')


def slice_stats(run, start, stop, initial):
    """Inclusive daily-index slice; preserve prior equity, never reset the account."""
    daily = run['account_daily']
    selected = daily[start:stop+1]
    opening = initial if start == 0 else daily[start-1]['equity']
    start_day, end_day = selected[0]['session'], selected[-1]['session']
    bars = [p for p in run['account_points'] if start_day <= p['session'] <= end_day]
    # Report local slice risk separately from drawdown against the full account's high-water mark.
    peak, inherited_worst = initial, 0.
    for point in run['account_points']:
        if point['session'] > end_day:
            break
        peak = max(peak, point['equity'])
        if point['session'] >= start_day:
            inherited_worst = max(inherited_worst, 1. - point['equity']/peak)
    return {
        'start_session': start_day, 'end_session': end_day, 'sessions': len(selected),
        'opening_equity': opening, 'closing_equity': selected[-1]['equity'],
        'net_return': ratio_return(selected[-1]['equity'], opening),
        'bar_drawdown_with_slice_opening': drawdown((p['equity'] for p in bars), opening),
        'session_drawdown_with_slice_opening': drawdown((p['equity'] for p in selected), opening),
        'bar_drawdown_with_continuous_peak': inherited_worst,
        'holding_bar_fraction': sum(p['quantity'] > 0 for p in bars)/len(bars),
        'holding_session_close_fraction': sum(p['quantity'] > 0 for p in selected)/len(selected),
    }


def compare_slice(candidate, benchmark, start, stop, initial):
    own, hold = (slice_stats(run, start, stop, initial) for run in (candidate, benchmark))
    return {'candidate': own, 'buy_hold': hold,
            'excess_net_return': own['net_return'] - hold['net_return'],
            'relative_wealth_return': (1. + own['net_return'])/(1. + hold['net_return']) - 1.}


def longest_lag(windows):
    best, current = [], []
    for window in windows:
        if window['excess_net_return'] < 0:
            current.append(window)
            if len(current) > len(best):
                best = list(current)
        else:
            current = []
    if not best:
        return {'consecutive_windows': 0, 'start_session': None, 'end_session': None,
                'minimum_excess_return': None, 'maximum_excess_return': None}
    return {'consecutive_windows': len(best),
            'start_session': best[0]['candidate']['start_session'],
            'end_session': best[-1]['candidate']['end_session'],
            'minimum_excess_return': min(w['excess_net_return'] for w in best),
            'maximum_excess_return': max(w['excess_net_return'] for w in best),
            'note': 'Overlapping 252-session windows stepped by 21 sessions; not independent samples.'}


def summarize(payload):
    candidate, benchmark = payload['runs']['candidate'], payload['runs']['buy_hold']
    initial = payload['request']['initial_cash']
    for account in (candidate, benchmark):
        _validate_run(account, initial)
    daily = candidate['account_daily']
    if [p['session'] for p in daily] != [p['session'] for p in benchmark['account_daily']]:
        raise ValueError('candidate and benchmark calendars differ')
    years = sorted({int(p['session'][:4]) for p in daily})
    annual = []
    for year in years:
        indices = [i for i,p in enumerate(daily) if int(p['session'][:4]) == year]
        value = compare_slice(candidate, benchmark, indices[0], indices[-1], initial)
        value['year'] = year
        value['coverage_statement'] = 'All retained sessions in this calendar year; no annualization of partial samples.'
        annual.append(value)
    rolling = [compare_slice(candidate, benchmark, start, start+251, initial)
               for start in range(0, len(daily)-251, 21)]
    counts = candidate['metrics']['rolling_60_closed_cycle_counts']
    profits = [trade['net_pnl'] for trade in candidate['trades'] if trade['net_pnl'] > 0]
    points = candidate['account_points']
    return {
        'audited_metrics': candidate['metrics'], 'buy_hold_metrics': benchmark['metrics'],
        'holding_bar_fraction': sum(p['quantity'] > 0 for p in points)/len(points),
        'holding_session_close_fraction': sum(p['quantity'] > 0 for p in daily)/len(daily),
        'frequency_60_sessions': {'complete_windows': len(counts),
            'closed_cycle_median': candidate['metrics']['rolling_60_closed_cycle_median'],
            'windows_at_least_three': sum(n >= 3 for n in counts),
            'coverage_at_least_three': sum(n >= 3 for n in counts)/len(counts) if counts else None},
        'profit_concentration': {'basis': 'MAX_SINGLE', 'positive_closed_cycles': len(profits),
            'positive_closed_profit_sum': sum(profits),
            'maximum_single_profit_fraction': max(profits)/sum(profits) if profits else None,
            'status': 'COMPUTED' if profits else 'NOT_APPLICABLE_NO_POSITIVE_CLOSED_CYCLE',
            'open_position_at_end': points[-1]['quantity'] > 0,
            'note': 'Closed-cycle net profits only; unclosed mark-to-market gains are excluded.'},
        'closed_loss_fraction': (sum(t['net_pnl'] < 0 for t in candidate['trades']) / len(candidate['trades'])
                                 if candidate['trades'] else None),
        'order_reason_counts': dict(Counter(row['reason'] for row in candidate['orders'])),
        'fill_count': len(candidate['fills']),
        'annual': annual, 'rolling_252_step_21': rolling,
        'longest_consecutive_rolling_lag': longest_lag(rolling),
        'data_quality': candidate['data_quality'],
    }


def _economic(value):
    """Exclude implementation-dependent bookkeeping IDs, retain all economic fields."""
    if isinstance(value, list):
        return [_economic(item) for item in value]
    if isinstance(value, dict):
        return {key: _economic(item) for key,item in value.items()
                if key not in {'decision_id', 'cycle_id', 'fill_id', 'order_id', 'plan_id'}}
    return value


def verify_hold_path(payloads):
    control = payloads['C0000']['runs']['candidate']
    checks = []
    for key,payload in payloads.items():
        builtin = payload['runs']['buy_hold']
        for field in ('account_points', 'account_daily', 'fills', 'trades', 'actions', 'metrics'):
            same = _economic(control[field]) == _economic(builtin[field])
            checks.append({'candidate': key, 'field': field, 'equal': same})
    return {'status': 'PASS' if all(c['equal'] for c in checks) else 'FAIL',
            'comparison': 'C0000 candidate versus every embedded buy_hold; exact economic paths, identity IDs excluded',
            'checks': checks}


def load_accounts():
    rows = read(WORK/'others/accounts.json')
    if set(rows) != set(configurations()):
        raise ValueError('account manifest does not contain all fixed structures')
    payloads, references = {}, {}
    for key,record in rows.items():
        reference = EvidenceRef.from_dict(record['evidence'])
        if reference.experiment != EXPERIMENT or (reference.schema, reference.schema_version) != ('equity_research', 2):
            raise ValueError('account evidence belongs to a different experiment or schema')
        content = reference.resolve(ROOT).read_bytes()
        # Public publisher writes EquityEvaluationResult.content directly; there is no wrapper.
        payload = EquityEvaluationResult(record['request_hash'], content).payload
        if (payload.get('schema'), payload.get('schema_version')) != ('equity-research/v2', 2):
            raise ValueError('unexpected serialized equity account schema')
        if payload['evaluation_id'] != record['evaluation_id'] or payload['evaluation_identity'] != record['evaluation_identity']:
            raise ValueError('manifest account identity differs from published evidence')
        if payload['request']['candidate_id'] != key:
            raise ValueError('manifest candidate key differs from published account')
        payloads[key], references[key] = payload, reference
    return payloads, references


def account_ref(reference, payload):
    identity = dict(payload['evaluation_identity'])
    identity['candidate'] = CandidateKey(**identity['candidate'])
    return AccountRunRef(reference, EvaluationIdentity(**identity))


def diagnostics(payloads, references):
    root = ROOT/'research/S017/assets/runs/EX002_20261028/diagnostics'
    research = context()
    pairs = [('C0003', 'C0002'), ('C0005', 'C0004'), ('C0006', 'C0005')]
    pairs.extend((key, 'C0000') for key in sorted(payloads) if key != 'C0000')
    result = {}
    for subject, control in pairs:
        key = subject+'_vs_'+control
        path = root/(key+'.json')
        diagnosis = diagnose_accounts(REPOSITORY, AccountDiagnosisRequest(
            account_ref(references[control], payloads[control]),
            account_ref(references[subject], payloads[subject]),
            EvaluationWindow('DEV_2019_2025', date(2019,1,2), date(2025,12,31))))
        raw = diagnosis.to_dict()
        save(path, raw)
        published = material(research, 'diagnosis-'+key, path)
        # Do not rewrite the platform's annual partial_year field.
        summaries = []
        for index, pnl in enumerate(diagnosis.pnl_breakdown):
            summaries.append({'evaluation_id': pnl.evaluation_id,
                'opening_equity': pnl.daily[0].opening_equity if pnl.daily else None,
                'closing_equity': pnl.daily[-1].closing_equity if pnl.daily else None,
                'entry': sum(p.entry for p in pnl.daily), 'holding': sum(p.holding for p in pnl.daily),
                'exit': sum(p.exit for p in pnl.daily), 'fees': sum(p.fees for p in pnl.daily),
                'residual': sum(p.residual for p in pnl.daily),
                'annual': raw['pnl_breakdown'][index]['annual']})
        result[key] = {'status': diagnosis.status.value, 'issues': list(diagnosis.issues),
            'baseline': control, 'alternative': subject, 'raw_path': path.relative_to(ROOT).as_posix(),
            'evidence': published.to_dict(),
            'pnl_summary': summaries,
            'cycle_path_rows': len(diagnosis.path_comparison), 'daily_path_rows': len(diagnosis.daily_paths),
            'reconciliation': raw['reconciliation'],
            'partial_year_note': 'Original platform flag retained; Jan 1 calendar-day comparison can label a full trading year partial.'}
        print('DIAGNOSIS', key, diagnosis.status.value, flush=True)
    return result


def main():
    payloads, references = load_accounts()
    path_check = verify_hold_path(payloads)
    output = {'schema': 's017-stage2-analysis/v1', 'scope': '2019-01-02 through 2025-12-31 development only',
        'source_accounts': {key: ref.to_dict() for key,ref in references.items()},
        'semantics': {'annual_return': 'year-end equity divided by preceding session equity, initial cash for first year',
            'rolling_return': '252 retained sessions, 21-session step, incomplete trailing windows excluded',
            'excess_return': 'candidate net return minus buy_hold net return on the same continuous-account slice',
            'holding': 'fraction of bar/session-close observations with positive quantity, not elapsed wall-clock exposure',
            'drawdown': 'slice-opening and full-account inherited peak reported separately; all drawdowns are positive magnitudes',
            'independence': 'overlapping windows and 30-minute observations are not independent samples'},
        'buy_hold_path_verification': path_check,
        'accounts': {key: summarize(value) for key,value in payloads.items()},
        'diagnostics': diagnostics(payloads, references)}
    okay = path_check['status'] == 'PASS' and all(d['status'] == 'COMPUTED' for d in output['diagnostics'].values())
    output['status'] = 'PASS' if okay else 'FAIL'
    save(WORK/'others/analysis.json', output)
    if not okay:
        raise RuntimeError('analysis contains failed economic-path verification or account diagnosis')
    print('ANALYSIS PASS', WORK/'others/analysis.json', flush=True)


if __name__ == '__main__':
    main()
