"""One pre-reviewed frozen-center repair mechanism, public formal account and benchmark."""
from dataclasses import asdict
from datetime import date
import json
from time import perf_counter
from common import (WORK,EXPERIMENT,PARAMETERS,prepare_data,candidate,request,read,save,digest,material)
from metrics import summary
from czsc_trader.application import publish_evidence_many,diagnose_accounts,publish_evidence
from czsc_trader.research_tools import (ResearchExecutionSession,ExecutionCheckpointRequest,EvaluationEvidenceWrite,
    AccountRunRef,AccountDiagnosisRequest,EvaluationIdentity,EvaluationWindow,MaterialEvidenceWrite)
from strategy_manager import CandidateKey
from czsc_trader.research_tools.equity_replay import materialize_equity


def main():
 started=perf_counter();checked=read(WORK/'others/precheck.json')
 if checked['status']!='PASS' or checked['strategy_sha256']!=digest(WORK/'src/strategy.py'):raise ValueError('Current public causal precheck required')
 if set(PARAMETERS)!={'C0321'}:raise ValueError('One pre-reviewed mechanism only')
 census=read(WORK/'others/census_publication.json')
 if census['status']!='PASS':raise ValueError('Locked pre-account census required')
 research,prepared,_=prepare_data();c=candidate('C0321');save(WORK/'protocols/definitions.json',{'C0321':c.definition.to_dict()})
 frozen={str(p.relative_to(WORK)).replace('\\','/'):material(research,'pre-'+str(i),p).to_dict() for i,p in enumerate([*sorted((WORK/'src').glob('*.py')),*sorted((WORK/'protocols').glob('*.*'))])}
 for name in ('precheck.json','census_pre_run.json','census_publication.json','design_pre_label_publication.json'):
  frozen['pre-account/'+name]=material(research,'pre-account-'+name,WORK/'others'/name).to_dict()
 save(WORK/'others/pre_run.json',frozen)
 with ResearchExecutionSession(research,experiment=EXPERIMENT,checkpoint=ExecutionCheckpointRequest(EXPERIMENT.experiment_id+'-frozen-center'),on_progress=lambda e:print('PHASE',str(e.phase),e.completed,e.total,flush=True)) as execution:
  handles=(research.evaluation.prepare(request(c,prepared),execution=execution),)
  outcomes=research.evaluation.evaluate_many(handles,execution=execution)
  save(WORK/'others/execution_status.json',[{'candidate':'C0321','status':x.status.value,'error':None if x.error is None else {'code':x.error.code,'message':x.error.message}} for x in outcomes])
  if any(x.result is None or x.status.value!='SUCCEEDED' for x in outcomes):raise ValueError('Formal account failed')
  payload=materialize_equity(outcomes[0].result).payload
  pubs=publish_evidence_many(research,(EvaluationEvidenceWrite(EXPERIMENT,'formal-C0321',handles[0],outcomes[0].result),),execution=execution)
  if pubs[0].status.value!='PUBLISHED':raise ValueError('Account publication failed')
  manifest={'C0321':{'evidence':pubs[0].reference.to_dict(),'evaluation_identity':payload['evaluation_identity'],'evaluation_id':payload['evaluation_id'],'request_hash':outcomes[0].result.request_hash}}
  save(WORK/'others/accounts.json',manifest);save(WORK/'others/execution_stats.json',{'session':asdict(execution.stats),'equity':asdict(execution.equity_statistics)})
 if payload['request']['initial_cash']!=100000.:raise ValueError('Fresh100000 required')
 for name in ('candidate','buy_hold'):
  run=payload['runs'][name]
  if run['decisions'][0]['portfolio_revision']!=0 or any(f['interval_start'][:10]<'2024-01-02' for f in run['fills']):raise ValueError('Inherited account not allowed')
  if name=='candidate':
   f={x['key']:x['text'] for x in run['decisions'][0]['explanation']['basis']}
   if f['portfolio_quantity']!='0' or float(f['portfolio_cash'])!=100000. or f['cycle_present']!='False':raise ValueError('Candidate did not start empty')
 csum=summary(payload['runs']['candidate'],100000.);bsum=summary(payload['runs']['buy_hold'],100000.)
 goals={'annualized_return':csum['annualized_return']>=1.5*bsum['annualized_return'] if bsum['annualized_return']>0 else csum['annualized_return']>0,'relative_drawdown':csum['bar_max_drawdown']<=.8*bsum['bar_max_drawdown'],'absolute_drawdown':csum['bar_max_drawdown']<=.25,'frequency_median':csum['rolling_60_closed_cycle_median']>=6,'frequency_coverage':csum['coverage_at_least_three']>=.9}
 save(WORK/'others/analysis.json',{'status':'PASS','summaries':{'C0321':{'parameters':PARAMETERS['C0321'],'candidate':csum,'benchmark':bsum,'goals':goals,'all_goals_met':all(goals.values())}},'source_accounts':manifest,'source_sha256':digest(WORK/'src/run.py'),'elapsed_seconds':perf_counter()-started,'new_economic_policies':1,'candidate_compute':1,'benchmark_compute':1,'same_train_not_independent':True})
 print('RESULT C0321',csum,goals,flush=True)
 identity=dict(payload['evaluation_identity']);identity['candidate']=CandidateKey(**identity['candidate'])
 diagnosis=diagnose_accounts(__import__('common').REPOSITORY,AccountDiagnosisRequest(AccountRunRef(pubs[0].reference,EvaluationIdentity(**identity)),None,EvaluationWindow('TRAIN_2024_2025',date(2024,1,2),date(2025,12,31))))
 if diagnosis.status.value!='COMPUTED' or any(abs(x.residual)>1e-6 for x in diagnosis.reconciliation):raise ValueError('Public mechanism diagnosis failed')
 dref=publish_evidence(research,MaterialEvidenceWrite(EXPERIMENT,'single-mechanism-public-diagnosis',json.dumps(diagnosis.to_dict(),ensure_ascii=False).encode(),'application/json','json'))
 save(WORK/'others/diagnosis.json',{'result':dref.to_dict(),'status':diagnosis.status.value,'single_account':True,'new_compute':0})
 print('ECONOMIC_EVIDENCE_READY_FOR_MECHANISM_REVIEW',flush=True)

if __name__=='__main__':main()
