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
        assert origin.startswith(('EX012_', 'EX013_', 'EX014_', 'EX015_', 'EX020_')), origin
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


def prepare_required(ctx, request, label):
    """Persist an explicit failure; never substitute inputs or download warmup."""
    try:
        return ctx.evaluation.prepare(request)
    except Exception as error:
        write(RUNS / 'parameter_preparation_failure.json', {
            'status': 'FAILED', 'phase': 'parameter_declaration_prepare', 'label': label,
            'error_type': type(error).__name__, 'message': str(error),
            'required_warmup': 'max(original warmup, confirmation.lookback + 21)',
            'provider_calls': list(SOURCE_CALLS),
            'policy': 'Existing authorized S013 assets only; no fallback, download, shortened warmup, point replacement or automatic retry.'})
        raise RuntimeError('FAILED parameter preparation for ' + label + ': ' + str(error)) from error


def select_new_centers(experiment, analysis):
    """If either same-length aggregator qualifies, evaluate both for contrast."""
    configurations = {config['label']: config for config in experiment['configurations']}
    assert set(configurations) == {'N0', 'N1'}
    qualified = {label for label in configurations if analysis['rows'][label]['qualified']}
    if not qualified:
        return []
    return [configurations[label] for label in ('N0', 'N1')]


def declare(first_candidate):
    assert not MANIFEST.exists(), 'Parameter plans already declared'
    assert not (RUNS / 'parameter_preparation_failure.json').exists(), 'Prior preparation FAILED retained; explicit technical audit required before retry'
    source_check()
    geometry = read(PROTOCOLS / 'geometry.json')
    geometry_ref = EvidenceRef.from_dict(read(PROTOCOLS / 'geometry_reference.json'))
    assert read(geometry_ref.resolve(ROOT)) == geometry
    analysis = read(RUNS / 'analysis.json')
    assert analysis['status'] == 'PASS'
    experiment = read(PROTOCOLS / 'plan.json')
    selected_new = select_new_centers(experiment, analysis)
    if not selected_new:
        output = {'status': 'NOT_APPLICABLE', 'reason': 'NO_NEW_FOUR_GATE_QUALIFIED_CONFIGURATION',
                  'geometry': geometry_ref.to_dict(), 'new_parameter_accounts': 0,
                  'new_parameter_business_accounts': 0, 'reused_parameter_accounts': 0,
                  'actual_parameter_evaluations': 0, 'unqualified_control_keys': [],
                  'qualified_flags': {label: row['qualified'] for label, row in analysis['rows'].items()}}
        output['reference'] = publish_material(context(1), 'parameter-not-applicable', output).to_dict()
        write(MANIFEST, output)
        print({'parameters': 'NOT_APPLICABLE', 'new_parameter_accounts': 0}, flush=True)
        return
    assert [x[0] for x in geometry['coordinates']] == [
        'bull.range_window', 'bull.entry', 'bull.exit', 'bull.max_hold',
        'bear.range_window', 'bear.entry', 'bear.exit', 'bear.max_hold', 'bear.acf_min',
        'regime_window', 'regime_threshold', 'confirmation.lookback', 'confirmation.threshold']
    ctx = context(8)
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
    selected = [original, *selected_new]
    for config in selected_new:
        assert [get_path(config['payload']['parameters'], name) for name, *_ in geometry['coordinates']] == [
            get_path(original['payload']['parameters'], name) for name, *_ in geometry['coordinates']]
    assert first_candidate == 8704, 'EX028 prospectively reserved C8704..C8767'
    matched_design = None
    number = first_candidate
    for config in selected:
        center, result = resolve_center(config)
        center_ref = EvidenceRef.from_dict(center_refs[config['label']])
        formal = read(center_ref.resolve(ROOT))
        validate_evaluation_evidence(formal)
        assert serialize_evaluation_evidence(center, result) == formal
        assert plain(center.strategy.payload) == config['payload']
        center = prepare_required(ctx, center, config['label'] + '-CENTER')
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
        if config['label'] == 'B0-TIME':
            prior_root=ROOT/'research/S013'
            origin='EX015_20261011'
            manifest_name='parameter_plans.json'
            previous=read(prior_root/'experiments'/origin/'protocols'/manifest_name)
            record=next(row for row in previous['centers'] if row['label']==config['label'])
            previous_cache=ROOT/'.tmp'/('s013-mechanism-'+origin[:5])/'parameters'
            transport=next(row for row in cache_read(previous_cache/'prepared.pkl.gz') if row['label']==config['label'])
            old_design=transport['plan'].design
            assert old_design.protocol==design.protocol and old_design.center==design.center
            assert old_design.space.coordinates==design.space.coordinates and old_design.points==design.points
            assert record['center_reference']==center_ref.to_dict()
            previous_matrix=read(prior_root/'assets/runs'/origin/'parameter_matrix.json')
            old_rows=sorted((row for row in previous_matrix['rows'] if row['center']==config['label']),
                            key=lambda row:row['point_index'])
            assert len(old_rows)==32 and sorted(row['point_index'] for row in old_rows)==list(range(32))
            for row in old_rows:
                ref=EvidenceRef.from_dict(row['reference'])
                assert sha256(ref.resolve(ROOT).read_bytes()).hexdigest()==ref.sha256
                old_bound,old_result=cache_read(previous_cache/(row['label']+'.pkl.gz'))
                assert old_result.request_hash==row['request_hash'] and old_result.result_hash==row['result_hash']
                assert old_bound.lineage.parameter_binding.point==old_design.bind_point(row['point_index'])
                formal_point = read(ref.resolve(ROOT))
                validate_evaluation_evidence(formal_point)
                assert serialize_evaluation_evidence(old_bound, old_result) == formal_point
                assert old_result.runs[0].identity.content_sha256 == row['content_sha256']
                cache_write(TRANSPORT/(row['label']+'.pkl.gz'),(old_bound,old_result))
                reused_rows.append({**row,'reused':True,'reused_from':origin,'actual_this_experiment':False})
                identities.add(row['content_sha256'])
            records.append({**record,'reused':True,'reused_from':origin,
                            'role':'original bull H8/bear H4 TIME baseline; all 13 coordinates and 32 points exactly matched',
                            'center_qualified':analysis['rows'][config['label']]['qualified']})
            prepared.append(transport)
            matched_design = old_design
            print({'reused_original_parameter_accounts':32,'center':config['label'],'source_ids_and_bindings':'PRESERVED'},flush=True)
            continue
        assert matched_design is not None
        assert matched_design.protocol == design.protocol
        assert matched_design.space.coordinates == design.space.coordinates
        assert matched_design.points == design.points
        children, configs = [], []
        for point in design.points:
            assert number <= 8767
            identifier = f'C{number:04}'
            number += 1
            assert not (ROOT / 'research/S013/assets/candidates' / identifier).exists(), identifier
            assert not (ROOT / 'research/registrations/S013/candidates' / (identifier + '.json')).exists(), identifier
            payload = plain(center.strategy.payload)
            payload['parameters'] = materialize(parameters, geometry, point.coordinates)
            child = StrategyCandidate('S013', identifier, payload, center.strategy.source_root)
            child_request = replace(center, experiment_id=EXPERIMENT.experiment_id, strategy=child,
                runtime_binding={**center.runtime_binding, 'candidate_id': child.reference_id},
                input_bindings={}, lineage=None)
            child_request = prepare_required(ctx, child_request, config['label'] + f'-P{point.index:02}')
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
            bound.append(prepare_required(ctx, replace(child, lineage=EvaluationLineage(derivation, binding)), child_config['label'] + '-BOUND'))
        records.append({'label': config['label'], 'candidate_id': center.strategy.candidate_id,
            'mechanism': config['mechanism'], 'background': config['background'],
            'center_qualified': analysis['rows'][config['label']]['qualified'],
            'role': (('qualified new bear ACF deviation from lagged ' if analysis['rows'][config['label']]['qualified'] else
                      'unqualified symmetric bear ACF deviation from lagged ') +
                     {'N0': 'MEDIAN', 'N1': 'MEAN'}[config['label']] +
                     (' center' if analysis['rows'][config['label']]['qualified'] else
                      ' exact-coordinate diagnostic control; not promoted')),
            'fixed_aggregation': {'N0': 'MEDIAN', 'N1': 'MEAN'}[config['label']],
            'reference_window_coordinate': 'confirmation.lookback',
            'acf_gate_units': 'current ACF20 minus preceding L-ACF20 median/mean; same ACF units, >= original bear.acf_min',
            'matched_control': 'B0-TIME',
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
        'selection': 'If either new lagged-reference ACF deviation center qualifies, evaluate both at all 32 points; the unqualified median/mean reference is a prospectively declared symmetric diagnostic control only, never promoted or registered. Original B0-TIME EX015 32 points exactly reused. B0-SHORT_MEDIAN and B0-SHORT_MEAN remain center-only with no parameter supplements.',
        'matched_comparison': 'Every evaluated new center versus B0-TIME, plus N0 lagged MEDIAN versus N1 lagged MEAN to isolate reference aggregation statistics at the same L. All 13 numerical centers and all 32 point coordinates exactly match across these comparisons.',
        'original_comparison': 'Original bull H8/bear H4 and both new centers share the same complete domains, protocol, all 13 numeric centers and every 32-point coordinate. Bear ACF gate input becomes current ACF20 minus lagged median/mean of preceding L estimates, in original ACF units. Original confirmation.lookback also becomes L, introducing shared-coordinate coupling with confirmation normalization; no new numeric knob or timer change.',
        'warmup_policy': 'Require max(original warmup, confirmation.lookback + 21) from existing authorized S013 assets. Missing prepared coverage explicitly FAILED, never download, truncate, fill or replace points.',
        'qualified_new_centers': [config['label'] for config in selected_new if analysis['rows'][config['label']]['qualified']],
        'evaluated_new_centers': [config['label'] for config in selected_new],
        'diagnostic_control_centers': [config['label'] for config in selected_new if not analysis['rows'][config['label']]['qualified']],
        'unqualified_control_keys': [config['label'] for config in selected_new if not analysis['rows'][config['label']]['qualified']],
        'qualified_flags': {label: row['qualified'] for label, row in analysis['rows'].items()},
        'historical_comparison': geometry['difference_from_historical']}
    assert len(reused_rows) == 32
    assert document['new_parameter_business_accounts'] == 32 * len(selected_new)
    document['reference'] = publish_material(ctx, 'parameter-plan-manifest', document).to_dict()
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
    assert not (RUNS / 'parameter_precheck.json').exists()
    source_check()
    rows = []
    actual_evaluations = 0
    for center in cache_read(TRANSPORT / 'prepared.pkl.gz'):
        record=next(row for row in manifest['centers'] if row['label']==center['label'])
        if record.get('reused'):
            proof=read(ROOT/'research/S013/assets/runs'/record['reused_from']/'parameter_precheck.json')
            assert proof['status']=='PASS'
            proof_ref = EvidenceRef.from_dict(proof['reference'])
            assert file_hash(proof_ref.resolve(ROOT)) == proof_ref.sha256
            assert read(proof_ref.resolve(ROOT)) == {key: value for key, value in proof.items() if key != 'reference'}
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
    assert actual_evaluations == 2 * (len(manifest['centers']) - 1)
    proof['reference'] = publish_material(context(1), 'parameter-precheck', proof).to_dict()
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
        study = optuna.create_study(direction='maximize', study_name='S013-EX028-fixed-parameter-diagnostic',
                                   sampler=optuna.samplers.RandomSampler(seed=13))
        for index in range(len(items)):
            study.enqueue_trial({'point': index})
        for index in range(len(items)):
            trial = study.ask()
            assert trial.suggest_int('point', 0, len(items) - 1) == index
        reused_rows=manifest['reused_rows']
        assert len(reused_rows) == 32
        assert [row['point_index'] for row in reused_rows] == list(range(32))
        assert all(row['center'] == 'B0-TIME' for row in reused_rows)
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
    assert state['status'] == 'COMPLETE'
    assert state['actual_run_evaluations'] == 31 * (len(manifest['centers']) - 1)
    state['new_parameter_business_accounts'] = manifest['new_parameter_business_accounts']
    state['reused_parameter_accounts'] = 32
    state['actual_parameter_evaluations'] = state['actual_run_evaluations'] + read(RUNS / 'parameter_precheck.json')['actual_evaluations']
    assert state['actual_parameter_evaluations'] == 33 * (len(manifest['centers']) - 1)
    state['reference'] = publish_material(ctx, 'parameter-complete-matrix', state).to_dict()
    write(CHECKPOINT, state)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('declare', 'precheck', 'run'))
    parser.add_argument('--first-candidate', type=int, default=8704)
    args = parser.parse_args()
    if args.phase == 'declare':
        declare(args.first_candidate)
    elif args.phase == 'precheck':
        precheck()
    else:
        run()


if __name__ == '__main__':
    main()
