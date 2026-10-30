"""Authenticate EX029 V3 closures and compare fixed entry and holding rules.

Public diagnoses audit the original continuous accounts. This analysis never
removes trades or synthesizes counterfactual account equity from event labels.
"""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import date
import json
import math
import multiprocessing as mp
from pathlib import Path
from statistics import median

from common import (ROOT, WORK, REPOSITORY, EXPERIMENT, context, read, save,
                    digest, material)
from czsc_trader.application import diagnose_accounts
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.account_diagnosis import AccountDiagnosisRequest, AccountRunRef
from czsc_trader.research_tools.equity_evaluation import EquityEvaluationResult
from czsc_trader.research_tools.equity_replay_v3 import materialize_v3
from czsc_trader.research_tools.evaluation import EvaluationIdentity, EvaluationWindow
from strategy_manager import CandidateKey
from strategy_runtime import EquityInputBinding, EquityStrategyDefinition, canonical_sha256

EXPECTED = {'C0055': {'entry_mechanism': 'S017-M012', 'max_holding_bars': 6},
            'C0056': {'entry_mechanism': 'S017-M017', 'max_holding_bars': 6},
            'C0057': {'entry_mechanism': 'S017-M018', 'max_holding_bars': 6},
            'C0058': {'entry_mechanism': 'S017-M017', 'max_holding_bars': 13}}
FIELDS = ('initial_cash', 'fee_rate', 'window', 'history_start', 'specification_hash',
          'specification', 'benchmark_sha256', 'benchmark', 'sources', 'instrument',
          'drawdown_basis', 'concentration_basis', 'frequency_window_days', 'measurement_tier')
PAIRS = (('C0056', 'C0055'), ('C0056', 'C0057'), ('C0058', 'C0056'))


def run_ref(reference, payload):
    identity = dict(payload['evaluation_identity'])
    identity['candidate'] = CandidateKey(**identity['candidate'])
    return AccountRunRef(reference, EvaluationIdentity(**identity))


def load_accounts():
    manifest = read(WORK/'others/accounts_v3.json')
    if not manifest:
        return {}, {}
    if set(manifest) != set(EXPECTED):
        raise ValueError('Exactly the four predeclared EX029 accounts are required')
    payloads, refs, closure_cache = {}, {}, {}
    for key in EXPECTED:
        record = manifest[key]
        reference = EvidenceRef.from_dict(record['evidence'])
        if (reference.experiment != EXPERIMENT or reference.media_type != 'application/json'
                or (reference.schema, reference.schema_version) != ('equity_research', 3)):
            raise ValueError('Account evidence identity, schema or experiment differs')
        path = reference.resolve(ROOT)
        content = path.read_bytes()
        from hashlib import sha256
        if sha256(content).hexdigest() != reference.sha256:
            raise ValueError('Account evidence changed during read')
        result = EquityEvaluationResult(record['request_hash'], content)
        envelope = result.payload
        allowed = {(envelope[name]['kind'], envelope[name]['sha256'])
                   for name in ('input_ref', 'candidate_ref', 'benchmark_ref')}

        def resolve(artifact):
            if (set(artifact) != {'kind', 'sha256'}
                    or (artifact['kind'], artifact['sha256']) not in allowed):
                raise ValueError('Resolver permits only this V3 document closure')
            target = path.parent/(artifact['sha256']+'.json')
            if target not in closure_cache:
                closure_cache[target] = target.read_bytes()
            return closure_cache[target]

        view = materialize_v3(result, resolve)
        payload = view.payload
        identity = run_ref(reference, payload).identity
        request = payload['request']
        if (payload.get('schema') != 'equity-research/v3' or payload.get('schema_version') != 3
                or set(payload['runs']) != {'candidate', 'buy_hold'}
                or identity.candidate != CandidateKey('S017', key)
                or payload['evaluation_id'] != record['evaluation_id'] or not record['evaluation_id']
                or identity.evaluation_id != payload['evaluation_id']
                or payload['evaluation_identity'] != record['evaluation_identity']
                or identity.content_sha256 != request['content_sha256']
                or identity.content_sha256 != request['candidate_identity']['content_sha256']
                or identity.input_sha256 != request['data_manifest']
                or identity.protocol_sha256 != record['request_hash']
                or identity.environment_sha256 != canonical_sha256(request['engine_sources'])
                or request['candidate_id'] != key
                or request['experiment'] != {'strategy_id': 'S017', 'experiment_id': EXPERIMENT.experiment_id}):
            raise ValueError('Account manifest does not bind its immutable payload: '+key)
        payloads[key], refs[key] = payload, reference
        print('ACCOUNT_BOUND', key, flush=True)
    return payloads, refs


def economic(value):
    if isinstance(value, list):
        return [economic(item) for item in value]
    if isinstance(value, dict):
        return {key: economic(item) for key, item in value.items()
                if key not in {'decision_id', 'cycle_id', 'fill_id', 'order_id', 'plan_id'}}
    return value


def contract_checks(payloads):
    base = payloads['C0055']
    checks = []
    bindings = {}
    for key, payload in payloads.items():
        request = payload['request']
        definition = EquityStrategyDefinition.from_dict(request['candidate_definition'])
        binding = EquityInputBinding.from_dict(request['input_binding'])
        hashes = {name: item['content_sha256'] for name, item in payload['data'].items()}
        if (json.loads(json.dumps(binding.to_dict())) != request['input_binding']
                or binding.prepared.manifest_sha256 != request['data_manifest']
                or binding.instrument != definition.instrument
                or binding.to_dict()['instrument'] != request['instrument']
                or binding.specification_hash != definition.execution_spec.fingerprint
                or binding.specification_hash != request['specification_hash']
                or binding.warmup_bars != definition.warmup_bars or definition.warmup_bars != 261
                or request['warmup_bars'] != 261
                or set(hashes) != {'bars', 'sessions', 'actions', 'constraints'}
                or dict(binding.expected_identities) != hashes
                or binding.auxiliary_inputs or definition.auxiliary_inputs
                or definition.content_identity.content_sha256 != request['content_sha256']
                or definition.feedback_mode != 'CONFIRMED_EXECUTION' or definition.session_context
                or definition.analysis_price != 'RAW' or definition.contract_version != 3
                or json.loads(definition.parameters_json) != EXPECTED[key]):
            raise ValueError('Typed input or fixed parameters differ: '+key)
        bindings[key] = binding
        base_definition = base['request']['candidate_definition']
        for field in ('contract_version', 'entrypoint', 'source_files', 'source_sha256',
                      'dependencies', 'feature_graph', 'state_schema'):
            if request['candidate_definition'][field] != base_definition[field]:
                raise ValueError('V3 implementation or dependency closure differs: '+key+'/'+field)
        for field in ('input_ref', 'benchmark_ref', 'benchmark_identity'):
            if payload[field] != base[field]:
                raise ValueError('V3 shared input or benchmark closure differs: '+key+'/'+field)
        for field in FIELDS:
            if request[field] != base['request'][field]:
                raise ValueError('Economic contract differs: '+key+'/'+field)
            checks.append(key+'/'+field)
        for product in ('bars', 'sessions', 'actions', 'constraints'):
            if payload['data'][product] != base['data'][product]:
                raise ValueError('Market data identity differs: '+key+'/'+product)
        for field in ('account_points', 'account_daily', 'fills', 'trades', 'actions', 'metrics'):
            if economic(payload['runs']['buy_hold'][field]) != economic(base['runs']['buy_hold'][field]):
                raise ValueError('Paired buyhold path differs: '+key+'/'+field)
    if any(binding != bindings['C0055'] for binding in bindings.values()):
        raise ValueError('Complete input bindings must match')
    return {'status': 'PASS', 'equal_economic_fields': checks,
            'same_complete_input_bindings': True, 'same_market_data': True,
            'contract_version': 3, 'same_graph_state_and_declared_dependencies': True,
            'v3_artifact_hash_owner_input_closure_authenticated': True,
            'paired_buyhold_complete_path_equal': True,
            'ignored_bookkeeping_ids_only': ['decision_id', 'cycle_id', 'fill_id', 'order_id', 'plan_id']}


def drawdown(values):
    peak, worst = values[0], 0.
    for value in values:
        peak = max(peak, value)
        worst = max(worst, 1.-value/peak)
    return worst


def summary(run, initial, *, entry_decisions=False):
    metrics, daily, points, trades = run['metrics'], run['account_daily'], run['account_points'], run['trades']
    counts = metrics['rolling_60_closed_cycle_counts']
    positive = sorted((t['net_pnl'] for t in trades if t['net_pnl'] > 0), reverse=True)
    negative = [t['net_pnl'] for t in trades if t['net_pnl'] < 0]
    annual, opening = [], initial
    for year in sorted({row['session'][:4] for row in daily}):
        selected = [row for row in daily if row['session'].startswith(year)]
        closing = selected[-1]['equity']
        annual.append({'year': int(year), 'sessions': len(selected), 'opening_equity': opening,
                       'closing_equity': closing, 'net_return': closing/opening-1.})
        opening = closing
    rolling = []
    for start in range(0, len(daily)-252+1, 21):
        population = daily[start:start+252]
        opening = daily[start-1]['equity'] if start else initial
        values = [opening, *[r['equity'] for r in population]]
        rolling.append({'start_session': population[0]['session'], 'end_session': population[-1]['session'],
            'net_return': values[-1]/opening-1., 'daily_max_drawdown': drawdown(values)})
    facts = Counter()
    hold_counts = []
    for row in (run['decisions'] if entry_decisions else []):
        if row['signal_status'] != 'EVALUATED':
            raise ValueError('All observed input must have evaluated decisions')
        explanation = row['explanation']
        values = {item['key']: item['text'] for item in explanation['basis']}
        if values['entry_signal'] not in ('True', 'False') or values['held'] not in ('True', 'False'):
            raise ValueError('Decision facts must be explicit booleans')
        signal, held = values['entry_signal'] == 'True', values['held'] == 'True'
        facts['decisions'] += 1
        facts['entry_signals'] += int(signal)
        facts['held_signals_ignored'] += int(signal and held)
        facts['flat_signals'] += int(signal and not held)
        if held and float(row['target']) == 0:
            hold_counts.append(int(values['holding_bars']))
    return {'total_return': metrics['total_return'], 'annualized_return': metrics['annualized_return'],
        'bar_max_drawdown': metrics['bar_max_drawdown'], 'daily_max_drawdown': metrics['daily_max_drawdown'],
        'closed_cycles': metrics['closed_cycles'], 'rolling_60_closed_cycle_median': metrics['rolling_60_closed_cycle_median'],
        'frequency_60_sessions': {'complete_windows': len(counts),
            'windows_at_least_three': sum(x >= 3 for x in counts),
            'coverage_at_least_three': sum(x >= 3 for x in counts)/len(counts) if counts else None},
        'fees': metrics['fees'], 'holding_bar_fraction': sum(r['quantity'] > 0 for r in points)/len(points),
        'mean_invested_equity_fraction': math.fsum(r['quantity']*r['close']/r['equity'] for r in points)/len(points),
        'ending_equity': points[-1]['equity'], 'ending_quantity': points[-1]['quantity'],
        'year_returns': annual, 'rolling_252_sessions_step21': rolling,
        'trade_pnl': {'closed_count': len(trades), 'net_pnl': math.fsum(t['net_pnl'] for t in trades),
            'win_rate': len(positive)/len(trades) if trades else None,
            'mean_cycle_net_return': math.fsum(t['net_return'] for t in trades)/len(trades) if trades else None,
            'median_cycle_net_return': median(t['net_return'] for t in trades) if trades else None,
            'profit_factor': math.fsum(positive)/-math.fsum(negative) if negative else None,
            'top_five_positive_pnl_share': math.fsum(positive[:5])/math.fsum(positive) if positive else None},
        'decision_counts': dict(facts), 'exit_decision_holding_bars_median': median(hold_counts) if hold_counts else None,
        'audited_metrics': metrics}


def goals(own, benchmark):
    coverage = own['frequency_60_sessions']['coverage_at_least_three']
    freq = own['rolling_60_closed_cycle_median']
    return {'annualized_return': own['annualized_return'] >= 1.5*benchmark['annualized_return']
                if benchmark['annualized_return'] > 0 else own['annualized_return'] > 0,
            'relative_drawdown': own['bar_max_drawdown'] <= .8*benchmark['bar_max_drawdown'],
            'absolute_drawdown': own['bar_max_drawdown'] <= .25,
            'frequency_median': freq is not None and freq >= 6,
            'frequency_coverage': coverage is not None and coverage >= .9}


def diagnosis_worker(request):
    return diagnose_accounts(REPOSITORY, request)


def main():
    payloads, refs = load_accounts()
    if not payloads:
        save(WORK/'others/account_analysis.json', {'status': 'NOT_RUN', 'reason': 'No formal accounts',
            'new_strategy_accounts': 0, 'public_diagnoses': 0})
        save(WORK/'others/account_validation.json', {'status': 'NOT_RUN', 'reason': 'No formal accounts'})
        print('ACCOUNT_ANALYSIS_NOT_RUN', flush=True)
        return
    contracts = contract_checks(payloads)
    requests = [AccountDiagnosisRequest(run_ref(refs[control], payloads[control]),
        run_ref(refs[subject], payloads[subject]),
        EvaluationWindow('DEV_2019_2025', date(2019, 1, 2), date(2025, 12, 31))) for subject, control in PAIRS]
    research, diagnostics, coverage = context(), {}, {k: [] for k in EXPECTED}
    with ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context('spawn')) as pool:
        for (subject, control), result in zip(PAIRS, pool.map(diagnosis_worker, requests), strict=True):
            name = subject+'_vs_'+control
            reconciled = result.to_dict()['reconciliation']
            expected_ids = {payloads[k]['evaluation_id'] for k in (control, subject)}
            if (result.status.value != 'COMPUTED' or result.issues or result.sources != (refs[control], refs[subject])
                    or len(reconciled) != 2 or {x['evaluation_id'] for x in reconciled} != expected_ids
                    or any(not math.isfinite(x['residual']) or abs(x['residual']) > 1e-7 for x in reconciled)):
                raise ValueError('Public diagnosis not computed with exact sources and reconciled money PnL: '+name)
            path = WORK/'others/diagnostics'/(name+'.json')
            save(path, result.to_dict())
            reference = material(research, 'diagnosis-'+name, path)
            diagnostics[name] = {'status': result.status.value, 'issues': list(result.issues),
                'evidence': reference.to_dict(), 'sources_match': True, 'reconciliation': reconciled,
                'path_comparison_counts': {'both_enter': sum(x.baseline_cycle_id is not None and x.alternative_cycle_id is not None for x in result.path_comparison),
                    'baseline_only': sum(x.baseline_cycle_id is not None and x.alternative_cycle_id is None for x in result.path_comparison),
                    'alternative_only': sum(x.baseline_cycle_id is None and x.alternative_cycle_id is not None for x in result.path_comparison)}}
            coverage[subject].append(name)
            coverage[control].append(name)
            print('DIAGNOSIS_COMPUTED', name, flush=True)
    summaries = {}
    for key, payload in payloads.items():
        own = summary(payload['runs']['candidate'], payload['request']['initial_cash'], entry_decisions=True)
        benchmark = summary(payload['runs']['buy_hold'], payload['request']['initial_cash'])
        check = goals(own, benchmark)
        summaries[key] = {'parameters': EXPECTED[key], 'candidate': own, 'benchmark': benchmark,
                          'goals': check, 'all_goals_met': all(check.values())}
    if not all(coverage.values()):
        raise ValueError('Every new account needs a complete public audit')
    output = {'schema': 's017-low-background-account-comparison/v3', 'status': 'PASS',
        'experiment': EXPERIMENT.experiment_id, 'analysis_source_sha256': digest(Path(__file__)),
        'source_accounts': {k: v.to_dict() for k, v in refs.items()}, 'account_manifest_sha256': digest(WORK/'others/accounts_v3.json'),
        'contract_checks': contracts, 'summaries': summaries, 'diagnostics': diagnostics,
        'public_audit_coverage': coverage, 'public_diagnoses': len(PAIRS), 'new_strategy_accounts': len(payloads),
        'semantics': {'annual': 'Continuous year-end equity ratios; no annual reset.',
            'rolling': '252 consecutive session slices inherit prior account equity and positions; step21, no strategy replay.',
            'holding': 'Fraction of positive-quantity completed account observations, not natural elapsed time.',
            'comparison': 'Filtering and exit changes alter future available capital and entry sequence; not same-trade causal isolation.',
            'goals': 'All five original requirements apply simultaneously; public audit PASS does not imply economic acceptance.'},
        'limitations': ['Repeatedly seen 2019-2025 development pool; no reserved 2026 use.',
            'No new parameter search, no candidate registration or phase-three approval.',
            'Year and rolling slices describe continuous accounts; no retroactive rules or deleted losses.']}
    save(WORK/'others/account_analysis.json', output)
    save(WORK/'others/account_validation.json', {'status': 'PASS', 'scope': 'IDENTITY_COMMON_CONTRACT_AND_PUBLIC_ACCOUNT_AUDIT',
        'analysis_sha256': digest(WORK/'others/account_analysis.json'), 'analysis_source_sha256': digest(Path(__file__)),
        'contracts': contracts, 'all_accounts_audited': True, 'public_diagnoses': len(PAIRS)})
    print('ACCOUNT_ANALYSIS_PASS', flush=True)


if __name__ == '__main__':
    main()
