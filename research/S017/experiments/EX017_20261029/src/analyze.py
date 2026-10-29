"""Authenticate retained accounts and report descriptive, continuous-account facts."""
from datetime import date
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import json
import multiprocessing
import os

from threadpoolctl import threadpool_limits

from czsc_trader.application import diagnose_accounts
from czsc_trader.research_tools import EvidenceRef, ExperimentRef
from czsc_trader.research_tools.account_diagnosis import (AccountDiagnosisRequest, AccountDiagnosisResult, AccountRunRef)
from czsc_trader.research_tools.equity_evaluation import EquityEvaluationResult
from czsc_trader.research_tools.evaluation import EvaluationIdentity, EvaluationWindow
from strategy_manager import CandidateKey
from strategy_runtime import canonical_sha256, EquityInputBinding, EquityStrategyDefinition

from run import ROOT, WORK, REPOSITORY, EXPERIMENT, configurations, context, read, save, material

CONTROL = ExperimentRef('S017', 'EX003_20261028')
CONTROL_ID = 'C0013'
OLD_CONTROLS = {'C0013': CONTROL,
    'C0037': ExperimentRef('S017', 'EX011_20261029'),
    'C0044': ExperimentRef('S017', 'EX015_20261029')}
PRIMARY = ('bars', 'sessions', 'actions', 'constraints')
ECONOMIC_FIELDS = ('initial_cash', 'fee_rate', 'window', 'history_start', 'specification_hash',
    'specification', 'benchmark_sha256', 'benchmark', 'sources', 'instrument', 'drawdown_basis',
    'concentration_basis', 'frequency_window_days', 'measurement_tier')


def load_accounts(work, experiment, keys, *, exact=False):
    """Bind immutable account bytes; the required public diagnoses audit economics."""
    rows = read(work / 'others/accounts.json')
    if exact and set(rows) != set(keys) or not set(keys) <= set(rows):
        raise ValueError('account manifest differs from the requested fixed candidate set')
    payloads, references = {}, {}
    for key in keys:
        record = rows[key]
        reference = EvidenceRef.from_dict(record['evidence'])
        if (reference.experiment != experiment or reference.media_type != 'application/json'
                or (reference.schema, reference.schema_version) != ('equity_research', 2)):
            raise ValueError('account reference belongs to a different experiment or schema')
        # resolve is the public authenticated reader in the current platform.
        # Recheck the bytes actually decoded, including any change after resolve.
        content = reference.resolve(ROOT).read_bytes()
        if sha256(content).hexdigest() != reference.sha256:
            raise ValueError('account evidence changed after reference authentication')
        payload = EquityEvaluationResult(record['request_hash'], content).payload
        identity = account_ref(reference, payload).identity
        if (payload.get('schema') != 'equity-research/v2' or payload.get('schema_version') != 2
                or set(payload['runs']) != {'candidate', 'buy_hold'}
                or payload['evaluation_id'] != record['evaluation_id']
                or identity.evaluation_id != payload['evaluation_id']
                or identity.candidate != CandidateKey(experiment.strategy_id, key)
                or identity.content_sha256 != payload['request']['candidate_identity']['content_sha256']
                or identity.content_sha256 != payload['request']['content_sha256']
                or identity.input_sha256 != payload['request']['data_manifest']
                or identity.protocol_sha256 != record['request_hash']
                or identity.environment_sha256 != canonical_sha256(payload['request']['engine_sources'])
                or payload['evaluation_identity'] != record['evaluation_identity']
                or payload['request']['candidate_id'] != key
                or payload['request']['experiment'] != {
                    'strategy_id': experiment.strategy_id, 'experiment_id': experiment.experiment_id}):
            raise ValueError('account manifest identity differs from published evidence')
        payloads[key], references[key] = payload, reference
        print('REFERENCE_BOUND', experiment.experiment_id, key, flush=True)
    return payloads, references


def comparison_pairs(keys):
    if tuple(keys) != ('C0046',):
        raise ValueError('the fixed combination requires exactly the new C0046')
    extra = read(WORK / 'protocols/comparisons.json')
    if extra != [['C0046', 'C0037'], ['C0046', 'C0044']]:
        raise ValueError('the two structural controls and their order must remain fixed')
    return (('C0046', 'C0013'), ('C0046', 'C0037'), ('C0046', 'C0044'))


def verify_input_declarations(payloads):
    """Authenticate every binding; the three ORB inputs must be entirely equal."""
    if set(payloads) != {'C0013', 'C0037', 'C0044', 'C0046'}:
        raise ValueError('the new combined ORB requires exactly its three historical controls')
    bindings, definitions, checks = {}, {}, []
    for key, payload in payloads.items():
        request = payload['request']
        definition = EquityStrategyDefinition.from_dict(request['candidate_definition'])
        binding = EquityInputBinding.from_dict(request['input_binding'])
        actual_hashes = {name: value['content_sha256'] for name, value in payload['data'].items()}
        closed_cycle = key != 'C0013'
        valid = (json.loads(json.dumps(binding.to_dict())) == request['input_binding']
            and binding.prepared.manifest_sha256 == request['data_manifest']
            and binding.instrument == definition.instrument
            and binding.to_dict()['instrument'] == request['instrument']
            and binding.specification_hash == definition.execution_spec.fingerprint == request['specification_hash']
            and binding.warmup_bars == definition.warmup_bars == request['warmup_bars'] == 261
            and set(actual_hashes) == set(PRIMARY)
            and dict(binding.expected_identities) == actual_hashes
            and not binding.auxiliary_inputs and not definition.auxiliary_inputs
            and definition.content_identity.content_sha256 == request['content_sha256']
            and definition.feedback_mode == ('CONFIRMED_CLOSED_CYCLE_V1' if closed_cycle else 'CONFIRMED_EXECUTION')
            and definition.session_context is closed_cycle and definition.analysis_price == 'RAW')
        if not valid:
            raise ValueError('input binding or declaration differs from the original account: ' + key)
        bindings[key], definitions[key] = binding, definition
        checks.append({'candidate': key, 'field': 'input_binding_and_definition', 'equal': True,
                       'warmup_bars': 261})
    if not (bindings['C0046'] == bindings['C0037'] == bindings['C0044']):
        raise ValueError('all ORB binding fields must match, without warmup exceptions')
    expected = {'C0037': {'volume_gate': True}, 'C0044': {'allow_overnight': True},
                'C0046': {'volume_gate': True, 'allow_overnight': True}}
    for key, parameters in expected.items():
        if json.loads(definitions[key].parameters_json) != parameters:
            raise ValueError('fixed ORB policy parameters differ: ' + key)
    checks.append({'candidate': 'C0046', 'field': 'C0037_C0044_full_input_binding', 'equal': True,
                   'allowed_binding_differences': []})
    return checks


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
    checks.extend(verify_input_declarations(payloads))
    return {'status': 'PASS', 'checks': checks,
        'manifest_note': 'Legacy C13 retains its authenticated preparation and feedback contract. C46, C37 and C44 require identical complete typed input bindings with warmup261, closed-cycle feedback, session context and no auxiliary inputs. All four accounts retain exact primary metadata/content and economic contracts.'}


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


NATIVE_THREAD_ENV = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
    'BLIS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS', 'NUMEXPR_MAX_THREADS')


def diagnose_request(request):
    """Each spawn worker performs the unchanged complete public diagnosis once."""
    if type(request) is not AccountDiagnosisRequest:
        raise TypeError('parallel diagnosis requires a typed request')
    with threadpool_limits(limits=1):
        result = diagnose_accounts(REPOSITORY, request)
    if type(result) is not AccountDiagnosisResult:
        raise TypeError('public diagnosis returned an unexpected result type')
    return result


@contextmanager
def parallel_diagnoses(requests, *, worker=diagnose_request):
    """Three independent audits, ordered consumption and parent-only publication.

    The optional worker is a pure-synthetic spawn test seam; main always uses the
    complete public diagnose_request. Exceptions propagate without retry. Pending
    work is cancelled on exit and running children are joined before returning.
    """
    requests = tuple(requests)
    if len(requests) != 3 or any(type(item) is not AccountDiagnosisRequest for item in requests):
        raise ValueError('the fixed combination requires exactly three typed public diagnosis requests')
    previous = {name: os.environ.get(name) for name in NATIVE_THREAD_ENV}
    pool, futures = None, []
    try:
        for name in NATIVE_THREAD_ENV:
            os.environ[name] = '1'
        pool = ProcessPoolExecutor(max_workers=3, mp_context=multiprocessing.get_context('spawn'))
        futures = [pool.submit(worker, request) for request in requests]

        def ordered_results():
            for future in futures:
                result = future.result()
                if type(result) is not AccountDiagnosisResult:
                    raise TypeError('parallel diagnosis returned an unexpected result type')
                yield result

        yield ordered_results()
    finally:
        for future in futures:
            future.cancel()
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
        for name, old in previous.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old


def main():
    keys = tuple(configurations())
    if CONTROL_ID in keys:
        raise ValueError('new candidate IDs must not overwrite the historical control identity')
    payloads, refs = load_accounts(WORK, EXPERIMENT, keys, exact=True)
    for key, experiment in OLD_CONTROLS.items():
        old, old_refs = load_accounts(experiment.resolve(ROOT), experiment, (key,))
        payloads.update(old)
        refs.update(old_refs)
    contracts, hold_path = verify_contracts(payloads), verify_hold_path(payloads)
    pairs = comparison_pairs(keys)
    research, diagnostics = context(), {}
    audit_coverage = {key: [] for key in payloads}
    requests = tuple(AccountDiagnosisRequest(
        account_ref(refs[control], payloads[control]), account_ref(refs[subject], payloads[subject]),
        EvaluationWindow('DEV_2019_2025', date(2019, 1, 2), date(2025, 12, 31)))
        for subject, control in pairs)
    with parallel_diagnoses(requests) as outcomes:
        for (subject, control), diagnosis in zip(pairs, outcomes, strict=True):
            name = subject + '_vs_' + control
            path = WORK / 'others/diagnostics' / (name + '.json')
            save(path, diagnosis.to_dict())
            reference = material(research, 'diagnosis-' + name, path)
            sources_match = diagnosis.sources == (refs[control], refs[subject])
            diagnostics[name] = {'status': diagnosis.status.value, 'issues': list(diagnosis.issues),
                'evidence': reference.to_dict(), 'reconciliation': diagnosis.to_dict()['reconciliation'],
                'sources_match': sources_match}
            if diagnosis.status.value == 'COMPUTED' and sources_match:
                audit_coverage[subject].append(name)
                audit_coverage[control].append(name)
            print('DIAGNOSIS', name, diagnosis.status.value, flush=True)
    summaries = {}
    for key, payload in payloads.items():
        own = summarize_run(payload['runs']['candidate'], payload['request']['initial_cash'])
        benchmark = summarize_run(payload['runs']['buy_hold'], payload['request']['initial_cash'])
        checks = goals(own, benchmark)
        summaries[key] = {'candidate': own, 'benchmark': benchmark,
                          'goals': checks, 'all_goals_met': all(checks.values())}
    okay = (all(item['status'] == 'COMPUTED' and item['sources_match'] for item in diagnostics.values())
            and all(audit_coverage.values()))
    output = {'schema': 's017-stage2-context-analysis/v1', 'experiment': EXPERIMENT.experiment_id,
        'status': 'PASS' if okay else 'FAIL', 'analysis_source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
        'source_accounts': {key: ref.to_dict() for key, ref in refs.items()},
        'contract_checks': contracts, 'paired_buyhold_check': hold_path,
        'summaries': summaries, 'diagnostics': diagnostics, 'new_configurations': len(keys),
        'public_audit_coverage': {'status': 'PASS' if all(audit_coverage.values()) else 'FAIL',
            'required_accounts': sorted(payloads), 'diagnoses_by_account': audit_coverage,
            'basis': 'Every account must occur in a COMPUTED public diagnose_accounts result with exact ordered EvidenceRef sources; account loading does not repeat the economic audit.'},
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
