"""Execute the complete bounded neighborhoods and two center fee stresses via TDR."""
from dataclasses import asdict, replace
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from time import perf_counter
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / '.tmp/s019-stage4'
SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ.update(TEMP=str(SCRATCH), TMP=str(SCRATCH), OMP_NUM_THREADS='1',
    OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
sys.path.insert(0, str(WORK.parent / 'EX013_20261110/src'))
from runner import metrics  # noqa: E402
from data_window import replay_context, HISTORY_START, SOURCE  # noqa: E402
from czsc_trader import research_tools as d  # noqa: E402
from czsc_trader.application import RepositoryContext, load_candidate, publish_evidence  # noqa: E402
from czsc_trader.research_tools.equity_replay import materialize_equity  # noqa: E402
from dataflows import TimeInterval  # noqa: E402
from strategy_manager import CandidateKey, CandidateDerivation, CandidateDerivationKind, CandidateEvidence  # noqa: E402
from strategy_evaluator import (AssessmentCandidate, ParameterAxis, BooleanDomain, CategoricalDomain,  # noqa: E402
    RealDomain, IntegerDomain, ExplicitValues, BoundedLocalStep, RelativeChangeLimit,
    ParameterNeighborhoodProtocol, ParameterNeighborhoodRequest, ParameterNeighborhoodSpace,
    build_parameter_neighborhood_design)

EXP = d.ExperimentRef('S019', WORK.name)


def read(path):
    return json.loads(path.read_bytes())


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode()


def save(path, value):
    temporary = SCRATCH / (path.name+'.pending')
    temporary.write_bytes(encoded(value))
    os.replace(temporary, path)


def request_for(candidate, pressure=False):
    zone = ZoneInfo('America/New_York')
    window = TimeInterval(datetime(2022,1,3,9,30,tzinfo=zone), datetime(2026,10,30,16,tzinfo=zone))
    return d.EquityEvaluationRequest(EXP,candidate,window,HISTORY_START,d.EquitySources(SOURCE,SOURCE,SOURCE),
        100000., .002 if pressure else .001, benchmark=d.EvaluationBenchmark(d.EquityBuyHold(candidate.definition.execution_spec)),
        window_id='FULL',scenario_id='STRESS' if pressure else 'STANDARD',
        measurement_tier='STRESS' if pressure else 'FORMAL',drawdown_basis='SESSION_CLOSE',concentration_basis='MAX_SINGLE')


def construction(center):
    params = json.loads(center.definition.parameters_json)
    axes, explanations = [], []
    active = {'weak_fraction','trail_atr'} | ({'participation_threshold','quiet_fraction'} if center.candidate_id=='C0224' else set())
    for key,value in sorted(params.items()):
        if type(value) is bool:
            domain,rule,unit = BooleanDomain(),ExplicitValues((value,)),'fixed_structure'
        elif type(value) is str:
            domain,rule,unit = CategoricalDomain((value,)),ExplicitValues((value,)),'fixed_structure'
        elif type(value) is int:
            domain = IntegerDomain(1,65 if key=='hold_days' else 64)
            rule,unit = BoundedLocalStep(RelativeChangeLimit(.05)),'trading_sessions'
        else:
            assert key in active
            domain = RealDomain(0.,1.,lower_closed=False) if key in ('weak_fraction','quiet_fraction') else RealDomain(0.,sys.float_info.max,lower_closed=False)
            rule,unit = BoundedLocalStep(RelativeChangeLimit(.05)),'ratio'
        axes.append(ParameterAxis(key,value,domain,rule,(key,),unit))
        explanations.append({'parameter':key,'center':value,'varies':key in active,
            'reason':'Continuous business parameter, +/-5%; search step is not a legal quantization.' if key in active else
            'Integer minimum one-session change exceeds5%; retained at center.' if type(value) is int else
            'Fixed structural category/boolean; no structural changes in this sensitivity test.'})
    mapping={'center_id':center.candidate_id,'content_hash':center.content_identity.content_sha256,
        'axes':explanations,'payload_mapping':'Axis names map directly to complete strategy parameters.'}
    feasibility={'source_unchanged':True,'fixed_structure':True,'fraction_domains':'0 < weak_fraction,quiet_fraction <= 1',
        'positive_atr_and_participation_threshold':True,'integer_domains':'1..64 for input spans;1..65 for held-count horizon',
        'warmup':'Both unchanged registered warmups cover all fixed spans; no new data or lookback needed.'}
    result=build_parameter_neighborhood_design(ParameterNeighborhoodRequest(
        AssessmentCandidate(f'S019-{center.candidate_id}',center.content_identity.content_sha256),
        ParameterNeighborhoodProtocol(max_combinations=1000000),ParameterNeighborhoodSpace(tuple(axes),sha256(encoded(mapping)).hexdigest(),sha256(encoded(feasibility)).hexdigest())),
        feasibility=lambda values: True)
    assert result.status.value=='COMPLETE', result
    design=result.design
    assert design.point_count == (8 if center.candidate_id=='C0135' else 80)
    return design,mapping,feasibility


def main():
    execute = '--run' in sys.argv
    recover = '--recover' in sys.argv
    repo = RepositoryContext.discover(ROOT)
    centers=[load_candidate(repo,CandidateKey('S019',row['id'])) for row in read(WORK/'protocols/centers.json')]
    specs=[construction(center) for center in centers]
    for center,(design,mapping,feasibility) in zip(centers,specs,strict=True):
        for suffix,value in (('design',design.to_dict()),('mapping',mapping),('feasibility',feasibility)):
            path=WORK/f'protocols/{center.candidate_id}_{suffix}.json'
            if path.exists():
                assert read(path)==json.loads(encoded(value))
            else:
                save(path,value)
    print('PREFLIGHT_PASS',[(c.candidate_id,s[0].point_count) for c,s in zip(centers,specs,strict=True)],flush=True)
    if not execute:
        return
    result_path=WORK/'others/account_results.json'
    assert recover or not result_path.exists(), 'Existing results require explicit inspection and recovery'
    result=read(result_path) if result_path.exists() else {'status':'RUNNING','accounts':{},'batches':[]}
    assert result['status']!='COMPLETE', 'Completed account batch must be reused'
    started=perf_counter()
    context=replay_context(repo,centers[0].definition.execution_spec)
    jobs=[]
    next_id=246
    try:
        with d.ResearchExecutionSession(context,experiment=EXP,on_progress=lambda x:print(x,flush=True)) as execution:
            for center,(design,mapping,feasibility) in zip(centers,specs,strict=True):
                def material(name,value):
                    return publish_evidence(context,d.MaterialEvidenceWrite(EXP,f'{center.candidate_id}-{name}',encoded(value),'application/json','json'))
                map_ref,feasible_ref=material('mapping',mapping),material('feasibility',feasibility)
                central=context.evaluation.prepare(request_for(center),execution=execution)
                children=[]
                for point in design.points:
                    parameters={v.name:v.value for v in point.values}
                    child=replace(center,candidate_id=f'C{next_id:04}',definition=replace(center.definition,
                        parameters_json=json.dumps(parameters,sort_keys=True,separators=(',',':'))))
                    assert not (ROOT/f'research/S019/assets/candidates/{child.candidate_id}').exists()
                    next_id+=1
                    children.append(child)
                prepared=tuple(context.evaluation.prepare(request_for(child),execution=execution) for child in children)
                plan=d.ParameterEvaluationPlan.create(design,central,prepared,mapping_evidence=map_ref,
                    feasibility_evidence=feasible_ref,dataflows=context.data,execution=execution)
                plan_path=WORK/f'others/{center.candidate_id}_parameter_plan.json'
                if plan_path.exists():
                    assert read(plan_path)==json.loads(encoded(plan.to_dict()))
                save(plan_path,plan.to_dict())
                plan_ref=material('parameter-plan',plan.to_dict())
                save(WORK/f'others/{center.candidate_id}_parameter_plan_ref.json',plan_ref.to_dict())
                pressure=context.evaluation.prepare(request_for(center,True),execution=execution)
                jobs.append((center.candidate_id,'STRESS',pressure))
                for index,(child,point,handle) in enumerate(zip(children,design.points,prepared,strict=True)):
                    derivation=CandidateDerivation(center.key,center.content_identity.content_sha256,
                        child.key,child.content_identity.content_sha256,CandidateDerivationKind.PARAMETERS,
                        {v.name:v.value for v in point.values},design.protocol.sha256,
                        CandidateEvidence(plan_ref.resolve(ROOT).relative_to(ROOT).as_posix(),plan_ref.sha256))
                    bound=replace(handle.request,lineage=d.EvaluationLineage(derivation,plan.bind_point(plan_ref,index,repository_root=ROOT)))
                    jobs.append((center.candidate_id,f'P{index:03}',context.evaluation.prepare(bound,execution=execution)))
            assert len(jobs)==90
            save(WORK/'protocols/job_manifest.json',[{'parent':parent,'label':label,'candidate_id':h.candidate.candidate_id,
                'content_hash':h.candidate.content_identity.content_sha256,'parameters':json.loads(h.candidate.definition.parameters_json)} for parent,label,h in jobs])
            pending=[]
            for parent,label,handle in jobs:
                key=f'{parent}_{label}'
                if key in result['accounts']:
                    row=result['accounts'][key]
                    ref=d.EvidenceRef.from_dict(row['account_ref'])
                    assert sha256(ref.resolve(ROOT).read_bytes()).hexdigest()==ref.sha256
                    assert row['content_hash']==handle.candidate.content_identity.content_sha256
                else:
                    pending.append((parent,label,handle))
            print('PLANS_READY',len(pending),'new strategy accounts',flush=True)
            for offset in range(0,len(pending),4):
                batch=pending[offset:offset+4]
                begun=perf_counter()
                outcomes=context.evaluation.evaluate_many(tuple(h for _,_,h in batch),execution=execution)
                statuses=[]
                for (parent,label,handle),outcome in zip(batch,outcomes,strict=True):
                    key=f'{parent}_{label}'
                    statuses.append({'key':key,'status':outcome.status.value,'error':str(outcome.error) if outcome.error else None})
                    if outcome.result is None:
                        continue
                    ref=publish_evidence(context,d.EvaluationEvidenceWrite(EXP,key,handle,outcome.result),execution=execution)
                    payload=materialize_equity(outcome.result).payload
                    run,bh=payload['runs']['candidate'],payload['runs']['buy_hold']
                    m,b=metrics(run,bh['metrics']['daily_max_drawdown']),metrics(bh,bh['metrics']['daily_max_drawdown'])
                    assert all(x['observed_through']<=x['decision_at']<=x['execution_start'] and 0<=x['target']<=1 for x in run['decisions'])
                    assert all(x['cash']>=-1e-8 and x['quantity']>=0 for x in run['account_points'])
                    assert all(x['quantity']>0 and x['quantity']==int(x['quantity']) for x in run['fills'])
                    gates={'nar':m['nar']>=.5,'calmar':m['calmar'] is not None and m['calmar']>=4.5,
                        'relative_dd':m['drawdown']<b['drawdown'] if label=='STRESS' else m['drawdown']<=.9*b['drawdown'],
                        'absolute_dd':m['drawdown']<=.25}
                    result['accounts'][key]={'parent':parent,'label':label,'candidate_id':handle.candidate.candidate_id,
                        'content_hash':handle.candidate.content_identity.content_sha256,'parameters':json.loads(handle.candidate.definition.parameters_json),
                        'definition':handle.candidate.definition.to_dict(),'account_ref':ref.to_dict(),
                        'candidate':m,'benchmark':b,'selfcheck_gates':gates,'selfcheck_pass':all(gates.values()),
                        'chronology_cash_integer_audit':'PASS'}
                    save(result_path,result)
                    save(WORK/f'others/{key}_account.json',ref.to_dict())
                    print('ACCOUNT',key,round(m['nar'],6),round(m['drawdown'],6),round(m['calmar'],6),all(gates.values()),flush=True)
                result['batches'].append({'statuses':statuses,'seconds':perf_counter()-begun})
                save(result_path,result)
                assert all(x['status']=='SUCCEEDED' for x in statuses), 'Stop on failed or unknown outcome; inspect before retry'
            result.update(status='COMPLETE',elapsed_seconds=perf_counter()-started,workload=asdict(execution.equity_statistics),
                execution_stats=asdict(execution.stats),new_search_trials=0,reused_center_accounts=2)
            assert len(result['accounts'])==90
            save(result_path,result)
    except BaseException as error:
        result.update(status='STOPPED',error=repr(error),elapsed_seconds=perf_counter()-started)
        save(result_path,result)
        raise
    rows=[]
    for center in read(WORK/'protocols/centers.json'):
        cid=center['id']
        rows.append({'id':cid,'center_account':center['account_ref'],
            'stress_account':result['accounts'][f'{cid}_STRESS']['account_ref'],
            'parameter_plan':read(WORK/f'others/{cid}_parameter_plan_ref.json'),
            'parameter_accounts':[r['account_ref'] for r in result['accounts'].values() if r['parent']==cid and r['label']!='STRESS']})
    save(WORK/'others/assessment_inputs.json',{'source_candidates':read(ROOT/'research/S019/deliveries/CANDIDATES/5/receipt.json')['reference'],
        'source_mandate':read(ROOT/'research/S019/deliveries/MANDATE/2/receipt.json')['reference'],'centers':rows})
    print('STAGE4_ACCOUNTS_COMPLETE',len(result['accounts']),flush=True)


if __name__=='__main__':
    main()
