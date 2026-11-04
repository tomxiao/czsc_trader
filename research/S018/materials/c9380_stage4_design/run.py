"""Approved C9380 bounded sensitivity: 81 strategy accounts, two shared benchmarks."""
from pathlib import Path
import os
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
SCRATCH = ROOT / '.tmp/s018-c9380-stage4'
SCRATCH.mkdir(parents=True, exist_ok=True)
sys.pycache_prefix = str(SCRATCH / 'pycache')
os.environ['TMP'] = os.environ['TEMP'] = str(SCRATCH)
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'

import argparse
from dataclasses import asdict, replace
from datetime import date, datetime
from hashlib import sha256
import json
import math
from time import perf_counter
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo
import numpy as np
import psutil
from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, create_research_context, load_candidate,
    get_research_overview, create_experiment, ExperimentRequest, publish_evidence, publish_evidence_many)
from dataflows import (AssetClass, BarFrequency, EquityDataRequest, EquityProduct, EquityQuery,
    InstrumentId, MarketId, PreparedDataRef, ProviderBinding, ProviderConfig, PriceAdjustment,
    SourceRef, TimeInterval)
from strategy_manager import CandidateKey, CandidateDerivation, CandidateDerivationKind, CandidateEvidence
from strategy_runtime import ExecutionResources
from strategy_evaluator import (AssessmentCandidate, ParameterAxis, RealDomain, IntegerDomain,
    CategoricalDomain, ExplicitValues, BoundedLocalStep, RelativeChangeLimit, AbsoluteChangeLimit,
    ParameterNeighborhoodProtocol, ParameterNeighborhoodRequest, ParameterNeighborhoodSpace,
    build_parameter_neighborhood_design, DeclaredParameterPointSet)
from czsc_trader.research_tools.equity_replay import materialize_equity

DESIGN_DIR = ROOT / 'research/S018/materials/c9380_stage4_design'
FAMILY = ROOT / 'research/S018'
EXP = d.ExperimentRef('S018', 'EX064_20261104')
WORK = EXP.resolve(ROOT)
OUT = WORK / 'others'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = SCRATCH / (uuid4().hex + '.json')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str)+'\n', encoding='utf-8')
    os.replace(temporary, path)


def normalize(values, center):
    return {key: type(center[key])(value) for key, value in values.items()}


def construction(center, mapping_sha, feasible_sha):
    proposed = read(DESIGN_DIR/'point_set.json')
    params = json.loads(center.definition.parameters_json)
    assert params == proposed['center']
    assert center.content_identity.content_sha256 == proposed['candidate_content_hash']
    axes = []
    for key, value in params.items():
        if isinstance(value, str):
            domain, rule, unit = CategoricalDomain((value,)), ExplicitValues((value,)), 'mode'
        elif type(value) is int:
            domain = IntegerDomain(2 if key == 'beta_window' else 1, sys.maxsize)
            rule, unit = BoundedLocalStep(RelativeChangeLimit(.05)), 'trading_sessions'
        else:
            if key in ('common_budget', 'other_budget'):
                domain = RealDomain(0., 1.)
            elif key == 'initial_fraction':
                domain = RealDomain(0., 1., lower_closed=False)
            elif key == 'common_share':
                domain = RealDomain(0., sys.float_info.max)
            else:
                domain = RealDomain(-1., sys.float_info.max, lower_closed=False)
            rule = BoundedLocalStep(AbsoluteChangeLimit(.0005) if value == 0 else RelativeChangeLimit(.05))
            unit = 'ratio'
        axes.append(ParameterAxis(key, value, domain, rule, (key,), unit))
    result = build_parameter_neighborhood_design(ParameterNeighborhoodRequest(
        AssessmentCandidate('S018-C9380', center.content_identity.content_sha256),
        ParameterNeighborhoodProtocol(), ParameterNeighborhoodSpace(tuple(axes), mapping_sha, feasible_sha)),
        feasibility=lambda values: True)
    assert result.status.value == 'COMPLETE', result
    full = result.design
    assert full.point_count == 4373
    keys = sorted(params)
    lookup = {tuple(dict((v.name, v.value) for v in point.values)[key] for key in keys): i
              for i, point in enumerate(full.points)}
    indices = tuple(lookup[tuple(point['parameters'][key] for key in keys)] for point in proposed['points'])
    declared = DeclaredParameterPointSet(full, indices, sha256((DESIGN_DIR/'point_set.json').read_bytes()).hexdigest())
    assert len(set(indices)) == declared.point_count == 79
    children = tuple(replace(center, candidate_id=f'C{1000+i:04}', definition=replace(center.definition,
        parameters_json=json.dumps(normalize(point['parameters'], params), sort_keys=True, separators=(',', ':'))))
        for i, point in enumerate(proposed['points']))
    assert all(not (FAMILY/'assets/candidates'/child.candidate_id).exists() for child in children)
    signs = np.array([p['signs'] for p in proposed['points'] if p['id'].startswith('J')])
    columns = [np.ones(64), *signs.T]
    columns.extend(signs[:, i]*signs[:, j] for i in range(8) for j in range(i+1, 8))
    matrix = np.array(columns).T
    assert np.array_equal(matrix.T @ matrix, 64*np.eye(37))
    return proposed, declared, children


def frozen_context(repo, center):
    spec = center.definition.execution_spec
    offline = create_research_context(repo, d.ResearchBatchRef('S018'),
        providers=ProviderConfig(bindings={}, equity_bindings={}), execution_spec=spec,
        resources=ExecutionResources(12, 1, 17))
    def ref(path):
        value = read(path)['reference']
        return PreparedDataRef(UUID(value['space_id']), UUID(value['preparation_id']), value['manifest_sha256'])
    raw_ref = ref(FAMILY/'experiments/EX001_20261104/others/daily_preparation.json')
    hfq_ref = ref(FAMILY/'experiments/EX049_20261104/others/data_preparation.json')
    raw_source = SourceRef('futu', 's018-mu-daily-20261104')
    sources = d.EquitySources(raw_source, raw_source,
        SourceRef('s018-mu-actions', 'futu-spglobal-crosscheck-v1'),
        SourceRef('s018-mu-rules', 'daily-research-assumptions-v1'))
    first, last = date(2022, 1, 3), date(2026, 10, 30)
    results = {}
    for product in EquityProduct:
        request = EquityDataRequest(center.definition.instrument, getattr(sources, product.name.lower()),
            EquityQuery(product, first, last, BarFrequency.DAILY))
        result = offline.data.fetch(request, prepared=raw_ref)
        assert result.ready, result.error
        results[request.parameters] = result
    for aux in center.definition.auxiliary_inputs:
        for request in aux.requests(first, last):
            result = offline.data.fetch(request, prepared=hfq_ref)
            assert result.ready, result.error
            results[request.parameters] = result
    def frozen(request):
        result = results[request.parameters]
        return result.dataframe, dict(result.identity.metadata)
    bindings = {p.provider_key: ProviderBinding(p.source.provider, p.source.revision, frozen) for p in results}
    context = create_research_context(repo, d.ResearchBatchRef('S018'),
        providers=ProviderConfig(bindings={}, equity_bindings=bindings), execution_spec=spec,
        resources=ExecutionResources(12, 1, 17))
    identities = [{'request': str(p), 'content_sha256': v.identity.content_sha256} for p,v in results.items()]
    return context, sources, identities


def request_for(candidate, sources, pressure=False):
    zone = ZoneInfo('America/New_York')
    window = TimeInterval(datetime(2023,1,3,9,30,tzinfo=zone), datetime(2026,10,30,16,tzinfo=zone))
    return d.EquityEvaluationRequest(EXP, candidate, window, date(2022,1,3), sources, 100000., .002 if pressure else .001,
        benchmark=d.EvaluationBenchmark(d.EquityBuyHold(candidate.definition.execution_spec)),
        window_id='MU_DEVELOPMENT', scenario_id='PRESSURE' if pressure else 'STANDARD',
        measurement_tier='STRESS' if pressure else 'FORMAL', drawdown_basis='BAR_CLOSE', concentration_basis='MAX_SINGLE')


def metric(run):
    m = run['metrics']
    counts = m['rolling_60_closed_cycle_counts']
    ratio = m['annualized_return']/m['bar_max_drawdown'] if m['bar_max_drawdown'] > 1e-12 else None
    return dict(annual=m['annualized_return'], dd=m['bar_max_drawdown'],
        calmar=ratio if ratio is not None and math.isfinite(ratio) else None,
        closed=m['closed_cycles'], median=m['rolling_60_closed_cycle_median'],
        coverage=sum(n >= 3 for n in counts)/len(counts))


def main():
    global OUT
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--recover-unsubmitted', action='store_true')
    args = parser.parse_args()
    repo = RepositoryContext.discover(ROOT)
    overview = get_research_overview(repo, d.ResearchBatchRef('S018'))
    print('OVERVIEW', len(overview.experiments), [(x.stage.value,x.revision) for x in overview.deliveries], flush=True)
    center = load_candidate(repo, CandidateKey('S018','C9380'))
    mapping = {'center': center.content_identity.content_sha256,
        'parameters': json.loads(center.definition.parameters_json),
        'axes': read(DESIGN_DIR/'point_set.json')['axes'],
        'rules': 'Real nonzero +/-5%; zero +/-0.0005; integers nearest valid day within5%; category unchanged.',
        'numeric_domain_ends': 'Machine representable maxima only; business upper bound 1 for budgets/fraction.'}
    feasible = {'all_generated_local_points_legal': True, 'source_unchanged': True,
        'history': 'All axes produce max(63,beta_window+entry_days+1,max_hold+1)=63.',
        'positive_integer_times': True, 'no_leverage_budget': True, 'margin_strictly_greater_than_minus_one': True}
    encode = lambda value: (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode()
    proposed, design, children = construction(center, sha256(encode(mapping)).hexdigest(), sha256(encode(feasible)).hexdigest())
    print('PREFLIGHT_PASS', {'center': center.content_identity.content_sha256, 'neighbors': design.point_count,
        'full_geometry_only': design.source_design.point_count, 'strategy_accounts':81, 'shared_benchmarks':2}, flush=True)
    if not args.run:
        return
    if args.recover_unsubmitted:
        assert args.run
        previous = read(OUT/'results.json')
        statuses = read(OUT/'batch_00_status.json')
        assert previous['status']=='STOPPED' and not previous['accounts']
        assert len(statuses)==12 and all(x['status']=='CANCELLED' and 'task was not submitted: [WinError 5]' in x['error'] for x in statuses)
        assert read(OUT/'progress.json')['unknown']==0
        prior_out=OUT
        OUT=WORK/'others/recovery_01'
        assert not OUT.exists(), 'Recovery already attempted; inspect before any further action.'
    else:
        assert not WORK.exists(), 'Existing EX064: inspect actual state; no implicit rerun.'
    assert psutil.virtual_memory().available > 16*2**30, 'Review available memory before starting.'
    start = perf_counter()
    context, sources, identities = frozen_context(repo, center)
    if not args.recover_unsubmitted:
        actual = create_experiment(context, ExperimentRequest('C9380 bounded parameter sensitivity',
            'Does the fixed C9380 survive 79 declared local perturbations and doubled trading fees?', date(2026,11,4)))
        assert actual == EXP, actual
    OUT.mkdir(exist_ok=True)
    (WORK/'src'/('run_recovery.py' if args.recover_unsubmitted else 'run.py')).write_bytes(Path(__file__).read_bytes())
    if not args.recover_unsubmitted:
        (WORK/'src/strategy.py').write_bytes((center.source_root/'strategy.py').read_bytes())
    save(OUT/'approved_point_set.json', proposed)
    save(OUT/'input_identities.json', identities)
    authorization = {'status':'AUTHORIZED', 'user_instruction':'开始吧', 'scope':'79 parameters, standard, pressure, two shared benchmarks',
        'calmar_policy':'User confirmed Calmar robustness; no annual-return substitution.',
        'proposal_sha256':sha256((DESIGN_DIR/'proposal.md').read_bytes()).hexdigest(),
        'point_set_sha256':sha256((DESIGN_DIR/'point_set.json').read_bytes()).hexdigest(),
        'stage4_complete':False, 'selection_or_search':False}
    save(OUT/'authorization.json', authorization)
    if args.recover_unsubmitted:
        save(OUT/'recovery_decision.json',{'reason':'First batch cancelled before submission by Windows sandbox WinError5.',
            'prior_results_sha256':sha256((prior_out/'results.json').read_bytes()).hexdigest(),
            'prior_status_sha256':sha256((prior_out/'batch_00_status.json').read_bytes()).hexdigest(),
            'unknown_tasks':0,'completed_strategy_accounts':0,'additional_design_points':0,
            'decision':'One explicit recovery using approved process permissions; retain original failed attempt.'})
    manifest = {'status':'PREPARING', 'accounts':{}, 'batches':[], 'planned_strategy_accounts':81,
        'planned_benchmarks':2, 'parameter_count':79, 'required_passes':65,
        'original_center_hash':center.content_identity.content_sha256}
    save(OUT/'results.json', manifest)
    refs = []
    def progress(event):
        save(OUT/'progress.json', {'phase':event.phase.value, 'completed':event.completed, 'total':event.total,
            'failed':event.failed, 'unknown':event.unknown, 'elapsed_seconds':perf_counter()-start})
    try:
        with d.ResearchExecutionSession(context, experiment=EXP,
                checkpoint=d.ExecutionCheckpointRequest('EX064-C9380-bounded-recovery1' if args.recover_unsubmitted else 'EX064-C9380-bounded-v1'), on_progress=progress) as execution:
            def material(name, value):
                content = value if isinstance(value, bytes) else encode(value)
                reference = publish_evidence(context, d.MaterialEvidenceWrite(EXP, name, content, 'application/json', 'json'), execution=execution)
                refs.append(reference)
                return reference
            mapping_ref, feasible_ref = material('parameter-mapping',mapping), material('parameter-feasibility',feasible)
            material('approved-point-set',(DESIGN_DIR/'point_set.json').read_bytes())
            material('authorization',authorization)
            central = context.evaluation.prepare(request_for(center,sources), execution=execution)
            unbound = tuple(context.evaluation.prepare(request_for(child,sources), execution=execution) for child in children)
            plan = d.ParameterEvaluationPlan.create(design, central, unbound, mapping_evidence=mapping_ref,
                feasibility_evidence=feasible_ref, dataflows=context.data, execution=execution)
            save(OUT/'parameter_plan.json', plan.to_dict())
            plan_ref = material('parameter-plan',(OUT/'parameter_plan.json').read_bytes())
            save(OUT/'parameter_plan_ref.json',plan_ref.to_dict())
            jobs = [('CENTER',central), ('PRESSURE',context.evaluation.prepare(request_for(center,sources,True),execution=execution))]
            for local,(child,point,index) in enumerate(zip(children,design.points,design.point_indices,strict=True)):
                derivation = CandidateDerivation(center.key,center.content_identity.content_sha256,
                    child.key,child.content_identity.content_sha256,CandidateDerivationKind.PARAMETERS,
                    {v.name:v.value for v in point.values},design.protocol.sha256,
                    CandidateEvidence(plan_ref.repository_path,plan_ref.sha256))
                request = replace(unbound[local].request,lineage=d.EvaluationLineage(derivation,
                    plan.bind_point(plan_ref,index,repository_root=ROOT)))
                jobs.append((proposed['points'][local]['id'],context.evaluation.prepare(request,execution=execution)))
            del unbound
            assert len(jobs)==81
            save(OUT/'job_manifest.json',[{'label':label,'candidate':h.candidate.candidate_id,
                'content_hash':h.candidate.content_identity.content_sha256,
                'point_index':h.request.lineage.parameter_binding.point.point_index if h.request.lineage else None}
                for label,h in jobs])
            material('job-manifest',(OUT/'job_manifest.json').read_bytes())
            print('PLAN_READY',79,plan_ref.sha256,'elapsed',round(perf_counter()-start,2),flush=True)
            for offset in range(0,len(jobs),12):
                if (OUT/'pause_requested').exists():
                    raise RuntimeError('Explicit pause requested before next batch')
                batch = jobs[offset:offset+12]
                begun = perf_counter()
                outcomes = context.evaluation.evaluate_many(tuple(h for _,h in batch),execution=execution)
                status = [{'label':label,'status':o.status.value,'error':str(o.error) if o.error else None}
                          for (label,_),o in zip(batch,outcomes,strict=True)]
                save(OUT/f'batch_{offset//12:02d}_status.json',status)
                good = [(job,o) for job,o in zip(batch,outcomes,strict=True) if o.status.value=='SUCCEEDED' and o.result is not None]
                receipts = publish_evidence_many(context,tuple(d.EvaluationEvidenceWrite(EXP,'c9380-'+label,h,o.result)
                    for (label,h),o in good),execution=execution) if good else ()
                save(OUT/f'batch_{offset//12:02d}_publication.json',[
                    {'label':job[0],'status':receipt.status.value,'error':str(receipt.error) if receipt.error else None,
                     'reference':receipt.reference.to_dict() if receipt.reference else None}
                    for (job,_),receipt in zip(good,receipts,strict=True)])
                for ((label,handle),outcome),receipt in zip(good,receipts,strict=True):
                    assert receipt.status.value=='PUBLISHED', receipt.error
                    refs.append(receipt.reference)
                    payload = materialize_equity(outcome.result).payload
                    run, bh = payload['runs']['candidate'],payload['runs']['buy_hold']
                    assert all(row['observed_through'] < row['execution_start'] for row in run['decisions'])
                    m,b = metric(run),metric(bh)
                    if label=='CENTER':
                        old=read(FAMILY/'experiments/EX063_20261104/others/results.json')['accounts']['C9380']['candidate']
                        assert all(math.isclose(m[k],old[k],rel_tol=1e-12,abs_tol=1e-12) for k in m), (m,old)
                        gates={'calmar':m['calmar']>=1.5*b['calmar'],'dd_relative':m['dd']<=.8*b['dd'],
                            'dd_absolute':m['dd']<=.25,'median':m['median']>=6,'coverage':m['coverage']>=.9}
                    elif label=='PRESSURE':
                        gates={'calmar':m['calmar'] is not None and m['calmar']>b['calmar'],
                            'dd_relative':m['dd']<b['dd'] if b['dd'] else m['dd']==0,'dd_absolute':m['dd']<=.25}
                    else:
                        gates={'calmar':m['calmar'] is not None and m['calmar']>=1.25*b['calmar'],
                            'dd_relative':m['dd']<=.9*b['dd'],'dd_absolute':m['dd']<=.25}
                    row={'candidate_id':handle.candidate.candidate_id,'config':json.loads(handle.candidate.definition.parameters_json),
                        'candidate':m,'benchmark':b,'gates':gates,'account_ref':receipt.reference.to_dict(),
                        'definition':handle.candidate.definition.to_dict(),'content_hash':handle.candidate.content_identity.content_sha256,
                        'parameter_binding':handle.request.lineage.parameter_binding.to_dict() if handle.request.lineage else None}
                    manifest['accounts'][label]=row
                    save(OUT/'results.json',manifest)
                    save(OUT/'evidence_refs.json',[r.to_dict() for r in refs])
                    print('ACCOUNT_PUBLISHED',label,m,gates,flush=True)
                manifest['batches'].append({'offset':offset,'count':len(batch),'seconds':perf_counter()-begun})
                manifest.update(status='RUNNING',elapsed_seconds=perf_counter()-start,workload=asdict(execution.equity_statistics))
                save(OUT/'results.json',manifest)
                assert len(good)==len(batch), 'Batch not fully successful; stop without implicit retry.'
                del outcomes, good, receipts, payload, run, bh
            stats=asdict(execution.equity_statistics)
            assert stats['candidate_runs']==81 and stats['benchmark_runs']==2,stats
            assert len(manifest['accounts'])==81
            manifest.update(status='COMPLETED',elapsed_seconds=perf_counter()-start,workload=stats)
            save(OUT/'results.json',manifest)
            material('results',(OUT/'results.json').read_bytes())
            material('input-identities',identities)
            save(OUT/'evidence_refs.json',[r.to_dict() for r in refs])
            print('COMPLETED',81,2,'elapsed',manifest['elapsed_seconds'],flush=True)
    except BaseException as error:
        manifest.update(status='STOPPED',error=repr(error),elapsed_seconds=perf_counter()-start)
        save(OUT/'results.json',manifest)
        save(OUT/'evidence_refs.json',[r.to_dict() for r in refs])
        raise


if __name__=='__main__':
    main()
