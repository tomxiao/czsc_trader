"""Authenticate EX027 accounts and explain fixed-entry exit competition.

Identity, contract and descriptive accounting helpers adapt EX017's independent
analysis methodology. No historical account result is used. Public diagnostics
certify economics; this file never runs a strategy or creates a simulated ledger.
"""
# ruff: noqa: E402
from collections import Counter
from datetime import date, datetime
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from statistics import median
import json
import gzip
import math
import multiprocessing
import os

NATIVE_THREAD_ENV = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
    'BLIS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS', 'NUMEXPR_MAX_THREADS')
for variable in NATIVE_THREAD_ENV:
    os.environ[variable] = '1'
from threadpoolctl import threadpool_limits
from czsc_trader.application import diagnose_accounts
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.account_diagnosis import AccountDiagnosisRequest, AccountDiagnosisResult, AccountRunRef
from czsc_trader.research_tools.equity_evaluation import EquityEvaluationResult
from czsc_trader.research_tools.evaluation import EvaluationIdentity, EvaluationWindow
from strategy_manager import CandidateKey
from strategy_runtime import canonical_sha256, EquityInputBinding, EquityStrategyDefinition
from strategy_runtime.signal_explanation import SignalExplanationSnapshot
from run import ROOT, WORK, REPOSITORY, EXPERIMENT, configurations, context, read, save, material

CONTROL_ID = 'C0048'
KEYS = ('C0048', 'C0049', 'C0050')
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


def verify_input_declarations(payloads):
    bindings, checks = {}, []
    expected = configurations()
    if tuple(payloads) != KEYS or tuple(expected) != KEYS:
        raise ValueError('Exactly the three frozen EX027 accounts are required')
    for key, payload in payloads.items():
        request = payload['request']
        definition = EquityStrategyDefinition.from_dict(request['candidate_definition'])
        binding = EquityInputBinding.from_dict(request['input_binding'])
        hashes = {name: value['content_sha256'] for name, value in payload['data'].items()}
        if not (json.loads(json.dumps(binding.to_dict())) == request['input_binding']
                and binding.prepared.manifest_sha256 == request['data_manifest']
                and binding.instrument == definition.instrument
                and binding.to_dict()['instrument'] == request['instrument']
                and binding.specification_hash == definition.execution_spec.fingerprint == request['specification_hash']
                and binding.warmup_bars == definition.warmup_bars == request['warmup_bars'] == 261
                and set(hashes) == set(PRIMARY) and dict(binding.expected_identities) == hashes
                and not binding.auxiliary_inputs and not definition.auxiliary_inputs
                and definition.content_identity.content_sha256 == request['content_sha256']
                and definition.feedback_mode == 'CONFIRMED_EXECUTION'
                and definition.session_context is False and definition.analysis_price == 'RAW'
                and json.loads(definition.parameters_json) == expected[key]):
            raise ValueError('Input binding or fixed strategy definition differs: '+key)
        bindings[key] = binding
        checks.append({'candidate': key, 'field': 'typed_binding_definition_and_fixed_parameters', 'equal': True})
    if not all(value == bindings[CONTROL_ID] for value in bindings.values()):
        raise ValueError('Three complete input bindings must match')
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
        'manifest_note': 'All three accounts require equal complete input bindings, primary data and economic contracts; only the frozen exit parameters differ.'}


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
        'baseline': 'EX027/C0048 embedded buy_hold; only implementation bookkeeping IDs excluded'}


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
        'total_return': metrics['total_return'], 'annualized_return': metrics['annualized_return'], 'bar_max_drawdown': metrics['bar_max_drawdown'],
        'daily_max_drawdown': metrics['daily_max_drawdown'], 'closed_cycles': metrics['closed_cycles'],
        'rolling_60_closed_cycle_median': metrics['rolling_60_closed_cycle_median'], 'fees': metrics['fees'],
        'frequency_60_sessions': {'complete_windows': len(counts),
            'windows_at_least_three': sum(count >= 3 for count in counts),
            'coverage_at_least_three': sum(count >= 3 for count in counts) / len(counts) if counts else None},
        'holding_bar_fraction': sum(row['quantity'] > 0 for row in points) / len(points),
        'holding_session_close_fraction': sum(row['quantity'] > 0 for row in daily) / len(daily),
        'year_returns': annual, 'audited_metrics': metrics,
        'mean_cash_equity_fraction': math.fsum(row['cash']/row['equity'] for row in points)/len(points),
        'mean_invested_equity_fraction': math.fsum(row['quantity']*row['close']/row['equity'] for row in points)/len(points),
        'ending_quantity': points[-1]['quantity'], 'ending_cash': points[-1]['cash'],
        'ending_equity': points[-1]['equity'],
        'trade_pnl': trade_summary(run, initial),
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
    """Two independent audits, ordered consumption and parent-only publication.

    The optional worker is a pure-synthetic spawn test seam; main always uses the
    complete public diagnose_request. Exceptions propagate without retry. Pending
    work is cancelled on exit and running children are joined before returning.
    """
    requests = tuple(requests)
    if len(requests) != 2 or any(type(item) is not AccountDiagnosisRequest for item in requests):
        raise ValueError('the fixed combination requires exactly two typed public diagnosis requests')
    previous = {name: os.environ.get(name) for name in NATIVE_THREAD_ENV}
    pool, futures = None, []
    try:
        for name in NATIVE_THREAD_ENV:
            os.environ[name] = '1'
        pool = ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context('spawn'))
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


def trade_summary(run, initial):
    trades = run['trades']
    gains = sorted((r['net_pnl'] for r in trades if r['net_pnl'] > 0), reverse=True)
    losses = [r['net_pnl'] for r in trades if r['net_pnl'] < 0]
    positive, negative = math.fsum(gains), math.fsum(losses)
    closed_net = math.fsum(r['net_pnl'] for r in trades)
    final = run['account_points'][-1]
    return {'closed_count': len(trades), 'closed_net_pnl': closed_net,
        'positive_pnl': positive, 'negative_pnl': negative,
        'wins': len(gains), 'losses': len(losses), 'zero_pnl': sum(r['net_pnl'] == 0 for r in trades),
        'win_rate': len(gains)/len(trades) if trades else None,
        'profit_factor': positive/-negative if negative else None,
        'mean_cycle_net_return': math.fsum(r['net_return'] for r in trades)/len(trades) if trades else None,
        'median_cycle_net_return': median(r['net_return'] for r in trades) if trades else None,
        'largest_positive_pnl_share': gains[0]/positive if positive else None,
        'top_five_positive_pnl_share': math.fsum(gains[:5])/positive if positive else None,
        'nonclosed_equity_change': final['equity']-initial-closed_net,
        'closed_pnl_by_exit_year': {year: math.fsum(r['net_pnl'] for r in trades if r['exit_at'].startswith(year))
            for year in map(str, range(2019, 2026))},
        'scope': 'Closed-cycle money PnL includes fees; exit-year sums are not continuous annual returns. Nonclosed change includes open-position mark-to-market and entry fees; no hypothetical liquidation.'}


def decision_facts(decision):
    if decision['signal_status'] != 'EVALUATED':
        raise ValueError('This fixed all-observed input contract requires evaluated decisions')
    explanation = SignalExplanationSnapshot.from_dict(decision['explanation'])
    facts = {item.key: item.text for item in explanation.basis}
    if len(facts) != len(explanation.basis):
        raise ValueError('Duplicate strategy explanation facts')
    for field in ('entry_signal', 'entry_ready', 'held'):
        if facts[field] not in ('True', 'False'):
            raise ValueError('Ambiguous boolean explanation: '+field)
        facts[field] = facts[field] == 'True'
    facts['holding_bars'] = int(facts['holding_bars'])
    if facts['exit_trigger'] == 'None':
        facts['exit_trigger'] = None
    elif facts['exit_trigger'] not in ('S017-M009', 'S017-M010', 'S017-M011'):
        raise ValueError('Unknown numbered exit trigger')
    return facts


def audit_mechanism(run):
    """Classify observed decisions using actual ledger feedback, not target alone."""
    decisions, points = run['decisions'], run['account_points']
    if len(decisions) != len(points):
        raise ValueError('Every decision requires its corresponding account point')
    orders = {r['order_id']: r for r in run['orders']}
    fills = {r['order_id']: r for r in run['fills']}
    if len(orders) != len(run['orders']) or len(fills) != len(run['fills']):
        raise ValueError('Single-order single-fill prototype required')
    counts, ignored_sides, attempts, filled_reasons = Counter(), Counter(), Counter(), Counter()
    rows, maps, exit_rows = [], [], []
    quantity = 0
    for decision, point in zip(decisions, points, strict=True):
        key = decision['decision_id']
        if point['decision_id'] != key or point['account_revision'] != decision['portfolio_revision']:
            raise ValueError('Decision/account point alignment differs')
        facts = decision_facts(decision)
        held, signal = facts['held'], facts['entry_signal']
        if held != (quantity > 0):
            raise ValueError('Explanation held flag differs from actual pre-decision quantity')
        maps.append((decision['observed_through'], decision['execution_start'], signal, facts['entry_ready']))
        counts['decisions'] += 1
        counts['held_decisions' if held else 'flat_decisions'] += 1
        if not facts['entry_ready']:
            counts['not_ready'] += 1
        if signal:
            counts['entry_signals'] += 1
            counts['held_signals_ignored' if held else 'flat_signals'] += 1
            if held:
                ignored_sides[decision['side']] += 1
            rows.append({'decision_id': key, 'observed_through': decision['observed_through'],
                'execution_start': decision['execution_start'], 'held_before': held,
                'side': decision['side'], 'target': decision['target'],
                'order_reason': orders[key]['reason'] if key in orders else None,
                'filled_side': fills[key]['side'] if key in fills else None})
        if not held and int(decision['target']) != int(signal):
            raise ValueError('Flat target differs from M005')
        if held and int(decision['target']) != int(facts['exit_trigger'] is None):
            raise ValueError('Held target differs from latched exit')
        if decision['side'] == 'BUY':
            if held or not signal or key not in orders or orders[key]['side'] != 'BUY':
                raise ValueError('Buy intent is not a flat M005 order')
            counts['buy_orders'] += 1
            if key in fills:
                counts['actual_buy_fills'] += 1
            else:
                counts['unfilled_buy_orders'] += 1
        elif not held and signal:
            if decision['side'] != 'WAIT' or decision['quantity'] != 0:
                raise ValueError('Unexecuted flat signal lacks the expected zero-size WAIT')
            counts['flat_signals_without_order'] += 1
        if decision['side'] == 'SELL':
            if not held or facts['exit_trigger'] is None or key not in orders:
                raise ValueError('Sell attempt lacks actual holding/exit trigger/order')
            trigger = facts['exit_trigger']
            attempts[trigger] += 1
            if key in fills:
                filled_reasons[trigger] += 1
            exit_rows.append({'decision_id': key, 'execution_start': decision['execution_start'],
                'trigger': trigger, 'first_trigger_at': facts['exit_trigger_at'],
                'holding_bars': facts['holding_bars'], 'actual_entry': facts['actual_entry'],
                'anchor': facts['anchor'], 'order_reason': orders[key]['reason'],
                'filled': key in fills, 'cycle_id': fills[key]['cycle_id'] if key in fills else None})
        quantity = point['quantity']
    for name in ('decisions', 'held_decisions', 'flat_decisions', 'not_ready', 'entry_signals',
                 'held_signals_ignored', 'flat_signals', 'buy_orders', 'actual_buy_fills',
                 'unfilled_buy_orders', 'flat_signals_without_order'):
        counts.setdefault(name, 0)
    if counts['entry_signals'] != counts['held_signals_ignored']+counts['flat_signals']:
        raise ValueError('Signal decomposition fails')
    if counts['flat_signals'] != counts['buy_orders']+counts['flat_signals_without_order']:
        raise ValueError('Flat-signal decomposition fails')
    if counts['actual_buy_fills'] != sum(f['side'] == 'BUY' for f in run['fills']):
        raise ValueError('Actual buy-fill count differs')
    if sum(filled_reasons.values()) != len(run['trades']):
        raise ValueError('Filled exit reasons must cover each closed cycle')
    closed_holds = [r['holding_bars'] for r in exit_rows if r['filled']]
    return {'counts': dict(counts), 'ignored_signal_sides': dict(ignored_sides),
        'order_failure_reasons': dict(Counter(r['reason'] for r in run['orders'] if r['status'] != 'FILLED')),
        'exit_attempts_by_trigger': dict(attempts), 'closed_exits_by_trigger': dict(filled_reasons),
        'closed_holding_bars': {'min': min(closed_holds) if closed_holds else None,
            'median': median(closed_holds) if closed_holds else None,
            'max': max(closed_holds) if closed_holds else None},
        'signal_decisions': rows, 'exit_decisions': exit_rows,
        'scope': 'Current completed-bar M005 evaluated even while held. Ignored signals include both HOLD and SELL branches. These are opportunity counts, not forgone profits.'}, maps


def authenticate_pre_run():
    refs = read(WORK/'others/pre_run_evidence.json')
    for name, value in refs.items():
        reference = EvidenceRef.from_dict(value)
        content = reference.resolve(ROOT).read_bytes()
        if sha256(content).hexdigest() != reference.sha256:
            raise ValueError('Pre-run material changed: '+name)
    reference = EvidenceRef.from_dict(refs['entry-reproduction'])
    path = WORK/'others/entry_reproduction.json'
    if sha256(path.read_bytes()).hexdigest() != reference.sha256:
        raise ValueError('Entry reproduction differs from frozen pre-run evidence')
    result = read(path)
    if result['status'] != 'PASS':
        raise ValueError('Entry reproduction must pass')
    return result, reference


def reference_signals():
    """Read only published M005 membership, never historical performance."""
    publication = read(ROOT/'research/S017/experiments/EX024_20261029/others/publication.json')
    reference = EvidenceRef.from_dict(publication['materials']['signal-facts'])
    content = reference.resolve(ROOT).read_bytes()
    if sha256(content).hexdigest() != reference.sha256:
        raise ValueError('Published M005 facts changed')
    facts = json.loads(gzip.decompress(content))
    mapping = {datetime.fromisoformat(row['signal_at']): 'S017-M005' in row['signals'] for row in facts}
    if len(mapping) != len(facts) or len(mapping) != 22790 or sum(mapping.values()) != 324:
        raise ValueError('Published M005 population differs from the frozen protocol')
    return mapping, reference


def main():
    keys = tuple(configurations())
    if keys != KEYS:
        raise ValueError('Only the three new EX027 accounts are allowed')
    reproduction, reproduction_ref = authenticate_pre_run()
    reference_map, reference_ref = reference_signals()
    payloads, refs = load_accounts(WORK, EXPERIMENT, keys, exact=True)
    contracts, hold_path = verify_contracts(payloads), verify_hold_path(payloads)
    mechanism, expected_map = {}, None
    for key, payload in payloads.items():
        mechanism[key], signal_map = audit_mechanism(payload['runs']['candidate'])
        if expected_map is None:
            expected_map = signal_map
        elif signal_map != expected_map:
            raise ValueError('Three accounts must retain identical M005 market signals and readiness')
        if mechanism[key]['counts']['entry_signals'] != 324 or mechanism[key]['counts']['decisions'] != 22790:
            raise ValueError('Full account signal population differs from frozen census')
        actual_map = {datetime.fromisoformat(stamp): signal for stamp, _, signal, _ in signal_map}
        if len(actual_map) != len(signal_map) or actual_map != reference_map:
            raise ValueError('Each actual account signal must match published EX024 membership')
    pairs = (('C0049', CONTROL_ID), ('C0050', CONTROL_ID))
    research, diagnostics = context(), {}
    coverage = {key: [] for key in keys}
    requests = tuple(AccountDiagnosisRequest(account_ref(refs[control], payloads[control]),
        account_ref(refs[subject], payloads[subject]),
        EvaluationWindow('DEV_2019_2025', date(2019, 1, 2), date(2025, 12, 31))) for subject, control in pairs)
    with parallel_diagnoses(requests) as outcomes:
        for (subject, control), diagnosis in zip(pairs, outcomes, strict=True):
            name = subject+'_vs_'+control
            path = WORK/'others/diagnostics'/(name+'.json')
            save(path, diagnosis.to_dict())
            reference = material(research, 'diagnosis-'+name, path)
            sources_match = diagnosis.sources == (refs[control], refs[subject])
            reconciliation = diagnosis.to_dict()['reconciliation']
            identity_set = {account_ref(refs[k], payloads[k]).identity.evaluation_id for k in (control, subject)}
            residual_ok = (len(reconciliation) == 2 and {r['evaluation_id'] for r in reconciliation} == identity_set
                and all(math.isfinite(r['residual']) and abs(r['residual']) <= 1e-7 for r in reconciliation))
            diagnostics[name] = {'status': diagnosis.status.value, 'issues': list(diagnosis.issues),
                'evidence': reference.to_dict(), 'sources_match': sources_match,
                'reconciliation': reconciliation, 'residual_check': residual_ok,
                'path_comparison_counts': {'both_enter': sum(r.baseline_cycle_id is not None and r.alternative_cycle_id is not None for r in diagnosis.path_comparison),
                    'baseline_only': sum(r.baseline_cycle_id is not None and r.alternative_cycle_id is None for r in diagnosis.path_comparison),
                    'alternative_only': sum(r.baseline_cycle_id is None and r.alternative_cycle_id is not None for r in diagnosis.path_comparison)}}
            if diagnosis.status.value == 'COMPUTED' and sources_match and residual_ok:
                coverage[control].append(name)
                coverage[subject].append(name)
            print('DIAGNOSIS', name, diagnosis.status.value, flush=True)
    summaries = {}
    for key, payload in payloads.items():
        own = summarize_run(payload['runs']['candidate'], payload['request']['initial_cash'])
        benchmark = summarize_run(payload['runs']['buy_hold'], payload['request']['initial_cash'])
        checks = goals(own, benchmark)
        summaries[key] = {'candidate': own, 'benchmark': benchmark, 'goals': checks,
            'all_goals_met': all(checks.values()), 'mechanism': mechanism[key]}
    okay = all(coverage.values())
    output = {'schema': 's017-fixed-entry-exit-competition/v1', 'experiment': EXPERIMENT.experiment_id,
        'status': 'PASS' if okay else 'FAIL', 'analysis_source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
        'analysis_source_path': 'src/analyze_v2.py',
        'source_accounts': {key: ref.to_dict() for key, ref in refs.items()},
        'entry_reproduction': {'evidence': reproduction_ref.to_dict(), 'result': reproduction,
            'published_reference': reference_ref.to_dict(), 'actual_account_membership_match': 'PASS',
            'full_account_common_signal_map_sha256': canonical_sha256(expected_map)},
        'contract_checks': contracts, 'paired_buyhold_check': hold_path,
        'summaries': summaries, 'diagnostics': diagnostics,
        'public_audit_coverage': {'status': 'PASS' if okay else 'FAIL', 'required_accounts': list(keys),
            'diagnoses_by_account': coverage,
            'basis': 'Each new account is covered by a COMPUTED public diagnosis with exact ordered evidence and reconciled money PnL.'},
        'new_configurations': 3, 'formal_requests': 3, 'account_replays': 6, 'public_diagnoses': 2,
        'method_sources': [{'path': 'research/S017/experiments/EX017_20261029/src/analyze.py',
            'sha256': sha256((ROOT/'research/S017/experiments/EX017_20261029/src/analyze.py').read_bytes()).hexdigest(),
            'usage': 'Adapted typed identity, common economic contract, benchmark equality and descriptive annual/holding/frequency helpers. No historical account result is read.'}],
        'semantics': {'annual': 'Continuous year-end equity ratios; no annual reset.',
            'holding': 'Positive-quantity account observations; not elapsed wall-clock exposure.',
            'ignored_signals': 'Contemporaneous M005 while already held, including exit decisions; not independent trades or lost money.',
            'paths': 'Changed exits change capital availability and subsequent entries; account delta is not the isolated effect on identical trades.',
            'frequency': 'Complete overlapping 60-session windows with actual closed cycles; no forced terminal close.',
            'goals': 'The five user-confirmed gates are evaluated simultaneously; technical PASS does not imply financial acceptance.'},
        'limitations': ['Repeatedly studied 2019-2025 development pool; no reserved 2026 results.',
            'No original label mean is substituted for account PnL; no counterfactual skipped-trade simulation.',
            'Fixed exits are representative hypotheses, not optimized parameters.']}
    save(WORK/'others/analysis.json', output)
    print('ANALYSIS', output['status'], {key: value['all_goals_met'] for key, value in summaries.items()}, flush=True)
    if not okay:
        raise RuntimeError('Public diagnosis coverage or reconciliation failed')


if __name__ == '__main__':
    main()
