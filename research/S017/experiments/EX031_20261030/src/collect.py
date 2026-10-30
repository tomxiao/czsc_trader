"""Authenticate retained S017 evidence; describe existing accounts, never replay."""
# ruff: noqa: E402
import json
import math
import os
from collections import Counter
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
os.environ['TEMP'] = os.environ['TMP'] = str(ROOT / '.tmp')
from czsc_trader.application import RepositoryContext, validate_experiment
from czsc_trader.research_tools import (
    EvidenceRef, ExperimentRef, ExperimentValidationRequest, ExperimentValidationScope,
)
from czsc_trader.research_tools.equity_evaluation import EquityEvaluationResult
from czsc_trader.research_tools.equity_replay_v3 import materialize_v3

REPOSITORY = RepositoryContext.discover(ROOT)
EXPERIMENTS = ROOT / 'research/S017/experiments'
SELECTED = ('EX006_20261028', 'EX018_20261029', 'EX027_20261029',
            'EX028_20261030', 'EX029_20261030', 'EX030_20261030')


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
                    encoding='utf-8', newline='\n')


def authenticated(ref):
    reference = EvidenceRef.from_dict(ref)
    if reference.experiment.strategy_id != 'S017':
        raise ValueError('Cross-batch evidence refused')
    path = reference.resolve(ROOT)
    if digest(path) != reference.sha256:
        raise ValueError('Source changed during read')
    return path


def close(actual, expected):
    if not math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-7):
        raise ValueError(f'Numerical disagreement: {actual} != {expected}')


def describe(run, initial):
    points = run['account_points']
    daily = run['account_daily']
    sessions = [p['session'] for p in daily]
    if len(sessions) != 1760 or any(s > '2025-12-31' for s in sessions):
        raise ValueError('Authorized development boundary changed')
    equity = [initial, *[p['equity'] for p in points]]
    peak, drawdown = initial, 0.
    for value in equity:
        peak = max(peak, value)
        drawdown = max(drawdown, 1 - value / peak)
    closed = [t for t in run['trades'] if t['status'] == 'CLOSED']
    counts = Counter(datetime.fromisoformat(t['exit_at'].replace('Z', '+00:00'))
                     .astimezone(ZoneInfo('America/New_York')).date().isoformat() for t in closed)
    if set(counts) - set(sessions):
        raise ValueError('Exit lies outside observed sessions')
    rolling = [sum(counts[s] for s in sessions[i - 59:i + 1]) for i in range(59, len(sessions))]
    fees = sum(f['fees'] for f in run['fills'])
    ending = equity[-1]
    net_pnl = sum(t['net_pnl'] for t in closed)
    nonclosed_change = ending - initial - net_pnl
    if points[-1]['quantity'] == 0:
        close(net_pnl, ending - initial)
    positive = sorted((t['net_pnl'] for t in closed if t['net_pnl'] > 0), reverse=True)
    return {
        'annualized_return': (ending / initial) ** (252 / len(sessions)) - 1,
        'bar_max_drawdown': drawdown,
        'closed_cycles': len(closed),
        'rolling_60_closed_cycle_median': median(rolling),
        'coverage_at_least_three': mean(n >= 3 for n in rolling),
        'complete_windows': len(rolling),
        'holding_bar_fraction': mean(p['quantity'] > 0 for p in points),
        'ending_equity': ending, 'ending_quantity': points[-1]['quantity'],
        'fees': fees, 'closed_net_pnl': net_pnl,
        'net_equity_change': ending - initial,
        'nonclosed_equity_change': nonclosed_change,
        'account_mark_to_market_change_before_direct_fees': ending - initial + fees,
        'win_rate': mean(t['net_pnl'] > 0 for t in closed),
        'mean_cycle_net_return': mean(t['net_return'] for t in closed),
        'top_five_positive_pnl_share': sum(positive[:5]) / sum(positive),
        'year_returns': {str(y): daily[max(i for i, p in enumerate(daily) if p['session'].startswith(str(y)))]['equity'] /
                         (initial if y == 2019 else daily[max(i for i, p in enumerate(daily) if p['session'].startswith(str(y - 1)))]['equity']) - 1
                         for y in range(2019, 2026)},
    }


def main():
    overview = read(ROOT / '.tmp/s017_diagnosis_overview.json')
    if len(overview['experiments']) != 30 or any(e['report_state'] != 'PUBLISHED' for e in overview['experiments']):
        raise ValueError('Unexpected predecessor report inventory')
    save(WORK / 'others/intake_overview.json', overview)
    sources, report_refs, published = {}, [], {}
    for item in overview['experiments']:
        eid = item['experiment']['experiment_id']
        work = EXPERIMENTS / eid
        reference = item['report']
        snapshot = read(authenticated(reference))
        close_hash = digest(work / 'report.md')
        if close_hash != snapshot['report_sha256']:
            raise ValueError('Report diverged from published snapshot: ' + eid)
        report_refs.append(reference)
        sources[str((work / 'report.md').relative_to(ROOT)).replace('\\', '/')] = close_hash
        published[eid] = {e['sha256'] for e in snapshot['evidence']}
    checks = {}
    for eid in SELECTED:
        check = validate_experiment(REPOSITORY, ExperimentValidationRequest(
            ExperimentRef('S017', eid), ExperimentValidationScope.REPORT_PUBLICATION))
        checks[eid] = check.to_dict()
        if check.status.value != 'PASS':
            raise ValueError('Predecessor publication check failed: ' + eid)
        print('SOURCE_PUBLICATION_PASS', eid, flush=True)
    rows, account_refs, diagnosis_refs = {}, {}, {}
    for eid, name in [('EX027_20261029', 'analysis.json'),
                      ('EX029_20261030', 'account_analysis.json'),
                      ('EX030_20261030', 'account_analysis.json')]:
        path = EXPERIMENTS / eid / 'others' / name
        if digest(path) not in published[eid]:
            raise ValueError('Analysis not bound by its published report')
        sources[str(path.relative_to(ROOT)).replace('\\', '/')] = digest(path)
        analysis = read(path)
        if analysis['status'] != 'PASS':
            raise ValueError('Retained analysis failed')
        for key, reference in analysis['source_accounts'].items():
            if key in rows:
                if reference != account_refs[key]:
                    raise ValueError('Reused account identity differs')
                continue
            path = authenticated(reference)
            content = path.read_bytes()
            envelope = json.loads(content)
            result = EquityEvaluationResult(envelope['request_hash'], content)
            if envelope['schema_version'] == 3:
                allowed = {(envelope[n]['kind'], envelope[n]['sha256']) for n in ('input_ref', 'candidate_ref', 'benchmark_ref')}

                def resolve(ref):
                    if set(ref) != {'kind', 'sha256'} or (ref['kind'], ref['sha256']) not in allowed:
                        raise ValueError('Unowned V3 dependency')
                    return (path.parent / (ref['sha256'] + '.json')).read_bytes()

                payload = materialize_v3(result, resolve).payload
            elif envelope['schema_version'] == 2:
                payload = result.payload
            else:
                raise ValueError('Unsupported retained account schema')
            request = payload['request']
            if request['candidate_id'] != key or request['fee_rate'] != .001 or request['initial_cash'] != 100000.:
                raise ValueError('Account identity or economic contract differs')
            current = describe(payload['runs']['candidate'], request['initial_cash'])
            retained = analysis['summaries'][key]['candidate']
            for field in ('annualized_return', 'bar_max_drawdown', 'closed_cycles', 'rolling_60_closed_cycle_median',
                          'fees', 'holding_bar_fraction', 'ending_equity'):
                close(current[field], retained[field])
            close(current['coverage_at_least_three'], retained['frequency_60_sessions']['coverage_at_least_three'])
            metric = payload['runs']['candidate']['metrics']
            for field in ('annualized_return', 'bar_max_drawdown', 'closed_cycles', 'fees', 'rolling_60_closed_cycle_median'):
                close(current[field], metric[field])
            if current['complete_windows'] != 1701:
                raise ValueError('Frequency denominator changed')
            current['goals'] = retained_goals = analysis['summaries'][key]['goals']
            benchmark = analysis['summaries'][key]['benchmark']
            independently_checked = {
                'annualized_return': current['annualized_return'] >= 1.5 * benchmark['annualized_return'],
                'relative_drawdown': current['bar_max_drawdown'] <= .8 * benchmark['bar_max_drawdown'],
                'absolute_drawdown': current['bar_max_drawdown'] <= .25,
                'frequency_median': current['rolling_60_closed_cycle_median'] >= 6,
                'frequency_coverage': current['coverage_at_least_three'] >= .9,
            }
            if independently_checked != retained_goals:
                raise ValueError('Original goal judgment differs')
            rows[key], account_refs[key] = current, reference
            print('EXISTING_ACCOUNT_VERIFIED', key, flush=True)
        for value in analysis['diagnostics'].values():
            ref = value['evidence']
            authenticated(ref)
            diagnosis_refs[ref['sha256']] = ref
    if len(rows) != 9 or len(diagnosis_refs) != 7 or any(all(r['goals'].values()) for r in rows.values()):
        raise ValueError('Selected coverage or economic conclusion differs')
    save(WORK / 'others/diagnostic_facts.json', {
        'schema': 's017-existing-evidence-diagnosis/v1', 'status': 'PASS',
        'baseline_head': 'd51bd6b6f5c25547e0bc4f2691eff71d63448a19',
        'source_hashes': sources, 'report_refs': report_refs,
        'predecessor_publication_checks': checks, 'accounts': rows,
        'account_refs': account_refs, 'public_diagnosis_refs': list(diagnosis_refs.values()),
        'new_strategy_configurations': 0, 'new_account_replays': 0, 'new_public_account_diagnoses': 0,
        'semantics': {
            'money': 'Equity change plus paid direct fees is original-path accounting only, not a zero-cost counterfactual account. Open-position change is kept separately; no hypothetical liquidation.',
            'frequency': '1701 overlapping 60-session windows are not independent samples.',
            'scope': 'Nine selected existing accounts, seven existing public diagnoses; not full-batch numerical recertification.',
            'sources': 'Thirty published report texts authenticated; six key report source closures validated; no market data fetched.',
        },
    })
    print('DIAGNOSIS_FACTS_PASS', len(rows), len(diagnosis_refs), flush=True)


if __name__ == '__main__':
    main()
