"""Formal, source-bound V4 mechanism comparison, with immutable negative results."""
from dataclasses import asdict
from datetime import date
import json
from time import perf_counter
from common import (ROOT,WORK,EXPERIMENT,REPOSITORY,PARAMETERS,context,prepare_data,candidate,request,save,read,digest,material)
from metrics import summary
from strategy_manager import CandidateKey
from czsc_trader.application import publish_evidence,publish_evidence_many,diagnose_accounts,validate_experiment
from czsc_trader.research_tools import (ResearchExecutionSession,ExecutionCheckpointRequest,EvaluationEvidenceWrite,
    AccountRunRef,AccountDiagnosisRequest,EvaluationIdentity,EvaluationWindow,EvidenceRef,
    ExperimentReportWrite,ExperimentOutcome,ExperimentValidationRequest,ExperimentValidationScope)
from czsc_trader.research_tools.equity_replay import materialize_equity

def main():
    started=perf_counter()
    checked=read(WORK/'others/precheck.json')
    if checked['status']!='PASS' or checked['strategy_sha256']!=digest(WORK/'src/strategy.py'): raise ValueError('Current precheck required')
    research,prepared,_=prepare_data()
    candidates={key:candidate(key) for key in PARAMETERS}
    save(WORK/'protocols/definitions.json',{k:v.definition.to_dict() for k,v in candidates.items()})
    frozen={str(p.relative_to(WORK)).replace('\\','/'):material(research,'pre-'+str(i),p).to_dict()
        for i,p in enumerate([*sorted((WORK/'src').glob('*.py')),*sorted((WORK/'protocols').glob('*.*'))])}
    for name,path in [('restart-authorization',ROOT/'research/S017/materials/STAGE2_FINANCIAL_LOGIC_RESTART_20261031.json'),('continuation-census-source',ROOT/'research/S017/materials/M005_CONTINUATION_CENSUS_20261031.py'),('continuation-census',ROOT/'research/S017/materials/M005_CONTINUATION_CENSUS_20261031.json'),('alternative-clues-source',ROOT/'.tmp/s017_training_alternative_clues.py'),('alternative-clues',ROOT/'.tmp/s017_training_alternative_clues.json'),('legacy-control-source',ROOT/'research/S017/experiments/EX050_20261031/src/strategy.py'),('legacy-boundary-impact',ROOT/'.tmp/s017_ex050_boundary_impact.json'),('withdrawn-work-proposal',ROOT/'research/S017/materials/STAGE3_FEASIBILITY_PROPOSAL_20261031.json')]:
        frozen['batch-material/'+name]=material(research,name,path).to_dict()
    save(WORK/'others/pre_run.json',frozen)
    with ResearchExecutionSession(research,experiment=EXPERIMENT,checkpoint=ExecutionCheckpointRequest(EXPERIMENT.experiment_id+'-v4-new-training-prepared'),on_progress=lambda e: print('PHASE',str(e.phase),e.completed,e.total,flush=True)) as execution:
        handles=tuple(research.evaluation.prepare(request(c,prepared),execution=execution) for c in candidates.values())
        outcomes=research.evaluation.evaluate_many(handles,execution=execution)
        save(WORK/'others/execution_status.json',[{'candidate':p.candidate.candidate_id,'status':o.status.value,'error':None if o.error is None else asdict(o.error)} for p,o in zip(handles,outcomes,strict=True)])
        if any(o.result is None or o.status.value!='SUCCEEDED' for o in outcomes): raise ValueError('Formal account failed')
        payloads={p.candidate.candidate_id:materialize_equity(o.result).payload for p,o in zip(handles,outcomes,strict=True)}
        pubs=publish_evidence_many(research,tuple(EvaluationEvidenceWrite(EXPERIMENT,'formal-'+p.candidate.candidate_id,p,o.result) for p,o in zip(handles,outcomes,strict=True)),execution=execution)
        if any(p.status.value!='PUBLISHED' for p in pubs): raise ValueError('Formal publication incomplete')
        manifest={p.candidate.candidate_id:{'evidence':pub.reference.to_dict(),'evaluation_identity':payloads[p.candidate.candidate_id]['evaluation_identity'],'evaluation_id':payloads[p.candidate.candidate_id]['evaluation_id'],'request_hash':o.result.request_hash} for p,o,pub in zip(handles,outcomes,pubs,strict=True)}
        save(WORK/'others/accounts.json',manifest)
        save(WORK/'others/execution_stats.json',{'session':asdict(execution.stats),'equity':asdict(execution.equity_statistics)})
    fresh_checks={}
    for key,payload in payloads.items():
        if payload['request']['initial_cash']!=100000.:raise ValueError('Initial cash must be 100000')
        for kind in ('candidate','buy_hold'):
            run=payload['runs'][kind];first=run['decisions'][0]
            if first['portfolio_revision']!=0:raise ValueError('Initial revision must be zero')
            if any(row['interval_start'][:10]<'2024-01-02' for row in run['fills']):raise ValueError('No inherited pre-training fills')
            if any(row['entry_at'][:10]<'2024-01-02' for row in run['trades']):raise ValueError('No inherited pre-training trades')
            if kind=='candidate':
                facts={v['key']:v['text'] for v in first['explanation']['basis']}
                if facts['portfolio_quantity']!='0' or float(facts['portfolio_cash'])!=100000. or facts['cycle_present']!='False':raise ValueError('Candidate must start empty')
            fresh_checks[key+'_'+kind]={'initial_revision':0,'no_pre_training_fills_or_trades':True}
    save(WORK/'others/fresh_start_validation.json',{'status':'PASS','checks':fresh_checks,'first_completed_point_may_hold':'Normal first-interval buy is allowed; not used as initial flat check'})
    from common import authenticate
    old_manifest=read(ROOT/'research/S017/experiments/EX050_20261031/others/accounts.json')
    old_path=authenticate(old_manifest['C0108']['evidence']); old_envelope=read(old_path)
    allowed={(old_envelope[n]['kind'],old_envelope[n]['sha256']) for n in ('input_ref','candidate_ref','benchmark_ref')}
    def resolve(item):
        if (item['kind'],item['sha256']) not in allowed:raise ValueError('Unowned control dependency')
        return (old_path.parent/(item['sha256']+'.json')).read_bytes()
    old=materialize_equity(old_path.read_bytes(),resolve).payload
    fields={'decisions':('observed_through','decision_at','execution_start','execution_end','target','reference_price','limit_price','quantity','side','signal_status'),'orders':('valid_start','valid_end','side','quantity','limit_price','status','reason'),'fills':('interval_start','interval_end','side','quantity','price','fees','time_precision'),'account_points':('time','cash','quantity','receivable','equity','close','session','valuation_stale'),'account_daily':('time','cash','quantity','receivable','equity','close','session','valuation_stale'),'trades':('entry_at','exit_at','cost','income','net_pnl','net_return','status')}
    checks={}
    for name in ('candidate','buy_hold'):
        for table,keys in fields.items():
            a=old['runs'][name][table];b=payloads['C0109']['runs'][name][table]
            equal=len(a)==len(b) and all(all(x[k]==y[k] for k in keys) for x,y in zip(a,b))
            checks[name+'_'+table]=equal
    save(WORK/'others/control_comparison.json',{'status':'PASS' if all(checks.values()) else 'FAIL','old_reference':old_manifest['C0108']['evidence'],'checks':checks,'ignored':'Identity, explanations and source hashes; complete listed economic fields checked'})
    if not all(checks.values()):raise ValueError('M005 control economic path changed')
    summaries={}
    for key,payload in payloads.items():
        c=summary(payload['runs']['candidate'],100000.); b=summary(payload['runs']['buy_hold'],100000.)
        goals={'annualized_return':(c['annualized_return']>=1.5*b['annualized_return'] if b['annualized_return']>0 else c['annualized_return']>0),'relative_drawdown':c['bar_max_drawdown']<=.8*b['bar_max_drawdown'],'absolute_drawdown':c['bar_max_drawdown']<=.25,'frequency_median':c['rolling_60_closed_cycle_median']>=6,'frequency_coverage':c['coverage_at_least_three']>=.9}
        summaries[key]={'parameters':PARAMETERS[key],'candidate':c,'benchmark':b,'goals':goals,'all_goals_met':all(goals.values())}
        print('RESULT',key,json.dumps({f:c[f] for f in ('annualized_return','bar_max_drawdown','closed_cycles','rolling_60_closed_cycle_median','coverage_at_least_three')}),flush=True)
    save(WORK/'others/analysis.json',{'status':'PASS','summaries':summaries,'source_accounts':manifest,'source_sha256':digest(WORK/'src/run.py'),'elapsed_seconds':perf_counter()-started,'sample':'Reused 2024-2025 training, whole-entry-interval-excluded 2x2 boundary policies; 2026 test sealed'})
    def ref(key):
        identity=dict(payloads[key]['evaluation_identity']); identity['candidate']=CandidateKey(**identity['candidate'])
        return AccountRunRef(EvidenceRef.from_dict(manifest[key]['evidence']),EvaluationIdentity(**identity))
    keys=list(manifest); diagnoses=[]
    for key in keys[1:]:
        d=diagnose_accounts(REPOSITORY,AccountDiagnosisRequest(ref(keys[0]),ref(key),EvaluationWindow('TRAIN_2024_2025',date(2024,1,2),date(2025,12,31))))
        if d.status.value!='COMPUTED' or any(abs(r.residual)>1e-6 for r in d.reconciliation): raise ValueError('Public diagnosis failed')
        diagnoses.append(publish_evidence(research,__import__('czsc_trader.research_tools',fromlist=['MaterialEvidenceWrite']).MaterialEvidenceWrite(EXPERIMENT,'diagnosis-'+key,json.dumps(d.to_dict(),ensure_ascii=False).encode(),'application/json','json')).to_dict())
    save(WORK/'others/diagnoses.json',diagnoses)
    print('ECONOMIC_EVIDENCE_READY_FOR_RESEARCH_REPORT',EXPERIMENT.experiment_id,flush=True)

if __name__=='__main__':main()
