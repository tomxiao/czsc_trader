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
    import optuna
    study=optuna.create_study(study_name='S017_EX056_ENTRY_BACKGROUND',directions=('maximize','minimize'),sampler=optuna.samplers.TPESampler(seed=17))
    trials={}
    for key in ('C0221','C0222'):
        pars=PARAMETERS[key];study.enqueue_trial({'g_when_u':pars['g_when_u'],'g_when_other':pars['g_when_other']})
    for key in ('C0221','C0222'):
        t=study.ask();u=t.suggest_float('g_when_u',0.,1.);other=t.suggest_float('g_when_other',0.,1.)
        if u!=PARAMETERS[key]['g_when_u'] or other!=PARAMETERS[key]['g_when_other']:raise ValueError('Only two fixed enqueued mappings permitted')
        trials[key]=t
    save(WORK/'others/study_launch.json',{'study_name':study.study_name,'fixed_enqueued':[{'candidate_id':key,'trial':t.number,'parameters':t.params} for key,t in trials.items()],'only_fixed_two':True,'no_adaptive_extension':True})
    candidates={key:candidate(key) for key in PARAMETERS}
    save(WORK/'protocols/definitions.json',{k:v.definition.to_dict() for k,v in candidates.items()})
    frozen={str(p.relative_to(WORK)).replace('\\','/'):material(research,'pre-'+str(i),p).to_dict()
        for i,p in enumerate([*sorted((WORK/'src').glob('*.py')),*sorted((WORK/'protocols').glob('*.*'))])}
    for name in ('s017_e0_prior_uptrend_geometry.py','s017_e0_prior_uptrend_geometry.json','s017_uprev_frequency_upper_bound.py','s017_uprev_frequency_upper_bound.json'):
        frozen['entry-background-geometry/'+name]=material(research,name,ROOT/'.tmp'/name).to_dict()
    frozen['study-api-precheck']=material(research,'fixed-study-api-precheck',WORK/'others/study_api_precheck.json').to_dict()
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
    originals=read(WORK/'protocols/economic_reference.json')
    fields={'decisions':('observed_through','decision_at','execution_start','execution_end','target','reference_price','limit_price','quantity','side','signal_status'),'orders':('valid_start','valid_end','side','quantity','limit_price','status','reason'),'fills':('interval_start','interval_end','side','quantity','price','fees','time_precision'),'account_points':('time','cash','quantity','receivable','equity','close','session','valuation_stale'),'account_daily':('time','cash','quantity','receivable','equity','close','session','valuation_stale'),'trades':('entry_at','exit_at','cost','income','net_pnl','net_return','status')}
    checks={}
    for key in ('C0219','C0220'):
        old_path=authenticate(originals[key]['evidence']);envelope=read(old_path)
        allowed={(envelope[n]['kind'],envelope[n]['sha256']) for n in ('input_ref','candidate_ref','benchmark_ref')}
        def resolve(item):
            if (item['kind'],item['sha256']) not in allowed:raise ValueError('Unowned prior dependency')
            return (old_path.parent/(item['sha256']+'.json')).read_bytes()
        old=materialize_equity(old_path.read_bytes(),resolve).payload
        for name in ('candidate','buy_hold'):
            for table,keys in fields.items():
                a=old['runs'][name][table];b=payloads[key]['runs'][name][table]
                checks[key+'_'+name+'_'+table]=len(a)==len(b) and all(all(x[k]==y[k] for k in keys) for x,y in zip(a,b))
    save(WORK/'others/control_comparison.json',{'status':'PASS' if all(checks.values()) else 'FAIL','originals':originals,'checks':checks,'scope':'24 complete economic projections;identity/source/explanation fields intentionally differ'})
    if not all(checks.values()):raise ValueError('E0 exact economic path guard failed')
    summaries={}
    for key,payload in payloads.items():
        c=summary(payload['runs']['candidate'],100000.); b=summary(payload['runs']['buy_hold'],100000.)
        goals={'annualized_return':(c['annualized_return']>=1.5*b['annualized_return'] if b['annualized_return']>0 else c['annualized_return']>0),'relative_drawdown':c['bar_max_drawdown']<=.8*b['bar_max_drawdown'],'absolute_drawdown':c['bar_max_drawdown']<=.25,'frequency_median':c['rolling_60_closed_cycle_median']>=6,'frequency_coverage':c['coverage_at_least_three']>=.9}
        summaries[key]={'parameters':PARAMETERS[key],'candidate':c,'benchmark':b,'goals':goals,'all_goals_met':all(goals.values())}
        print('RESULT',key,json.dumps({f:c[f] for f in ('annualized_return','bar_max_drawdown','closed_cycles','rolling_60_closed_cycle_median','coverage_at_least_three')}),flush=True)
    for key,t in trials.items():
        s=summaries[key];t.set_user_attr('candidate_id',key);t.set_user_attr('all_goals_met',s['all_goals_met']);t.set_user_attr('goals',s['goals']);t.set_user_attr('fixed_full_parameters',PARAMETERS[key]);t.set_user_attr('source_sha256',digest(WORK/'src/strategy.py'))
        study.tell(t,(s['candidate']['annualized_return'],s['candidate']['bar_max_drawdown']))
    save(WORK/'others/study_trials.json',{'study_name':study.study_name,'method':'Fixed two mapping enqueue/ask/tell;no adaptive proposals or domain extension','trial_count':2,'unique_new_economic_policies':2,'outside_study_technical_controls':['C0219','C0220'],'trials':[{'number':t.number,'state':t.state.name,'parameters':t.params,'values':t.values,'user_attrs':t.user_attrs} for t in study.trials]})
    save(WORK/'others/analysis.json',{'status':'PASS','summaries':summaries,'source_accounts':manifest,'source_sha256':digest(WORK/'src/run.py'),'elapsed_seconds':perf_counter()-started,'sample':'Entry-frozen background mapping;2 new economic policies+2 static new-source controls;2026 sealed'})
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
