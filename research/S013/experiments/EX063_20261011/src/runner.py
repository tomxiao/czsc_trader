"""Source-only execution draft: all financial stages require a future public method.

No experiment/ID is allocated by this module. Import and freeze-draft are pure
source operations. A future root-approved successor must bind exact source,
collision proof, input primer, reuse identities and method before executing.
"""
from __future__ import annotations

import argparse
import copyreg
from dataclasses import dataclass, replace
import gzip
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import pickle
import sys
from types import MappingProxyType

from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence
from czsc_trader.research_tools import (
    EvaluationEvidenceWrite, EvaluationLineage, EvaluationResources, MaterialEvidenceWrite,
    ParameterEvaluationPlan, ResearchBatchRef,
)
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence
from czsc_trader.research_tools.parameter_evaluation import read_parameter_plan
from dataflows import Dataset, ProviderBinding, ProviderConfig
from strategy_manager import CandidateDerivation, CandidateDerivationKind, CandidateEvidence, CandidateKey
from strategy_runtime import StrategyCandidate

import prepared_audit

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
HERE = Path(__file__).resolve().parent
DRIVER = ROOT / '.tmp/s013-management-driver'
BRIDGE = ROOT / '.tmp/s013-management-bridge'
EX058 = ROOT / 'research/S013/experiments/EX058_20261011'
REVISION = 'S013-EX062-existing-only'
AUTHORIZATION = 'AUTHORIZED_FOR_FIXED_MANAGEMENT_COMPARISON'
LABELS = ('B0', 'N_LOCK', 'N_CURRENT')


def load(name, path):
    path = path.resolve()
    if name in sys.modules:
        if Path(sys.modules[name].__file__).resolve() != path:
            raise ValueError('Module name collision: ' + name)
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def capabilities():
    bridge = load('_management_runner_bridge', BRIDGE / 'bridge.py')
    bridge.source_guard()
    _, audit, _ = bridge.capabilities()
    return sys.modules['draft'], audit, sys.modules['fivechecks_reference'], bridge


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')


def file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def restore_mapping(value):
    return MappingProxyType(value)


def save_native(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError('Immutable native cache already exists')
    with gzip.open(path, 'wb') as stream:
        writer = pickle.Pickler(stream, protocol=pickle.HIGHEST_PROTOCOL)
        writer.dispatch_table = {**copyreg.dispatch_table,
            MappingProxyType: lambda x: (restore_mapping, (dict(x),))}
        writer.dump(value)


def read_native(path):
    # Only execute stages call this. Trusted exact-source local artifacts, never external pickles.
    load('common', EX058 / 'src/common.py')
    if 'EX062' in str(path):
        # Optional old fee cache reducer only. No EX062 result read during import.
        load('robust_center_draft', ROOT / 'research/S013/experiments/EX062_20261011/src/robust_center_draft.py')
    with gzip.open(path, 'rb') as stream:
        return pickle.load(stream)


def scoped_path(relative):
    target = (ROOT / relative).resolve()
    if not target.is_relative_to(ROOT) or not (relative.startswith('.tmp/') or relative.startswith('research/S013/')):
        raise ValueError('Only explicitly bound S013/workspace temporary artifacts allowed')
    return target


def evidence(value):
    reference = EvidenceRef.from_dict(value)
    if reference.experiment.strategy_id != 'S013':
        raise ValueError('S013 public evidence required')
    return reference


@dataclass(frozen=True)
class ExecutionContract:
    experiment: ExperimentRef
    method_reference: EvidenceRef
    work: Path
    method: dict


def require_method(reference_path, work):
    ref = evidence(read(reference_path))
    method = read(ref.resolve(ROOT))
    if method.get('authorization') != AUTHORIZATION or method.get('provider_revision') != REVISION:
        raise ValueError('Future public execution authorization and unchanged pinned provider revision required')
    experiment = ExperimentRef('S013', method['experiment_id'])
    if ref.experiment != experiment or method.get('policies') != list(LABELS):
        raise ValueError('Public method experiment/fixed policy mismatch')
    expected_sources = {'runner.py': file_hash(HERE / 'runner.py'), 'prepared_audit.py': file_hash(HERE / 'prepared_audit.py')}
    if method.get('runner_source_files') != expected_sources:
        raise ValueError('Public method does not bind exact execution runner')
    for relative, digest in method['external_source_files'].items():
        if file_hash(scoped_path(relative)) != digest:
            raise ValueError('Bound external source drift: ' + relative)
    if method.get('baseline_fee_reuse') is not None:
        reducer = 'research/S013/experiments/EX062_20261011/src/robust_center_draft.py'
        if method['external_source_files'].get(reducer) != file_hash(ROOT / reducer):
            raise ValueError('Optional old fee cache requires exact public-bound reducer source')
    draft, _, _, _ = capabilities()
    reserve = draft.Reservation(experiment.experiment_id, **method['reservation'])
    new_ids = (reserve.lock_center, reserve.current_center, *reserve.lock_points, *reserve.current_points)
    collision = evidence(method['collision_reference'])
    collision_doc = read(collision.resolve(ROOT))
    if collision_doc.get('status') != 'PASS' or collision_doc.get('candidate_ids') != list(new_ids):
        raise ValueError('Public collision audit must cover all66 exact prospective IDs')
    primer = evidence(method['input_primer_reference'])
    doc = read(primer.resolve(ROOT))
    if doc.get('status') != 'PASS' or doc.get('provider_revision') != REVISION or not doc.get('prepared_inputs'):
        raise ValueError('Prospective pinned subset/input primer proof required; no fallback')
    if method.get('pinned_inputs') != doc['prepared_inputs']:
        raise ValueError('Exact public pinned request/identity/space table must be copied without changes')
    if method.get('policy_parameters') != expected_parameters(draft):
        raise ValueError('Frozen center numbers/categories differ from original fixed policies')
    if set(method['source_roots']) != set(LABELS):
        raise ValueError('All three explicit immutable source roots required')
    work = Path(work).resolve()
    if not work.is_relative_to(ROOT / '.tmp'):
        raise ValueError('Execution artifacts stay in repository .tmp')
    return ExecutionContract(experiment, ref, work, method)


def expected_parameters(draft):
    p, _ = draft.metadata()
    return {'B0': p, 'N_LOCK': p | {'exit_on_regime_change': False},
            'N_CURRENT': p | {'exit_on_regime_change': False, 'mechanism': draft.CURRENT}}


def context(contract, workers=1):
    def forbidden(request):
        raise RuntimeError('Pinned existing-only cache miss is terminal; root must declare a new subset primer, never external fallback: ' + str(request.dataset))
    bindings = {d: ProviderBinding(str(d), REVISION, forbidden) for d in (
        Dataset.TRADING_CALENDAR, Dataset.ETF_OHLCV, Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY)}
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S013'),
        providers=ProviderConfig(bindings=bindings), resources=EvaluationResources(workers, 1, 13))


def material(ctx, contract, name, value):
    return publish_evidence(ctx, MaterialEvidenceWrite(contract.experiment, name,
        (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode(), 'application/json', 'json'))


def native_audit(ctx, pair, reference, contract):
    request, result = pair
    formal = read(reference.resolve(ROOT))
    _, audit, _, bridge = capabilities()
    identity = ctx.runtime.identify(request.strategy, dependencies=request.dependencies)
    economic = audit.audit_native(request, result, formal, ctx.runtime, content_sha256=identity.content_sha256)
    account = load('_management_runner_original_cash_audit', EX058 / 'src/account_reference.py').verify_account(request, result)
    signal = prepared_audit.audit_prepared(ctx, request, result, bridge, contract.method['pinned_inputs'])
    if request.workers != 1 or request.price_basis.value != 'HFQ_RESEARCH':
        raise ValueError('Fixed single-native worker / HFQ contract required')
    return {'status': 'PASS', 'economics': economic, 'account': account, 'signal': signal,
            'public_native_reference': reference.to_dict(), 'content_sha256': identity.content_sha256,
            'method_reference': contract.method_reference.to_dict(), 'whole_formal_native_exact': True}


def reuse_account(ctx, contract, item):
    path = scoped_path(item['cache_path'])
    if file_hash(path) != item['cache_sha256']:
        raise ValueError('Frozen exact native cache bytes differ before decode')
    pair = read_native(path)
    reference = evidence(item['reference'])
    audited = native_audit(ctx, pair, reference, contract)
    request, result = pair
    if (request.strategy.candidate_id != item['candidate_id'] or audited['content_sha256'] != item['content_sha256']
            or result.request_hash != item['request_hash'] or result.result_hash != item['result_hash']):
        raise ValueError('Exact native reuse identity/request/result mismatch')
    return pair, reference, audited


def authenticate_baseline(ctx, contract):
    items = contract.method['baseline_reuse']
    if len(items['points']) != 32 or [x['point_index'] for x in items['points']] != list(range(32)):
        raise ValueError('All32 old points ordered and retained')
    center, ref, center_audit = reuse_account(ctx, contract, items['center'])
    if center[0].strategy.candidate_id != 'C8880' or dict(center[0].strategy.payload['parameters']) != contract.method['policy_parameters']['B0']:
        raise ValueError('Original C8880 payload/identity must remain native')
    if center[0].strategy.source_root.resolve() != scoped_path(contract.method['source_roots']['B0']):
        raise ValueError('Old original source-root identity must remain native')
    plan = read_parameter_plan(evidence(items['plan_reference']), ROOT)
    if plan.design.center.candidate_id != 'S013-C8880':
        raise ValueError('Original plan center mismatch')
    rows = [reuse_account(ctx, contract, item) for item in items['points']]
    draft, _, _, _ = capabilities()
    _, coordinates = draft.metadata()
    for i, (pair, _, _) in enumerate(rows):
        req = pair[0]
        if (req.lineage is None or req.lineage.parameter_binding is None
                or req.lineage.parameter_binding.point != plan.design.bind_point(i)
                or req.lineage.parameter_binding.plan != evidence(items['plan_reference'])
                or req.dependencies != center[0].dependencies
                or req.strategy.payload['runtime'] != center[0].strategy.payload['runtime']
                or dict(req.strategy.payload['parameters']) != draft.materialize(dict(center[0].strategy.payload['parameters']), coordinates, plan.design.points[i].coordinates)):
            raise ValueError('Old full13 geometry/payload/source/dependency/binding differs')
    return {'center': center, 'center_reference': ref, 'points': tuple(x[0] for x in rows),
            'point_references': tuple(x[1] for x in rows), 'plan': plan,
            'center_audit': center_audit, 'point_audits': tuple(x[2] for x in rows)}


def journal(contract):
    path = contract.work / 'journal.json'
    if not path.exists():
        return {'method_sha256': contract.method_reference.sha256, 'accounts': {}, 'attempts': 0, 'status': 'NEW'}
    state = read(path)
    if state['method_sha256'] != contract.method_reference.sha256:
        raise ValueError('Work directory belongs to a different public method')
    return state


def checkpoint(contract, state):
    write(contract.work / 'journal.json', state)


def begin(contract, state, labels):
    """Mark every scheduled native evaluation before dispatch; never retry ambiguous/failed calls."""
    if len(set(labels)) != len(labels) or any(label in state['accounts'] for label in labels):
        raise RuntimeError('Existing account status cannot be silently retried or replaced')
    if state['attempts'] + len(labels) > 72:
        raise RuntimeError('Declared maximum72 actual evaluations exceeded')
    state['attempts'] += len(labels)
    for label in labels:
        state['accounts'][label] = {'status': 'INFLIGHT'}
    checkpoint(contract, state)


def retain(ctx, contract, state, label, request, result):
    """Preserve full successful native before publication/audit; later failures remain visible."""
    path = contract.work / 'native' / (label + '.pkl.gz')
    save_native(path, (request, result))
    reference = publish_evidence(ctx, EvaluationEvidenceWrite(contract.experiment, label, request, result))
    item = {'status': 'CACHED_PUBLISHED', 'cache_path': path.relative_to(ROOT).as_posix(),
            'cache_sha256': file_hash(path),
            'reference': reference.to_dict(), 'candidate_id': request.strategy.candidate_id,
            'content_sha256': ctx.runtime.identify(request.strategy, dependencies=request.dependencies).content_sha256,
            'request_hash': result.request_hash, 'result_hash': result.result_hash}
    state['accounts'][label] = item
    checkpoint(contract, state)
    audited = native_audit(ctx, (request, result), reference, contract)
    write(contract.work / 'audits' / (label + '.json'), audited)
    state['accounts'][label]['status'] = 'COMPLETE'
    checkpoint(contract, state)
    return (request, result), reference, audited


def execute_one(ctx, contract, state, request, label):
    if label in state['accounts']:
        item = state['accounts'][label]
        if item['status'] != 'COMPLETE':
            raise RuntimeError('Non-complete evaluation requires root-reviewed successor recovery, never financial retry')
        pair, ref, audit = reuse_account(ctx, contract, item)
        if serialize_evaluation_evidence(*pair) != serialize_evaluation_evidence(request, pair[1]):
            raise ValueError('Complete local reuse request drift')
        return pair, ref, audit
    begin(contract, state, (label,))
    try:
        if ctx.evaluation.resources.max_workers == 1:
            result = ctx.evaluation.evaluate(request)
        else:
            outcomes = ctx.evaluation.evaluate_many((request,))
            if len(outcomes) != 1 or outcomes[0].status.value != 'SUCCEEDED':
                raise RuntimeError('Spawn evaluation did not succeed: ' + str(outcomes))
            result = outcomes[0].result
        return retain(ctx, contract, state, label, request, result)
    except Exception as error:
        state['accounts'][label]['status'] = 'FAILED'
        state['accounts'][label]['failure'] = {'type': type(error).__name__, 'message': str(error)}
        state['status'] = 'FAILED'
        checkpoint(contract, state)
        raise


def implementation_request(ctx, contract, old, parent_ref, label, identifier):
    draft, _, _, _ = capabilities()
    temporary = draft.candidate(label, identifier, contract.method['policy_parameters']['B0'])
    strategy = StrategyCandidate('S013', identifier, dict(temporary.payload), scoped_path(contract.method['source_roots'][label]))
    identity = ctx.runtime.identify(strategy, dependencies=old.dependencies)
    parent = ctx.runtime.identify(old.strategy, dependencies=old.dependencies)
    lineage = CandidateDerivation(CandidateKey('S013', 'C8880'), parent.content_sha256,
        CandidateKey('S013', identifier), identity.content_sha256, CandidateDerivationKind.IMPLEMENTATION,
        {'management_policy': {'before': 'original_immediate_regime_exit', 'after': label}},
        contract.method_reference.sha256, CandidateEvidence(parent_ref.repository_path, parent_ref.sha256))
    return ctx.evaluation.prepare(replace(old, experiment_id=contract.experiment.experiment_id,
        strategy=strategy, runtime_binding={'candidate_id': strategy.reference_id,
            'source_files': list(strategy.payload['runtime']['source_files']),
            'implementation_sha256': strategy.payload['runtime']['source_sha256']},
        execution_data=old.execution_data, input_bindings={}, lineage=EvaluationLineage(lineage)))


def declaration(contract):
    state = journal(contract)
    if state['status'] != 'NEW' or (contract.work / 'prepared.pkl.gz').exists():
        raise RuntimeError('Declaration is immutable; use subsequent explicit stages')
    ctx = context(contract)
    old = authenticate_baseline(ctx, contract)
    records = {'B0': old}
    for label, key in (('N_LOCK', 'lock_center'), ('N_CURRENT', 'current_center')):
        records[label] = {'center_request': implementation_request(ctx, contract, old['center'][0], old['center_reference'],
            label, contract.method['reservation'][key])}
    save_native(contract.work / 'prepared.pkl.gz', records)
    state.update(status='DECLARED', reused_native_unique=33, records_reference=material(ctx, contract,
        'management-prepared-centers', {'status': 'PREPARED_NOT_EVALUATED',
            'prepared_cache_sha256': file_hash(contract.work / 'prepared.pkl.gz'), 'centers': {
            label: {
                'candidate_id': record['center_request'].strategy.candidate_id,
                'content_sha256': ctx.runtime.identify(record['center_request'].strategy,
                    dependencies=record['center_request'].dependencies).content_sha256,
                'input_bindings': {k: v.to_dict() for k, v in record['center_request'].input_bindings.items()}}
            for label, record in records.items() if label != 'B0'},
            'method_reference': contract.method_reference.to_dict()}).to_dict())
    checkpoint(contract, state)
    return state


def records(contract):
    manifest = read(evidence(journal(contract)['records_reference']).resolve(ROOT))
    path = contract.work / 'prepared.pkl.gz'
    if file_hash(path) != manifest['prepared_cache_sha256']:
        raise ValueError('Prepared request cache differs from prospective public manifest')
    return read_native(path)


def point_plans(contract):
    manifest = read(evidence(journal(contract)['point_plans_reference']).resolve(ROOT))
    path = contract.work / 'point_plans.pkl.gz'
    if file_hash(path) != manifest['prepared_cache_sha256']:
        raise ValueError('All declared point requests/plans cache differs from public manifest')
    return read_native(path)


def center_results(ctx, contract, state, prepared):
    result = {'B0': (prepared['B0']['center'], prepared['B0']['center_reference'], prepared['B0']['center_audit'])}
    for label in LABELS[1:]:
        item = state['accounts'].get(label)
        if item is None or item['status'] != 'COMPLETE':
            raise RuntimeError('Both complete centers, including failures of economics, are required')
        result[label] = reuse_account(ctx, contract, item)
    return result


def preflight(contract):
    prepared, state = records(contract), journal(contract)
    if state['status'] not in ('DECLARED', 'CENTER_PREFLIGHT_PASS'):
        raise RuntimeError('Failed/unknown stage cannot proceed or retry')
    serial, spawn = context(contract, 1), context(contract, 8)
    _, audit, _, _ = capabilities()
    for label in LABELS[1:]:
        first = execute_one(serial, contract, state, prepared[label]['center_request'], label)
        second = execute_one(spawn, contract, state, prepared[label]['center_request'], label + '-technical-spawn')
        audit.exact_serial_spawn(first[0], second[0])
    state['status'] = 'CENTER_PREFLIGHT_PASS'
    checkpoint(contract, state)
    return state


def declare_points(ctx, contract, prepared, centers, label):
    draft, _, _, _ = capabilities()
    pair, center_ref, audited = centers[label]
    gates = audited['economics']['gates']
    identifiers = tuple(contract.method['reservation']['lock_points' if label == 'N_LOCK' else 'current_points'])
    mapping, feasibility = evidence(contract.method['mapping_reference']), evidence(contract.method['feasibility_reference'])
    blueprint = draft.parameter_draft(label, pair[0], gates, identifiers,
        content_sha256=audited['content_sha256'], mapping_sha256=mapping.sha256, feasibility_sha256=feasibility.sha256)
    if blueprint['status'] == 'NOT_APPLICABLE':
        return {'status': 'NOT_APPLICABLE', 'new_parameter_evaluations': 0}
    # Rebind child to the explicitly declared immutable formal source root,
    # not the prototype source path used by the pure blueprint generator.
    children = tuple(ctx.evaluation.prepare(replace(req,
        strategy=StrategyCandidate('S013', req.strategy.candidate_id, dict(req.strategy.payload), pair[0].strategy.source_root),
        execution_data=pair[0].execution_data)) for req in blueprint['children'])
    plan = ParameterEvaluationPlan.create(blueprint['design'], pair[0], children,
        mapping_evidence=mapping, feasibility_evidence=feasibility, dataflows=ctx.data)
    ref = material(ctx, contract, label + '-parameter-plan', plan.to_dict())
    bound = []
    p, _ = draft.metadata()
    for i, child in enumerate(children):
        changes = {c.name: {'before': draft.get(p, c.name), 'after': draft.get(child.strategy.payload['parameters'], c.name)}
            for c in plan.design.space.coordinates if draft.get(p, c.name) != draft.get(child.strategy.payload['parameters'], c.name)}
        derive = CandidateDerivation(CandidateKey('S013', pair[0].strategy.candidate_id), audited['content_sha256'],
            CandidateKey('S013', child.strategy.candidate_id), ctx.runtime.identify(child.strategy, dependencies=child.dependencies).content_sha256,
            CandidateDerivationKind.PARAMETERS, changes, draft.PROTOCOL.sha256,
            CandidateEvidence(center_ref.repository_path, center_ref.sha256))
        bound.append(replace(child, lineage=EvaluationLineage(derive, plan.bind_point(ref, i, repository_root=ROOT))))
    return {'status': 'DECLARED', 'children': tuple(bound), 'plan': plan, 'plan_reference': ref,
            'baseline_pairing': draft.pairing_status(prepared['B0']['plan'].design, plan.design)}


def execute_batch(ctx, contract, state, requests, labels):
    pending = [(req, label) for req, label in zip(requests, labels, strict=True) if label not in state['accounts']]
    for label in labels:
        if label in state['accounts'] and state['accounts'][label]['status'] != 'COMPLETE':
            raise RuntimeError('Uncertain/failed batch task cannot be financially retried')
    if not pending:
        return
    begin(contract, state, tuple(label for _, label in pending))
    try:
        outcomes = ctx.evaluation.evaluate_many(tuple(req for req, _ in pending))
    except Exception as error:
        state['status'] = 'FAILED'
        state['dispatch_failure'] = {'type': type(error).__name__, 'message': str(error)}
        checkpoint(contract, state)
        raise
    failures = []
    if len(outcomes) != len(pending):
        raise RuntimeError('Incomplete dispatch outcomes; INFLIGHT preserved, no rerun')
    for (req, label), outcome in zip(pending, outcomes, strict=True):
        try:
            if outcome.status.value != 'SUCCEEDED':
                raise RuntimeError(str(outcome.error))
            retain(ctx, contract, state, label, req, outcome.result)
        except Exception as error:
            state['accounts'][label].update(status='FAILED', failure={'type': type(error).__name__, 'message': str(error)})
            failures.append(label)
    if failures:
        state['status'] = 'FAILED'
        checkpoint(contract, state)
        raise RuntimeError('Terminal failures retained with all available complete natives: ' + ','.join(failures))


def run(contract):
    state, prepared = journal(contract), records(contract)
    if state['status'] not in ('CENTER_PREFLIGHT_PASS', 'STANDARD_ACCOUNTS_COMPLETE'):
        raise RuntimeError('Both serial/spawn technical checks must pass; failures cannot proceed')
    ctx = context(contract, 8)
    centers = center_results(ctx, contract, state, prepared)
    point_file = contract.work / 'point_plans.pkl.gz'
    if not point_file.exists():
        if any('-P' in label for label in state['accounts']):
            raise RuntimeError('Missing declared point artifacts after financial start requires explicit successor recovery')
        plans = {label: declare_points(ctx, contract, prepared, centers, label) for label in LABELS[1:]}
        save_native(point_file, plans)  # All public point plans frozen before point finance.
        state['point_plans_reference'] = material(ctx, contract, 'management-all-point-plans', {
            'prepared_cache_sha256': file_hash(point_file), 'plans': {
                label: {'status': plan['status'], 'reference': None if plan['status'] == 'NOT_APPLICABLE'
                    else plan['plan_reference'].to_dict()} for label, plan in plans.items()}}).to_dict()
        checkpoint(contract, state)
    plans = point_plans(contract)
    _, audit, _, _ = capabilities()
    for label, plan in plans.items():
        if plan['status'] == 'NOT_APPLICABLE':
            continue
        first = execute_one(context(contract), contract, state, plan['children'][0], label + '-P00')
        repeated = execute_one(ctx, contract, state, plan['children'][0], label + '-P00-technical-spawn')
        audit.exact_serial_spawn(first[0], repeated[0])
        for start in range(1, 32, 8):
            stop = min(start + 8, 32)
            execute_batch(ctx, contract, state, plan['children'][start:stop], tuple(f'{label}-P{i:02}' for i in range(start, stop)))
    state['status'] = 'STANDARD_ACCOUNTS_COMPLETE'
    checkpoint(contract, state)
    return state


def panels(ctx, contract):
    prepared, state = records(contract), journal(contract)
    centers = center_results(ctx, contract, state, prepared)
    plans = point_plans(contract)
    result = {'B0': (centers['B0'], tuple(zip(prepared['B0']['points'], prepared['B0']['point_references'], prepared['B0']['point_audits'], strict=True)), prepared['B0']['plan'])}
    for label in LABELS[1:]:
        plan = plans[label]
        points = () if plan['status'] == 'NOT_APPLICABLE' else tuple(
            reuse_account(ctx, contract, state['accounts'][f'{label}-P{i:02}']) for i in range(32))
        result[label] = centers[label], points, None if not points else plan['plan']
    return result


def analyze(contract):
    if journal(contract)['status'] != 'STANDARD_ACCOUNTS_COMPLETE':
        raise RuntimeError('All declared native accounts required before analysis')
    ctx = context(contract)
    draft, _, _, _ = capabilities()
    rows, comparisons, summaries = {}, {}, []
    native_panels = panels(ctx, contract)
    for label, (center, points, plan) in native_panels.items():
        econ = center[2]['economics']
        summary = {'q10_cagr': None, 'q90_drawdown': None, 'joint_pass_count': None}
        if points:
            summary = draft.summarize(econ['net_cagr'], econ['drawdown'],
                [p[2]['economics']['net_cagr'] for p in points], [p[2]['economics']['drawdown'] for p in points],
                [tuple(p[2]['economics']['gates'][g] for g in draft.GATES) for p in points])
        rows[label] = {'center_economics': econ, 'parameter_summary': summary,
            'center_reference': center[1].to_dict(), 'parameter_references': [p[1].to_dict() for p in points]}
        summaries.append(draft.Summary(label, tuple(econ['gates'][g] for g in draft.GATES),
            econ['net_cagr'], econ['drawdown'], summary['q10_cagr'], summary['q90_drawdown'], summary['joint_pass_count']))
        if label != 'B0' and points:
            pairing = draft.pairing_status(native_panels['B0'][2].design, plan.design)
            comparisons[label] = {'pairing': pairing}
            if pairing['status'] == 'EXACT_NUMERIC_PAIRING':
                comparisons[label]['paired_points'] = [{'index': i,
                    'cagr_difference': p[2]['economics']['net_cagr'] - b[2]['economics']['net_cagr'],
                    'drawdown_difference': p[2]['economics']['drawdown'] - b[2]['economics']['drawdown']}
                    for i, (p, b) in enumerate(zip(points, native_panels['B0'][1], strict=True))]
    output = {'status': 'COMPLETE', 'rows': rows, 'selection': draft.selection(tuple(summaries)),
              'mechanism_comparisons': comparisons, 'center_qualification': 'only original four gates',
              'same_market_development_pool': True, 'objective_achieved': False,
              'limits': 'Point pairing compares two complete native mechanism accounts. No deleted-trade profit projection, out-of-sample assertion or automatic goal completion.'}
    write(contract.work / 'analysis.json', output)
    return output


def selfchecks(contract):
    ctx = context(contract)
    draft, _, checks, _ = capabilities()
    analysis = read(contract.work / 'analysis.json')
    native_panels = panels(ctx, contract)
    state, output = journal(contract), {}
    if state['status'] != 'STANDARD_ACCOUNTS_COMPLETE':
        raise RuntimeError('Failed/unknown financial state cannot run pressure accounts')
    for label in analysis['selection']['fivecheck_labels']:
        center, points, plan = native_panels[label]
        expected = replace(draft.pressure_request(center[0][0]), experiment_id=contract.experiment.experiment_id)
        if label == 'B0' and contract.method.get('baseline_fee_reuse') is not None:
            stress = reuse_account(ctx, contract, contract.method['baseline_fee_reuse'])
            # Old fee request experiment/derivation may differ, but all business/data/source bindings must match.
            old = stress[0][0]
            if replace(old, experiment_id=expected.experiment_id, lineage=expected.lineage) != expected:
                raise ValueError('Old B0 fee account is not exact declared source/numbers/inputs/fees')
        else:
            stress = execute_one(ctx, contract, state, expected, 'fee-stress-' + label)
        result = checks.assess_native(center=checks.NativeEvaluation(*center[0]),
            points=tuple(checks.NativeEvaluation(*p[0]) for p in points), design=plan.design,
            stress=checks.NativeEvaluation(*stress[0]))
        output[label] = {'panel': result.panel.to_dict(), 'economics': result.economics,
                         'limitations': result.limitations, 'fee_reference': stress[1].to_dict(),
                         'diagnostic_only': True, 'center_economic_gate_unchanged': True}
    write(contract.work / 'selfchecks.json', output)
    return output


def closeout(contract):
    state, analysis = journal(contract), read(contract.work / 'analysis.json')
    selfcheck = read(contract.work / 'selfchecks.json')
    if any(a['status'] != 'COMPLETE' for a in state['accounts'].values()):
        raise RuntimeError('Incomplete/failed accounts remain failure evidence, not successful closeout')
    qualified = [label for label in LABELS[1:] if analysis['rows'][label]['center_economics']['qualified']]
    result = {'status': 'NATIVE_EVIDENCE_BUNDLE_COMPLETE', 'method_reference': contract.method_reference.to_dict(),
        'analysis': analysis, 'fivechecks': selfcheck, 'new_actual_evaluations': state['attempts'],
        'all_new_native_accounts': state['accounts'], 'qualified_registration_candidates': qualified,
        'account_audits': {label: read(contract.work / 'audits' / (label + '.json')) for label in state['accounts']},
        'candidate_registry_written': False, 'candidate_set_assembled': False, 'archive_validated': False,
        'objective_achieved': False,
        'remaining_formal_delivery': 'Root explicitly registers only original-four-gate qualified candidates; creates CandidateSet and formal archive validation using public APIs. This runner does not claim FULL acceptance.'}
    result['public_bundle_reference'] = material(context(contract), contract, 'management-native-bundle', result).to_dict()
    write(contract.work / 'closeout.json', result)
    return result


def freeze_draft():
    draft, _, _, _ = capabilities()
    parameters = expected_parameters(draft)
    return {'status': 'SOURCE_ONLY_EXECUTION_DRAFT', 'authorization': None,
        'provider_revision': REVISION, 'policies': list(LABELS), 'policy_parameters': parameters,
        'runner_source_files': {n: file_hash(HERE / n) for n in ('runner.py', 'prepared_audit.py')},
        'new_account_preparations': 0, 'new_account_evaluations': 0, 'provider_calls': [],
        'maximum_new_business_standard': 66, 'maximum_new_actual_including_technical_and_fees': 72,
        'required_root_bindings': ['experiment_id', 'collision-checked reservation66', 'source_roots',
            'external_source_files', 'collision_reference', 'input_primer_reference', 'baseline_reuse33',
            'mapping_reference', 'feasibility_reference', 'pinned_inputs copied from public subset primer',
            'optional exact baseline_fee_reuse', 'public execution method reference'],
        'supports': ['public prepare/evaluate/evaluate_many', 'terminal native journal', 'full native caches and public refs',
            'public source/data/request/formal serialization identity', 'original cash audit', 'independent prepared features/state',
            'serial/spawn center and P00 repeat', 'four-gate conditional full32', 'actual-vector exact pairing',
            'five diagnostics and at-most-one preferred new fee stress'],
        'not_implemented': ['candidate registration / CandidateSet assembly / full archive validation; root formal delivery remains explicit'],
        'limits': 'No collision allocation, financial execution, prepared input authentication, financial outcome or new experiment has occurred by freezing this draft.'}


def root_template():
    """Non-executable field scaffold. Every null/public reference is filled by root later."""
    draft, _, _, bridge = capabilities()
    external = {}
    manifests = (*bridge.PINS, '.tmp/s013-management-bridge/freeze.json')
    for relative in manifests:
        path = ROOT / relative
        external[relative] = file_hash(path)
        for name, digest in read(path)['frozen_files'].items():
            external[(path.parent / name).relative_to(ROOT).as_posix()] = digest
    for path in (EX058 / 'src/common.py', EX058 / 'src/account_reference.py',
                 ROOT / 'research/S013/experiments/EX062_20261011/src/robust_center_draft.py'):
        external[path.relative_to(ROOT).as_posix()] = file_hash(path)
    def native_item(candidate_id, cache_path):
        return {'candidate_id': candidate_id, 'cache_path': cache_path, 'cache_sha256': None,
                'reference': None, 'content_sha256': None, 'request_hash': None, 'result_hash': None}
    return {'status': 'PROSPECTIVE_TEMPLATE_NOT_EXECUTABLE', 'authorization': None,
        'required_authorization_after_root_decision': AUTHORIZATION,
        'experiment_id': None, 'provider_revision': REVISION, 'policies': list(LABELS),
        'policy_parameters': expected_parameters(draft),
        'runner_source_files': {name: file_hash(HERE / name) for name in ('runner.py', 'prepared_audit.py')},
        'external_source_files': external,
        'reservation': {'lock_center': None, 'current_center': None, 'lock_points': [None] * 32, 'current_points': [None] * 32},
        'source_roots': {'B0': 'research/S013/experiments/EX058_20261011/src/strategy_runtime',
                         'N_LOCK': None, 'N_CURRENT': None},
        'source_root_notes': 'Root supplies immutable formal roots. N_LOCK six-file closure exact EX058; N_CURRENT seven-file prototype closure exact. IDs not allocated/declared by draft.',
        'collision_reference': None, 'input_primer_reference': None,
        'pinned_inputs': {}, 'pinned_input_record_schema': {
            'key': 'canonical_sha256(binding.plan.to_dict()[requests][role])',
            'value': {'request': 'complete public request dictionary',
                      'identity': 'dataset/source/symbol/data_start/data_cutoff/content_sha256/metadata',
                      'space_id': 'actual public PreparedDataRef space UUID'}},
        'baseline_reuse': {
            'center': native_item('C8880', '.tmp/s013-mechanism-EX058/N0.pkl.gz'),
            'plan_reference': None,
            'points': [dict(native_item(f'C{8840 + i:04}',
                '.tmp/s013-mechanism-EX058/parameters/N0/<EX058-original-native-row-label>.pkl.gz'),
                point_index=i) for i in range(32)]},
        'baseline_fee_reuse': None,
        'fee_reuse_note': 'Optional exact previously authenticated EX062 baseline fee account: same native_item fields, SHA before decode, full serialization and source/inputs/parameters/cost reconciliation after decode. No EX062 outcome has been read by draft author.',
        'mapping_reference': None, 'feasibility_reference': None,
        'scope': 'Fixed original center numbers and complete original13 domain/32/.05/seed13/HALF_EVEN. No optimizer or parameter reselection.',
        'cli': {stage: f'.venv/Scripts/python.exe .tmp/s013-management-runner/runner.py {stage}'
            + ('' if stage == 'freeze-draft' else ' --method-reference <root-public-bare-EvidenceRef-json> --work .tmp/<root-selected-work-directory>')
            for stage in ('freeze-draft', 'declaration', 'preflight', 'run', 'analyze', 'selfchecks', 'closeout')},
        'ordered_execution': ['root experiment/ID collision checks/source freeze/input primer/public method first',
            'declaration (authenticate old33; prepare only2centers)',
            'preflight (both centers serial and spawn; actual4)',
            'run (qualifying centers full32, P00duplicate and31 batch; plans public before finance)',
            'analyze (all three rows, exact typed-coordinate pairings)',
            'selfchecks (B0 and at most one preferred new center; 0..2 new fee natives)',
            'closeout (native evidence bundle only; root separately registers/assembles/archives)'],
        'failure_policy': 'Terminal FAILED/INFLIGHT/unknown accounts retained. No retry, replacement or external fallback. Artifact-only successor recovery requires separately reviewed/root-declared correction.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('freeze-draft', 'declaration', 'preflight', 'run', 'analyze', 'selfchecks', 'closeout'))
    parser.add_argument('--method-reference')
    parser.add_argument('--work')
    args = parser.parse_args()
    if args.stage == 'freeze-draft':
        write(HERE / 'method_draft.json', freeze_draft())
        write(HERE / 'prospective_method_template.json', root_template())
        print('SOURCE_ONLY_EXECUTION_DRAFT')
        return
    if not args.method_reference or not args.work:
        parser.error('Future public method reference and explicit .tmp work directory required')
    contract = require_method(args.method_reference, args.work)
    print(json.dumps(globals()[args.stage](contract), allow_nan=False))


if __name__ == '__main__':
    # Give the trusted cache reducer one stable import name across CLI stages.
    sys.modules['runner'] = sys.modules[__name__]
    restore_mapping.__module__ = 'runner'
    main()
