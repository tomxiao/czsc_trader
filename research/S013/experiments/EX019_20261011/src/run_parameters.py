"""Prospective public parameter plans, causal account precheck and fixed queues."""
# ruff: noqa: E402
import os

for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[variable] = '1'

import argparse
from copy import deepcopy
from dataclasses import replace
import json
from hashlib import sha256
import time

import optuna
import pandas as pd
from strategy_evaluator import (
    AssessmentCandidate, ParameterCoordinate, ParameterCoordinateKind,
    ParameterDesignRequest, ParameterPerturbationProtocol, ParameterSpace,
    build_parameter_perturbation_design,
)
from strategy_manager import CandidateDerivation, CandidateDerivationKind, CandidateEvidence, CandidateKey
from strategy_runtime import StrategyCandidate, canonical_sha256
from czsc_trader.application import publish_evidence, publish_evidence_many
from czsc_trader.research_tools import (
    EvaluationEvidenceWrite, EvaluationLineage, MaterialEvidenceWrite, ParameterEvaluationPlan,
)
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence
from common import (
    CACHE, EXPERIMENT, PROTOCOLS, ROOT, RUNS, SOURCE_CALLS, SRC,
    cache_read, cache_write, context, file_hash, read, write,
)

TRANSPORT = CACHE / 'parameters'
MANIFEST = PROTOCOLS / 'parameter_plans.json'
INITIAL_MANIFEST = MANIFEST
CONTROL_MANIFEST = PROTOCOLS / 'parameter_plans_with_control.json'
CHECKPOINT = RUNS / 'parameter_matrix.json'


def plain(value):
    return json.loads(json.dumps(value, default=dict, allow_nan=False))


def publish_material(ctx, name, value):
    return publish_evidence(ctx, MaterialEvidenceWrite(
        EXPERIMENT, name, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode(),
        'application/json', 'json'))


def get_path(parameters, name):
    target = parameters
    for part in name.split('.'):
        target = target[part]
    return target


def materialize(parameters, geometry, values):
    parameters = deepcopy(parameters)
    for (name, _, _, kind), value in zip(geometry['coordinates'], values, strict=True):
        parts = name.split('.')
        target = parameters
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = int(value) if kind == 'INTEGER' else float(value)
    return parameters


def feasible(coordinates):
    # Exact order is authenticated by the already published geometry.
    return bool(coordinates[1] < coordinates[2] and coordinates[5] < coordinates[6])


def resolve_center(config, experiment_id=EXPERIMENT.experiment_id):
    """Follow declared S013 control reuse; do not assume a display label has a cache."""
    if config.get('reused'):
        origin = config['reuse_from']
        assert origin.startswith(('EX012_', 'EX013_', 'EX014_', 'EX015_')), origin
        actual_cache = ROOT / '.tmp' / ('s013-mechanism-' + origin[:5]) / (config['reuse_label'] + '.pkl.gz')
        if actual_cache.exists():
            return cache_read(actual_cache)
        plan = read(ROOT / f'research/S013/experiments/{origin}/protocols/plan.json')
        original = next(x for x in plan.get('controls', []) + plan['configurations']
                        if x.get('label', x.get('background', '') + '-' + x.get('mode', '')) == config['reuse_label'])
        return resolve_center(original, origin)
    folder = ROOT / '.tmp' / ('s013-mechanism-' + experiment_id[:5])
    return cache_read(folder / (config['label'] + '.pkl.gz'))


def source_check():
    for relative, digest in read(PROTOCOLS / 'plan.json')['source_files'].items():
        assert file_hash(SRC / relative) == digest


def declare(first_candidate, matched_control=False):
    assert not MANIFEST.exists(), 'Parameter plans already declared'
    source_check()
    geometry = read(PROTOCOLS / 'geometry.json')
    geometry_ref = EvidenceRef.from_dict(read(PROTOCOLS / 'geometry_reference.json'))
    assert read(geometry_ref.resolve(ROOT)) == geometry
    analysis = read(RUNS / 'analysis.json')
    assert analysis['status'] == 'PASS'
    experiment = read(PROTOCOLS / 'plan.json')
    qualified = [x for x in experiment['configurations'] if analysis['rows'][x['label']]['qualified']]
    if not qualified:
        output = {'status': 'NOT_APPLICABLE', 'reason': 'NO_NEW_FOUR_GATE_QUALIFIED_CONFIGURATION',
                  'geometry': geometry_ref.to_dict(), 'new_parameter_accounts': 0}
        output['reference'] = publish_material(context(1), 'parameter-not-applicable', output).to_dict()
        write(MANIFEST, output)
        print({'parameters': 'NOT_APPLICABLE', 'new_parameter_accounts': 0}, flush=True)
        return
    assert [x[0] for x in geometry['coordinates']] == [
        'bull.range_window', 'bull.entry', 'bull.exit', 'bull.max_hold',
        'bear.range_window', 'bear.entry', 'bear.exit', 'bear.max_hold', 'bear.acf_min',
        'regime_window', 'regime_threshold', 'confirmation.lookback', 'confirmation.threshold']
    ctx = context(8)
    initial=read(INITIAL_MANIFEST) if matched_control else None
    if matched_control:
        assert initial['status']=='DECLARED' and not CHECKPOINT.exists()
        mapping=EvidenceRef.from_dict(initial['mapping'])
        feasibility=EvidenceRef.from_dict(initial['feasibility'])
    else:
        mapping = publish_material(ctx, 'parameter-coordinate-mapping', {
            'geometry': geometry_ref.to_dict(), 'ordered_coordinates': geometry['coordinates'],
            'mapping': geometry['mapping'], 'fixed_or_categorical': geometry['fixed_or_categorical']})
        feasibility = publish_material(ctx, 'parameter-coordinate-feasibility', {
            'geometry': geometry_ref.to_dict(), 'predicate': geometry['feasibility'],
            'indices': {'bull_entry': 1, 'bull_exit': 2, 'bear_entry': 5, 'bear_exit': 6},
            'no_outcome_filter': True})
    protocol = ParameterPerturbationProtocol(**geometry['protocol'])
    center_refs = read(RUNS / 'account_references.json')
    original = next(x for x in experiment['controls'] if x['label'] == 'B0-TIME')
    records, prepared, identities, reused_rows = [], [], set(), []
    selected=[original,next(row for row in experiment['controls'] if row['label']=='B2-TIME'),*qualified]
    if matched_control:
        records=list(initial['centers'])
        prepared=list(cache_read(TRANSPORT/'prepared.pkl.gz'))
        reused_rows=list(initial['reused_rows'])
        identities={child['content_sha256'] for row in records for child in row['children']}
        selected=[next(row for row in experiment['controls'] if row['label']=='B2-TIME')]
    number = first_candidate
    for config in selected:
        center, result = resolve_center(config)
        center_ref = EvidenceRef.from_dict(center_refs[config['label']])
        formal = read(center_ref.resolve(ROOT))
        validate_evaluation_evidence(formal)
        assert serialize_evaluation_evidence(center, result) == formal
        assert plain(center.strategy.payload) == config['payload']
        center = ctx.evaluation.prepare(center)
        actual = ctx.runtime.identify(center.strategy, dependencies=center.dependencies)
        assert actual.content_sha256 == config['content_sha256']
        central = AssessmentCandidate(center.strategy.reference_id, actual.content_sha256)
        parameters = plain(center.strategy.payload['parameters'])
        space = ParameterSpace(tuple(ParameterCoordinate(
            name, float(get_path(parameters, name)), lower, upper, ParameterCoordinateKind(kind))
            for name, lower, upper, kind in geometry['coordinates']), mapping.sha256, feasibility.sha256)
        design_result = build_parameter_perturbation_design(
            ParameterDesignRequest(central, protocol, space), feasibility=feasible)
        assert design_result.status.value == 'COMPLETE', design_result.to_dict()
        design = design_result.design
        if config['label'] in ('B0-TIME','B2-TIME'):
            prior_root=ROOT/'research/S013'
            origin='EX015_20261011' if config['label']=='B0-TIME' else 'EX017_20261011'
            manifest_name='parameter_plans.json' if config['label']=='B0-TIME' else 'parameter_plans_with_control.json'
            previous=read(prior_root/'experiments'/origin/'protocols'/manifest_name)
            record=next(row for row in previous['centers'] if row['label']==config['label'])
            previous_cache=ROOT/'.tmp'/('s013-mechanism-'+origin[:5])/'parameters'
            transport=next(row for row in cache_read(previous_cache/'prepared.pkl.gz') if row['label']==config['label'])
            old_design=transport['plan'].design
            assert old_design.protocol==design.protocol and old_design.center==design.center
            assert old_design.space.coordinates==design.space.coordinates and old_design.points==design.points
            assert record['center_reference']==center_ref.to_dict()
            previous_matrix=read(prior_root/'assets/runs'/origin/'parameter_matrix.json')
            old_rows=[row for row in previous_matrix['rows'] if row['center']==config['label']]
            assert len(old_rows)==32 and sorted(row['point_index'] for row in old_rows)==list(range(32))
            for row in old_rows:
                ref=EvidenceRef.from_dict(row['reference'])
                assert sha256(ref.resolve(ROOT).read_bytes()).hexdigest()==ref.sha256
                old_bound,old_result=cache_read(previous_cache/(row['label']+'.pkl.gz'))
                assert old_result.request_hash==row['request_hash'] and old_result.result_hash==row['result_hash']
                assert old_bound.lineage.parameter_binding.point==old_design.bind_point(row['point_index'])
                cache_write(TRANSPORT/(row['label']+'.pkl.gz'),(old_bound,old_result))
                reused_rows.append({**row,'reused':True,'reused_from':origin,'actual_this_experiment':False})
                identities.add(row['content_sha256'])
            records.append({**record,'reused':True,'reused_from':origin})
            prepared.append(transport)
            print({'reused_original_parameter_accounts':32,'center':config['label'],'source_ids_and_bindings':'PRESERVED'},flush=True)
            continue
        children, configs = [], []
        for point in design.points:
            assert number <= 9999
            identifier = f'C{number:04}'
            number += 1
            assert not (ROOT / 'research/S013/assets/candidates' / identifier).exists(), identifier
            payload = plain(center.strategy.payload)
            payload['parameters'] = materialize(parameters, geometry, point.coordinates)
            child = StrategyCandidate('S013', identifier, payload, center.strategy.source_root)
            child_request = replace(center, experiment_id=EXPERIMENT.experiment_id, strategy=child,
                runtime_binding={**center.runtime_binding, 'candidate_id': child.reference_id},
                input_bindings={}, lineage=None)
            child_request = ctx.evaluation.prepare(child_request)
            children.append(child_request)
            child_identity = ctx.runtime.identify(child, dependencies=child_request.dependencies)
            assert child_identity.source_sha256 == actual.source_sha256
            assert child_identity.content_sha256 not in identities
            identities.add(child_identity.content_sha256)
            changes = {name: {'before': get_path(parameters, name),
                             'after': get_path(payload['parameters'], name)}
                       for name, *_ in geometry['coordinates']
                       if get_path(parameters, name) != get_path(payload['parameters'], name)}
            configs.append({'label': config['label'] + f'-P{point.index:02}',
                            'candidate_id': identifier, 'changes': changes,
                            'content_sha256': child_identity.content_sha256})
        plan = ParameterEvaluationPlan.create(design, center, tuple(children),
            mapping_evidence=mapping, feasibility_evidence=feasibility, dataflows=ctx.data)
        plan_ref = publish_material(ctx, 'parameter-plan-' + config['label'].lower(), plan.to_dict())
        bound = []
        for index, (child, child_config) in enumerate(zip(children, configs, strict=True)):
            derivation = CandidateDerivation(CandidateKey('S013', center.strategy.candidate_id),
                central.content_sha256, CandidateKey('S013', child.strategy.candidate_id),
                plan.children[index].candidate.content_sha256, CandidateDerivationKind.PARAMETERS,
                child_config['changes'], protocol.sha256,
                CandidateEvidence(center_ref.repository_path, center_ref.sha256))
            binding = plan.bind_point(plan_ref, index, repository_root=ROOT)
            bound.append(ctx.evaluation.prepare(replace(child, lineage=EvaluationLineage(derivation, binding))))
        records.append({'label': config['label'], 'candidate_id': center.strategy.candidate_id,
            'mechanism': config['mechanism'], 'background': config['background'],
            'center_reference': center_ref.to_dict(), 'plan_reference': plan_ref.to_dict(),
            'design': design.to_dict(), 'children': configs,
            'center_request_sha256': plan.center_request_sha256})
        prepared.append({'label': config['label'], 'center': center, 'result': result,
                         'children': tuple(bound), 'plan': plan})
        print({'declared_center': config['label'], 'points': 32, 'attempts': design.attempts}, flush=True)
    assert not SOURCE_CALLS
    cache_write(TRANSPORT / 'prepared.pkl.gz', tuple(prepared))
    document = {'status': 'DECLARED', 'geometry': geometry_ref.to_dict(),
        'mapping': mapping.to_dict(), 'feasibility': feasibility.to_dict(),
        'analysis_sha256': file_hash(RUNS / 'analysis.json'), 'centers': records,
        'point_count': 32 * len(records), 'resources': {'max_workers': 8, 'native_threads': 1, 'seed': 13},
        'reused_rows':reused_rows,'reused_parameter_accounts':len(reused_rows),
        'new_parameter_business_accounts':32*len(records)-len(reused_rows),
        'selection': 'Original H4 and unqualified H3 diagnostic controls, plus every new four-gate-qualified configuration; no neighbor performance filtering',
        'historical_comparison': geometry['difference_from_historical']}
    if matched_control:
        document.update(initial_manifest=initial['reference'],
            supplementary_control={'center':'B2-TIME','role':'unqualified H3 matched numeric-coordinate mechanism control',
                'rationale':'Only N2 qualified at H3. Separate effect of entry confirmation from changing original H4 to H3.',
                'timing':'Declared after N2 representative technical precheck, before any bulk parameter evaluation or viewing parameter metrics.',
                'not_qualification':'Not registered or promoted as a qualified candidate; all original economic criteria remain.'})
    document['reference'] = publish_material(ctx, 'parameter-plan-manifest-with-control' if matched_control else 'parameter-plan-manifest', document).to_dict()
    write(MANIFEST, document)


def equal_results(serial, spawned):
    assert serial.result_hash == spawned.result_hash
    for left, right in zip(serial.runs, spawned.runs, strict=True):
        pd.testing.assert_frame_equal(left.signals.decisions, right.signals.decisions, check_exact=True)
        for a, b in ((left.execution, right.execution), (left.buyhold.execution, right.buyhold.execution)):
            for field in ('decisions', 'orders', 'fills', 'account_daily', 'trades'):
                pd.testing.assert_frame_equal(getattr(a, field), getattr(b, field), check_exact=True)


def precheck():
    manifest = read(MANIFEST)
    if manifest['status'] == 'NOT_APPLICABLE':
        return
    initial_proof=read(RUNS/'parameter_precheck.json') if MANIFEST==CONTROL_MANIFEST else None
    if initial_proof is None:
        assert not (RUNS / 'parameter_precheck.json').exists()
    else:
        assert initial_proof['status']=='PASS'
        write(RUNS/'parameter_precheck_initial.json',initial_proof)
    source_check()
    rows = [] if initial_proof is None else list(initial_proof['rows'])
    actual_evaluations=0 if initial_proof is None else initial_proof['actual_evaluations']
    for center in cache_read(TRANSPORT / 'prepared.pkl.gz'):
        if any(row['center']==center['label'] for row in rows):
            continue
        record=next(row for row in manifest['centers'] if row['label']==center['label'])
        if record.get('reused'):
            proof=read(ROOT/'research/S013/assets/runs'/record['reused_from']/'parameter_precheck.json')
            assert proof['status']=='PASS'
            previous=next(row for row in proof['rows'] if row['center']==center['label'])
            rows.append({**previous,'reused':True,'source_reference':proof['reference']})
            continue
        bound = center['children'][0]
        serial = context(1).evaluation.evaluate(bound)
        cache_write(TRANSPORT / (center['label'] + '-P00.pkl.gz'), (bound, serial))
        spawned = context(2).evaluation.evaluate_many((bound,))[0]
        assert spawned.status.value == 'SUCCEEDED', spawned.error
        cache_write(TRANSPORT / (center['label'] + '-P00-spawn.pkl.gz'), (bound, spawned.result))
        equal_results(serial, spawned.result)
        actual_evaluations+=2
        rows.append({'center': center['label'], 'point': 0, 'result_hash': serial.result_hash,
                     'serial_spawn': 'EXACT_EQUAL signals and five strategy/benchmark ledgers'})
        print({'parameter_precheck': center['label'], 'status': 'PASS'}, flush=True)
    assert not SOURCE_CALLS
    proof = {'status': 'PASS', 'rows': rows, 'actual_evaluations': actual_evaluations, 'provider_calls': SOURCE_CALLS}
    if initial_proof is not None:
        proof['prior_reference']=initial_proof['reference']
    proof['reference'] = publish_material(context(1), 'parameter-precheck-with-control' if MANIFEST==CONTROL_MANIFEST else 'parameter-precheck', proof).to_dict()
    write(RUNS / 'parameter_precheck.json', proof)


def run():
    manifest = read(MANIFEST)
    if manifest['status'] == 'NOT_APPLICABLE':
        return
    assert read(RUNS / 'parameter_precheck.json')['status'] == 'PASS'
    source_check()
    ctx = context(8)
    prepared = cache_read(TRANSPORT / 'prepared.pkl.gz')
    items = [(record, cfg, bound) for record, transport in zip(manifest['centers'], prepared, strict=True)
             for cfg, bound in zip(record['children'], transport['children'], strict=True)]
    study_path = TRANSPORT / 'study.pkl.gz'
    if study_path.exists():
        study = cache_read(study_path)
        state = read(CHECKPOINT)
        assert all(x['status'] == 'SUCCEEDED' for x in state['rows']), 'Explicit failures require researcher decision'
        assert state.get('inflight') is None, 'Unfinished batch requires explicit technical audit before retry'
    else:
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study = optuna.create_study(direction='maximize', study_name='S013-EX019-fixed-parameter-diagnostic',
                                   sampler=optuna.samplers.RandomSampler(seed=13))
        for index in range(len(items)):
            study.enqueue_trial({'point': index})
        for index in range(len(items)):
            trial = study.ask()
            assert trial.suggest_int('point', 0, len(items) - 1) == index
        reused_rows=manifest['reused_rows']
        assert [row['point_index'] for row in reused_rows]==list(range(32))*2
        for index,row in enumerate(reused_rows):
            result=cache_read(TRANSPORT/(row['label']+'.pkl.gz'))[1]
            study.tell(index,float(result.runs[0].observation.net_cagr))
        state = {'status': 'PARTIAL', 'rows': reused_rows, 'inflight': None, 'actual_run_evaluations': 0,
                 'planned_business_accounts': len(items), 'provider_calls': []}
        cache_write(study_path, study)
        write(CHECKPOINT, state)
    started = time.perf_counter()
    for offset in range(len(state['rows']), len(items), 8):
        batch = items[offset:offset + 8]
        pending = [(record, cfg, bound) for record, cfg, bound in batch
                   if not (TRANSPORT / (cfg['label'] + '.pkl.gz')).exists()]
        state['inflight'] = [cfg['label'] for _, cfg, _ in pending]
        state['actual_run_evaluations'] += len(pending)
        write(CHECKPOINT, state)
        outcomes = ctx.evaluation.evaluate_many(tuple(bound for _, _, bound in pending)) if pending else ()
        failures = []
        for (_, cfg, bound), outcome in zip(pending, outcomes, strict=True):
            if outcome.status.value == 'SUCCEEDED':
                cache_write(TRANSPORT / (cfg['label'] + '.pkl.gz'), (bound, outcome.result))
            else:
                failures.append({'label': cfg['label'], 'status': outcome.status.value,
                                 'error': {'code': outcome.error.code, 'message': outcome.error.message}})
        if failures:
            state.update(status='FAILED', failures=failures, inflight=None)
            write(CHECKPOINT, state)
            raise RuntimeError('Parameter failures retained; no automatic substitution or retry')
        requests, loaded = [], []
        for record, cfg, expected in batch:
            bound, result = cache_read(TRANSPORT / (cfg['label'] + '.pkl.gz'))
            assert canonical_sha256(bound.lineage.derivation.to_dict()) == canonical_sha256(expected.lineage.derivation.to_dict())
            assert result.runs[0].identity.content_sha256 == cfg['content_sha256']
            loaded.append((record, cfg, bound, result))
            requests.append(EvaluationEvidenceWrite(EXPERIMENT, 'parameter-account-' + cfg['label'].lower(), bound, result))
        published = publish_evidence_many(ctx, tuple(requests))
        assert all(x.status.value == 'PUBLISHED' for x in published), [(x.status, x.error) for x in published]
        for index, ((record, cfg, bound, result), outcome) in enumerate(zip(loaded, published, strict=True), start=offset):
            study.tell(index, float(result.runs[0].observation.net_cagr))
            state['rows'].append({'label': cfg['label'], 'center': record['label'], 'point_index': index % 32,
                'candidate_id': cfg['candidate_id'], 'content_sha256': cfg['content_sha256'], 'status': 'SUCCEEDED',
                'reference': outcome.reference.to_dict(), 'request_hash': result.request_hash, 'result_hash': result.result_hash})
        state.update(status='COMPLETE' if len(state['rows']) == len(items) else 'PARTIAL', inflight=None,
                     elapsed_seconds=time.perf_counter() - started, provider_calls=SOURCE_CALLS)
        cache_write(study_path, study)
        write(CHECKPOINT, state)
        print({'parameter_accounts': len(state['rows']), 'planned': len(items), 'status': state['status']}, flush=True)
    assert not SOURCE_CALLS
    state['reference'] = publish_material(ctx, 'parameter-complete-matrix', state).to_dict()
    write(CHECKPOINT, state)


def main():
    global MANIFEST
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('declare', 'precheck', 'run'))
    parser.add_argument('--first-candidate', type=int, default=9000)
    parser.add_argument('--matched-control',action='store_true')
    args = parser.parse_args()
    if args.matched_control:
        MANIFEST=CONTROL_MANIFEST
    if args.phase == 'declare':
        declare(args.first_candidate,args.matched_control)
    elif args.phase == 'precheck':
        precheck()
    else:
        run()


if __name__ == '__main__':
    main()
