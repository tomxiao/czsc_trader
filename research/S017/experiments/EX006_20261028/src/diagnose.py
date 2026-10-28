"""Diagnose retained S017 accounts; no strategy evaluation or holdout access."""
from datetime import date
from hashlib import sha256
import importlib.util
import json
from math import exp, fsum, isclose, log
from pathlib import Path
import sys

from czsc_trader.application import diagnose_accounts, publish_evidence
from czsc_trader.research_tools import ExperimentRef, MaterialEvidenceWrite
from czsc_trader.research_tools.account_diagnosis import AccountDiagnosisRequest
from czsc_trader.research_tools.evaluation import EvaluationWindow

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
EXPERIMENT = ExperimentRef('S017', 'EX006_20261028')
PRIOR_PATH = ROOT/'research/S017/experiments/EX004_20261028/src/analyze.py'
spec = importlib.util.spec_from_file_location('_s017_ex004_for_diagnosis', PRIOR_PATH)
if spec is None or spec.loader is None:
    raise ImportError('cannot load exact retained analysis helpers')
PRIOR = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = PRIOR
spec.loader.exec_module(PRIOR)
REPOSITORY = PRIOR.REPOSITORY
DEPENDENCIES = (PRIOR_PATH, PRIOR_PATH.with_name('run.py'), PRIOR.PRIOR_SOURCE, PRIOR.PRIOR_RUNNER_SOURCE)
COMPARISONS = (('C0013', 'C0000'), ('C0029', 'C0000'), ('C0029', 'C0013'))
STATES = ('BOTH_HELD', 'BOTH_FLAT', 'BASELINE_ONLY_HELD', 'SUBJECT_ONLY_HELD', 'TRANSITION')


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, ensure_ascii=False, indent=2).encode())


def material(context, name, path):
    return publish_evidence(context, MaterialEvidenceWrite(
        EXPERIMENT, name, path.read_bytes(), 'application/json', 'json'))


def totals(rows):
    return {
        'intervals': len(rows),
        'subject_log_return': fsum(row['subject_log_return'] for row in rows),
        'baseline_log_return': fsum(row['baseline_log_return'] for row in rows),
        'relative_log_return': fsum(row['relative_log_return'] for row in rows),
    }


def exposure_decomposition(subject, baseline, initial):
    """Accounting locations on original accounts, never a trading counterfactual."""
    a, b = subject['account_points'], baseline['account_points']
    if [(p['time'], p['session']) for p in a] != [(p['time'], p['session']) for p in b]:
        raise ValueError('account timestamps or sessions differ')
    prior_a = prior_b = initial
    qa = qb = 0
    seen_subject = False
    rows = []
    for pa, pb in zip(a, b):
        if not '2019-01-02' <= pa['session'] <= '2025-12-31':
            raise ValueError('observation outside development authorization')
        if min(prior_a, prior_b, pa['equity'], pb['equity']) <= 0:
            raise ValueError('log attribution requires positive original equity')
        la, lb = log(pa['equity']/prior_a), log(pb['equity']/prior_b)
        if pa['quantity'] != qa or pb['quantity'] != qb:
            state = 'TRANSITION'
        elif qa > 0 and qb > 0:
            state = 'BOTH_HELD'
        elif qa == 0 and qb == 0:
            state = 'BOTH_FLAT'
        elif qb > 0:
            state = 'BASELINE_ONLY_HELD'
        else:
            state = 'SUBJECT_ONLY_HELD'
        rows.append({
            'time': pa['time'], 'session': pa['session'], 'state': state,
            'subject_log_return': la, 'baseline_log_return': lb, 'relative_log_return': la-lb,
            'flat_phase': ('AFTER_PRIOR_HOLDING' if seen_subject else 'BEFORE_FIRST_ENTRY')
                          if state == 'BASELINE_ONLY_HELD' else None,
            'baseline_sign': 'UP' if lb > 0 else 'DOWN' if lb < 0 else 'ZERO',
            'cross_session': bool(rows and rows[-1]['session'] != pa['session']),
        })
        seen_subject = seen_subject or pa['quantity'] > 0
        prior_a, prior_b = pa['equity'], pb['equity']
        qa, qb = pa['quantity'], pb['quantity']
    total = totals(rows)
    target = log(a[-1]['equity']/b[-1]['equity'])
    residual = total['relative_log_return']-target
    if not isclose(residual, 0., abs_tol=1e-10):
        raise ValueError('relative log returns do not telescope to original final wealth')
    result = {}
    windows = [('FULL', lambda r: True), ('PRE_2025', lambda r: r['session'] < '2025-01-01'),
               ('YEAR_2025', lambda r: r['session'] >= '2025-01-01')]
    windows += [(str(y), lambda r, year=y: int(r['session'][:4]) == year) for y in range(2019, 2025)]
    for name, predicate in windows:
        selected = [row for row in rows if predicate(row)]
        if not selected:
            continue
        states = {state: totals([row for row in selected if row['state'] == state]) for state in STATES}
        sums = totals(selected)
        if sum(x['intervals'] for x in states.values()) != len(selected):
            raise ValueError('state partition incomplete')
        if not isclose(fsum(x['relative_log_return'] for x in states.values()), sums['relative_log_return'], abs_tol=1e-10):
            raise ValueError('state partition does not reconcile')
        flat = [row for row in selected if row['state'] == 'BASELINE_ONLY_HELD']
        flat_detail = []
        for phase in ('BEFORE_FIRST_ENTRY', 'AFTER_PRIOR_HOLDING'):
            for sign in ('UP', 'DOWN', 'ZERO'):
                group = [row for row in flat if row['flat_phase'] == phase and row['baseline_sign'] == sign]
                flat_detail.append({'phase': phase, 'baseline_sign': sign, **totals(group)})
        result[name] = {'totals': sums, 'relative_wealth_change': exp(sums['relative_log_return'])-1.,
                        'states': states, 'flat_breakdown': flat_detail,
                        'cross_session': totals([row for row in selected if row['cross_session']]),
                        'within_session': totals([row for row in selected if not row['cross_session']])}
    # Contiguous flat episodes are descriptive, inherit real prices and prior holdings.
    episodes, current = [], []
    for row in rows:
        if row['state'] == 'BASELINE_ONLY_HELD':
            if current and current[-1]['flat_phase'] != row['flat_phase']:
                episodes.append(current)
                current = []
            current.append(row)
        elif current:
            episodes.append(current)
            current = []
    if current:
        episodes.append(current)
    compact_episodes = [{'start': group[0]['time'], 'end': group[-1]['time'],
                         'phase': group[0]['flat_phase'], **totals(group)} for group in episodes]
    return {'status': 'PASS', 'windows': result, 'telescoping_residual': residual,
            'terminal_subject_equity': a[-1]['equity'], 'terminal_baseline_equity': b[-1]['equity'],
            'terminal_relative_wealth': a[-1]['equity']/b[-1]['equity'],
            'flat_episodes': compact_episodes,
            'semantics': [
                'Each interval joins the previous observed equity to current equity; first interval begins at declared initial cash.',
                'Any endpoint quantity change in either account is TRANSITION; unchanged positive quantities are held states.',
                'States are mutually exclusive and additive in log wealth, not additive percentage returns or independent causal contributions.',
                'UP/DOWN and flat episode outcomes are hindsight descriptions, never decision-time signal inputs.',
                'AFTER_PRIOR_HOLDING means any prior held observation; it does not assume an alternative immediate re-entry was feasible.',
                'A cross-session interval includes the entire gap between prior close and current observation, including the first bar; it is not pure overnight return.',
                'Constant positive holdings of the same stock can still differ due to residual cash weights, fees and prior wealth; BOTH_HELD is not an alpha estimate.',
                'No position or fee is changed, no strategy is replayed, and no zero-cost counterfactual is computed.',
            ]}


def selfcheck():
    def account(q, equity):
        return {'account_points': [{'time': str(i), 'session': '2019-01-02', 'quantity': amount, 'equity': value}
                                   for i, (amount, value) in enumerate(zip(q, equity))]}
    # all five mutually exclusive endpoint categories plus separate switch intervals
    subject = account([0, 0, 1, 1, 0, 0, 1, 1], [100, 100, 99, 105, 104, 104, 103, 110])
    baseline = account([0, 0, 0, 0, 1, 1, 1, 1], [100, 100, 100, 100, 99, 102, 103, 110])
    value = exposure_decomposition(subject, baseline, 100)
    states = value['windows']['FULL']['states']
    assert all(states[s]['intervals'] for s in STATES)
    assert value['terminal_relative_wealth'] == 1.
    assert abs(value['windows']['FULL']['totals']['relative_log_return']) < 1e-12
    return {'status': 'PASS', 'checks': ['all five states nonempty', 'mutually exclusive complete partition',
                                        'whole-account telescoping', 'zero net relative wealth reconciliation']}


def main():
    checks = selfcheck()
    dependency_hashes = {path: sha256(path.read_bytes()).hexdigest() for path in DEPENDENCIES}
    payloads, refs = {}, {}
    for experiment_id, keys in [('EX002_20261028', ('C0000',)), ('EX003_20261028', ('C0013',)),
                                ('EX005_20261028', ('C0029',))]:
        experiment = ExperimentRef('S017', experiment_id)
        p, r = PRIOR.load_subset(experiment.resolve(ROOT), experiment, keys)
        payloads.update(p)
        refs.update(r)
    contract = PRIOR.verify_contracts(payloads)
    buyhold = PRIOR.PRIOR.verify_hold_path(payloads)
    research = PRIOR.RUN.context()
    summary = {key: PRIOR.PRIOR.summarize(value) for key, value in payloads.items()}
    diagnoses, decomposition = {}, {}
    for subject, baseline in COMPARISONS:
        key = subject+'_vs_'+baseline
        diagnosis = diagnose_accounts(REPOSITORY, AccountDiagnosisRequest(
            PRIOR.account_ref(refs[baseline], payloads[baseline]),
            PRIOR.account_ref(refs[subject], payloads[subject]),
            EvaluationWindow('DEV_2019_2025', date(2019, 1, 2), date(2025, 12, 31))))
        raw = diagnosis.to_dict()
        path = ROOT/'research/S017/assets/runs/EX006_20261028/diagnostics'/(key+'.json')
        save(path, raw)
        evidence = material(research, 'diagnosis-'+key, path)
        if diagnosis.status.value != 'COMPUTED':
            raise ValueError(f'public diagnosis {key}: {diagnosis.status.value} {diagnosis.issues}')
        pnl = []
        for index, value in enumerate(diagnosis.pnl_breakdown):
            pnl.append({'evaluation_id': value.evaluation_id,
                        'opening_equity': value.daily[0].opening_equity,
                        'closing_equity': value.daily[-1].closing_equity,
                        **{name: fsum(getattr(row, name) for row in value.daily)
                           for name in ('entry', 'holding', 'exit', 'fees', 'residual')},
                        'annual': raw['pnl_breakdown'][index]['annual']})
        diagnoses[key] = {'status': diagnosis.status.value, 'issues': list(diagnosis.issues),
                         'subject': subject, 'baseline': baseline, 'evidence': evidence.to_dict(),
                         'raw_path': path.relative_to(ROOT).as_posix(), 'pnl': pnl,
                         'reconciliation': raw['reconciliation'],
                         'path_rows': len(diagnosis.path_comparison), 'daily_rows': len(diagnosis.daily_paths)}
        decomposition[key] = exposure_decomposition(payloads[subject]['runs']['candidate'],
                                                    payloads[baseline]['runs']['candidate'],
                                                    payloads[subject]['request']['initial_cash'])
        print('DIAGNOSIS', key, diagnosis.status.value, flush=True)
    if any(sha256(path.read_bytes()).hexdigest() != digest for path, digest in dependency_hashes.items()):
        raise ValueError('a retained helper changed during diagnosis')
    compact = {}
    for key, value in summary.items():
        metric = value['audited_metrics']
        compact[key] = {'metrics': {field: metric[field] for field in
                       ('annualized_return', 'total_return', 'bar_max_drawdown', 'closed_cycles', 'fees', 'rolling_60_closed_cycle_median')},
                        'holding_bar_fraction': value['holding_bar_fraction'],
                        'order_reason_counts': value['order_reason_counts'], 'fill_count': value['fill_count'],
                        'annual': value['annual'], 'source': refs[key].to_dict(),
                        'evaluation_id': payloads[key]['evaluation_id']}
    output = {'schema': 's017-research-diagnosis/v1', 'status': 'PASS',
              'scope': 'retained development accounts 2019-01-02 to 2025-12-31 only; no new replay',
              'new_strategy_evaluations': 0, 'new_public_diagnoses': len(diagnoses),
              'source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'dependencies': [{'path': p.relative_to(ROOT).as_posix(), 'sha256': h} for p, h in dependency_hashes.items()],
              'selfcheck': checks, 'contract_comparability': contract, 'buyhold_path_verification': buyhold,
              'accounts': compact, 'diagnoses': diagnoses, 'exposure_decomposition': decomposition,
              'limitations': ['Same exposed development data and result-selected representatives; not independent validation.',
                              'Accounting attribution and log-state attribution identify where returns occurred, not independent causes.',
                              'Direct fees are amounts charged on original paths; adding them back is not a feasible zero-fee account.',
                              'The latest research round has lower drawdown but lower return; this diagnostic does not change targets or eligibility.']}
    save(WORK/'others/numeric_analysis.json', output)
    print('NUMERIC_ANALYSIS PASS', WORK/'others/numeric_analysis.json', flush=True)


if __name__ == '__main__':
    main()
