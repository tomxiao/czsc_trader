"""Bounded, resumable formal account publication and migration registration.

This module never freezes, qualifies, deploys or changes research intent. A
dispatch without a durable result is explicitly blocked instead of rerun.
"""
from __future__ import annotations

import argparse
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
import pickle
from collections.abc import Mapping
from decimal import Decimal
import traceback
from uuid import UUID

from dataflows import ProviderConfig
from strategy_manager import CandidateKey, StrategyRegistry
from strategy_runtime import ExecutionPriceBasis, StrategyCandidate, StrategyRuntime, canonical_sha256
from czsc_trader.application import (
    CandidateRegistrationRequest, ExperimentRequest, RepositoryContext, create_experiment,
    create_research_context, load_candidate, publish_evidence, register_candidate,
)
from czsc_trader.application.runtime_acceptance import prospective_release
from czsc_trader.research_tools import (
    EvaluationBenchmark, EvaluationCost, EvaluationEvidenceWrite, EvaluationRequest,
    EvaluationResources, EvaluationWindow, EvidenceRef, ExperimentRef, LimitBuyHold, ResearchBatchRef,
)
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from czsc_trader.research_tools._evaluation_workers import pack


ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
RECEIPTS = EX / 'others/formal_migration_registration'
STATE = RECEIPTS / 'state'
INVENTORY = ROOT / '.tmp/window-contract-governance-inventory.json'
SOURCE_CONFIG = EX / 'protocols/market_equivalence_cases.json'
REFERENCES = ('S001-v1', 'S001-v2', 'S002-v1', 'S007-v1', 'S011-v1', 'S003-v1')
REPOSITORY = RepositoryContext.discover(ROOT)
RESOURCES = EvaluationResources(max_workers=1, native_threads_per_worker=1, random_seed=17)


def plain(value):
    if is_dataclass(value):
        return {item.name: plain(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return value.relative_to(ROOT).as_posix() if value.is_absolute() and value.is_relative_to(ROOT) else str(value)
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    return value


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write_once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(plain(value), ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f'immutable receipt differs: {path.relative_to(ROOT)}')
    else:
        with path.open('xb') as stream:
            stream.write(data)


def blob_once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = pack(value)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('existing transport differs; explicit recovery is required')
    else:
        with path.open('xb') as stream:
            stream.write(data)
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': digest(path)}


def load_blob(reference):
    path = ROOT / reference['path']
    if not path.resolve().is_relative_to(ROOT / '.tmp') or digest(path) != reference['sha256']:
        raise ValueError('temporary transport pickle identity differs')
    return pickle.loads(path.read_bytes())  # Only this turn's SHA-bound local transport.


def selected(reference):
    inventory = read(INVENTORY)
    row = next(item for item in inventory['releases'] if item['reference'] == reference)
    candidate_info = row['selected_migration_candidate']
    cases = [case for case in read(SOURCE_CONFIG)['cases'] if case['reference'] == reference]
    expected = {name: candidate_info[name] for name in ('candidate_id', 'payload_path', 'source_root')}
    if not cases or any(case['candidate'] != expected for case in cases):
        raise ValueError('inventory and executed source selection differ')
    payload_path = ROOT / expected['payload_path']
    if digest(payload_path) != candidate_info['payload_sha256']:
        raise ValueError('selected payload changed after governance inventory')
    candidate = StrategyCandidate(reference.split('-')[0], expected['candidate_id'],
                                  read(payload_path), ROOT / expected['source_root'])
    identity = StrategyRuntime().identify(candidate, dependencies=())
    if identity.source_sha256 != candidate_info['source_sha256']:
        raise ValueError('selected source closure changed after inventory')
    return row, candidate, identity


def context_for(family):
    return create_research_context(REPOSITORY, ResearchBatchRef(family), resources=RESOURCES,
                                   providers=ProviderConfig(env_file=ROOT / '.env'))


def family_experiment(context):
    path = RECEIPTS / f'family-{context.strategy_id}.json'
    if path.exists():
        return ExperimentRef.from_dict(read(path)['experiment'])
    # Allocation is durable in experiment.json before its cross-task pointer.
    # If interrupted here, do not silently allocate a second experiment.
    marker = STATE / f'{context.strategy_id}-allocation.json'
    if marker.exists():
        raise RuntimeError('family experiment allocation interrupted; inspect existing experiment before explicit recovery')
    write_once(marker, {'status': 'ALLOCATION_STARTED', 'family': context.strategy_id,
                        'source': SOURCE_CONFIG.relative_to(ROOT).as_posix()})
    experiment = create_experiment(context, ExperimentRequest(
        '窗口契约迁移正式账户与候选登记',
        '仅登记已选定迁移实现，计算固定窗口一次策略与LimitBuyHold账户，为正式技术检验和冻结方案提供schema7证据；不进行策略搜索或生产变更。',
        date(2026, 10, 20),
    ))
    write_once(path, {'experiment': experiment.to_dict(), 'family_intent_changed': False,
                      'frozen_versions_created': 0, 'production_writes': 0})
    return experiment


def terms(reference, candidate):
    definition = StrategyRuntime().describe(candidate)
    family, version = reference.split('-')
    original = StrategyRuntime(REPOSITORY.strategy_root).describe(prospective_release(
        StrategyRegistry(REPOSITORY.strategy_root).get_version(family, version)))
    if definition.execution != original.execution:
        raise ValueError('migration execution contract differs from original')
    settings = definition.execution.settings
    if definition.execution.policy_type == 'FROZEN_RULE':
        instrument = settings['instrument']
        fee = float(settings['capital']['fee_rate'])
        market = {name: instrument[name] for name in ('lot_size', 'price_tick', 'price_limit_ratio', 'maximum_order_quantity')}
        origin = 'ORIGINAL_RUNTIME_EXECUTION_INSTRUMENT'
    elif reference == 'S003-v1' and definition.execution.policy_type == 'INTRADAY_OVERLAY':
        fee = float(settings['one_way_cost'])
        market = {'lot_size': int(settings['lot_size']), 'price_tick': .001,
                  'price_limit_ratio': .1, 'maximum_order_quantity': 1000000}
        origin = 'EXPLICIT_510500_CN_ETF_BENCHMARK_TERMS; LOT_FROM_ORIGINAL_OVERLAY'
    else:
        raise ValueError('unsupported explicitly selected execution policy')
    benchmark = EvaluationBenchmark(LimitBuyHold(
        lot_size=int(market['lot_size']), premium=.01, price_tick=float(market['price_tick']),
        price_limit_ratio=float(market['price_limit_ratio']), maximum_order_quantity=int(market['maximum_order_quantity']),
    ))
    return definition, fee, benchmark, {'instrument': market, 'terms_source': origin,
                                       'strategy_one_way_cost': fee, 'benchmark': benchmark.to_dict()}


def raw_request(reference, context, experiment):
    row, candidate, identity = selected(reference)
    definition, fee, benchmark, execution_terms = terms(reference, candidate)
    end = date(2026, 8, 28) if reference == 'S001-v1' else date(2026, 9, 2)
    request = EvaluationRequest(
        repository_root=ROOT, experiment_id=experiment.experiment_id, strategy=candidate,
        runtime_binding={'candidate_id': candidate.reference_id,
                         'source_files': list(candidate.payload['runtime']['source_files']),
                         'implementation_sha256': candidate.payload['runtime']['source_sha256']},
        symbol=definition.tradable_symbol, asset_type='etf',
        windows=(EvaluationWindow('full', date(2026, 6, 1), end),), data_cutoff=end,
        initial_cash=100000, costs=(EvaluationCost('baseline', fee),), benchmark=benchmark,
        workers=1, execution_mode='FULL', dependencies=(), price_basis=ExecutionPriceBasis.UNADJUSTED,
    )
    summary = {'repository_root': '.', 'experiment_id': experiment.experiment_id,
               'strategy': {'strategy_id': candidate.strategy_family_id, 'candidate_id': candidate.candidate_id,
                            'payload_path': row['selected_migration_candidate']['payload_path'],
                            'source_root': row['selected_migration_candidate']['source_root'],
                            'payload_sha256': row['selected_migration_candidate']['payload_sha256']},
               'runtime_binding': dict(request.runtime_binding), 'symbol': request.symbol, 'asset_type': request.asset_type,
               'windows': plain(request.windows), 'data_cutoff': end.isoformat(), 'initial_cash': request.initial_cash,
               'costs': plain(request.costs), 'benchmark': benchmark.to_dict(), 'price_basis': request.price_basis.value,
               'workers': 1, 'resources': plain(RESOURCES), 'frequency_window_days': 60, 'execution_mode': 'FULL',
               'dependencies': [], 'derivation': None, 'content_identity': plain(identity),
               'original_frozen_reference': reference, 'original_frozen_release_hash': row['release_hash'],
               'original_selection_data_cutoff': row['actual_selection_data_cutoff'],
               'execution_terms': execution_terms}
    return request, summary


def bind(reference, context, experiment):
    directory = STATE / reference
    prepared_path = directory / 'prepared.json'
    request, summary = raw_request(reference, context, experiment)
    if prepared_path.exists():
        saved = read(prepared_path)
        if saved['request_specification'] != summary:
            raise ValueError('prepared request specification changed; explicit successor required')
        bound = load_blob(saved['bound_request_pickle'])
        if (bound.strategy.payload != request.strategy.payload or bound.input_bindings['full'].prepared.space_id
                != context.data.binding.space_id or bound.execution_data.fingerprint != saved['request_summary']['execution_fingerprint']):
            raise ValueError('saved bound request identity differs')
        return bound, saved
    bound = context.evaluation.prepare(request)
    summary.update(input_bindings={key: value.to_dict() for key, value in bound.input_bindings.items()},
                   execution_fingerprint=bound.execution_data.fingerprint,
                   execution_prepared=plain(bound.execution_data.prepared),
                   execution_requests={key: plain(value) for key, value in bound.execution_data.requests.items()},
                   execution_input_identities=bound.execution_data.input_identities,
                   pricing=bound.execution_data.pricing.to_dict(),
                   market_rules=bound.execution_data.market_rules.to_dict())
    transport = blob_once(ROOT / '.tmp/formal-migration-transport' / reference / 'bound-request.pkl', bound)
    record = {'status': 'PREPARED_NOT_DISPATCHED', 'experiment': experiment.to_dict(),
              'request_specification': raw_request(reference, context, experiment)[1],
              'request_summary': summary, 'bound_request_pickle': transport,
              'source_script_sha256': digest(Path(__file__))}
    write_once(prepared_path, record)
    write_once(experiment.resolve(ROOT) / 'protocols' / f'{reference}-evaluation-request.json', record)
    return bound, record


def account(reference, context, experiment, bound, prepared_record):
    directory = STATE / reference
    evidence_path, outcome_path = directory / 'account_evidence.json', directory / 'outcome.json'
    if evidence_path.exists():
        evidence = EvidenceRef.from_dict(read(evidence_path)['account_evidence'])
    else:
        if outcome_path.exists():
            outcome_receipt = read(outcome_path)
            if outcome_receipt['status'] != 'SUCCEEDED':
                raise RuntimeError('prior account outcome was not successful; automatic retry is forbidden')
            result = load_blob(outcome_receipt['result_pickle'])
        else:
            dispatch_path = directory / 'dispatch.json'
            if dispatch_path.exists():
                raise RuntimeError('prior dispatch lacks a durable outcome; account status is unknown and rerun is forbidden')
            write_once(dispatch_path, {'status': 'DISPATCHED_ONCE', 'reference': reference,
                       'candidate': bound.strategy.reference_id, 'bound_request_pickle': prepared_record['bound_request_pickle'],
                       'request_summary_sha256': canonical_sha256(prepared_record['request_summary']),
                       'strategy_accounts': 1, 'buyhold_accounts': 1, 'workers': 1})
            outcome, = context.evaluation.evaluate_many((bound,))
            result = outcome.result
            receipt = {'status': outcome.status.value, 'request_hash': outcome.request_hash,
                       'error': None if outcome.error is None else plain(outcome.error)}
            if outcome.status.value == 'SUCCEEDED':
                receipt['result_pickle'] = blob_once(
                    ROOT / '.tmp/formal-migration-transport' / reference / 'result.pkl', result)
                receipt['result_hash'] = result.result_hash
            write_once(outcome_path, receipt)
            if outcome.status.value != 'SUCCEEDED':
                raise RuntimeError(f'formal account failed, no retry: {receipt}')
        evidence = publish_evidence(context, EvaluationEvidenceWrite(
            experiment, f'window-contract-migration-{reference.lower()}', bound, result))
        write_once(evidence_path, {'account_evidence': evidence.to_dict()})
    document = read(evidence.resolve(ROOT))
    validate_evaluation_evidence(document)
    selected_row, candidate, identity = selected(reference)
    if (evidence.schema, evidence.schema_version) != ('account_evaluation', 7) or len(document['runs']) != 1:
        raise ValueError('formal support must be schema7 with exactly one coordinate')
    run = document['runs'][0]
    if (run['identity']['content_sha256'] != identity.content_sha256
            or run['candidate_id'] != candidate.candidate_id
            or (run['window_id'], run['scenario_id']) != ('full', 'baseline')
            or document['data_identity'] != bound.execution_data.fingerprint
            or document['request_identity']['initial_cash'] != 100000
            or document['request_identity']['price_basis'] != ExecutionPriceBasis.UNADJUSTED.value
            or document['request_identity']['input_bindings'] != prepared_record['request_summary']['input_bindings']):
        raise ValueError('published formal evidence differs from selected bound request')
    return evidence, document


def register(reference, context, experiment, bound, prepared_record, evidence, document):
    key = CandidateKey(bound.strategy.strategy_family_id, bound.strategy.candidate_id)
    path = REPOSITORY.research_registry_root / key.strategy_id / 'candidates' / f'{key.candidate_id}.json'
    if path.exists():
        registered = load_candidate(REPOSITORY, key)
        if StrategyRuntime().identify(registered, dependencies=()) != StrategyRuntime().identify(bound.strategy, dependencies=()):
            raise ValueError('existing candidate identity differs from this migration')
        registration = StrategyRegistry(REPOSITORY.research_registry_root).get_candidate(
            key, evidence_root=REPOSITORY.research_root / key.strategy_id)
        if registration.origin.experiment_id != experiment.experiment_id:
            raise ValueError('existing registration origin belongs to another experiment')
    else:
        registration = register_candidate(REPOSITORY, CandidateRegistrationRequest(
            bound.strategy, experiment, (evidence,), dependencies=(), derivation=None))
    loaded = load_candidate(REPOSITORY, key)
    if StrategyRuntime().identify(loaded, dependencies=()).content_sha256 != registration.content_sha256:
        raise ValueError('registered snapshot identity is not reproducible')
    receipt = {'status': 'REGISTERED_SCHEMA7_ACCOUNT', 'original_reference': reference,
               'experiment': experiment.to_dict(), 'account_evidence': evidence.to_dict(),
               'registration': registration.to_dict(), 'bound_request_pickle': prepared_record['bound_request_pickle'],
               'request_summary': prepared_record['request_summary'], 'request_hash': document['request_hash'],
               'result_hash': document['result_hash'], 'candidate_derivation': None,
               'migration_source_selection': 'To be recorded separately by MigrationSelection; no fabricated legacy CandidateDerivation.',
               'frozen': False, 'qualified': False, 'deployed': False, 'production_writes': 0}
    write_once(RECEIPTS / f'{reference}.json', receipt)
    write_once(experiment.resolve(ROOT) / 'others' / f'{reference}-registration.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=('prepare', 'execute'), required=True)
    parser.add_argument('--references', nargs='+', choices=REFERENCES, default=list(REFERENCES[:-1]))
    parser.add_argument('--allow-s003', action='store_true', help='Only after the reviewed TXE fix is confirmed.')
    args = parser.parse_args()
    for reference in args.references:
        family = reference.split('-')[0]
        try:
            if reference == 'S003-v1' and args.phase == 'execute' and not args.allow_s003:
                raise ValueError('S003 formal execution awaits confirmed TXE fix and --allow-s003')
            final_path = RECEIPTS / f'{reference}.json'
            context = context_for(family)
            experiment = family_experiment(context)
            if final_path.exists():
                final = read(final_path)
                evidence = EvidenceRef.from_dict(final['account_evidence'])
                validate_evaluation_evidence(read(evidence.resolve(ROOT)))
                loaded = load_candidate(REPOSITORY, CandidateKey(family, final['registration']['key']['candidate_id']))
                _, _, identity = selected(reference)
                if StrategyRuntime().identify(loaded, dependencies=()).content_sha256 != identity.content_sha256:
                    raise ValueError('completed registration identity no longer matches selection')
                print(json.dumps({'reference': reference, 'status': 'LOADED_EXISTING_REGISTERED_REF',
                                  'account_evidence': evidence.to_dict()}, ensure_ascii=False), flush=True)
                continue
            bound, prepared_record = bind(reference, context, experiment)
            if args.phase == 'prepare':
                print(json.dumps({'reference': reference, 'status': 'PREPARED_NOT_DISPATCHED',
                                  'experiment': experiment.to_dict(),
                                  'execution_fingerprint': bound.execution_data.fingerprint}, ensure_ascii=False), flush=True)
                continue
            evidence, document = account(reference, context, experiment, bound, prepared_record)
            receipt = register(reference, context, experiment, bound, prepared_record, evidence, document)
            print(json.dumps({'reference': reference, 'status': receipt['status'],
                              'account_evidence': receipt['account_evidence'],
                              'registration_content_sha256': receipt['registration']['content_sha256']}, ensure_ascii=False), flush=True)
        except BaseException as error:
            failure_root = STATE / reference / 'failures'
            failure_root.mkdir(parents=True, exist_ok=True)
            number = len(tuple(failure_root.glob('*.json'))) + 1
            write_once(failure_root / f'{number:03}.json', {
                'status': 'FAILED_NO_AUTOMATIC_ACCOUNT_RETRY', 'phase': args.phase, 'reference': reference,
                'error_type': type(error).__name__, 'error': str(error),
                'recorded_at': datetime.now(timezone.utc).isoformat(), 'source_script_sha256': digest(Path(__file__)),
            })
            traceback.print_exc()
            raise


if __name__ == '__main__':
    main()
