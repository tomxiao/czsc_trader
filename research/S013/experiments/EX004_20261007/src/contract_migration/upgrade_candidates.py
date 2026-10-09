"""Recompute S013 successors through TDR and authenticate all economic rows."""
# ruff: noqa: E402
import os
for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[variable] = '1'

import argparse
import ast
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
ROOT = SRC.parents[4]
sys.path.insert(0, str(SRC))

import pandas as pd
from dataflows import Dataset, ProviderBinding, ProviderConfig
from strategy_runtime import StrategyInputBinding, StrategyRuntime
from strategy_manager import (CandidateKey, CandidateEvidence, CandidateDerivation,
                              CandidateDerivationKind)
from czsc_trader.application import (RepositoryContext, create_research_context,
                                    publish_evidence, register_candidate, load_candidate,
                                    CandidateRegistrationRequest)
from czsc_trader.research_tools import (ResearchBatchRef, EvaluationResources,
                                     EvaluationEvidenceWrite, MaterialEvidenceWrite)
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence
from common import request as range_request, cache_write
from common_adaptive import request as adaptive_request
from economic_equivalence import compare_evidence

OUT = ROOT / 'research/S013/assets/runs/EX004_20261007/contract_migration'
PLAN = SRC.parent / 'protocols/contract_migration_20261009.json'
EXPERIMENT = ExperimentRef('S013', 'EX004_20261007')
BASELINES = ROOT / '.tmp/s013-equivalence-baselines.json'
SOURCE_CALLS = []


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                    encoding='utf-8', newline='\n')


def forbidden_source(request):
    SOURCE_CALLS.append(str(request))
    raise AssertionError('all continuation inputs must already exist in S013')


def context(workers):
    bindings = {dataset: ProviderBinding(str(dataset), 'S013-contract-continuation', forbidden_source)
                for dataset in (Dataset.TRADING_CALENDAR, Dataset.ETF_OHLCV,
                                Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY)}
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S013'),
                                  providers=ProviderConfig(bindings=bindings),
                                  resources=EvaluationResources(workers, 1, 13))


def verify_source_algorithms(record, candidate):
    for entry in record['source_files']:
        before = ROOT / 'research/S013' / entry['path']
        assert sha256(before.read_bytes()).hexdigest() == entry['sha256']
        name = Path(entry['path']).name
        current = candidate.source_root / 'strategies' / name
        for label in ('calculate_history', 'components', '__init__', 'definition'):
            def nodes(path):
                tree = ast.parse(path.read_text(encoding='utf-8'))
                return [ast.dump(node, include_attributes=False) for node in ast.walk(tree)
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == label]
            assert nodes(before) == nodes(current), (record['key'], name, label)


def verify_inputs(research, original, bound):
    proofs = []
    for window, old_value in original['input_bindings'].items():
        old = StrategyInputBinding.from_mapping(old_value)
        new = bound.input_bindings[window]
        for field in ('tradable_window', 'calendar_name', 'calendar_sha256', 'requests',
                      'calendar_dates', 'signal_dates', 'calculation_dates'):
            assert getattr(old.plan, field) == getattr(new.plan, field), (bound.strategy.candidate_id, field)
        old_entries = research.data._store.load_preparation(old.prepared)
        for name, request in new.plan.requests.items():
            fetched = research.data.fetch(request, prepared=new.prepared)
            assert fetched.ready, fetched
            matches = [entry for entry in old_entries if entry['request']['dataset'] == str(request.dataset)
                       and entry['request']['symbol'] == request.symbol
                       and entry['request']['frequency'] == request.frequency
                       and entry['request']['start'] == request.start
                       and entry['request']['end'] == request.end
                       and entry['request']['required_cutoff'] == request.required_cutoff]
            assert len(matches) == 1, (name, matches)
            asset = research.data._store.read(matches[0]['asset_id'])
            dates = pd.to_datetime(asset.dataframe.Date)
            cutoff = pd.Timestamp(request.end) + (pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
                                                   if len(request.end) == 10 else pd.Timedelta(0))
            selected = asset.dataframe.loc[(dates >= pd.Timestamp(request.start)) & (dates <= cutoff)].reset_index(drop=True)
            pd.testing.assert_frame_equal(selected, fetched.dataframe, check_exact=True)
            proofs.append({'window': window, 'input': name, 'rows': len(selected),
                           'content_sha256': fetched.identity.content_sha256})
    return proofs


def setup():
    saved_baselines = OUT / 'baseline_candidates.json'
    baselines = read(saved_baselines if saved_baselines.exists() else BASELINES)
    if not saved_baselines.exists():
        write(saved_baselines, baselines)
    registry_root = ROOT / 'research/registrations/S013/candidates'
    historical = {item['candidate_id']: read(registry_root / f"{item['candidate_id']}.json") for item in baselines}
    plan = {'schema_version': 1, 'purpose': 'data and strategy contract migration; economic behavior preservation',
            'data_contract_version': 1, 'baseline_candidates': sorted(historical),
            'successors': {old: f'C{9001 + index:04}' for index, old in enumerate(sorted(historical))},
            'comparison': 'exact inputs, signals, relational ledgers and BuyHold; new identity hashes expected',
            'resources': {'max_workers': 4, 'native_threads_per_worker': 1, 'request_workers': 1},
            'window': ['2020-01-02', '2026-09-30'], 'price_basis': 'HFQ_RESEARCH',
            'preserve': ['historical data records', 'registered candidates', 'evidence', 'stage deliveries'],
            'approval': '用户批准 S013 数据契约迁移及策略升级；研究阶段保持阶段四完成、待用户决定'}
    if PLAN.exists():
        assert read(PLAN) == plan
    else:
        write(PLAN, plan)
    return baselines, historical, plan


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('precheck', 'execute'), required=True)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    baselines, historical, plan = setup()
    if args.mode == 'execute':
        migration = read(OUT / 'migration.json')
        assert migration['status'] == 'PASS', migration
    repository = RepositoryContext.discover(ROOT)
    research = context(1 if args.mode == 'precheck' else 4)
    cache_folder = ROOT / '.tmp/s013-contract-upgrade'
    cache_folder.mkdir(exist_ok=True)
    execution = None
    bound_requests = []
    indexed = {}
    for item in baselines:
        parent = item['candidate_id']
        record = historical[parent]['record']
        payload = read(ROOT / 'research/S013' / record['payload']['path'])
        number = int(plan['successors'][parent][1:])
        factory = adaptive_request if payload['runtime']['qualname'] == 'AdaptiveRange' else range_request
        request = factory(number, deepcopy(payload['parameters']), execution_data=execution)
        assert dict(request.strategy.payload['parameters']) == payload['parameters']
        verify_source_algorithms(record, request.strategy)
        identity = StrategyRuntime().identify(request.strategy, dependencies=request.dependencies)
        if (ROOT / 'research/registrations/S013/candidates' / f'{request.strategy.candidate_id}.json').exists():
            loaded = load_candidate(repository, CandidateKey('S013', request.strategy.candidate_id))
            assert StrategyRuntime().identify(loaded, dependencies=request.dependencies) == identity
        if args.mode == 'precheck':
            continue
        old_evidence = read(ROOT / item['path'])
        bound = research.evaluation.prepare(request)
        assert bound.execution_data.fingerprint == old_evidence['request_identity']['data_identity']
        if execution is None:
            execution = bound.execution_data
        proof = verify_inputs(research, old_evidence, bound)
        indexed[bound.strategy.candidate_id] = (item, historical[parent], proof)
        bound_requests.append(bound)
        print(json.dumps({'phase': 'inputs-verified', 'parent': parent,
                          'successor': bound.strategy.candidate_id}), flush=True)
    if args.mode == 'precheck':
        write(OUT / 'strategy_contract_precheck.json', {'status': 'PASS', 'candidates': len(baselines),
               'unchanged': ['parameters', 'signal calculation', 'feature calculation', 'parameter validation', 'definition'],
               'public_runtime_load': True})
        print(json.dumps({'status': 'PASS', 'public_runtime_candidates': len(baselines)}))
        return
    assert not SOURCE_CALLS
    precheck_ids = {bound_requests[0].strategy.candidate_id,
                    next(req.strategy.candidate_id for req in bound_requests if
                         req.strategy.payload['runtime']['qualname'] == 'AdaptiveRange')}
    results = {}
    for request in bound_requests:
        if request.strategy.candidate_id not in precheck_ids:
            continue
        result = research.evaluation.evaluate(request)
        item, _, _ = indexed[request.strategy.candidate_id]
        compare_evidence(read(ROOT / item['path']), serialize_evaluation_evidence(request, result))
        results[request.strategy.candidate_id] = result
        print(json.dumps({'phase': 'account-precheck-pass', 'candidate': request.strategy.candidate_id}), flush=True)
    pending = tuple(req for req in bound_requests if req.strategy.candidate_id not in results)
    outcomes = research.evaluation.evaluate_many(pending)
    for request, outcome in zip(pending, outcomes):
        assert outcome.status.value == 'SUCCEEDED', (request.strategy.candidate_id, outcome)
        results[request.strategy.candidate_id] = outcome.result
    rows = []
    for request in bound_requests:
        item, record, inputs = indexed[request.strategy.candidate_id]
        result = results[request.strategy.candidate_id]
        proof = compare_evidence(read(ROOT / item['path']), serialize_evaluation_evidence(request, result))
        rows.append({'parent': item['candidate_id'], 'successor': request.strategy.candidate_id,
                     'parent_reference': item['reference'], 'inputs': inputs, 'economic_equivalence': proof,
                     'stage4_center': item['stage4_center']})
        cache_write(cache_folder / f'{request.strategy.candidate_id}.pkl.gz', (request, result))
    assert not SOURCE_CALLS
    write(OUT / 'candidate_equivalence.json', {'status': 'PASS', 'candidates': rows,
                                              'external_supplier_access': False})
    # Publication starts only after the entire requested migration has passed.
    receipts = []
    for request, row in zip(bound_requests, rows):
        evidence = publish_evidence(research, EvaluationEvidenceWrite(
            EXPERIMENT, f"contract-migration-{request.strategy.candidate_id.lower()}", request,
            results[request.strategy.candidate_id]))
        old_record = historical[row['parent']]['record']
        identity = StrategyRuntime().identify(request.strategy, dependencies=request.dependencies)
        parent_ref = row['parent_reference']
        from czsc_trader.research_tools.evidence import EvidenceRef
        origin = EvidenceRef.from_dict(parent_ref)
        derivation = CandidateDerivation(
            CandidateKey('S013', row['parent']), old_record['content_sha256'],
            CandidateKey('S013', row['successor']), identity.content_sha256,
            CandidateDerivationKind.IMPLEMENTATION,
            {'calendar_request': 'strategy declares its calendar DataRequest',
             'derive_calculation_scope': 'strategy declares complete data requests; original economic behavior preserved'},
            sha256(PLAN.read_bytes()).hexdigest(), CandidateEvidence(origin.repository_path, origin.sha256))
        registered = register_candidate(repository, CandidateRegistrationRequest(
            request.strategy, EXPERIMENT, (evidence,), request.dependencies, derivation))
        loaded = load_candidate(repository, CandidateKey('S013', row['successor']))
        assert StrategyRuntime().identify(loaded, dependencies=request.dependencies) == identity
        receipts.append({'parent': row['parent'], 'successor': row['successor'],
                         'registration': registered.to_dict(), 'evidence': evidence.to_dict(),
                         'source_root': loaded.source_root.relative_to(ROOT).as_posix()})
    for parent, original in historical.items():
        assert read(ROOT / 'research/registrations/S013/candidates' / f'{parent}.json') == original
    proof_evidence = publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT,
        'contract-migration-economic-equivalence', (OUT / 'candidate_equivalence.json').read_bytes(),
        'application/json', 'json'))
    write(OUT / 'successor_registrations.json', {'status': 'PASS', 'candidates': receipts,
          'equivalence_evidence': proof_evidence.to_dict(), 'suppliers_accessed': False,
          'historical_registrations_unchanged': True, 'research_stage_changed': False})
    print(json.dumps({'status': 'PASS', 'registered_successors': len(receipts),
                      'parent_registrations_unchanged': True, 'suppliers_accessed': False}), flush=True)


if __name__ == '__main__':
    main()
