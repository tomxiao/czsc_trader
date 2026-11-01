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
    if checked['helper_sha256']!=digest(WORK/'src/session_features.py') or checked['precheck_sha256']!=digest(WORK/'src/precheck.py'):raise ValueError('Exact helper and executed precheck required')
    research,prepared,_=prepare_data()
    candidates={key:candidate(key) for key in PARAMETERS}
    save(WORK/'protocols/definitions.json',{k:v.definition.to_dict() for k,v in candidates.items()})
    frozen={str(p.relative_to(WORK)).replace('\\','/'):material(research,'pre-'+str(i),p).to_dict()
        for i,p in enumerate([*sorted((WORK/'src').glob('*.py')),*sorted((WORK/'protocols').glob('*.*'))])}
    for name,path in [('reused-entry-census',WORK/'others/reused_entry_census.json')]:
        frozen['pre-account/'+name]=material(research,name,path).to_dict()
    for name,sha in {'s017_upper_events_c222_clock_coverage.py':'75400f71b1c2c9d84ea9daf70cdabdbe804b7dd76a3319d41f1b35834568cc91','s017_upper_events_c222_clock_coverage.json':'919a3f734d13633a0c472572d8d4a57c3bbb9d1d899c096dcfe6cc5d57247016'}.items():
        path=ROOT/'.tmp'/name
        if digest(path)!=sha:raise ValueError('Outcome-blind prior coverage bytes differ')
        frozen['prior-coverage/'+name]=material(research,name,path).to_dict()
    frozen['all-clock-market-mapping']=material(research,'all-clock-market-mapping',WORK/'others/all_clock_features_precheck.json').to_dict()
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
    summaries={}
    for key,payload in payloads.items():
        c=summary(payload['runs']['candidate'],100000.); b=summary(payload['runs']['buy_hold'],100000.)
        goals={'annualized_return':(c['annualized_return']>=1.5*b['annualized_return'] if b['annualized_return']>0 else c['annualized_return']>0),'relative_drawdown':c['bar_max_drawdown']<=.8*b['bar_max_drawdown'],'absolute_drawdown':c['bar_max_drawdown']<=.25,'frequency_median':c['rolling_60_closed_cycle_median']>=6,'frequency_coverage':c['coverage_at_least_three']>=.9}
        summaries[key]={'parameters':PARAMETERS[key],'candidate':c,'benchmark':b,'goals':goals,'all_goals_met':all(goals.values())}
        print('RESULT',key,json.dumps({f:c[f] for f in ('annualized_return','bar_max_drawdown','closed_cycles','rolling_60_closed_cycle_median','coverage_at_least_three')}),flush=True)
    save(WORK/'others/analysis.json',{'status':'PASS','summaries':summaries,'source_accounts':manifest,'source_sha256':digest(WORK/'src/run.py'),'financial_strategy_sha256':digest(WORK/'src/strategy.py'),'session_helper_sha256':digest(WORK/'src/session_features.py'),'elapsed_seconds':perf_counter()-started,'sample':'Fixed UP_CROSS/UP_ACCEPT by STATIC_H/ACCEPTED2x2;four new policies;no new labels or parameter search;2026 sealed'})
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
