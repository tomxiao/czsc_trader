"""Observation-only S015 revision: authenticated historical replay, no new search."""
from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
sys.dont_write_bytecode = True
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import cloudpickle
import pandas as pd
from czsc_trader.application import (
    RepositoryContext, create_research_context, publish_evidence,
    CandidateRegistrationRequest, register_candidate,
)
from czsc_trader.research_tools import (
    ResearchBatchRef, ExperimentRef, ExecutionResources, EvidenceRef,
    MaterialEvidenceWrite, EvaluationEvidenceWrite,
)
from strategy_manager import CandidateKey
from strategy_runtime import (
    StrategyCandidate, StrategyRelease, StrategyRuntime, StrategyInit, StrategyInputBinding,
    implementation_sha256, SignalHistoryMode, TradingPoint, PortfolioSnapshot, ExecutionState,
    EntryCycleState, EntryCyclePhase, materialize_observation,
)
from trading_execution_engine import HistoricalExecutor
from strategy_evaluator import ReplayEvidence, compare_ledgers, LedgerComparisonRequest, LedgerComparisonMode

ROOT = Path(__file__).resolve().parents[5]
EX = ExperimentRef('S015', 'EX084_20261025')
HOME = EX.resolve(ROOT)
SOURCE = HOME / 'src/strategy_runtime'
CACHE = ROOT / '.tmp/s015-ex084'
OUT = HOME / 'others'
KEY = CandidateKey('S015', 'C9800')
ZONE = ZoneInfo('Asia/Shanghai')
NAMES = ('decisions', 'orders', 'fills', 'account_daily', 'trades')


def plain(value):
    if is_dataclass(value):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (Decimal, Path)):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return value


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plain(value), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def context():
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S015'),
                                   resources=ExecutionResources(2, 1, 13))


def sources():
    original = read(ROOT / 'strategies/S015/versions/v1.json')
    payload = original['strategy_payload']
    payload['runtime']['source_files'] = ['strategies/price_process.py', 'strategies/observation_display.py']
    payload['runtime']['source_sha256'] = implementation_sha256(tuple(payload['runtime']['source_files']), source_root=SOURCE)
    child = StrategyCandidate('S015', 'C9800', payload, SOURCE)
    old = StrategyRelease.from_mapping(read(ROOT / 'strategies/S015/versions/v1.json'))
    return old, child


def requests():
    saved = read(HOME.parent / 'EX082_20261025/others/prepared.json')
    return cloudpickle.loads(EvidenceRef.from_dict(saved['requests']).resolve(ROOT).read_bytes())


def bind(ctx, source, request, tag):
    old = request.input_bindings['full']
    instance = StrategyRuntime(ctx.repository.strategy_root, dataflows=ctx.data).create(StrategyInit(
        source, old.plan.tradable_window, CACHE / 'bindings' / tag, pricing=request.execution_data.pricing))
    calendar = ctx.data.fetch(old.plan.requests[old.plan.calendar_name], prepared=old.prepared)
    kwargs = {}
    if '__trading_status' in old.plan.requests:
        kwargs = {'trading_status': ctx.data.fetch(old.plan.requests['__trading_status'], prepared=old.prepared),
                  'status_request': old.plan.requests['__trading_status']}
    plan = instance.plan_inputs(calendar, **kwargs)
    left, right = old.plan.to_dict(), plan.to_dict()
    left.pop('strategy')
    right.pop('strategy')
    assert left == right
    binding = StrategyInputBinding(plan, old.prepared)
    instance.prepare_data(binding=binding)
    return instance, binding


def prepare():
    ctx = context()
    old, child = sources()
    identity = StrategyRuntime().identify(child, dependencies=())
    protocol = {
        'candidate': KEY.to_dict(), 'content_identity': plain(identity),
        'original': {'reference': old.release_id, 'release_hash': old.release_hash},
        'authorization': '用户：同意，请新开分支执行。DEV负责修改平台代码，RSCH负责策略升级。',
        'scope': 'S015 signal panel observation only. Retain all original series/facts and trading AST.',
        'inputs': 'EX082 authenticated preparations; 2025-01-02..2026-10-21, no new market fetch.',
        'acceptance': 'Zero-tolerance original signal columns and all five economic ledgers, WINDOW and CONTINUOUS; 200/600-share existing-cycle plan probes.',
        'costs': ['standard .001', 'fee_x2 .002'], 'new_search_trials': 0,
        'preview': 'Historical technical replay; not forward observation or production execution.',
        'boundary': 'No frozen-package mutation, no deployment, no new freeze request.',
    }
    path = HOME / 'protocols/observation_upgrade_final.json'
    assert not path.exists()
    save(path, protocol)
    save(OUT / 'identity.json', plain(identity))
    print('PREPARED', identity.content_sha256, flush=True)


def equal_frame(left, right, identities):
    assert set(left.columns) == set(right.columns) and left.index.equals(right.index), {
        'only_old': list(set(left.columns) - set(right.columns)),
        'only_new': list(set(right.columns) - set(left.columns)), 'rows': (len(left), len(right))}
    for col in left:
        for a, b in zip(left[col], right[col], strict=True):
            if pd.isna(a) or pd.isna(b):
                assert bool(pd.isna(a)) == bool(pd.isna(b)), col
            elif col in {'entry_cycle_before', 'entry_cycle_after', 'entry_cycle'}:
                aa, bb = json.loads(a), json.loads(b)
                if aa is None or bb is None:
                    assert aa == bb
                    continue
                assert set(aa) == set(bb)
                for key in aa:
                    alias = 'signal_identity' if key == 'opening_signal_identity' else key
                    if alias in {'cycle_id', 'signal_identity'}:
                        forward, reverse = identities.setdefault(alias, ({}, {}))
                        assert forward.setdefault(aa[key], bb[key]) == bb[key]
                        assert reverse.setdefault(bb[key], aa[key]) == aa[key]
                    else:
                        assert aa[key] == bb[key], (col, key, aa[key], bb[key])
            elif col in {'decision_id', 'order_id', 'fill_id', 'cycle_id', 'entry_cycle_id', 'plan_identity', 'signal_identity'}:
                alias = 'cycle_id' if col == 'entry_cycle_id' else col
                forward, reverse = identities.setdefault(alias, ({}, {}))
                assert forward.setdefault(a, b) == b and reverse.setdefault(b, a) == a, col
            else:
                assert a == b, (col, a, b)


def run_account(instance, binding, data, mode):
    executor = HistoricalExecutor(
        strategy_reference=instance.definition.release_id, symbol='159326.SZ',
        execution_daily=data.execution_daily, execution_intraday=data.execution_intraday,
        evaluation_start=pd.Timestamp(binding.plan.tradable_window.start),
        evaluation_end=pd.Timestamp(binding.plan.tradable_window.end), initial_cash=100000.,
        execution_policy=instance.definition.execution, order_types=instance.definition.capabilities.order_types,
        checkpoints=instance.definition.capabilities.checkpoints, account_id='observation-upgrade',
        execution_five_minute=data.execution_five_minute, pricing=data.pricing, market_rules=data.market_rules)
    observations = []
    for trading_date, signal_date in binding.plan.signal_dates.items():
        point = TradingPoint(trading_date, datetime.combine(signal_date, time(20, 31), ZONE))
        portfolio, state = executor.snapshot(point)
        plan = instance.plan_at(point=point, portfolio=portfolio, state=state, history_mode=mode)
        observations.append(materialize_observation(instance.definition, plan).to_dict())
        executor.execute(plan)
    return executor.finish(), observations


def probes(instances, bindings, data, mode):
    signals = instances[0].inspect_signals(history_mode=mode)
    available = bindings[0].plan.signal_dates
    dates = []
    for field in ('entry_signal', 'exit_signal', 'target_position'):
        matches = [(t, s) for t, s in available.items() if bool(signals.loc[pd.Timestamp(s), field])]
        dates.extend(matches[:2])
    dates = sorted(set(dates))
    cases = []
    for quantity in (200, 600):
        for trading_date, signal_date in dates:
            point = TradingPoint(trading_date, datetime.combine(signal_date, time(20, 31), ZONE))
            portfolio = PortfolioSnapshot('probe-existing-cycle', '159326.SZ', Decimal(98000),
                Decimal(100000), quantity, 4, point.calculation_time, pricing=data.pricing)
            cycle = EntryCycleState('a'*64, 'b'*64, Decimal(1), Decimal(100000), 1000,
                                    Decimal(quantity)*Decimal('1.5'), EntryCyclePhase.ACTIVE)
            state = ExecutionState(4, point.calculation_time, 1000, entry_cycle=cycle)
            values = [plain(x.plan_at(point=point, portfolio=portfolio, state=state, history_mode=mode)) for x in instances]
            normalized = []
            for value in values:
                value = json.loads(json.dumps(value))
                for name in ('strategy', 'signal_identity', 'plan_identity'):
                    value.pop(name)
                value['evidence'] = {k: v for k, v in value['evidence'].items() if not k.startswith('obs_')}
                normalized.append(value)
            assert normalized[0] == normalized[1], (quantity, signal_date, normalized)
            cases.append({'quantity': quantity, 'signal_date': signal_date, 'status': 'EXACT_PUBLIC_PLAN',
                          'old': values[0], 'new': values[1]})
    return {'coverage_sufficient': True, 'failures': [], 'cases': cases}


def replay():
    ctx = context()
    old, child = sources()
    request = requests()[0]
    pairs = [bind(ctx, source, request, tag) for source, tag in ((old, 'old'), (child, 'new'))]
    instances, bindings = zip(*pairs, strict=True)
    case_dir = CACHE / 'equivalence'
    case_dir.mkdir(parents=True, exist_ok=True)
    for name, binding in zip(('old', 'new'), bindings, strict=True):
        save(case_dir / f'{name}_binding.json', binding.to_dict())
    modes = {}
    for mode in SignalHistoryMode:
        histories = [x.inspect_signals(history_mode=mode) for x in instances]
        equal_frame(histories[0], histories[1][histories[0].columns], {})
        for name, history in zip(('old', 'new'), histories, strict=True):
            history.to_csv(case_dir / f'{name}_{mode}_signals_full.csv')
        results = [run_account(x, b, request.execution_data, mode) for x, b in pairs]
        for before, after in zip(results[0][1], results[1][1], strict=True):
            assert before['series'] == after['series'] and before['facts'] == after['facts']
        history = histories[1]
        inactive = ~history.target_position.astype(bool)
        assert history.loc[inactive, ['obs_repair_target', 'obs_invalidation_origin']].isna().all().all()
        assert history.loc[inactive, 'obs_opportunity_status'].eq('INACTIVE').all()
        assert history.loc[~inactive, 'obs_opportunity_id'].str.len().eq(10).all()
        identities, checks = {}, []
        for name in NAMES:
            frames = [getattr(x[0], name) for x in results]
            for side, frame in zip(('old', 'new'), frames, strict=True):
                frame.to_csv(case_dir / f'{side}_{mode}_{name}.csv', index=False)
            comparison = frames[1]
            if name == 'decisions':
                added = set(comparison.columns) - set(frames[0].columns)
                assert added <= set(instances[1].definition.observation.signal_panel.evidence_fields)
                assert all(x.startswith('obs_') for x in added)
                comparison = comparison.drop(columns=list(added))
            equal_frame(frames[0], comparison, identities)
            checks.append({'name': name, 'comparison': 'EXACT_VALUES_ZERO_TOLERANCE', 'rows': len(frames[1])})
        save(case_dir / f'nonzero_plan_probes_{mode}.json', probes(instances, bindings, request.execution_data, mode))
        save(CACHE / f'historical_observations_{mode}.json', {'kind': 'HISTORICAL_TECHNICAL_REPLAY',
            'is_forward_observation': False, 'window': plain(bindings[0].plan.tradable_window),
            'observations': results[1][1]})
        modes[mode.value] = {'status': 'PASS', 'signals': {'comparison': 'EXACT_VALUES_ZERO_TOLERANCE', 'rows': len(histories[1])},
            'ledgers': {'checks': checks}, 'actual_fills': {'old': len(results[0][0].fills), 'new': len(results[1][0].fills)}}
        print('EXACT_EQUIVALENCE', mode, len(histories[1]), len(results[1][0].fills), flush=True)
    artifacts = [{'path': 'equivalence/' + p.name, 'sha256': sha256(p.read_bytes()).hexdigest()}
                 for p in sorted(case_dir.iterdir()) if p.name != 'result.json']
    result = {'status': 'PASS', 'scope': 'REAL_AUTHENTICATED_MARKET_PUBLIC_SRT_PLAN_AT_AND_TXE',
        'reference': 'S015-v1', 'window': plain(bindings[0].plan.tradable_window), 'initial_quantity': 0,
        'initial_cash': 100000, 'identity': {f'{name}_identity': plain(binding.plan.strategy)
          for name, binding in zip(('old', 'new'), bindings, strict=True)}, 'modes': modes, 'artifacts': artifacts}
    save(case_dir / 'result.json', result)
    save(OUT / 'equivalence_summary.json', result)


def evaluate():
    ctx = context()
    _, child = sources()
    refs, comparisons = [], []
    old_results = read(HOME.parent / 'EX082_20261025/others/results.json')['rows']
    for index, old in enumerate(requests()):
        _, binding = bind(ctx, child, old, f'evaluation-{index}')
        request = ctx.evaluation.prepare(replace(old, experiment_id=EX.experiment_id, strategy=child,
            runtime_binding={'candidate_id': child.reference_id, 'source_files': list(child.payload['runtime']['source_files']),
                      'implementation_sha256': child.payload['runtime']['source_sha256']},
            lineage=None, input_bindings={'full': binding}))
        result = ctx.evaluation.evaluate(request)
        ref = publish_evidence(ctx, EvaluationEvidenceWrite(EX, request.costs[0].scenario_id, request, result))
        refs.append(ref.to_dict())
        baseline = next(x for x in old_results if x['scenario_id'] == request.costs[0].scenario_id)
        left, = read(EvidenceRef.from_dict(baseline['evidence']).resolve(ROOT))['runs']
        right, = read(ref.resolve(ROOT))['runs']
        comparison = compare_ledgers(LedgerComparisonRequest(ReplayEvidence.from_dict(left['replay_evidence']),
            ReplayEvidence.from_dict(right['replay_evidence']), LedgerComparisonMode.ECONOMIC, 0.0))
        save(CACHE / ('evaluation_comparison_' + request.costs[0].scenario_id + '.json'), comparison.to_dict())
        identities = {}
        for name in NAMES:
            before = pd.DataFrame(left['replay_evidence'][name])
            after = pd.DataFrame(right['replay_evidence'][name])
            if name == 'decisions':
                added = set(after.columns) - set(before.columns)
                allowed = set(StrategyRuntime().describe(child).observation.signal_panel.evidence_fields)
                assert added <= allowed and all(x.startswith('obs_') for x in added)
                after = after.drop(columns=list(added))
            equal_frame(before, after, identities)
        assert left['buyhold'] == right['buyhold']
        comparisons.append({'scenario': request.costs[0].scenario_id, 'comparison': comparison.to_dict(),
            'observation_aware_comparison': 'EXACT_VALUES_ZERO_TOLERANCE',
            'normalization': 'Only declared new obs_ columns and bijective runtime-linked identifiers; all original economic fields retained.',
            'baseline': baseline['evidence'], 'upgraded': ref.to_dict()})
        print('EVALUATED', request.costs[0].scenario_id, ref.sha256, flush=True)
    save(OUT / 'account_evaluation_refs.json', refs)
    save(OUT / 'cost_scenario_comparisons.json', comparisons)


def publish():
    ctx = context()
    _, child = sources()
    identity = StrategyRuntime().identify(child, dependencies=())
    assert plain(identity) == read(OUT / 'identity.json')
    refs = tuple(EvidenceRef.from_dict(x) for x in read(OUT / 'account_evaluation_refs.json'))
    registration = register_candidate(ctx.repository, CandidateRegistrationRequest(child, EX, refs, ()))
    save(OUT / 'registration.json', registration.to_dict())
    artifacts = {}
    for path in sorted((CACHE / 'equivalence').iterdir()):
        ref = publish_evidence(ctx, MaterialEvidenceWrite(EX, path.stem, path.read_bytes(),
            'application/json' if path.suffix == '.json' else 'text/csv', path.suffix[1:]))
        artifacts['equivalence/' + path.name] = ref.to_dict()
    manifest = {'selected_migrations': {'S015-v1': {'candidate_id': 'C9800', 'candidate_identity': plain(identity)}},
                'artifacts': artifacts}
    save(OUT / 'equivalence_manifest.json', manifest)
    ref = publish_evidence(ctx, MaterialEvidenceWrite(EX, 'equivalence_manifest',
        (OUT / 'equivalence_manifest.json').read_bytes(), 'application/json', 'json'))
    save(OUT / 'equivalence_refs.json', {'manifest': ref.to_dict(), 'case': artifacts['equivalence/result.json']})
    print('REGISTERED_AND_PUBLISHED', registration.content_sha256, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'replay', 'evaluate', 'publish'))
    {'prepare': prepare, 'replay': replay, 'evaluate': evaluate, 'publish': publish}[parser.parse_args().mode]()

