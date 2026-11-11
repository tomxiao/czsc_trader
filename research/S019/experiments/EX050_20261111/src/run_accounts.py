"""Three complete stage-four neighborhoods with exact reused centers and public lineage."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from time import perf_counter

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
sys.path.insert(0,str(ROOT/'research/S019/experiments/EX048_20261111/src'))
import batch_runner as core  # noqa: E402
from strategy_manager import CandidateKey, CandidateDerivation, CandidateDerivationKind, CandidateEvidence  # noqa: E402
from strategy_evaluator import (AssessmentCandidate, ParameterAxis, BooleanDomain, CategoricalDomain,  # noqa: E402
    RealDomain, IntegerDomain, ExplicitValues, BoundedLocalStep, RelativeChangeLimit,
    ParameterNeighborhoodProtocol, ParameterNeighborhoodRequest, ParameterNeighborhoodSpace,
    build_parameter_neighborhood_design)

IDS = ('C0966','C1010','C0909')
POINT_COUNTS = {'C0966':242,'C1010':728,'C0909':728}
SOURCE = ROOT/'research/S019/experiments/EX046_20261111/src/strategy.py'
SOURCE_HASH = '0082d1ca613c6f475c651317db8622b23ff3e50725977592818ee7fe493e4fc8'


def normalize(value):
    return json.loads(core.encoded(value))


def construction(center):
    params = json.loads(center.definition.parameters_json)
    assert params['exit_policy'] in {'hard','ramp','ramp_rebuild'}
    assert params['participation_policy'] == 'linear'
    active = {'weak_fraction','quiet_fraction','participation_threshold','participation_width','trail_atr'}
    if params['exit_policy'] != 'hard':
        active.add('exit_width')
    assert (params['down_days'],params['hold_days'],params['participation_days']) == (1,5,3)
    axes, explanations = [], []
    for key,value in sorted(params.items()):
        if type(value) is bool:
            domain, rule, unit = BooleanDomain(), ExplicitValues((value,)), 'fixed_structure'
        elif type(value) is str:
            domain, rule, unit = CategoricalDomain((value,)), ExplicitValues((value,)), 'fixed_structure'
        elif type(value) is int:
            domain = IntegerDomain(value,value) if key == 'confirm_bars' else IntegerDomain(1,65 if key == 'hold_days' else 64)
            rule = BoundedLocalStep(RelativeChangeLimit(.05))
            unit = 'trading_sessions' if key != 'confirm_bars' else 'decision_bars'
        else:
            assert type(value) is float and key in active | {'exit_width'}
            domain = RealDomain(0.,1.,lower_closed=False) if key in {'weak_fraction','quiet_fraction'} else RealDomain(0.,sys.float_info.max,lower_closed=False)
            if key not in active:
                domain = RealDomain(value,value)
            rule = BoundedLocalStep(RelativeChangeLimit(.05))
            unit = 'entry_ATR_multiples' if key in {'trail_atr','exit_width'} else 'ratio'
        axes.append(ParameterAxis(key,value,domain,rule,(key,),unit))
        reason = ('Effective continuous parameter: full center and +/-5% Cartesian combinations.' if key in active else
            'Exit width is inactive under hard exit; retain exact center value.' if key == 'exit_width' else
            'Confirmation count is inactive under hard/ramp/ramp_rebuild exits; retain exact center value.' if key == 'confirm_bars' else
            'Minimum integer change exceeds 5%; fixed at center.' if type(value) is int else 'Fixed structural category/boolean.')
        explanations.append({'parameter':key,'center':value,'varies':key in active,'reason':reason})
    mapping = {'center_id':center.candidate_id,'content_hash':center.content_identity.content_sha256,
        'axes':explanations,'payload_mapping':'Axis names map directly to complete strategy parameters.'}
    feasibility = {'source_unchanged':True,'fixed_structure':True,'fraction_domains':'0 < weak_fraction,quiet_fraction <= 1',
        'positive_ratios_and_ATR_widths':True,'integer_domains':'1..64; hold_days 1..65',
        'inactive_coordinate_domains':'Only inactive confirm_bars, and exit_width under hard exit, use singleton domains; all effective axes retain natural domains.',
        'warmup':'Unchanged 900/65 warmup covers fixed spans; inactive hard-exit width is retained.'}
    result = build_parameter_neighborhood_design(ParameterNeighborhoodRequest(
        AssessmentCandidate('S019-'+center.candidate_id,center.content_identity.content_sha256),
        ParameterNeighborhoodProtocol(max_combinations=1000000),
        ParameterNeighborhoodSpace(tuple(axes),sha256(core.encoded(mapping)).hexdigest(),sha256(core.encoded(feasibility)).hexdigest())),
        feasibility=lambda values:True)
    assert result.status.value == 'COMPLETE'
    assert result.design.point_count == POINT_COUNTS[center.candidate_id]
    return result.design,mapping,feasibility


def used_ids(exclude=None):
    used = set()
    for folder in (ROOT/'research/S019/experiments',ROOT/'research/registrations/S019'):
        for path in folder.rglob('*.json'):
            if exclude is None or not path.is_relative_to(exclude):
                used.update(core.candidate_ids_in_record(path.read_text(encoding='utf-8')))
    for path in (ROOT/'research/S019/assets/candidates').iterdir():
        if re.fullmatch(r'C\d{4}',path.name):
            used.add(path.name)
    assert used
    return used


def authenticate_header(ref_dict,center,pressure):
    ref = core.d.EvidenceRef.from_dict(ref_dict)
    assert ref.experiment.strategy_id == 'S019' and ref.schema == 'equity_research' and ref.schema_version == 4
    raw = ref.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest() == ref.sha256
    header = json.loads(raw)
    request = header['request']
    assert request['candidate_id'] == center.candidate_id
    assert request['candidate_definition'] == normalize(center.definition.to_dict())
    assert request['content_sha256'] == center.content_identity.content_sha256
    assert request['candidate_identity'] == asdict(center.content_identity)
    assert request['fee_rate'] == (.002 if pressure else .001)
    assert request['scenario_id'] == ('STRESS' if pressure else 'STANDARD')
    assert request['measurement_tier'] == ('STRESS' if pressure else 'FORMAL')
    assert request['window_id'] == 'FULL' and request['lineage'] is None
    return header


def preflight(work,scratch):
    assert work.parent == ROOT/'research/S019/experiments' and work.name == 'EX050_20261111'
    scope = core.read(work/'protocols/scope.json')
    originals = core.read(work/'protocols/centers.json')
    assert tuple(scope['selected']) == tuple(r['id'] for r in originals) == IDS
    assert scope['expected_parameter_counts'] == POINT_COUNTS
    resources = scope['resources']
    assert resources['workers'] == resources['batch_size'] == 61 and resources['native_threads'] == 1
    core.ExecutionResources(resources['workers'],resources['native_threads'],resources['random_seed'])
    assert (work/'src/strategy.py').read_bytes() == SOURCE.read_bytes()
    assert core.equity_source_hash(work/'src',('strategy.py',)) == SOURCE_HASH
    repo = core.RepositoryContext.discover(ROOT)
    centers = [core.load_candidate(repo,CandidateKey('S019',cid)) for cid in IDS]
    designs = [construction(c) for c in centers]
    next_id = first = scope['first_child']
    assert type(first) is int and first+sum(POINT_COUNTS.values()) <= 10000
    prior = used_ids(exclude=work)
    reserved = {f'C{i:04}' for i in range(first,first+sum(POINT_COUNTS.values()))}
    assert first == max(int(cid[1:]) for cid in prior)+1 and not reserved & prior
    children, jobs = {}, []
    for center,original,(design,mapping,feasibility) in zip(centers,originals,designs,strict=True):
        assert original['definition'] == normalize(center.definition.to_dict())
        assert original['content_hash'] == center.content_identity.content_sha256
        assert center.definition.source_sha256 == SOURCE_HASH
        for key in ('center_account','stress_account'):
            authenticate_header(original[key],center,key == 'stress_account')
            pointer = work/f'others/{center.candidate_id}_{"center" if key == "center_account" else "stress"}_ref.json'
            core.immutable(pointer,original[key],scratch)
        for suffix,value in (('design',design.to_dict()),('mapping',mapping),('feasibility',feasibility)):
            core.immutable(work/f'protocols/{center.candidate_id}_{suffix}.json',value,scratch)
        group = []
        for index,point in enumerate(design.points):
            parameters = {v.name:v.value for v in point.values}
            child = replace(center,candidate_id=f'C{next_id:04}',source_root=work/'src',definition=replace(center.definition,
                parameters_json=json.dumps(parameters,sort_keys=True,separators=(',',':'))))
            next_id += 1
            group.append(child)
            jobs.append({'parent':center.candidate_id,'label':f'P{index:03}','candidate_id':child.candidate_id,
                'content_hash':child.content_identity.content_sha256,'parameters':parameters,'fee_rate':.001})
        children[center.candidate_id] = group
    assert next_id-first == 1698 and len(jobs) == 1698
    core.immutable(work/'protocols/job_manifest.json',jobs,scratch)
    dependencies = {Path(core.__file__).resolve().relative_to(ROOT).as_posix():core.digest(Path(core.__file__))}
    for name in ('runner','data_window','prepare_data','load_data'):
        path = Path(sys.modules[name].__file__).resolve()
        dependencies[path.relative_to(ROOT).as_posix()] = core.digest(path)
    manifest = {'version':1,'experiment':work.name,'runner_sha256':core.digest(Path(__file__)),
        'plan_sha256':core.digest(work/'protocols/plan.md'),'centers_sha256':core.digest(work/'protocols/centers.json'),
        'scope_sha256':core.digest(work/'protocols/scope.json'),'jobs_sha256':core.digest(work/'protocols/job_manifest.json'),
        'source_hashes':[SOURCE_HASH],'dependencies':dependencies,'resources':resources,
        'design_sha256':{cid:core.digest(work/f'protocols/{cid}_design.json') for cid in IDS},
        'checkpoint_run_id':'ex050-three-complete-neighborhoods','parameter_counts':POINT_COUNTS,
        'expected_new_strategy_runs':1698,'expected_reused_strategy_accounts':6,'expected_strategy_scenarios':1704,
        'expected_new_benchmark_runs':1,'reused_standard_centers':list(IDS),'reused_stress_centers':list(IDS),
        'first_child':first,'next_candidate_start':next_id,'reserved_proposed_candidate_ids':sorted(reserved),
        'new_search_trials':0,'optimizer_rounds_debited':0,
        'reuse_rule':'Only original standard and stress evidence is reused; every new child retains its exact parent and plan lineage.'}
    core.immutable(work/'protocols/run_manifest.json',manifest,scratch)
    print('PREFLIGHT_PASS',POINT_COUNTS,'new 1698; reuse 6; workers',resources['workers'],flush=True)
    return repo,originals,centers,designs,children,scope,manifest


def request_for(exp,candidate,pressure=False):
    value = core.request_for(exp,candidate)
    return replace(value,fee_rate=.002,scenario_id='STRESS',measurement_tier='STRESS') if pressure else value


def audit_basic(payload):
    run = payload['runs']['candidate']
    assert all(r['observed_through'] <= r['decision_at'] <= r['execution_start'] and 0 <= r['target'] <= 1 for r in run['decisions'])
    assert all(r['cash'] >= -1e-8 and r['quantity'] >= 0 for r in run['account_points'])
    assert all(r['quantity'] > 0 and r['quantity'] == int(r['quantity']) for r in run['fills'])


def account_row(parent,label,handle,ref,payload,reused=False):
    current = json.loads(handle.contract_content)
    if reused:
        core.check_reuse_contract(payload['request'],current)
    else:
        assert payload['request'] == current and payload['request_hash'] == sha256(handle.contract_content).hexdigest()
        assert payload['request']['lineage'] is not None
    audit_basic(payload)
    run,bh = payload['runs']['candidate'],payload['runs']['buy_hold']
    m,b = core.metrics(run,bh['metrics']['daily_max_drawdown']),core.metrics(bh,bh['metrics']['daily_max_drawdown'])
    gates = m['gates'] if label == 'CENTER' else {'nar':m['nar'] >= .5,'calmar':m['calmar'] is not None and m['calmar'] >= 4.5,
        'absolute_dd':m['drawdown'] <= .25,'relative_dd':(m['drawdown'] < b['drawdown'] if b['drawdown'] > 0 else m['drawdown'] == 0)
        if label == 'STRESS' else m['drawdown'] <= .9*b['drawdown']}
    return {'parent':parent,'label':label,'candidate_id':handle.candidate.candidate_id,
        'content_hash':handle.candidate.content_identity.content_sha256,'request_sha256':payload['request_hash'],
        'prepared_request_sha256':sha256(handle.contract_content).hexdigest(),
        'parameters':json.loads(handle.candidate.definition.parameters_json),'definition':normalize(handle.candidate.definition.to_dict()),
        'account_ref':ref.to_dict(),'candidate':m,'benchmark':b,'selfcheck_gates':gates,'selfcheck_pass':all(gates.values()),
        'chronology_cash_integer_audit':'PASS','role':'REUSED_EVIDENCE' if reused else 'SELF_CHECK'}


def write_assessment_inputs(work,originals,result,scope,scratch):
    core.immutable(work/'others/center_accounts.json',{row['id']:row['center_account'] for row in originals},scratch)
    core.immutable(work/'others/assessment_inputs.json',{'source_candidates':scope['predecessor'],
        'source_mandate':scope['source_mandate'],'centers':[{'id':row['id'],
            'center_account':row['center_account'],'stress_account':row['stress_account'],
            'parameter_plan':core.read(work/f'others/{row["id"]}_parameter_plan_ref.json'),
            'parameter_accounts':[result['accounts'][f'{row["id"]}_P{i:03}']['account_ref'] for i in range(POINT_COUNTS[row['id']])]} for row in originals]},scratch)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment',type=Path,required=True)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--recover',action='store_true')
    args = parser.parse_args()
    assert not args.recover or args.run
    work = args.experiment.resolve()
    scratch = ROOT/'.tmp/s019-ex050-accounts'
    scratch.mkdir(parents=True,exist_ok=True)
    os.environ.update(TEMP=str(scratch),TMP=str(scratch),PYTHONDONTWRITEBYTECODE='1')
    repo,originals,centers,designs,children,scope,manifest = preflight(work,scratch)
    if not args.run:
        return
    result_path,attempts_path = work/'others/account_results.json',work/'others/account_attempts.json'
    assert args.recover or (not result_path.exists() and not attempts_path.exists())
    result = core.read(result_path) if result_path.exists() else {'status':'RUNNING','accounts':{},'batches':[],
        'manifest':manifest,'new_search_trials':0,'reused_center_accounts':3,'reused_stress_accounts':3}
    assert result['manifest'] == manifest
    result.update(status='RUNNING',error=None)
    attempts = core.read(attempts_path) if attempts_path.exists() else []
    for old in attempts:
        if old['status'] == 'RUNNING':
            old.update(status='INTERRUPTED_WITH_PARTIAL_STATISTICS',statistics_complete=False)
    attempt = {'attempt':len(attempts)+1,'started_utc':datetime.now(timezone.utc).isoformat(),'status':'RUNNING',
        'statistics_complete':True,'equity_statistics':core.zero_statistics(),'elapsed_seconds':0.,
        'completed_at_start':len(result['accounts']),'error':None,'resources':manifest['resources']}
    attempts.append(attempt)
    core.save(attempts_path,attempts,scratch)
    resource = manifest['resources']
    base = core.replay_context(repo,centers[0].definition.execution_spec)
    context = replace(base,evaluation=core.EvaluationAccess(dataflows=base.data,
        resources=core.ExecutionResources(resource['workers'],resource['native_threads'],resource['random_seed']),
        strategy_id=base.strategy_id,execution_spec=base.execution_spec))
    exp = core.d.ExperimentRef('S019',work.name)
    checkpoint = core.d.ExecutionCheckpointRequest(manifest['checkpoint_run_id'],
        core.d.CheckpointMode.RESUME if args.recover else core.d.CheckpointMode.CREATE)
    execution,started,caught,in_compute = None,perf_counter(),None,False

    def snapshot(status):
        attempt.update(status=status,elapsed_seconds=perf_counter()-started,
            equity_statistics=asdict(execution.equity_statistics) if execution is not None and execution.equity_statistics is not None else core.zero_statistics())
        if execution is not None:
            attempt['execution_stats'] = asdict(execution.stats)
            if attempt['execution_stats']['unknown']:
                attempt['statistics_complete'] = False
        core.save(attempts_path,attempts,scratch)
        workload = {key:sum(a['equity_statistics'][key] for a in attempts) for key in ('input_snapshots','candidate_runs','benchmark_runs')}
        workload.update(account_timings=[t for a in attempts for t in a['equity_statistics']['account_timings']],
            reused_accounts=sum(r['role'] == 'REUSED_EVIDENCE' for r in result['accounts'].values()),
            scenario_accounts=len(result['accounts']))
        result.update(status=status,workload=workload,elapsed_seconds=sum(a['elapsed_seconds'] for a in attempts),
            replay_statistics_complete=all(a['statistics_complete'] for a in attempts),attempt_count=len(attempts))
        core.save(result_path,result,scratch)

    try:
        with core.d.ResearchExecutionSession(context,experiment=exp,checkpoint=checkpoint,on_progress=lambda p:print(p,flush=True)) as execution:
            jobs = []
            reused_prepared = []
            for center,original,(design,mapping,feasibility) in zip(centers,originals,designs,strict=True):
                central = context.evaluation.prepare(request_for(exp,center),execution=execution)
                stress = context.evaluation.prepare(request_for(exp,center,True),execution=execution)
                for label,handle,key_ref in (('CENTER',central,'center_account'),('STRESS',stress,'stress_account')):
                    key = center.candidate_id+'_'+label
                    pointer = work/f'others/{center.candidate_id}_{"center" if label == "CENTER" else "stress"}_ref.json'
                    ref,payload = core.read_account(pointer)
                    assert ref.to_dict() == original[key_ref]
                    row = account_row(center.candidate_id,label,handle,ref,payload,True)
                    if key in result['accounts']:
                        assert result['accounts'][key] == row
                    result['accounts'][key] = row
                    core.immutable(work/f'others/{key}_account.json',ref.to_dict(),scratch)
                    core.immutable(work/f'others/{key}_reuse.json',{'status':'PASS','source_account':ref.to_dict(),
                        'source_request_sha256':payload['request_hash'],'prepared_request_sha256':sha256(handle.contract_content).hexdigest(),
                        'request_match':'EXACT_EXCEPT_EXPERIMENT'},scratch)
                    reused_prepared.append({'key':key,'request_sha256':sha256(handle.contract_content).hexdigest(),
                        'source_request_sha256':payload['request_hash'],'source_account':ref.to_dict()})
                    snapshot('RUNNING')
                def material(name,value):
                    return core.publish_evidence(context,core.d.MaterialEvidenceWrite(exp,
                        center.candidate_id+'-'+name,core.encoded(value),'application/json','json'))
                map_ref,feasible_ref = material('mapping',mapping),material('feasibility',feasibility)
                group = children[center.candidate_id]
                planning_started = perf_counter()
                print('PARAMETER_PREPARATION_STARTED',center.candidate_id,len(group),flush=True)
                unbound = tuple(context.evaluation.prepare(request_for(exp,child),execution=execution) for child in group)
                print('UNBOUND_PREPARED',center.candidate_id,len(unbound),perf_counter()-planning_started,flush=True)
                plan = core.d.ParameterEvaluationPlan.create(design,central,unbound,mapping_evidence=map_ref,
                    feasibility_evidence=feasible_ref,dataflows=context.data,execution=execution)
                core.immutable(work/f'others/{center.candidate_id}_parameter_plan.json',plan.to_dict(),scratch)
                plan_ref = material('parameter-plan',plan.to_dict())
                core.immutable(work/f'others/{center.candidate_id}_parameter_plan_ref.json',plan_ref.to_dict(),scratch)
                for index,(child,point,handle) in enumerate(zip(group,design.points,unbound,strict=True)):
                    derivation = CandidateDerivation(center.key,center.content_identity.content_sha256,child.key,
                        child.content_identity.content_sha256,CandidateDerivationKind.PARAMETERS,
                        {v.name:v.value for v in point.values},design.protocol.sha256,
                        CandidateEvidence(plan_ref.resolve(ROOT).relative_to(ROOT).as_posix(),plan_ref.sha256))
                    bound = replace(handle.request,lineage=core.d.EvaluationLineage(derivation,
                        plan.bind_point(plan_ref,index,repository_root=ROOT)))
                    jobs.append((center.candidate_id,f'P{index:03}',context.evaluation.prepare(bound,execution=execution)))
                print('LINEAGE_PLAN_READY',center.candidate_id,len(group),perf_counter()-planning_started,flush=True)
            assert len(jobs) == 1698 and len(reused_prepared) == 6
            assert len({handle.snapshot.sha256 for _,_,handle in jobs}) == 1
            assert len({handle.benchmark_identity.sha256 for _,_,handle in jobs}) == 1
            core.immutable(work/'protocols/reused_request_manifest.json',reused_prepared,scratch)
            core.immutable(work/'protocols/prepared_request_manifest.json',[{'key':parent+'_'+label,
                'request_sha256':sha256(handle.contract_content).hexdigest(),'content_hash':handle.candidate.content_identity.content_sha256,
                'benchmark_identity':handle.benchmark_identity.sha256,'input_snapshot_sha256':handle.snapshot.sha256}
                for parent,label,handle in jobs],scratch)
            pending = []
            for parent,label,handle in jobs:
                key = parent+'_'+label
                pointer = work/f'others/{key}_account.json'
                if pointer.exists():
                    ref = core.d.EvidenceRef.from_dict(core.read(pointer))
                    raw = ref.resolve(ROOT).read_bytes()
                    assert sha256(raw).hexdigest() == ref.sha256
                    header = json.loads(raw)
                    assert header['request'] == json.loads(handle.contract_content)
                    assert header['request_hash'] == sha256(handle.contract_content).hexdigest()
                    if key in result['accounts']:
                        row = result['accounts'][key]
                        assert row['account_ref'] == ref.to_dict() and row['request_sha256'] == header['request_hash']
                        assert row['definition'] == header['request']['candidate_definition']
                        assert row['content_hash'] == handle.candidate.content_identity.content_sha256
                    else:
                        ref,payload = core.read_account(pointer)
                        result['accounts'][key] = account_row(parent,label,handle,ref,payload)
                else:
                    assert key not in result['accounts']
                    pending.append((parent,label,handle))
            assert set(result['accounts']) <= {parent+'_'+label for parent,label,_ in jobs} | {r['key'] for r in reused_prepared}
            snapshot('RUNNING')
            print('PLANS_READY',len(pending),'pending, workers',resource['workers'],flush=True)
            for offset in range(0,len(pending),resource['batch_size']):
                group = pending[offset:offset+resource['batch_size']]
                begun,in_compute = perf_counter(),True
                outcomes = context.evaluation.evaluate_many(tuple(h for _,_,h in group),execution=execution)
                in_compute = False
                snapshot('RUNNING')
                statuses = []
                for (parent,label,handle),outcome in zip(group,outcomes,strict=True):
                    key = parent+'_'+label
                    statuses.append({'key':key,'status':outcome.status.value,'error':str(outcome.error) if outcome.error else None})
                    if outcome.result is None:
                        continue
                    ref = core.publish_evidence(context,core.d.EvaluationEvidenceWrite(exp,key,handle,outcome.result),execution=execution)
                    core.immutable(work/f'others/{key}_account.json',ref.to_dict(),scratch)
                    payload = core.materialize_equity(outcome.result).payload
                    row = account_row(parent,label,handle,ref,payload)
                    result['accounts'][key] = row
                    core.immutable(work/f'others/{key}_result.json',row,scratch)
                    print('ACCOUNT',key,row['candidate']['nar'],row['candidate']['calmar'],row['selfcheck_pass'],flush=True)
                result['batches'].append({'attempt':attempt['attempt'],'statuses':statuses,'seconds':perf_counter()-begun})
                snapshot('RUNNING')
                assert all(s['status'] == 'SUCCEEDED' for s in statuses), 'Inspect failed/unknown work before explicit recovery'
            assert len(result['accounts']) == 1704
            result['status'] = 'COMPLETE'
    except BaseException as error:
        caught = error
        if in_compute:
            attempt['statistics_complete'] = False
        result['error'] = attempt['error'] = repr(error)
        raise
    finally:
        snapshot('COMPLETE' if caught is None and result['status'] == 'COMPLETE' else 'STOPPED')
    write_assessment_inputs(work,originals,result,scope,scratch)
    print('STAGE4_ACCOUNTS_COMPLETE',len(result['accounts']),result['workload']['candidate_runs'],
        result['workload']['benchmark_runs'],'reused',result['workload']['reused_accounts'],flush=True)


if __name__ == '__main__':
    main()
