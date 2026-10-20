"""Pinned S014 parameter design, exact center control, and independent selfchecks."""
import argparse
from dataclasses import replace
from datetime import date
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import socket
import sys

from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import (
    EvaluationRequest, EvaluationWindow, EvaluationCost, EvaluationBenchmark,
    EvaluationResources, EvaluationEvidenceWrite, MaterialEvidenceWrite,
    EvidenceRef, ExperimentRef, ParameterEvaluationPlan, EvaluationLineage,
)
from strategy_runtime import StrategyRuntime
from strategy_manager import CandidateKey, CandidateEvidence, CandidateDerivation, CandidateDerivationKind
from strategy_evaluator import (
    AssessmentCandidate, ParameterCoordinate, ParameterCoordinateKind, ParameterSpace,
    ParameterPerturbationProtocol, ParameterDesignRequest, ParameterDesignStatus,
    build_parameter_perturbation_design,
)
from czsc_trader.research_tools import LimitBuyHold
from parameter_mapping import COORDINATES, map_coordinates
from parameter_feasibility import feasible

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OWNER = ExperimentRef('S014', EX.name)
SOURCE = EX / 'src/strategy_runtime/strategies/trend_permission.py'


def offline_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def no_network(*args, **kwargs):
    raise RuntimeError('EX054 uses authenticated S014 offline inputs only')


socket.socket.connect = no_network
socket.create_connection = no_network


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, default=str, allow_nan=False)
        handle.write('\n')


def context():
    offline = offline_module(ROOT / 'research/S014/experiments/EX052_20261020/src/offline_inputs.py', 's014_stage4_offline')
    return offline.get_context(EvaluationResources(max_workers=2, native_threads_per_worker=1, random_seed=13))


def publish(ctx, path, name=None):
    media = {'.py': 'text/x-python', '.md': 'text/markdown', '.json': 'application/json'}
    return publish_evidence(ctx, MaterialEvidenceWrite(OWNER, name or 'ex054-' + path.stem,
        path.read_bytes(), media[path.suffix], path.suffix[1:]))


def candidate(parameters=None, candidate_id='C9524'):
    from build_candidate import build
    result = build() if parameters is None else build(parameters=parameters, candidate_id=candidate_id)
    return result[0] if isinstance(result, tuple) else result


def request(strategy, *, center=None, stress=False):
    return EvaluationRequest(
        repository_root=ROOT, experiment_id=EX.name, strategy=strategy,
        runtime_binding={'candidate_id': strategy.reference_id,
            'source_files': ['strategies/trend_permission.py'],
            'implementation_sha256': strategy.payload['runtime']['source_sha256']},
        symbol='600722.SH', asset_type='stock',
        windows=(EvaluationWindow('full', date(2020, 1, 2), date(2026, 10, 15)),),
        data_cutoff=date(2026, 10, 15), initial_cash=100000,
        costs=(EvaluationCost('double_cost' if stress else 'baseline', .002 if stress else .001,
                              'STRESS' if stress else 'FORMAL'),),
        benchmark=EvaluationBenchmark(LimitBuyHold(100, .01, .01, .1, 1000000)), workers=1,
        execution_data=None if center is None else center.execution_data,
        # Input bindings authenticate the strategy runtime identity as well as
        # raw data. Only the unchanged center can reuse the center binding.
        input_bindings={} if center is None or not stress else center.input_bindings,
    )


def center_control():
    assert not (EX / 'others/center_control.json').exists()
    ctx = context()
    strategy = candidate()
    bound = ctx.evaluation.prepare(request(strategy))
    sources = {str(p.relative_to(EX).as_posix()): publish(ctx, p, 'ex054-source-' + sha256(str(p).encode()).hexdigest()[:12]).to_dict()
        for p in sorted((EX / 'src').rglob('*.py'))}
    write(EX / 'protocols/center_dispatch.json', {'candidate': strategy.reference_id,
        'source_sha256': sha256(SOURCE.read_bytes()).hexdigest(), 'sources': sources,
        'authorization': 'User accepted DEV and authorized merge into research and continuation of S014 on 2026-10-20.',
        'window': ['2020-01-02', '2026-10-15'], 'new_market_calls': 0})
    outcome = ctx.evaluation.evaluate_many((bound,))[0]
    assert outcome.status.value == 'SUCCEEDED', outcome
    ref = publish_evidence(ctx, EvaluationEvidenceWrite(OWNER, 'c9524-equivalent-center', bound, outcome.result))
    compare = offline_module(ROOT / 'research/S014/experiments/EX053_20261020/work/compare_full_account.py', 's014_center_comparison')
    assert sha256(compare.ORIGINAL.read_bytes()).hexdigest() == compare.ORIGINAL_SHA
    comparison = compare.compare(read(compare.ORIGINAL), read(ref.resolve(ROOT)), expected_candidate='C9524')
    write(EX / 'others/center_control.json', {'status': comparison['status'], 'account': ref.to_dict(),
        'comparison': comparison, 'original_sha256': compare.ORIGINAL_SHA,
        'content_sha256': StrategyRuntime().identify(strategy, dependencies=()).content_sha256,
        'source_sha256': sha256(SOURCE.read_bytes()).hexdigest()})
    print('CENTER_EXACT', comparison, flush=True)


def prepared_design(ctx):
    control = read(EX / 'others/center_control.json')
    assert control['status'] == 'PASS_EXACT_BUSINESS_BEHAVIOR'
    assert sha256(SOURCE.read_bytes()).hexdigest() == control['source_sha256']
    central = ctx.evaluation.prepare(request(candidate()))
    center = AssessmentCandidate('S014-C9524', control['content_sha256'])
    mapping = publish(ctx, EX / 'src/parameter_mapping.py', 'ex054-parameter-mapping')
    constraint = publish(ctx, EX / 'src/parameter_feasibility.py', 'ex054-parameter-feasibility')
    space = ParameterSpace(tuple(ParameterCoordinate(name, float(value), float(lower), float(upper), ParameterCoordinateKind(kind))
                                  for name, value, lower, upper, kind in COORDINATES), mapping.sha256, constraint.sha256)
    result = build_parameter_perturbation_design(ParameterDesignRequest(center, ParameterPerturbationProtocol(), space), feasibility=feasible)
    assert result.status is ParameterDesignStatus.COMPLETE, result
    design = result.design
    children = tuple(ctx.evaluation.prepare(request(candidate(map_coordinates(p.coordinates), f'C{9530+p.index:04}'), center=central))
                     for p in design.points)
    plan = ParameterEvaluationPlan.create(design, central, children, mapping_evidence=mapping,
                                         feasibility_evidence=constraint, dataflows=ctx.data)
    return central, children, plan


def lock():
    ctx = context()
    _, _, plan = prepared_design(ctx)
    write(EX / 'protocols/parameter_plan.json', plan.to_dict())
    planref = publish(ctx, EX / 'protocols/parameter_plan.json', 'ex054-prospective-parameter-plan')
    write(EX / 'protocols/parameter_plan_ref.json', planref.to_dict())
    print('DESIGN_LOCKED', len(plan.children), planref.sha256, flush=True)


def execute():
    ctx = context()
    central, children, plan = prepared_design(ctx)
    planref = EvidenceRef.from_dict(read(EX / 'protocols/parameter_plan_ref.json'))
    assert ParameterEvaluationPlan.from_dict(read(planref.resolve(ROOT))) == plan
    centerref = EvidenceRef.from_dict(read(EX / 'others/center_control.json')['account'])
    center_evidence = CandidateEvidence(centerref.repository_path.removeprefix('research/S014/'), centerref.sha256)
    for start in range(0, len(children), 2):
        requests = []
        for index in range(start, min(start + 2, len(children))):
            prior = list((EX / 'others').glob(f'point_{index:02}*.json'))
            if any(read(p)['status'] == 'SUCCEEDED' for p in prior):
                continue
            child = children[index]
            child_id = plan.children[index].candidate
            derivation = CandidateDerivation(CandidateKey('S014', 'C9524'), plan.design.center.content_sha256,
                CandidateKey('S014', child.strategy.candidate_id), child_id.content_sha256,
                CandidateDerivationKind.PARAMETERS, {'parameters': map_coordinates(plan.design.points[index].coordinates)},
                planref.sha256, center_evidence)
            binding = plan.bind_point(planref, index, repository_root=ROOT)
            requests.append((index, replace(child, lineage=EvaluationLineage(derivation, binding))))
        if not requests:
            continue
        outcomes = ctx.evaluation.evaluate_many(tuple(r for _, r in requests))
        for (index, bound), outcome in zip(requests, outcomes, strict=True):
            record = {'index': index, 'candidate': bound.strategy.reference_id, 'status': outcome.status.value,
                      'request_hash': outcome.request_hash}
            if outcome.result is None:
                record['error'] = {'code': outcome.error.code, 'message': outcome.error.message}
            else:
                ref = publish_evidence(ctx, EvaluationEvidenceWrite(OWNER, f'ex054-parameter-point-{index:02}', bound, outcome.result))
                record['account'] = ref.to_dict()
            existing = list((EX / 'others').glob(f'point_{index:02}*.json'))
            suffix = '' if not existing else f'_retry{len(existing)}'
            write(EX / f'others/point_{index:02}{suffix}.json', record)
            print('POINT', index, record['status'], flush=True)
        if any(x.status.value != 'SUCCEEDED' for x in outcomes):
            raise RuntimeError('Retain failed points; no silent replacement or retry')
    if not (EX / 'others/stress.json').exists():
        bound = ctx.evaluation.prepare(request(candidate(), center=central, stress=True))
        outcome = ctx.evaluation.evaluate_many((bound,))[0]
        assert outcome.status.value == 'SUCCEEDED', outcome
        ref = publish_evidence(ctx, EvaluationEvidenceWrite(OWNER, 'ex054-center-double-cost', bound, outcome.result))
        write(EX / 'others/stress.json', {'status': 'SUCCEEDED', 'account': ref.to_dict(),
            'limitation': 'External one-way cost doubled; internal simulated feedback fee remains the fixed baseline 0.001 strategy rule.'})
        print('STRESS_SUCCEEDED', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('center', 'lock', 'execute'))
    args = parser.parse_args()
    {'center': center_control, 'lock': lock, 'execute': execute}[args.action]()
