"""Independent, read-only V4 source/number audit; never executes a strategy."""
from collections import Counter
from hashlib import sha256
import json

import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.equity_replay import materialize_equity

from common import ROOT, WORK, PARAMETERS, read, save, digest


def near(actual, expected, *, label):
    if not np.isclose(float(actual), float(expected), rtol=1e-10, atol=1e-6):
        raise ValueError(f'{label}: {actual} != {expected}')


def load_reference(value):
    reference = EvidenceRef.from_dict(value)
    if reference.experiment.strategy_id != 'S017':
        raise ValueError('Cross-batch source refused')
    path = reference.resolve(ROOT)
    content = path.read_bytes()
    if sha256(content).hexdigest() != reference.sha256:
        raise ValueError('Source changed while reading')
    return path, content


def numbers(run, initial):
    points, daily = pd.DataFrame(run['account_points']), pd.DataFrame(run['account_daily'])
    if len(points) != 22790 or len(daily) != 1760:
        raise ValueError('Unexpected original continuous-account population')
    sessions = daily['session'].astype(str).to_numpy()
    if sessions[0] != '2019-01-02' or sessions[-1] != '2025-12-31' or len(set(sessions)) != len(sessions):
        raise ValueError('Authorized session boundary or uniqueness differs')
    equity = points['equity'].to_numpy(dtype=np.float64)
    extended = np.r_[initial, equity]
    drawdown = 1. - extended / np.maximum.accumulate(extended)
    closed = pd.DataFrame([t for t in run['trades'] if t['status'] == 'CLOSED'])
    if closed.empty:
        counts = np.zeros(len(sessions), dtype=np.int64)
        pnl = np.array([], dtype=np.float64)
        returns = np.array([], dtype=np.float64)
    else:
        exit_dates = pd.to_datetime(closed['exit_at'], utc=True).dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d').to_numpy()
        indices = np.searchsorted(sessions, exit_dates)
        if np.any(indices >= len(sessions)) or not np.array_equal(sessions[indices], exit_dates):
            raise ValueError('Closed cycle exits outside declared trading sessions')
        counts = np.bincount(indices, minlength=len(sessions))
        pnl, returns = closed['net_pnl'].to_numpy(float), closed['net_return'].to_numpy(float)
    cumulative = np.r_[0, np.cumsum(counts)]
    rolling = cumulative[60:] - cumulative[:-60]
    if len(rolling) != 1701:
        raise ValueError('Frequency denominator differs')
    fees = float(np.asarray([f['fees'] for f in run['fills']], dtype=np.float64).sum())
    current = {
        'annualized_return': float(np.power(equity[-1] / initial, 252. / len(daily)) - 1.),
        'bar_max_drawdown': float(drawdown.max()),
        'closed_cycles': len(closed), 'fees': fees,
        'total_return': float(equity[-1] / initial - 1.),
        'rolling_60_closed_cycle_median': float(np.median(rolling)),
        'coverage_at_least_three': float(np.count_nonzero(rolling >= 3) / len(rolling)),
        'frequency_windows': len(rolling), 'ending_equity': float(equity[-1]),
        'ending_quantity': int(points['quantity'].iloc[-1]),
        'holding_bar_fraction': float(np.count_nonzero(points['quantity'].to_numpy() > 0) / len(points)),
        'mean_invested_equity_fraction': float(np.mean(points['quantity'].to_numpy() * points['close'].to_numpy() / equity)),
    }
    for field in ('annualized_return', 'bar_max_drawdown', 'closed_cycles', 'fees',
                  'total_return', 'rolling_60_closed_cycle_median'):
        near(current[field], run['metrics'][field], label='formal metric/' + field)
    if rolling.tolist() != run['metrics']['rolling_60_closed_cycle_counts']:
        raise ValueError('Formal rolling counts disagree with exit-date prefix sums')
    positive = pnl[pnl > 0]
    closed_pnl = float(pnl.sum())
    nonclosed = float(equity[-1] - initial - closed_pnl)
    if current['ending_quantity'] == 0:
        near(nonclosed, 0., label='closed account amount reconciliation')
    current['trade_pnl'] = {'closed_net_pnl': closed_pnl,
        'positive_pnl': float(positive.sum()), 'negative_pnl': float(pnl[pnl < 0].sum()),
        'nonclosed_equity_change': nonclosed,
        'win_rate': None if not len(pnl) else float(np.mean(pnl > 0)),
        'mean_cycle_net_return': None if not len(pnl) else float(returns.mean()),
        'median_cycle_net_return': None if not len(pnl) else float(np.median(returns)),
        'top_five_positive_pnl_share': None if not len(positive) else float(np.sort(positive)[-5:].sum() / positive.sum())}
    yearly = daily.assign(year=daily['session'].str[:4]).groupby('year', sort=True)['equity'].last()
    starts = np.r_[initial, yearly.to_numpy()[:-1]]
    current['year_returns'] = {year: float(value) for year, value in zip(yearly.index, yearly.to_numpy() / starts - 1., strict=True)}
    return current


def compare_summary(computed, retained, label):
    for field, value in computed.items():
        if isinstance(value, dict):
            compare_summary(value, retained[field], label + '/' + field)
        elif value is None:
            if retained[field] is not None:
                raise ValueError(label + '/' + field + ': missingness differs')
        else:
            near(value, retained[field], label=label + '/' + field)


def main():
    analysis_path = WORK / 'others/analysis.json'
    analysis_hash = digest(analysis_path)
    analysis = read(analysis_path)
    manifest = read(WORK / 'others/accounts.json')
    if analysis['status'] != 'PASS' or set(manifest) != set(PARAMETERS):
        raise ValueError('Completed analysis and exact declared account set required')
    if analysis['account_manifest_sha256'] != digest(WORK / 'others/accounts.json'):
        raise ValueError('Analysis account manifest binding differs')
    if analysis['analysis_source_sha256'] != digest(WORK / 'src/analyze.py'):
        raise ValueError('Analysis implementation binding differs')
    payloads, computed, immutable_refs = {}, {}, {}
    for key, record in manifest.items():
        value = record['evidence']
        reference = EvidenceRef.from_dict(value)
        if reference.experiment.experiment_id != WORK.name or (reference.schema, reference.schema_version) != ('equity_research', 4):
            raise ValueError('Wrong experiment owner or account schema')
        path, content = load_reference(value)
        envelope = json.loads(content)
        allowed = {(envelope[n]['kind'], envelope[n]['sha256']) for n in ('input_ref', 'candidate_ref', 'benchmark_ref')}

        def resolve(artifact):
            if set(artifact) != {'kind', 'sha256'} or (artifact['kind'], artifact['sha256']) not in allowed:
                raise ValueError('Dependency is outside this formal account closure')
            dependency = (path.parent / (artifact['sha256'] + '.json')).read_bytes()
            if sha256(dependency).hexdigest() != artifact['sha256']:
                raise ValueError('Dependency hash differs')
            return dependency

        payload = materialize_equity(content, resolve).payload
        if (payload['request']['candidate_id'] != key or payload['request_hash'] != record['request_hash']
                or payload['evaluation_id'] != record['evaluation_id']
                or payload['evaluation_identity'] != record['evaluation_identity']
                or value != analysis['source_accounts'][key]):
            raise ValueError('Formal manifest and analysis source identity differ')
        request = payload['request']
        if (request['fee_rate'] != .001 or request['initial_cash'] != 100000.
                or request['frequency_window_days'] != 60 or request['drawdown_basis'] != 'BAR_CLOSE'):
            raise ValueError('Original economic contract differs')
        current = {name: numbers(payload['runs'][name], request['initial_cash']) for name in ('candidate', 'buy_hold')}
        compare_summary(current['candidate'], analysis['summaries'][key]['candidate'], key + '/candidate')
        compare_summary(current['buy_hold'], analysis['summaries'][key]['benchmark'], key + '/benchmark')
        c, b = current['candidate'], current['buy_hold']
        goals = {'annualized_return': c['annualized_return'] >= 1.5 * b['annualized_return'] if b['annualized_return'] > 0 else c['annualized_return'] > 0,
            'relative_drawdown': c['bar_max_drawdown'] <= .8 * b['bar_max_drawdown'],
            'absolute_drawdown': c['bar_max_drawdown'] <= .25,
            'frequency_median': c['rolling_60_closed_cycle_median'] >= 6,
            'frequency_coverage': c['coverage_at_least_three'] >= .9}
        if goals != analysis['summaries'][key]['goals'] or all(goals.values()) != analysis['summaries'][key]['all_goals_met']:
            raise ValueError('Original five-goal judgment differs')
        current['goals'] = goals
        payloads[key], computed[key], immutable_refs[key] = payload, current, value
    if payloads['C0061']['runs']['buy_hold'] != payloads['C0062']['runs']['buy_hold']:
        raise ValueError('Complete shared benchmark differs')
    control = read(WORK / 'others/control_equivalence.json')
    if (control['status'] != 'PASS' or control['new_reference'] != immutable_refs['C0062']
            or any(v['status'] != 'PASS' for v in control['comparisons'].values())):
        raise ValueError('Old/new control equivalence is not source-bound PASS')
    diagnosis_ref = analysis['public_diagnosis']['reference']
    _, content = load_reference(diagnosis_ref)
    diagnosis = json.loads(content)
    if diagnosis['status'] != 'COMPUTED' or diagnosis['issues'] or digest(WORK / 'others/public_diagnosis.json') != diagnosis_ref['sha256']:
        raise ValueError('Public diagnosis is incomplete or changed')
    if {r['sha256'] for r in diagnosis['sources']} != {r['sha256'] for r in immutable_refs.values()}:
        raise ValueError('Public diagnosis refers to different accounts')
    by_id = {p['evaluation_id']: key for key, p in payloads.items()}
    if len(diagnosis['reconciliation']) != 2 or {r['evaluation_id'] for r in diagnosis['reconciliation']} != set(by_id):
        raise ValueError('Public diagnosis reconciliation coverage differs')
    for row in diagnosis['reconciliation']:
        key = by_id[row['evaluation_id']]
        end = computed[key]['candidate']['ending_equity']
        near(row['opening_equity'], 100000., label=key + '/public opening')
        near(row['closing_equity'], end, label=key + '/public closing')
        near(row['equity_change'], end - 100000., label=key + '/public net change')
        near(row['decomposed_change'], end - 100000., label=key + '/public decomposed change')
        near(row['residual'], 0., label=key + '/public residual')
    if diagnosis['reconciliation'] != analysis['public_diagnosis']['reconciliation']:
        raise ValueError('Retained public reconciliation differs')
    path_counts = Counter('both_enter' if row['baseline_cycle_id'] and row['alternative_cycle_id']
        else 'baseline_only' if row['baseline_cycle_id'] else 'alternative_only' for row in diagnosis['path_comparison'])
    if dict(path_counts) != analysis['public_diagnosis']['path_comparison_counts']:
        raise ValueError('Public path comparison counts differ')
    if analysis_hash != digest(analysis_path):
        raise ValueError('Analysis changed during verification')
    save(WORK / 'others/result_validation.json', {
        'status': 'PASS', 'scope': 'INDEPENDENT_FORMAL_V4_CLOSURES_NUMBERS_GOALS_PUBLIC_DIAGNOSIS',
        'analysis_sha256': analysis_hash, 'verification_source_sha256': digest(WORK / 'src/verify.py'),
        'account_manifest_sha256': digest(WORK / 'others/accounts.json'),
        'accounts': computed, 'source_accounts': immutable_refs,
        'public_diagnosis': diagnosis_ref, 'public_amount_reconciliation': 'PASS',
        'counts': {'new_economic_configurations': 1, 'technical_control_recomputations': 1,
            'shared_benchmarks': 1, 'formal_candidate_accounts_verified': 2, 'new_account_replays_by_verifier': 0},
        'method': 'NumPy cumulative peaks and indexed exit-day prefix sums; independent of analyze.summary.',
        'limitations': ['No new strategy execution or whole-repository regression.',
            'Control full-path equivalence is authenticated as an existing result, not rerun by this verifier.',
            'Repeated development sample and source/contract limitations remain.']})
    print('EX032_INDEPENDENT_RESULT_VALIDATION_PASS', flush=True)


if __name__ == '__main__':
    main()
