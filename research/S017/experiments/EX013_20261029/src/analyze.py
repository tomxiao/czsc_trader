"""Authenticate retained accounts and report descriptive, continuous-account facts."""
from datetime import date
from hashlib import sha256
from pathlib import Path
import json

from czsc_trader.application import diagnose_accounts
from czsc_trader.research_tools import EvidenceRef, ExperimentRef
from czsc_trader.research_tools.account_diagnosis import AccountDiagnosisRequest, AccountRunRef
from czsc_trader.research_tools.equity_assessment import build_equity_assessment_payload
from czsc_trader.research_tools.equity_evaluation import EquityEvaluationResult
from czsc_trader.research_tools.evaluation import EvaluationIdentity, EvaluationWindow
from strategy_manager import CandidateKey

from run import ROOT, WORK, REPOSITORY, EXPERIMENT, configurations, context, read, save, material

CONTROL = ExperimentRef('S017', 'EX003_20261028')
CONTROL_ID = 'C0013'
PRIMARY = ('bars', 'sessions', 'actions', 'constraints')
ECONOMIC_FIELDS = ('initial_cash', 'fee_rate', 'window', 'history_start', 'specification_hash',
    'specification', 'benchmark_sha256', 'benchmark', 'sources', 'instrument', 'drawdown_basis',
    'concentration_basis', 'frequency_window_days', 'measurement_tier')


def load_accounts(work, experiment, keys, *, exact=False):
    rows = read(work / 'others/accounts.json')
    if exact and set(rows) != set(keys) or not set(keys) <= set(rows):
        raise ValueError('account manifest differs from the requested fixed candidate set')
    payloads, references = {}, {}
    for key in keys:
        record = rows[key]
        reference = EvidenceRef.from_dict(record['evidence'])
        if reference.experiment != experiment or (reference.schema, reference.schema_version) != ('equity_research', 2):
            raise ValueError('account reference belongs to a different experiment or schema')
        # resolve is the public authenticated reader in the current platform.
        # Recheck the bytes actually decoded, including any change after resolve.
        content = reference.resolve(ROOT).read_bytes()
        if sha256(content).hexdigest() != reference.sha256:
            raise ValueError('account evidence changed after reference authentication')
        payload = EquityEvaluationResult(record['request_hash'], content).payload
        if (payload['evaluation_id'] != record['evaluation_id']
                or payload['evaluation_identity'] != record['evaluation_identity']
                or payload['request']['candidate_id'] != key
                or payload['request']['experiment'] != {
                    'strategy_id': experiment.strategy_id, 'experiment_id': experiment.experiment_id}):
            raise ValueError('account manifest identity differs from published evidence')
        evidence = build_equity_assessment_payload(payload)
        if len(evidence) != 1 or evidence[0].evaluation_id != payload['evaluation_id']:
            raise ValueError('public account authentication selected a different evaluation')
        payloads[key], references[key] = payload, reference
        print('AUTHENTICATED', experiment.experiment_id, key, flush=True)
    return payloads, references


def verify_contracts(payloads):
    control = payloads[CONTROL_ID]
    checks = []
    for key, payload in payloads.items():
        for field in ECONOMIC_FIELDS:
            equal = payload['request'][field] == control['request'][field]
            checks.append({'candidate': key, 'field': field, 'equal': equal})
            if not equal:
                raise ValueError(f'noncomparable economic contract: {key}/{field}')
        for product in PRIMARY:
            # Include every metadata field and the actual immutable content hash.
            equal = payload['data'][product] == control['data'][product]
            checks.append({'candidate': key, 'field': 'data.' + product, 'equal': equal})
            if not equal:
                raise ValueError(f'noncomparable primary market input: {key}/{product}')
    return {'status': 'PASS', 'checks': checks,
        'manifest_note': 'Joint preparation identities may differ; exact primary product hashes and full metadata must match. Auxiliary declarations remain independently authenticated by the public assessment API.'}


def economic(value):
    """Normalize bookkeeping IDs only, following retained EX002 verify_hold_path."""
    if isinstance(value, list):
        return [economic(item) for item in value]
    if isinstance(value, dict):
        return {key: economic(item) for key, item in value.items()
                if key not in {'decision_id', 'cycle_id', 'fill_id', 'order_id', 'plan_id'}}
    return value


def verify_hold_path(payloads):
    baseline = payloads[CONTROL_ID]['runs']['buy_hold']
    checks = []
    for key, payload in payloads.items():
        for field in ('account_points', 'account_daily', 'fills', 'trades', 'actions', 'metrics'):
            equal = economic(payload['runs']['buy_hold'][field]) == economic(baseline[field])
            checks.append({'candidate': key, 'field': field, 'equal': equal})
            if not equal:
                raise ValueError(f'embedded buyhold economic path differs: {key}/{field}')
    return {'status': 'PASS', 'checks': checks,
        'baseline': 'EX003/C0013 embedded buy_hold; only implementation bookkeeping IDs excluded'}


def summarize_run(run, initial):
    """Describe already authenticated facts; this is not a replacement account audit."""
    metrics, points, daily = run['metrics'], run['account_points'], run['account_daily']
    counts = metrics['rolling_60_closed_cycle_counts']
    annual = []
    opening = initial
    for year in sorted({row['session'][:4] for row in daily}):
        selected = [row for row in daily if row['session'].startswith(year)]
        closing = selected[-1]['equity']
        annual.append({'year': int(year), 'start_session': selected[0]['session'],
            'end_session': selected[-1]['session'], 'sessions': len(selected),
            'opening_equity': opening, 'closing_equity': closing, 'net_return': closing / opening - 1.})
        opening = closing
    return {
        'annualized_return': metrics['annualized_return'], 'bar_max_drawdown': metrics['bar_max_drawdown'],
        'daily_max_drawdown': metrics['daily_max_drawdown'], 'closed_cycles': metrics['closed_cycles'],
        'rolling_60_closed_cycle_median': metrics['rolling_60_closed_cycle_median'], 'fees': metrics['fees'],
        'frequency_60_sessions': {'complete_windows': len(counts),
            'windows_at_least_three': sum(count >= 3 for count in counts),
            'coverage_at_least_three': sum(count >= 3 for count in counts) / len(counts) if counts else None},
        'holding_bar_fraction': sum(row['quantity'] > 0 for row in points) / len(points),
        'holding_session_close_fraction': sum(row['quantity'] > 0 for row in daily) / len(daily),
        'year_returns': annual, 'audited_metrics': metrics,
    }


def goals(candidate, benchmark):
    coverage = candidate['frequency_60_sessions']['coverage_at_least_three']
    median = candidate['rolling_60_closed_cycle_median']
    checks = {
        'annualized_return': (candidate['annualized_return'] >= 1.5 * benchmark['annualized_return']
                              if benchmark['annualized_return'] > 0 else candidate['annualized_return'] > 0),
        'relative_drawdown': candidate['bar_max_drawdown'] <= .8 * benchmark['bar_max_drawdown'],
        'absolute_drawdown': candidate['bar_max_drawdown'] <= .25,
        'frequency_median': median is not None and median >= 6,
        'frequency_coverage': coverage is not None and coverage >= .9,
    }
    return checks


def account_ref(reference, payload):
    identity = dict(payload['evaluation_identity'])
    identity['candidate'] = CandidateKey(**identity['candidate'])
    return AccountRunRef(reference, EvaluationIdentity(**identity))


def main():
    keys = tuple(configurations())
    if CONTROL_ID in keys:
        raise ValueError('new candidate IDs must not overwrite the historical control identity')
    payloads, refs = load_accounts(WORK, EXPERIMENT, keys, exact=True)
    old, old_refs = load_accounts(CONTROL.resolve(ROOT), CONTROL, (CONTROL_ID,))
    payloads.update(old)
    refs.update(old_refs)
    contracts, hold_path = verify_contracts(payloads), verify_hold_path(payloads)
    pairs = read(WORK / 'protocols/comparisons.json')
    if type(pairs) is not list or any(type(pair) is not list or len(pair) != 2
            or any(key not in keys for key in pair) or pair[0] == pair[1] for pair in pairs):
        raise ValueError('comparisons must contain distinct subject/control IDs from this experiment')
    pairs = tuple(dict.fromkeys(tuple(pair) for pair in [*[[key, CONTROL_ID] for key in keys], *pairs]))
    research, diagnostics = context(), {}
    for subject, control in pairs:
        name = subject + '_vs_' + control
        diagnosis = diagnose_accounts(REPOSITORY, AccountDiagnosisRequest(
            account_ref(refs[control], payloads[control]), account_ref(refs[subject], payloads[subject]),
            EvaluationWindow('DEV_2019_2025', date(2019, 1, 2), date(2025, 12, 31))))
        path = WORK / 'others/diagnostics' / (name + '.json')
        save(path, diagnosis.to_dict())
        reference = material(research, 'diagnosis-' + name, path)
        diagnostics[name] = {'status': diagnosis.status.value, 'issues': list(diagnosis.issues),
            'evidence': reference.to_dict(), 'reconciliation': diagnosis.to_dict()['reconciliation']}
        print('DIAGNOSIS', name, diagnosis.status.value, flush=True)
    summaries = {}
    for key, payload in payloads.items():
        own = summarize_run(payload['runs']['candidate'], payload['request']['initial_cash'])
        benchmark = summarize_run(payload['runs']['buy_hold'], payload['request']['initial_cash'])
        checks = goals(own, benchmark)
        summaries[key] = {'candidate': own, 'benchmark': benchmark,
                          'goals': checks, 'all_goals_met': all(checks.values())}
    okay = all(item['status'] == 'COMPUTED' for item in diagnostics.values())
    output = {'schema': 's017-stage2-context-analysis/v1', 'experiment': EXPERIMENT.experiment_id,
        'status': 'PASS' if okay else 'FAIL', 'analysis_source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
        'source_accounts': {key: ref.to_dict() for key, ref in refs.items()},
        'contract_checks': contracts, 'paired_buyhold_check': hold_path,
        'summaries': summaries, 'diagnostics': diagnostics, 'new_configurations': len(keys),
        'formal_requests': len(keys), 'account_replays': 2 * len(keys), 'public_diagnoses': len(pairs),
        'method_sources': [{'path': 'research/S017/experiments/EX002_20261028/src/analyze.py',
            'sha256': sha256((ROOT / 'research/S017/experiments/EX002_20261028/src/analyze.py').read_bytes()).hexdigest(),
            'usage': 'Read-only methodology reference for economic-ID normalization and continuous-account annual/holding/frequency descriptions; no imports or private audit calls.'}],
        'semantics': {'annual': 'Year-end equity divided by preceding year-end equity; initial cash only for first year.',
            'holding': 'Fraction of positive-quantity bar and session-close observations; not elapsed-time exposure.',
            'frequency': 'Authenticated closed-cycle counts in all complete 60-session windows; overlapping windows are not independent.',
            'goals': 'Confirmed full-window economic and dual-frequency goals only; not robustness, selection, freezing or stage advancement.'},
        'limitations': ['Repeatedly seen development data, 2019-2025; not independent validation.',
                       'No holdout, new account replay, candidate registration or production access during analysis.']}
    save(WORK / 'others/analysis.json', output)
    print(json.dumps({key: summaries[key]['all_goals_met'] for key in keys}), flush=True)
    if not okay:
        raise RuntimeError('public account diagnosis contains incomplete or invalid evidence')


if __name__ == '__main__':
    main()
