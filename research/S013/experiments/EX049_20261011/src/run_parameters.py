"""EX049 prospective public three-center parameter comparison with exact native control reuse."""
# ruff: noqa: E402
import os
for variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[variable] = '1'
import argparse
from copy import deepcopy
from dataclasses import replace
import json
import time
import optuna
import pandas as pd
from strategy_evaluator import (
    AssessmentCandidate, ParameterCoordinate, ParameterCoordinateKind, ParameterDesignRequest,
    ParameterPerturbationProtocol, ParameterSpace, build_parameter_perturbation_design,
)
from strategy_manager import CandidateDerivation, CandidateDerivationKind, CandidateEvidence, CandidateKey
from strategy_runtime import StrategyCandidate, canonical_sha256
from czsc_trader.application import publish_evidence, publish_evidence_many
from czsc_trader.research_tools import EvaluationEvidenceWrite, EvaluationLineage, MaterialEvidenceWrite, ParameterEvaluationPlan
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence, validate_evaluation_evidence
from common import CACHE, EXPERIMENT, PROTOCOLS, ROOT, RUNS, SOURCE_CALLS, SRC, cache_read, cache_write, context, file_hash, read, write

TRANSPORT = CACHE / 'parameters'
MANIFEST = PROTOCOLS / 'parameter_plans.json'
CHECKPOINT = RUNS / 'parameter_matrix.json'
CONTROLS = ('B0-TIME', 'B0-COUPLED')
MECHANISM = 'MEAN_MOMENTUM3'
RESERVED_FIRST = 6440
RESERVED_LAST = 6471

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


def equal_results(serial, spawned):
    assert serial.result_hash == spawned.result_hash
    for left, right in zip(serial.runs, spawned.runs, strict=True):
        pd.testing.assert_frame_equal(left.signals.decisions, right.signals.decisions, check_exact=True)
        for a, b in ((left.execution, right.execution), (left.buyhold.execution, right.buyhold.execution)):
            for field in ('decisions', 'orders', 'fills', 'account_daily', 'trades'):
                pd.testing.assert_frame_equal(getattr(a, field), getattr(b, field), check_exact=True)


def source_check():
    experiment = read(PROTOCOLS / 'plan.json')
    reference = EvidenceRef.from_dict(read(PROTOCOLS / 'plan_reference.json'))
    assert reference.experiment == EXPERIMENT and file_hash(reference.resolve(ROOT)) == reference.sha256
    assert read(reference.resolve(ROOT)) == experiment
    for relative, digest in experiment['source_files'].items():
        assert file_hash(SRC / relative) == digest
    geometry = read(PROTOCOLS / 'geometry.json')
    reference = EvidenceRef.from_dict(read(PROTOCOLS / 'geometry_reference.json'))
    assert reference.experiment == EXPERIMENT and file_hash(reference.resolve(ROOT)) == reference.sha256
    assert read(reference.resolve(ROOT)) == geometry
    required = {'run_parameters.py', 'parameter_analysis.py', 'pair_parameters.py', 'declare_geometry.py',
                'common.py', 'account_reference.py', 'ledger_reference.py', 'analysis_reference.py'}
    assert set(geometry['helper_source_files']) == required
    for relative, digest in geometry['helper_source_files'].items():
        path = (SRC / relative).resolve()
        assert path.is_relative_to(SRC.resolve()) and file_hash(path) == digest
    assert file_hash(SRC / 'regime_oracle.py') == geometry['regime_oracle_sha256']
    legacy = geometry['legacy_direction_oracle']
    assert legacy['path'] == 'research/S013/experiments/EX043_20261011/src/direction_oracle.py'
    assert file_hash(ROOT / legacy['path']) == legacy['sha256']
    assert geometry['candidate_reservation'] == {'first': RESERVED_FIRST, 'last': RESERVED_LAST}
    return experiment, geometry


def resolve_center(config, experiment_id=EXPERIMENT.experiment_id, seen=None):
    seen = set() if seen is None else seen
    key = (experiment_id, config['label'])
    assert key not in seen, 'Cyclic native reuse chain'
    seen.add(key)
    if config.get('reused'):
        origin, label = config['reuse_from'], config['reuse_label']
        assert origin.startswith(('EX012_', 'EX013_', 'EX014_', 'EX015_', 'EX043_'))
        path = ROOT / '.tmp' / ('s013-mechanism-' + origin[:5]) / (label + '.pkl.gz')
        if path.exists():
            return cache_read(path)
        previous = read(ROOT / 'research/S013/experiments' / origin / 'protocols/plan.json')
        parent = next(row for row in previous.get('controls', []) + previous['configurations']
                      if row.get('label', row.get('background', '') + '-' + row.get('mode', '')) == label)
        assert parent['candidate_id'] == config['candidate_id'] and parent['payload'] == config['payload']
        assert parent['content_sha256'] == config['content_sha256']
        return resolve_center(parent, origin, seen)
    return cache_read(ROOT / '.tmp' / ('s013-mechanism-' + experiment_id[:5]) / (config['label'] + '.pkl.gz'))


def point_cache(control_key, native_label):
    assert control_key in (*CONTROLS, 'N0')
    assert native_label.startswith(('B0-TIME-P', 'N0-P')) and '/' not in native_label and '\\' not in native_label
    return TRANSPORT / control_key / (native_label + '.pkl.gz')


def select_new_centers(experiment, analysis):
    assert [row['label'] for row in experiment['controls']] == list(CONTROLS)
    assert [row['label'] for row in experiment['configurations']] == ['N0']
    config = experiment['configurations'][0]
    assert config['mechanism'] == MECHANISM and config['parent_control'] == 'B0-TIME'
    return [config] if analysis['rows']['N0']['qualified'] else []


def authenticate_center(ctx, config, reference, bound, result):
    ref = EvidenceRef.from_dict(reference)
    assert ref.experiment.strategy_id == 'S013' and file_hash(ref.resolve(ROOT)) == ref.sha256
    formal = read(ref.resolve(ROOT))
    validate_evaluation_evidence(formal)
    assert serialize_evaluation_evidence(bound, result) == formal
    assert plain(bound.strategy.payload) == config['payload'] and bound.strategy.candidate_id == config['candidate_id']
    identity = ctx.runtime.identify(bound.strategy, dependencies=bound.dependencies)
    assert identity.content_sha256 == config['content_sha256']
    assert identity.source_sha256 == config['payload']['runtime']['source_sha256']
    assert canonical_sha256(bound.runtime_binding) == result.runtime_binding_hash
    assert result.strategy_identity == bound.strategy.runtime_identity_sha256
    return ref, identity


def prepare_required(ctx, request, label):
    try:
        return ctx.evaluation.prepare(request)
    except Exception as error:
        write(RUNS / 'parameter_preparation_failure.json', {'status': 'FAILED', 'label': label,
            'error_type': type(error).__name__, 'message': str(error), 'provider_calls': list(SOURCE_CALLS),
            'policy': 'Existing prepared S013 assets only; bear-only two-day raw-bull exit confirmation requires W+2 prices plus unchanged original score/range/ACF dependencies. No fill, fallback, download, shortened warmup, point replacement or automatic retry.'})
        raise


def implementation_parent(ctx, experiment, refs, config):
    parent = next(row for row in experiment['controls'] if row['label'] == 'B0-TIME')
    bound, result = resolve_center(parent)
    reference, identity = authenticate_center(ctx, parent, refs['B0-TIME'], bound, result)
    assert parent['candidate_id'] == 'C2132'
    assert (ROOT / 'research/registrations/S013/candidates' / (parent['candidate_id'] + '.json')).is_file()
    old, new = deepcopy(parent['payload']['parameters']), deepcopy(config['payload']['parameters'])
    assert 'mechanism' not in old and new.pop('mechanism') == MECHANISM
    assert old == new, 'Only bear-held raw-bull regime exit gains fixed2 confirmation; all13 numeric centers unchanged'
    return {'control_key': 'B0-TIME', 'candidate_id': parent['candidate_id'],
        'content_sha256': identity.content_sha256, 'source_sha256': identity.source_sha256,
        'reference': reference.to_dict(), 'kind': 'IMPLEMENTATION',
        'scope': 'Registered original C2132 is the implementation parent. Only held-bear raw-bull regime exit requires current and previous complete daily rawbull. Original raw ACF20, score L, flat entry/rawroute, bull immediate rawbear exit and signal H remain.'}


def reuse_parameter_control(ctx, key, config, center_reference, design):
    origin, native_label, matrix_name = (
        ('EX015_20261011', 'B0-TIME', 'parameter_matrix.json') if key == 'B0-TIME' else
        ('EX043_20261011', 'N0', 'parameter_matrix_v3.json'))
    base = ROOT / 'research/S013'
    previous = read(base / 'experiments' / origin / 'protocols/parameter_plans.json')
    record = next(row for row in previous['centers'] if row['label'] == native_label)
    cache = ROOT / '.tmp' / ('s013-mechanism-' + origin[:5]) / 'parameters'
    transport = next(row for row in cache_read(cache / 'prepared.pkl.gz') if row['label'] == native_label)
    old_design = transport['plan'].design
    assert old_design.center == design.center and old_design.protocol == design.protocol
    assert old_design.space.coordinates == design.space.coordinates and old_design.points == design.points
    assert record['center_reference'] == center_reference
    matrix = read(base / 'assets/runs' / origin / matrix_name)
    assert matrix['status'] == 'COMPLETE'
    native_rows = sorted((row for row in matrix['rows'] if row['center'] == native_label), key=lambda row: row['point_index'])
    assert [row['point_index'] for row in native_rows] == list(range(32))
    rows = []
    for row in native_rows:
        bound, result = cache_read(cache / (row['label'] + '.pkl.gz'))
        ref = EvidenceRef.from_dict(row['reference'])
        assert file_hash(ref.resolve(ROOT)) == ref.sha256
        formal = read(ref.resolve(ROOT))
        validate_evaluation_evidence(formal)
        assert serialize_evaluation_evidence(bound, result) == formal
        assert bound.strategy.candidate_id == row['candidate_id'] and result.request_hash == row['request_hash']
        assert result.result_hash == row['result_hash'] and bound.dependencies == transport['center'].dependencies
        binding = bound.lineage.parameter_binding
        assert binding.point == old_design.bind_point(row['point_index'])
        assert binding.plan.to_dict() == record['plan_reference']
        assert file_hash(binding.plan.resolve(ROOT)) == binding.plan.sha256
        assert read(binding.plan.resolve(ROOT)) == transport['plan'].to_dict()
        identity = ctx.runtime.identify(bound.strategy, dependencies=bound.dependencies)
        assert identity.content_sha256 == row['content_sha256']
        assert identity.source_sha256 == config['payload']['runtime']['source_sha256']
        assert canonical_sha256(bound.runtime_binding) == result.runtime_binding_hash
        assert result.strategy_identity == bound.strategy.runtime_identity_sha256
        cache_write(point_cache(key, row['label']), (bound, result))
        rows.append({**deepcopy(row), 'control_key': key, 'reused': True,
                     'reused_from': origin, 'actual_this_experiment': False})
    return ({**deepcopy(record), 'control_key': key, 'native_label': native_label,
             'reused': True, 'reused_from': origin, 'center_qualified': True,
             'role': 'exact native ' + key + ' full32 control; original IDs/labels/plans/lineage preserved'},
            {**transport, 'control_key': key}, rows)


def declare(first_candidate=RESERVED_FIRST):
    assert not MANIFEST.exists() and not (RUNS / 'parameter_preparation_failure.json').exists()
    experiment, geometry = source_check()
    analysis = read(RUNS / 'analysis.json')
    assert analysis['status'] == 'PASS'
    selected = select_new_centers(experiment, analysis)
    flags = {label: row['qualified'] for label, row in analysis['rows'].items()}
    if not selected:
        output = {'status': 'NOT_APPLICABLE', 'reason': 'NO_NEW_FOUR_GATE_QUALIFIED_CONFIGURATION',
            'new_parameter_business_accounts': 0, 'reused_parameter_accounts': 0,
            'actual_parameter_evaluations': 0, 'planned_actual_parameter_evaluations': 0,
            'technical_duplicate_evaluations': 0, 'unqualified_control_keys': [], 'qualified_flags': flags}
        output['reference'] = publish_material(context(1), 'parameter-not-applicable', output).to_dict()
        write(MANIFEST, output)
        return
    assert first_candidate == RESERVED_FIRST
    assert all(analysis['rows'][key]['qualified'] for key in CONTROLS)
    ctx = context(8)
    geometry_ref = EvidenceRef.from_dict(read(PROTOCOLS / 'geometry_reference.json'))
    mapping = publish_material(ctx, 'parameter-coordinate-mapping', {'geometry': geometry_ref.to_dict(),
        'coordinates': geometry['coordinates'], 'mapping': geometry['mapping']})
    feasibility = publish_material(ctx, 'parameter-coordinate-feasibility', {'geometry': geometry_ref.to_dict(),
        'predicate': geometry['feasibility'], 'no_outcome_filter': True})
    protocol = ParameterPerturbationProtocol(**geometry['protocol'])
    refs = read(RUNS / 'account_references.json')
    records, prepared, reused_rows, identities = [], [], [], set()
    matched = None
    number = first_candidate
    for config in [*experiment['controls'], *selected]:
        key = config['label']
        center, result = resolve_center(config)
        center_ref, identity = authenticate_center(ctx, config, refs[key], center, result)
        parameters = plain(center.strategy.payload['parameters'])
        space = ParameterSpace(tuple(ParameterCoordinate(name, float(get_path(parameters, name)), low, high,
            ParameterCoordinateKind(kind)) for name, low, high, kind in geometry['coordinates']), mapping.sha256, feasibility.sha256)
        design_result = build_parameter_perturbation_design(ParameterDesignRequest(
            AssessmentCandidate(center.strategy.reference_id, identity.content_sha256), protocol, space), feasibility=feasible)
        assert design_result.status.value == 'COMPLETE', design_result.to_dict()
        design = design_result.design
        if matched is None:
            matched = design
        assert matched.space.coordinates == design.space.coordinates and matched.points == design.points
        if key in CONTROLS:
            record, transport, rows = reuse_parameter_control(ctx, key, config, center_ref.to_dict(), design)
            records.append(record)
            prepared.append(transport)
            reused_rows.extend(rows)
            identities.update(row['content_sha256'] for row in rows)
            continue
        assert key == 'N0' and config['mechanism'] == MECHANISM
        assert center.strategy.source_root.resolve() == (SRC / config['source_directory']).resolve()
        parent = implementation_parent(ctx, experiment, refs, config)
        children, configs = [], []
        for point in design.points:
            assert number <= RESERVED_LAST
            identifier = f'C{number:04}'
            number += 1
            assert not (ROOT / 'research/S013/assets/candidates' / identifier).exists()
            assert not (ROOT / 'research/registrations/S013/candidates' / (identifier + '.json')).exists()
            payload = plain(center.strategy.payload)
            payload['parameters'] = materialize(parameters, geometry, point.coordinates)
            child = StrategyCandidate('S013', identifier, payload, center.strategy.source_root)
            request = replace(center, experiment_id=EXPERIMENT.experiment_id, strategy=child,
                runtime_binding={**center.runtime_binding, 'candidate_id': child.reference_id}, input_bindings={}, lineage=None)
            request = prepare_required(ctx, request, f'N0-P{point.index:02}')
            child_identity = ctx.runtime.identify(child, dependencies=request.dependencies)
            assert child_identity.source_sha256 == identity.source_sha256 and child_identity.content_sha256 not in identities
            identities.add(child_identity.content_sha256)
            children.append(request)
            changes = {name: {'before': get_path(parameters, name), 'after': get_path(payload['parameters'], name)}
                for name, *_ in geometry['coordinates'] if get_path(parameters, name) != get_path(payload['parameters'], name)}
            configs.append({'label': f'N0-P{point.index:02}', 'point_index': point.index,
                'candidate_id': identifier, 'content_sha256': child_identity.content_sha256, 'changes': changes})
        plan = ParameterEvaluationPlan.create(design, center, tuple(children), mapping_evidence=mapping,
            feasibility_evidence=feasibility, dataflows=ctx.data)
        plan_ref = publish_material(ctx, 'parameter-plan-n0', plan.to_dict())
        bound = []
        for index, (child, cfg) in enumerate(zip(children, configs, strict=True)):
            derivation = CandidateDerivation(CandidateKey('S013', center.strategy.candidate_id), identity.content_sha256,
                CandidateKey('S013', child.strategy.candidate_id), plan.children[index].candidate.content_sha256,
                CandidateDerivationKind.PARAMETERS, cfg['changes'], protocol.sha256,
                CandidateEvidence(center_ref.repository_path, center_ref.sha256))
            binding = plan.bind_point(plan_ref, index, repository_root=ROOT)
            bound.append(prepare_required(ctx, replace(child, lineage=EvaluationLineage(derivation, binding)), cfg['label'] + '-BOUND'))
        records.append({'label': 'N0', 'control_key': 'N0', 'native_label': 'N0', 'reused': False,
            'candidate_id': center.strategy.candidate_id, 'mechanism': MECHANISM, 'background': config['background'],
            'center_qualified': True, 'role': 'qualified fixed2 confirmation for only bear-held raw-bull regime exit; raw entry/ACF20/score unchanged',
            'implementation_parent': parent, 'source_sha256': identity.source_sha256,
            'center_reference': center_ref.to_dict(), 'plan_reference': plan_ref.to_dict(),
            'design': design.to_dict(), 'children': configs, 'center_request_sha256': plan.center_request_sha256,
            'entry_direction_structure': 'No additional direction or category gate; original flat entry/rawroute/range/ACF20/score preserved.',
            'regime_exit_structure': 'Only held bear: current and previous complete daily rawstates must both be bull for regime exit. Held bull rawbear exits immediately. Previous rawstate includes pre-entry history; no holding-only reset.',
            'time_semantics': 'Original held-session H unchanged; loss>trailing>range>time>regime. Fixed2 confirmation never delays TIME.',
            'baseline_semantics': 'Original raw ACF20 entry gate; no centering, category context, smoothing or price gate. L remains active in original score; all13 coordinates remain active.'})
        prepared.append({'label': 'N0', 'control_key': 'N0', 'center': center, 'result': result,
            'children': tuple(bound), 'plan': plan})
    assert number == RESERVED_LAST + 1 and len(reused_rows) == 64 and not SOURCE_CALLS
    cache_write(TRANSPORT / 'prepared.pkl.gz', tuple(prepared))
    output = {'status': 'DECLARED', 'geometry': geometry_ref.to_dict(), 'centers': records,
        'mapping': mapping.to_dict(), 'feasibility': feasibility.to_dict(), 'reused_rows': deepcopy(reused_rows),
        'point_count': 96, 'new_parameter_business_accounts': 32, 'reused_parameter_accounts': 64,
        'planned_actual_parameter_evaluations': 33, 'technical_duplicate_evaluations': 1,
        'qualified_new_centers': ['N0'], 'unqualified_control_keys': [], 'qualified_flags': flags,
        'resources': {'max_workers': 8, 'native_threads': 1, 'seed': 13},
        'evaluation_count_basis': '64 exact old native controls reused without evaluation; new32business/33actual: P00serial+spawn2, remaining31bulk. Control aliases never replace native IDs/labels/lineage.',
        'historical_comparison': 'All13 original full domains/numeric centers/5%L2/PCG64seed13/HALF_EVEN/LINEAR32 coordinates identical. Original raw ACF versus fixed2 bear regime exit is a mechanism contrast; coupled MEAN L/BELOW reentry is an unchanged historical counterevidence cohort with disclosed structural differences; same coordinates do not prove robustness of categorical choices.',
        'selection': 'Only the new original-four-gate-qualified N0 receives32 new points. Controls are existing native identities only; no promotion/re-registration or new old-account evaluation.'}
    output['reference'] = publish_material(ctx, 'parameter-plan-manifest', output).to_dict()
    write(MANIFEST, output)


def precheck():
    source_check()
    manifest = read(MANIFEST)
    if manifest['status'] == 'NOT_APPLICABLE':
        return
    assert not (RUNS / 'parameter_precheck.json').exists()
    rows, actual = [], 0
    for record, transport in zip(manifest['centers'], cache_read(TRANSPORT / 'prepared.pkl.gz'), strict=True):
        key = record['control_key']
        assert key == transport['control_key']
        if record['reused']:
            proof = read(ROOT / 'research/S013/assets/runs' / record['reused_from'] / 'parameter_precheck.json')
            ref = EvidenceRef.from_dict(proof['reference'])
            assert proof['status'] == 'PASS' and file_hash(ref.resolve(ROOT)) == ref.sha256
            assert read(ref.resolve(ROOT)) == {name: value for name, value in proof.items() if name != 'reference'}
            native = next(row for row in proof['rows'] if row['center'] == record['native_label'])
            rows.append({**deepcopy(native), 'control_key': key, 'reused': True, 'source_reference': ref.to_dict()})
            continue
        bound = transport['children'][0]
        serial = context(1).evaluation.evaluate(bound)
        cache_write(point_cache(key, 'N0-P00'), (bound, serial))
        spawned = context(2).evaluation.evaluate_many((bound,))[0]
        assert spawned.status.value == 'SUCCEEDED', spawned.error
        cache_write(TRANSPORT / key / 'N0-P00-spawn.pkl.gz', (bound, spawned.result))
        equal_results(serial, spawned.result)
        actual += 2
        rows.append({'center': 'N0', 'control_key': key, 'point': 0, 'reused': False,
                     'result_hash': serial.result_hash, 'serial_spawn': 'EXACT_EQUAL signals and5strategy/benchmarkledgers'})
    assert actual == 2 and not SOURCE_CALLS
    proof = {'status': 'PASS', 'rows': rows, 'actual_evaluations': actual, 'provider_calls': []}
    proof['reference'] = publish_material(context(1), 'parameter-precheck', proof).to_dict()
    write(RUNS / 'parameter_precheck.json', proof)


def trial_index(global_index, reused_count):
    assert type(global_index) is int and type(reused_count) is int and reused_count == 64
    assert reused_count <= global_index < reused_count + 32
    return global_index - reused_count


def run():
    source_check()
    manifest = read(MANIFEST)
    if manifest['status'] == 'NOT_APPLICABLE':
        return
    assert read(RUNS / 'parameter_precheck.json')['status'] == 'PASS'
    ctx = context(8)
    prepared = cache_read(TRANSPORT / 'prepared.pkl.gz')
    record = next(row for row in manifest['centers'] if row['control_key'] == 'N0')
    transport = next(row for row in prepared if row['control_key'] == 'N0')
    items = list(zip(record['children'], transport['children'], strict=True))
    assert len(items) == 32
    reused_count = len(manifest['reused_rows'])
    assert reused_count == 64
    study_path = TRANSPORT / 'study.pkl.gz'
    if study_path.exists():
        study, state = cache_read(study_path), read(CHECKPOINT)
        assert state['status'] != 'FAILED' and state['inflight'] is None
        assert len(state['rows']) >= reused_count and state['rows'][:reused_count] == manifest['reused_rows']
    else:
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study = optuna.create_study(direction='maximize', sampler=optuna.samplers.RandomSampler(seed=13),
                                    study_name='S013-EX049-bear-bull2-fixed-parameter-diagnostic')
        for i in range(32):
            study.enqueue_trial({'point': i})
        for i in range(32):
            trial = study.ask()
            assert trial.suggest_int('point', 0, 31) == i
        state = {'status': 'PARTIAL', 'rows': deepcopy(manifest['reused_rows']), 'inflight': None,
            'actual_run_evaluations': 0, 'planned_business_accounts': 96, 'provider_calls': []}
        cache_write(study_path, study)
        write(CHECKPOINT, state)
    started = time.perf_counter()
    for offset in range(len(state['rows']) - reused_count, len(items), 8):
        batch = items[offset:offset + 8]
        pending = [(cfg, bound) for cfg, bound in batch if not point_cache('N0', cfg['label']).exists()]
        state['inflight'] = [cfg['label'] for cfg, _ in pending]
        state['actual_run_evaluations'] += len(pending)
        write(CHECKPOINT, state)
        outcomes = ctx.evaluation.evaluate_many(tuple(bound for _, bound in pending)) if pending else ()
        failures = []
        for (cfg, bound), outcome in zip(pending, outcomes, strict=True):
            if outcome.status.value == 'SUCCEEDED':
                cache_write(point_cache('N0', cfg['label']), (bound, outcome.result))
            else:
                failures.append({'label': cfg['label'], 'status': outcome.status.value,
                    'error': {'code': outcome.error.code, 'message': outcome.error.message}})
        if failures:
            state.update(status='FAILED', failures=failures, inflight=None)
            write(CHECKPOINT, state)
            raise RuntimeError('Parameter failures retained; no automatic retry/replacement')
        requests, loaded = [], []
        for cfg, expected in batch:
            bound, result = cache_read(point_cache('N0', cfg['label']))
            assert bound.lineage == expected.lineage
            assert result.runs[0].identity.content_sha256 == cfg['content_sha256']
            loaded.append((cfg, bound, result))
            requests.append(EvaluationEvidenceWrite(EXPERIMENT, 'parameter-account-' + cfg['label'].lower(), bound, result))
        published = publish_evidence_many(ctx, tuple(requests))
        assert all(outcome.status.value == 'PUBLISHED' for outcome in published)
        for index, ((cfg, bound, result), outcome) in enumerate(zip(loaded, published, strict=True), start=offset):
            global_index = reused_count + index
            study.tell(trial_index(global_index, reused_count), float(result.runs[0].observation.net_cagr))
            state['rows'].append({'label': cfg['label'], 'center': 'N0', 'control_key': 'N0',
                'point_index': cfg['point_index'], 'candidate_id': cfg['candidate_id'],
                'content_sha256': cfg['content_sha256'], 'status': 'SUCCEEDED', 'reference': outcome.reference.to_dict(),
                'request_hash': result.request_hash, 'result_hash': result.result_hash, 'reused': False})
        assert len(manifest['reused_rows']) == reused_count
        state.update(status='COMPLETE' if len(state['rows']) == 96 else 'PARTIAL', inflight=None,
                     elapsed_seconds=time.perf_counter() - started, provider_calls=SOURCE_CALLS)
        cache_write(study_path, study)
        write(CHECKPOINT, state)
        print({'parameter_rows': len(state['rows']), 'status': state['status']}, flush=True)
    assert state['status'] == 'COMPLETE' and state['actual_run_evaluations'] == 31 and not SOURCE_CALLS
    state.update(new_parameter_business_accounts=32, reused_parameter_accounts=64, actual_parameter_evaluations=33)
    state['reference'] = publish_material(ctx, 'parameter-complete-matrix', state).to_dict()
    write(CHECKPOINT, state)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('declare', 'precheck', 'run'))
    parser.add_argument('--first-candidate', type=int, default=RESERVED_FIRST)
    args = parser.parse_args()
    {'declare': lambda: declare(args.first_candidate), 'precheck': precheck, 'run': run}[args.phase]()


if __name__ == '__main__':
    main()
