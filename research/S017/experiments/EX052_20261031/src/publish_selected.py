"""Publish essential completed-trial ledgers by explicit public checkpoint RESUME only."""
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from common import ROOT,WORK,EXPERIMENT,read,save,prepare_data,candidate,request,material
from search import assess,params_hash
from czsc_trader.application import publish_evidence_many,diagnose_accounts
from czsc_trader.research_tools import (ResearchExecutionSession,ExecutionCheckpointRequest,CheckpointMode,EvaluationEvidenceWrite,EvidenceRef,AccountRunRef,EvaluationIdentity,AccountDiagnosisRequest,EvaluationWindow)
from czsc_trader.research_tools.equity_replay import materialize_equity
from strategy_manager import CandidateKey
from datetime import date

def main():
 data=read(WORK/'others/search_trials.json')
 if data['status']!='COMPLETED_PARAMETER_SEARCH':raise ValueError('Completed original Study required; no new search')
 rows=[r for r in data['unique_results'] if r['status']=='SUCCEEDED'];lookup={r['candidate_id']:r for r in rows}
 for r in rows:
  if r['all_goals_met']!=all(r['goals'].values()):raise ValueError('Qualification disagreement')
 passed=[r for r in rows if all(r['goals'].values())];selected={r['candidate_id'] for r in passed};reasons={r['candidate_id']:['ALL_ORIGINAL_FIVE_GOALS'] for r in passed}
 def add(r,why):selected.add(r['candidate_id']);reasons.setdefault(r['candidate_id'],[]).append(why)
 for p in ({'alpha':0.,'initial_fraction':0.,'accepted_fraction':0.},{'alpha':0.,'initial_fraction':1.,'accepted_fraction':0.},{'alpha':0.,'initial_fraction':0.,'accepted_fraction':1.},{'alpha':0.,'initial_fraction':1.,'accepted_fraction':1.}):
  matches=[r for r in rows if r['parameters']==p]
  if matches:add(matches[0],'FIXED_STRUCTURAL_CORNER')
 add(max(rows,key=lambda r:r['metrics']['annualized_return']),'GLOBAL_MAX_RETURN_NONQUALIFIED_IF_GATES_FAIL')
 if 'C0136' in lookup:add(lookup['C0136'],'EARLY_CURRENT_MAX_RETURN_DD_AUDIT_PRESERVED')
 ablation=read(WORK/'others/matched_ablation_plan.json');first_focal=ablation['comparisons'][0]['focal'] if ablation['comparisons'] else None
 for item in ablation['comparisons']:
  if item['focal']==first_focal:
   matched=next(r for r in rows if r['parameter_hash']==item['parameter_hash']);add(matched,'MATCHED_FIRST_FOCAL_COMPONENT_REMOVAL')
 freq=[r for r in rows if r['goals']['frequency_median'] and r['goals']['frequency_coverage']];risk=[r for r in freq if r['goals']['absolute_drawdown']];pool=risk or freq or rows
 add(max(pool,key=lambda r:r['metrics']['annualized_return']),'DIAGNOSTIC_MAX_RETURN_WITHIN_DISCLOSED_OTHER_GATE_POOL')
 add(min(pool,key=lambda r:r['metrics']['bar_max_drawdown']),'DIAGNOSTIC_LOW_DRAWDOWN_WITHIN_SAME_POOL')
 save(WORK/'others/evidence_selection.json',{'selected':sorted(selected),'all_passing':sorted(r['candidate_id'] for r in passed),'reasons':reasons,'not_adoption_selection':True,'complete_all_results_retained':'search_trials.json, including502day vectors and all original gates','no_new_trials_or_economic_runs':True})
 research,prepared,_=prepare_data();manifest=read(WORK/'others/baseline_accounts.json');groups=defaultdict(list)
 for key in sorted(selected):
  if key not in manifest:groups[lookup[key]['checkpoint_run_id']].append(lookup[key])
 restores=[]
 for run_id,group in groups.items():
  with ResearchExecutionSession(research,experiment=EXPERIMENT,checkpoint=ExecutionCheckpointRequest(run_id,CheckpointMode.RESUME),on_progress=lambda e:print('RESUME',run_id,e.phase,e.completed,e.total,flush=True)) as execution:
   handles=tuple(research.evaluation.prepare(request(candidate(r['candidate_id'],r['parameters']),prepared),execution=execution) for r in group)
   outcomes=research.evaluation.evaluate_many(handles,execution=execution)
   if execution.equity_statistics.candidate_runs or execution.equity_statistics.benchmark_runs:raise ValueError('Expected exact checkpoint reuse; unexpected economic compute must be reported')
   for r,o in zip(group,outcomes,strict=True):
    if o.status.value!='SUCCEEDED' or o.result is None or o.result.request_hash!=r['request_hash'] or o.result.result_hash!=r['result_hash']:raise ValueError('Original result identity not resumed exactly')
    payload=materialize_equity(o.result).payload;c,b,goals,cons=assess(payload)
    if c!=r['metrics'] or goals!=r['goals']:raise ValueError('Resumed complete metrics differ')
   pubs=publish_evidence_many(research,tuple(EvaluationEvidenceWrite(EXPERIMENT,'selected-'+r['candidate_id'],h,o.result) for r,h,o in zip(group,handles,outcomes,strict=True)),execution=execution)
   if any(p.status.value!='PUBLISHED' for p in pubs):raise RuntimeError('Selected evidence publication failed')
   for r,p in zip(group,pubs,strict=True):manifest[r['candidate_id']]={'evidence':p.reference.to_dict(),'evaluation_identity':r['evaluation_identity'],'evaluation_id':r['evaluation_id'],'parameters':r['parameters'],'selection_reasons':reasons[r['candidate_id']]}
   restores.append({'checkpoint':run_id,'selected':[r['candidate_id'] for r in group],'session':asdict(execution.stats),'equity':asdict(execution.equity_statistics)})
 save(WORK/'others/accounts.json',manifest);save(WORK/'others/selected_resume_stats.json',restores)
 summaries={}
 for key in manifest:
  if key in lookup:
   row=lookup[key];summaries[key]={'parameters':row['parameters'],'candidate':row['metrics'],'benchmark':row['benchmark_metrics'],'goals':row['goals'],'all_goals_met':row['all_goals_met']}
  else:summaries[key]=read(ROOT/'research/S017/experiments/EX051_20261031/others/analysis.json')['summaries']['C0113']
 save(WORK/'others/analysis.json',{'status':'PASS','summaries':summaries,'source_accounts':manifest,'scope':'Selected original exact checkpoint outcomes, not new accounts; all48 compact results in search_trials.json','joint_pass_all_study':[r['candidate_id'] for r in passed]})
 def ref(key):
  rec=manifest[key];v=dict(rec['evaluation_identity']);v['candidate']=CandidateKey(**v['candidate']);return AccountRunRef(EvidenceRef.from_dict(rec['evidence']),EvaluationIdentity(**v))
 diagnoses=[]
 for key in sorted(manifest):
  if key in ('C0114','C0115'):continue
  d=diagnose_accounts(__import__('common').REPOSITORY,AccountDiagnosisRequest(ref('C0115'),ref(key),EvaluationWindow('TRAIN_2024_2025',date(2024,1,2),date(2025,12,31))))
  if d.status.value!='COMPUTED' or any(abs(r.residual)>1e-6 for r in d.reconciliation):raise ValueError('Public pair reconciliation failed')
  path=WORK/'others'/('diagnosis-'+key+'.json');save(path,d.to_dict());diagnoses.append({'candidate':key,'reference':material(research,'diagnosis-'+key,path).to_dict()})
 save(WORK/'others/diagnoses.json',diagnoses);print('SELECTED_CHECKPOINT_PUBLICATION_COMPLETE',sorted(manifest),flush=True)
if __name__=='__main__':main()
