"""Sequential current stage-four API benchmarks, using isolated offline fixtures."""
# ruff: noqa: E402
from collections import Counter
from dataclasses import replace
from gc import collect
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests/functional'))
sys.path.insert(0, str(ROOT / 'packages/strategy_evaluator/tests/functional'))

import numpy as np
import psutil
import strategy_evaluator as se
from strategy_evaluator import research_models as m
from czsc_trader.research_tools import ParameterEvaluationPlan, ResearchExecutionSession, equity_replay
from czsc_trader.research_tools.equity_assessment import AssessmentProjection
from czsc_trader.research_tools.equity_evaluation import EquityEvaluationResult
from equity_parameter_support import equity_plan
from equity_test_support import setup_account_research
from test_stage4_bootstrap import interval_request
from test_research_assessment import candidate, policy, row




def measure(operation, repeats):
    samples = []
    memory = []
    process = psutil.Process()
    for _ in range(repeats):
        before = process.memory_info().rss
        start = perf_counter()
        result = operation()
        samples.append(perf_counter() - start)
        memory.append({'rss_before': before, 'rss_after': process.memory_info().rss})
        del result
    return {'repeats': repeats, 'seconds': samples,
            'median_seconds': median(samples), 'max_seconds': max(samples), 'memory_bytes': memory}


def benchmark_parameters(repeats=15):
    output = ROOT / '.tmp' / 'stage4-perf' / ('parameter-' + uuid4().hex)
    output.mkdir(parents=True)
    context, request, _, _ = setup_account_research(output / 'cold')
    with ResearchExecutionSession(context, experiment=request.experiment) as execution:
        cold = measure(lambda: context.evaluation.prepare(request, execution=execution), 1)
        warm = measure(lambda: context.evaluation.prepare(request, execution=execution), repeats)
    with equity_plan(output / 'plan') as (context, center, plan, reference, bound, execution):
        children = tuple(context.evaluation.prepare(replace(item.request, lineage=None), execution=execution)
                         for item in bound)
        create = measure(lambda: ParameterEvaluationPlan.create(plan.design, center, children,
            mapping_evidence=plan.mapping_evidence, feasibility_evidence=plan.feasibility_evidence,
            dataflows=context.data, execution=execution), repeats)
        bind = measure(lambda: plan.bind_point(reference, 0, children[0], execution=execution), repeats)
        inputs = {'centers': 1, 'children': len(children),
                  'snapshot_bytes': len(center.snapshot.artifact.content),
                  'input_bar_rows': len(json.loads(center.snapshot.artifact.content)['products']['bars']),
                  'workers': context.evaluation.resources.max_workers}
    result = {'kind': 'synthetic_public_api_latency', 'inputs': inputs,
              'prepare_cold': cold, 'prepare_session_reuse': warm,
              'ParameterEvaluationPlan.create': create, 'ParameterEvaluationPlan.bind_point': bind}
    (output / 'metrics.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result







def read_published_result(root, relative_path):
    """Read only; loading/hashing storage bytes is outside projection measurements."""
    import json
    from czsc_trader.application.equity_evidence_io import materialize_equity_document
    from czsc_trader.research_tools.evidence import managed_path
    content = managed_path(root, relative_path).read_bytes()
    header = json.loads(content)
    view = materialize_equity_document(root, relative_path, content)
    return EquityEvaluationResult(header["request_hash"], view.source_content, view.artifacts)


def benchmark_projections(result, *, repeats=3):
    """Measure public calls with existing immutable in-memory result bytes.

    Each sample creates a fresh materialized view. OS file reads and artifact
    construction are outside the boundary. Cold is the first call, later samples
    may reuse SE's bounded read_ledger cache. Byte counters cover actual JSON
    decoding through TDR's common _read, not SHA hashing or IPC bytes.
    """
    if type(result) is not EquityEvaluationResult or repeats < 1:
        raise TypeError("benchmark requires a V4 result and positive repeat count")
    operations = {
        "materialize": lambda: equity_replay.materialize_equity(result),
        "materialize_payload": lambda: equity_replay.materialize_equity(result).payload,
        "full_projection": lambda: equity_replay.build_equity_assessment(result),
        "parameter_projection": lambda: equity_replay.build_equity_assessment(
            result, projection=AssessmentProjection.PARAMETER_PERFORMANCE),
    }
    artifact_ids = {id(item.content): (item.kind, len(item.content)) for item in result.artifacts}
    original_read = equity_replay._read
    output = {}
    for name, operation in operations.items():
        samples, counts_per_sample, memory = [], [], []
        for _ in range(repeats):
            collect()
            counts = Counter()
            process = psutil.Process()
            before = process.memory_info().rss

            def measured_read(content):
                counts["total_json_reads"] += 1
                counts["total_json_bytes"] += len(content)
                item = artifact_ids.get(id(content))
                if item is not None:
                    kind, size = item
                    counts[kind + "_reads"] += 1
                    counts[kind + "_bytes"] += size
                return original_read(content)

            equity_replay._read = measured_read
            try:
                started = perf_counter()
                value = operation()
                seconds = perf_counter() - started
                memory.append({'rss_before': before, 'rss_after': process.memory_info().rss})
            finally:
                equity_replay._read = original_read
            samples.append(seconds)
            counts_per_sample.append(dict(counts))
            del value
        output[name] = {"seconds": samples, "median_seconds": median(samples),
            "cold_seconds": samples[0], "decode_counts": counts_per_sample, 'memory_bytes': memory}
    return output






def workloads(days=1000, repetitions=1000):
    neighborhood_requests = []
    for dimension in (5, 6):
        axes = tuple(se.ParameterAxis(f'p{i}', 0.5, se.RealDomain(0., 1.),
            se.BoundedLocalStep(se.RelativeChangeLimit(.05)), (f'p{i}',), 'ratio') for i in range(dimension))
        axes += tuple(se.ParameterAxis(f'fixed{i}', True, se.BooleanDomain(), se.ExplicitValues((True,)),
            (f'fixed{i}',), 'structure') for i in range(9))
        neighborhood_requests.append(se.ParameterNeighborhoodRequest(candidate(),
            se.ParameterNeighborhoodProtocol(max_combinations=1000000),
            se.ParameterNeighborhoodSpace(axes, 'a' * 64, 'b' * 64)))

    rng = np.random.default_rng(20261111)
    kwargs = dict(repetitions=repetitions, mean_block_length=21, seed=20261111)
    initial, strategy, benchmark = interval_request(rng.normal(.0005, .012, days),
        rng.normal(.0003, .01, days), **kwargs)
    baseline = replace(initial.evidence[0], frequency_window_days=60)
    design_request = se.ParameterNeighborhoodRequest(baseline.candidate,
        se.ParameterNeighborhoodProtocol(), se.ParameterNeighborhoodSpace((se.ParameterAxis('allocation', .5,
            se.RealDomain(0., 1.), se.BoundedLocalStep(se.RelativeChangeLimit(.05)), ('allocation',), 'ratio'),),
            'a' * 64, 'b' * 64))
    design = se.build_parameter_neighborhood_design(design_request, feasibility=lambda _: True).design
    links, neighbors = [], []
    for index in range(design.point_count):
        child = candidate(f'C{index+2:04d}', 'b')
        point = design.bind_point(index)
        links.append(se.PerturbationLink(baseline.candidate, child, 1., 'e' * 64, point))
        neighbors.append(replace(baseline, candidate=child, evaluation_id=m.digest((child, index)),
            parent=baseline.candidate, derivation_sha256='e' * 64,
            derivation_kind=se.AssessmentDerivationKind.PARAMETERS, parameter_point=point))
    stress = replace(baseline, evaluation_id='e' * 64, scenario_id='pressure',
        scenario_context=replace(baseline.scenario_context, one_way_cost=.002, measurement_tier='STRESS'))
    settings = replace(initial.protocol, rolling_window_days=252, rolling_step_days=21,
        parameter_protocol=design.protocol)
    full = se.CandidateAssessmentRequest((baseline.candidate,), settings, tuple(links),
        (baseline, stress, *neighbors), parameter_designs=(design,))
    numeric = se.CandidatePerformanceAssessmentRequest(replace(full, evidence=(baseline, stress)),
        tuple(se.project_parameter_performance(item) for item in neighbors))
    computed = se.paired_stationary_bootstrap(strategy, benchmark,
        champion_id='center', comparator_id='benchmark', **kwargs)
    supplied = replace(numeric, baseline_request=replace(numeric.baseline_request,
        bootstrap_evidence=(se.AssessmentBootstrapEvidence(baseline.candidate, baseline.evaluation_id,
            computed.cagr_result),)))
    rows = tuple(row(candidate(f'C{i+1:04d}', 'a'), annual=.1 + i * .01) for i in range(3))
    panel = se.AssessmentPanel('a' * 64, 'b' * 64, rows, (), (), formula_version='research-assessment-v7')
    comparison = se.CandidateComparisonRequest(tuple(item.candidate for item in rows),
        se.ResearchTargets((), 60), panel, policy())
    calls = {
        'neighborhood_5d_9fixed': lambda: se.build_parameter_neighborhood_design(neighborhood_requests[0], feasibility=lambda _: True),
        'neighborhood_6d_9fixed': lambda: se.build_parameter_neighborhood_design(neighborhood_requests[1], feasibility=lambda _: True),
        'assess_full': lambda: se.assess_candidates(full),
        'assess_numeric': lambda: se.assess_candidates(numeric),
        'assess_numeric_bootstrap_reuse': lambda: se.assess_candidates(supplied),
        'compare_candidates': lambda: se.compare_candidates(comparison),
        'paired_stationary_bootstrap': lambda: se.paired_stationary_bootstrap(strategy, benchmark,
            champion_id='center', comparator_id='benchmark', **kwargs),
    }
    return calls, dict(observations=days, bootstrap_repetitions=repetitions,
        baseline_accounts=2, parameter_accounts=len(neighbors), real_account_execution=False)


def benchmark_accounts(output, repeats):
    from czsc_trader.application import publish_evidence, publish_evidence_many
    from czsc_trader.research_tools import EvaluationEvidenceWrite, build_assessment_evidence
    from czsc_trader.research_tools._execution_checkpoint import CheckpointStore
    from strategy_runtime import ExecutionResources

    with equity_plan(output / 'accounts', resources=ExecutionResources(1, 1, 20261111)) as (
            context, center, plan, reference, children, execution):
        handles = (center, *children)
        def evaluate():
            values = context.evaluation.evaluate_many(handles, execution=execution)
            if any(item.result is None for item in values):
                raise RuntimeError(tuple(item.error for item in values))
            return values
        timing = {'evaluate_many_3_accounts': measure(evaluate, repeats)}
        results = evaluate()
        result = results[1].result
        timing['build_assessment_evidence_full'] = measure(lambda: build_assessment_evidence(
            children[0], result, execution=execution), repeats)
        timing['build_assessment_evidence_parameter'] = measure(lambda: build_assessment_evidence(
            children[0], result, execution=execution, projection=AssessmentProjection.PARAMETER_PERFORMANCE), repeats)
        writes = tuple(EvaluationEvidenceWrite(handle.experiment, f'account-{index}', handle, outcome.result)
                       for index, (handle, outcome) in enumerate(zip(handles, results, strict=True)))
        def publish():
            values = publish_evidence_many(context, writes, execution=execution)
            if any(item.status.value != 'PUBLISHED' for item in values):
                raise RuntimeError(tuple(item.error for item in values))
            return values
        timing['publish_evidence_many_cold'] = measure(publish, 1)
        timing['publish_evidence_many_session_reuse'] = measure(publish, repeats)
        timing['publish_evidence_session_reuse'] = measure(
            lambda: publish_evidence(context, writes[1], execution=execution), repeats)
        with CheckpointStore(output, center.experiment, 'benchmark', 'CREATE', 'a' * 64) as checkpoint:
            def save():
                for outcome in results:
                    checkpoint.save_equity_result(outcome.result.request_hash, outcome.result)
            timing['checkpoint_save_cold_3_accounts'] = measure(save, 1)
            timing['checkpoint_save_reuse_3_accounts'] = measure(save, repeats)
        with CheckpointStore(output, center.experiment, 'benchmark', 'RESUME', 'a' * 64) as checkpoint:
            def restore():
                return tuple(checkpoint.load_equity_result(handle, outcome.result.request_hash)
                             for handle, outcome in zip(handles, results, strict=True))
            timing['checkpoint_restore_cold_3_accounts'] = measure(restore, 1)
            timing['checkpoint_restore_reuse_3_accounts'] = measure(restore, repeats)
        header = result.payload
        inputs = {'accounts_per_batch': len(handles), 'workers': 1, 'native_threads': 1,
                  'artifact_bytes': sum(len(item.content) for item in result.artifacts),
                  'window': header['request']['window'], 'synthetic': True}
        timing.update(benchmark_projections(result, repeats=repeats))
    return {'inputs': inputs, 'interfaces': timing}


def benchmark_delivery(output, repeats):
    """Time current public ASSESSMENT storage APIs on the real integration fixture."""
    import pytest
    from dataflows import MarketId
    import test_mixed_parameter_assessment_delivery as fixture
    from czsc_trader.research_tools import delivery as d
    timings = {'assemble_delivery_assessment': [], 'validate_delivery_integrity': []}
    assemble, validate = fixture.assemble_delivery, fixture.validate_delivery
    def timed_assemble(context, definition, *args, **kwargs):
        started = perf_counter()
        result = assemble(context, definition, *args, **kwargs)
        if definition.stage is d.DeliveryStage.ASSESSMENT:
            timings['assemble_delivery_assessment'].append(perf_counter() - started)
        return result
    def timed_validate(*args, **kwargs):
        started = perf_counter()
        result = validate(*args, **kwargs)
        timings['validate_delivery_integrity'].append(perf_counter() - started)
        return result
    for index in range(repeats):
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(fixture, 'assemble_delivery', timed_assemble)
            patch.setattr(fixture, 'validate_delivery', timed_validate)
            fixture.test_TDR_12_C06_mixed_parameter_calmar_schema15_delivery_is_storage_only(
                output / f'delivery-{index}', patch, MarketId.CN)
    return {name: {'seconds': samples, 'median_seconds': median(samples), 'repeats': len(samples)}
            for name, samples in timings.items()}


def run_benchmarks(*, output, repeats=3, account_path=None):
    import os
    import platform
    from threadpoolctl import threadpool_limits
    output = Path(output).resolve()
    if not output.is_relative_to((ROOT / '.tmp').resolve()) or repeats < 1:
        raise ValueError('output must stay in repository .tmp and repeats must be positive')
    output.mkdir(parents=True, exist_ok=False)
    report = {'environment': {'python': platform.python_version(), 'platform': platform.platform(),
        'logical_cpus': os.cpu_count(), 'native_threads': 1, 'physical_memory_bytes': psutil.virtual_memory().total},
        'scope': 'Sequential offline API benchmark; setup/imports outside timing; no real account replay.'}
    with threadpool_limits(limits=1):
        print('Measuring preparation and parameter binding', flush=True)
        report['parameters'] = benchmark_parameters(repeats)
        print('Measuring SE calculations', flush=True)
        calls, metadata = workloads()
        report['se'] = {'inputs': metadata, 'interfaces': {name: measure(call, repeats) for name, call in calls.items()}}
        print('Measuring synthetic accounts, checkpoints and publication', flush=True)
        report['accounts'] = benchmark_accounts(output, repeats)
        print('Measuring ASSESSMENT publication and integrity reading', flush=True)
        report['delivery'] = benchmark_delivery(output, repeats)
        if account_path:
            print('Measuring read-only saved account projection', flush=True)
            result = read_published_result(ROOT, account_path)
            report['saved_account'] = {'source': account_path,
                'artifact_bytes': sum(len(item.content) for item in result.artifacts),
                'interfaces': benchmark_projections(result, repeats=repeats)}
    report['process_peak_working_set_bytes'] = getattr(psutil.Process().memory_info(), 'peak_wset', None)
    destination = output / 'metrics.json'
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(destination, flush=True)
    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Current stage-four public API benchmark')
    parser.add_argument('--output', type=Path, default=ROOT / '.tmp' / 'stage4-interface-benchmark' / uuid4().hex)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--account-path', help='Optional read-only managed published V4 parameter account path')
    args = parser.parse_args()
    run_benchmarks(output=args.output, repeats=args.repeats, account_path=args.account_path)
