"""Run all three approved EX050 parameter neighborhoods under the migrated V4 contract."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from functools import lru_cache
import json
from multiprocessing import get_context
import os
from time import perf_counter

import assess as ex
import validate_v4_migration as migration
from czsc_trader.application import publish_evidence_many
from czsc_trader.research_tools.equity_evaluation import EquityArtifact, EquityEvaluationResult
from strategy_evaluator import CandidatePerformanceAssessmentRequest
from strategy_runtime import EquityStrategyDefinition, StrategyPerformanceBudget


ROOT, WORK, core = migration.ROOT, migration.WORK, migration.core
EXP = migration.EXPERIMENT
OUT = WORK / 'others/v4_parameter_selfcheck'
SCRATCH = ROOT / '.tmp/s019-v4-parameter-selfcheck'
RUN_ID = 'ex050-v4-full-parameter-sensitivity'
BATCH_SIZE = 24


def candidate(candidate_id, definition, expected_hash):
    result = core.EquityStrategyCandidate('S019', candidate_id, definition, migration.SOURCE)
    if result.implementation_hash != expected_hash or definition.source_sha256 != migration.SOURCE_HASH:
        raise ValueError('migrated strategy identity differs from the validated manifest')
    return result


def publish_material(context, execution, name, value):
    return core.publish_evidence(context, ex.d.MaterialEvidenceWrite(EXP, name, core.encoded(value),
                                'application/json', 'json'), execution=execution)


def prepare_group(context, execution, row, children):
    original = row['original_id']
    definition = EquityStrategyDefinition.from_dict(row['definition'])
    center = candidate(row['new_id'], definition, row['new_content_sha256'])
    center_handle = context.evaluation.prepare(migration.previous.request_for(EXP, center), execution=execution)
    original_design = ex.m.ParameterNeighborhoodDesign.from_dict(ex.read(WORK / f'protocols/{original}_design.json'))
    if original_design.center.content_sha256 != row['original_content_sha256'] or len(children) != original_design.point_count:
        raise ValueError('migrated jobs differ from the approved neighborhood')

    mapping = ex.read(WORK / f'protocols/{original}_mapping.json')
    mapping.update(center_id=center.candidate_id, content_hash=center.implementation_hash,
                   migrated_from=original_design.center.to_dict(), approved_design_sha256=original_design.sha256)
    feasibility = ex.read(WORK / f'protocols/{original}_feasibility.json')
    mapping_ref = publish_material(context, execution, f'v4-param-{original}-mapping', mapping)
    feasibility_ref = publish_material(context, execution, f'v4-param-{original}-feasibility', feasibility)
    space = replace(original_design.space, mapping_sha256=mapping_ref.sha256, feasibility_sha256=feasibility_ref.sha256)
    design = replace(original_design, center=ex.m.AssessmentCandidate(f'S019-{center.candidate_id}', center.implementation_hash),
                     space=space)
    handles = []
    for job, point in zip(children, design.points, strict=True):
        if job['point'] != f'{original}_P{point.index:03}' or job['parameters'] != {v.name: v.value for v in point.values}:
            raise ValueError('migrated parameters or order differ from the approved point')
        child_definition = replace(definition, parameters_json=migration.canonical(job['parameters']).decode())
        child = candidate(job['new_id'], child_definition, job['new_content_sha256'])
        handles.append(context.evaluation.prepare(migration.previous.request_for(EXP, child), execution=execution))
    plan = ex.d.ParameterEvaluationPlan.create(design, center_handle, tuple(handles),
        mapping_evidence=mapping_ref, feasibility_evidence=feasibility_ref, dataflows=context.data, execution=execution)
    plan_ref = publish_material(context, execution, f'v4-param-{original}-plan', plan.to_dict())
    jobs = [(f'{original}_CENTER', center_handle)]
    jobs.extend((job['point'], plan.bind_point(plan_ref, index, handle, execution=execution))
                for index, (job, handle) in enumerate(zip(children, handles, strict=True)))
    return {'design': design.to_dict(), 'plan': plan_ref.to_dict()}, jobs


def load_scope():
    manifest = ex.read(migration.MANIFEST)
    validation = ex.read(migration.MANIFEST.with_name('budget_validation.json'))
    if (manifest['migration_source_sha256'] != migration.SOURCE_HASH
            or validation['migration_source_sha256'] != migration.SOURCE_HASH
            or validation['manifest_sha256'] != core.digest(migration.MANIFEST) or validation['status'] != 'PASS'):
        raise ValueError('migration source and budget acceptance identities differ')
    if len(manifest['points']) != sum(ex.COUNTS.values()):
        raise ValueError('migration does not cover the complete approved grid')
    return manifest, validation['budget']


def save_progress(state):
    core.save(OUT / 'progress.json', state, SCRATCH)


def run_accounts(manifest, budget, *, resume):
    manifest_digest = core.digest(migration.MANIFEST)
    progress_path = OUT / 'progress.json'
    if resume != progress_path.exists():
        raise ValueError('resume mode must match the presence of a prior progress record')
    state = ex.read(progress_path) if resume else {
        'migration_manifest_sha256': manifest_digest, 'budget': budget, 'checkpoint': RUN_ID,
        'accounts': {}, 'errors': {}, 'batches': [], 'attempts': [], 'expected_accounts': 1701,
    }
    if (state['migration_manifest_sha256'], state['budget'], state['checkpoint']) != (manifest_digest, budget, RUN_ID):
        raise ValueError('saved execution identity differs from the migrated scope')
    started = perf_counter()
    if state.get('status') in ('ACCOUNTS_COMPLETE', 'COMPLETE'):
        return state
    repository = core.RepositoryContext.discover(ROOT, explicit_root=ROOT)
    definition = EquityStrategyDefinition.from_dict(manifest['centers'][0]['definition'])
    base = core.replay_context(repository, definition.execution_spec)
    context = replace(base, evaluation=core.EvaluationAccess(dataflows=base.data,
        strategy_id=base.strategy_id, execution_spec=base.execution_spec))
    if context.repository.root != ROOT or context.data.binding.base_dir != ROOT:
        raise ValueError('formal evidence context does not match the S019 repository')
    mode = ex.d.CheckpointMode.RESUME if resume else ex.d.CheckpointMode.CREATE
    checkpoint = ex.d.ExecutionCheckpointRequest(RUN_ID, mode)
    with ex.d.ResearchExecutionSession(context, experiment=EXP, checkpoint=checkpoint,
            performance_budget=StrategyPerformanceBudget(max_seconds_per_1000_calls=budget)) as execution:
        state['status'] = 'PREPARING'
        save_progress(state)
        plans, all_jobs = {}, []
        for row in manifest['centers']:
            cid = row['original_id']
            children = [item for item in manifest['points'] if item['point'].startswith(cid + '_')]
            plans[cid], jobs = prepare_group(context, execution, row, children)
            all_jobs.extend(jobs)
            print(f'PLAN {cid} {len(children)} {perf_counter() - started:.1f}s', flush=True)
        if len(all_jobs) != state['expected_accounts']:
            raise ValueError('formal workload differs from the approved scope')
        core.immutable(OUT / 'plans.json', plans, SCRATCH)
        pending = []
        for label, handle in all_jobs:
            if label not in state['accounts']:
                pending.append((label, handle))
                continue
            _, content = ex.bytes_for(state['accounts'][label])
            header = json.loads(content)
            if header['request_hash'] != migration.digest(handle.contract_content):
                raise ValueError(f'published account differs from prepared request: {label}')
        state['status'] = 'REPLAYING'
        save_progress(state)
        print(f'REPLAY_START pending={len(pending)} existing={len(state["accounts"])}', flush=True)
        for offset in range(0, len(pending), BATCH_SIZE):
            batch = pending[offset:offset + BATCH_SIZE]
            batch_start = perf_counter()
            outcomes = context.evaluation.evaluate_many(tuple(handle for _, handle in batch), execution=execution)
            evaluated = perf_counter()
            publish = []
            for (label, handle), result in zip(batch, outcomes, strict=True):
                if result.result is None:
                    state['errors'][label] = {'status': result.status.value, 'error': asdict(result.error)}
                else:
                    write = ex.d.EvaluationEvidenceWrite(EXP, f'v4-param-{label}', handle, result.result)
                    publish.append((label, write))
            if publish:
                publications = publish_evidence_many(context, tuple(write for _, write in publish), execution=execution)
                for (label, _), outcome in zip(publish, publications, strict=True):
                    if outcome.reference is None:
                        state['errors'][label] = {'status': outcome.status.value, 'error': asdict(outcome.error)}
                    else:
                        state['accounts'][label] = outcome.reference.to_dict()
                        state['errors'].pop(label, None)
            stats = execution.stats
            state['worker_limit'] = stats.worker_limit
            state['batches'].append({'attempt': len(state['attempts']) + 1,
                'first': batch[0][0], 'last': batch[-1][0], 'count': len(batch),
                'evaluate_seconds': evaluated - batch_start, 'publish_seconds': perf_counter() - evaluated})
            save_progress(state)
            print(f'REPLAY {len(state["accounts"])}/{state["expected_accounts"]} '
                  f'failed={len(state["errors"])} workers={stats.worker_limit} '
                  f'batch={perf_counter() - batch_start:.1f}s last={batch[-1][0]}', flush=True)
        state['attempts'].append({'seconds': perf_counter() - started, 'execution_stats': asdict(execution.stats),
                                  'equity_statistics': asdict(execution.equity_statistics) if execution.equity_statistics else None})
        state['status'] = 'ACCOUNTS_COMPLETE' if len(state['accounts']) == state['expected_accounts'] else 'REPLAY_INCOMPLETE'
        save_progress(state)
    if state['status'] == 'REPLAY_INCOMPLETE':
        raise RuntimeError(f'{len(state["errors"])} accounts require explicit diagnosis before resume')
    return state


def artifact(directory, kind, digest):
    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('invalid account dependency digest')
    result = EquityArtifact(kind, (directory / (digest + '.json')).read_bytes())
    if result.sha256 != digest:
        raise ValueError('published dependency digest differs')
    return result


@lru_cache(maxsize=4)
def shared_artifact(directory, kind, digest):
    return artifact(directory, kind, digest)


def project_neighbor(item):
    label, pointer = item
    ref, content = ex.bytes_for(pointer)
    header = json.loads(content)
    directory = ref.resolve(ROOT).parent
    values = []
    for name in ('input_ref', 'candidate_ref', 'benchmark_ref'):
        dependency = header[name]
        load = artifact if name == 'candidate_ref' else shared_artifact
        values.append(load(directory, dependency['kind'], dependency['sha256']))
    result = EquityEvaluationResult(header['request_hash'], content, tuple(values))
    facts, = ex.build_equity_assessment(result, projection=ex.d.AssessmentProjection.PARAMETER_PERFORMANCE)
    return label, facts


def evaluate_sensitivity(state):
    started = perf_counter()
    if state['status'] == 'COMPLETE':
        return
    plans = ex.read(OUT / 'plans.json')
    accounts = state['accounts']
    designs = tuple(ex.m.ParameterNeighborhoodDesign.from_dict(row['design']) for row in plans.values())
    design_by_original = dict(zip(plans, designs, strict=True))
    centers = tuple(design.center for design in designs)
    standard = tuple(ex.fact(accounts[f'{cid}_CENTER'])[0] for cid in plans)
    if tuple(item.candidate for item in standard) != centers:
        raise ValueError('standard accounts differ from migrated centers')
    work = sorted((label, pointer) for label, pointer in accounts.items() if not label.endswith('_CENTER'))
    neighbors = []
    with ProcessPoolExecutor(max_workers=state['worker_limit'], mp_context=get_context('spawn')) as pool:
        for n, (label, facts) in enumerate(pool.map(project_neighbor, work), 1):
            cid, point = label.split('_')
            if facts.parent != design_by_original[cid].center or facts.parameter_point.point_index != int(point[1:]):
                raise ValueError('projected account identity or point differs from the approved plan')
            neighbors.append(facts)
            if n % 100 == 0 or n == len(work):
                print(f'PROJECT {n}/{len(work)} {perf_counter() - started:.1f}s', flush=True)
    links = tuple(ex.m.PerturbationLink(x.parent, x.candidate, 1., x.derivation_sha256, x.parameter_point) for x in neighbors)
    protocol = ex.m.NeighborhoodSelfCheckProtocol('s019-ex050-v4-parameter-sensitivity-v1',
        'FULL', 'STANDARD', 'STRESS', 252, 21, ex.m.QuantileMethod.LINEAR, 1, 10000, 21,
        20261110, 1e-8, designs[0].protocol, frequency_min_closed_cycles=3)
    baseline = ex.m.CandidateAssessmentRequest(centers, protocol, links, standard, parameter_designs=designs)
    request = CandidatePerformanceAssessmentRequest(baseline, tuple(neighbors))
    panel = ex.assess_candidates(request)
    targets = ex.target_set()
    parameter, = (target for target in targets.requirements if type(target) is ex.m.ParameterNeighborhoodTarget)
    comparison = ex.compare_candidates(ex.m.CandidateComparisonRequest(centers, replace(targets, requirements=(parameter,)),
        panel, ex.native_acceptance_policy()))
    rows = []
    by_center = {row.candidate: row for row in panel.rows}
    original_ids = {design.center: cid for cid, design in zip(plans, designs, strict=True)}
    for item in comparison.rows:
        checked, = item.target_checks
        if checked.valid_points != checked.required_points or checked.status is ex.m.TargetCheckStatus.INDETERMINATE:
            raise ValueError('parameter evidence coverage is incomplete')
        performances = by_center[item.candidate].parameter_performances
        defined_calmar = [point.annual_return / point.drawdown for point in performances if point.drawdown > 1e-12]
        rows.append({'original_id': original_ids[item.candidate], 'migrated_center': item.candidate.to_dict(),
            'status': checked.status.value, 'reason': checked.reason, 'points': checked.required_points,
            'joint_passes': checked.joint_passes, 'minimum_passes': checked.minimum_joint_passes,
            'pass_rate': checked.joint_passes / checked.required_points,
            'max_mdd': max(point.drawdown for point in performances),
            'min_nar': min(point.annual_return for point in performances),
            'min_calmar': min(defined_calmar) if defined_calmar else None,
            'check': checked.to_dict()})
        print('RESULT', rows[-1]['original_id'], rows[-1]['status'], rows[-1]['joint_passes'], rows[-1]['points'], flush=True)
    core.immutable(OUT / 'result.json', {'status': 'PARAMETER_SENSITIVITY_COMPLETE', 'rows': rows,
        'account_references': len(accounts), 'new_strategy_search_trials': 0, 'account_checkpoint': RUN_ID,
        'request_sha256': request.sha256, 'panel_sha256': panel.sha256, 'comparison_sha256': comparison.sha256,
        'plans_sha256': core.digest(OUT / 'plans.json'), 'targets_sha256': targets.sha256,
        'projection_and_assessment_seconds': perf_counter() - started}, SCRATCH)
    state['status'] = 'COMPLETE'
    save_progress(state)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    os.environ.update(TEMP=str(SCRATCH), TMP=str(SCRATCH), PYTHONDONTWRITEBYTECODE='1')
    migration_manifest, calibrated_budget = load_scope()
    evaluate_sensitivity(run_accounts(migration_manifest, calibrated_budget, resume=args.resume))
