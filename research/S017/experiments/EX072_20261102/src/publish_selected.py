"""Select existing public V4 evidence only. No session, evaluation, checkpoint or compute."""
from datetime import date
from common import ROOT,WORK,REPOSITORY,EXPERIMENT,read,save,authenticate,context,material
from search import assess
from czsc_trader.application import diagnose_accounts
from czsc_trader.research_tools import EvidenceRef,AccountRunRef,EvaluationIdentity,AccountDiagnosisRequest,EvaluationWindow
from czsc_trader.research_tools.equity_replay import materialize_equity
from strategy_manager import CandidateKey


def main():
    family=read(WORK/'others/search_trials.json')
    if family['status']!='COMPLETED_PARAMETER_SEARCH':raise ValueError('Completed actual Study required')
    rows=[r for r in family['unique_results'] if r['status']=='SUCCEEDED'];lookup={r['candidate_id']:r for r in rows};allrefs=read(WORK/'others/all_accounts.json')
    selected={};reasons={}
    def add(row,reason):
        cid=row['candidate_id'];selected[cid]=row;reasons.setdefault(cid,[]).append(reason)
    passed=[r for r in rows if all(r['goals'].values())]
    for row in passed:add(row,'Every COMPLETE actual unique original-five AND qualifier')
    add(sorted(rows,key=lambda r:(-r['metrics']['annualized_return'],r['candidate_id']))[0],'Full-family max return,not automatically qualified')
    feasible=[r for r in rows if all(v for k,v in r['goals'].items() if k!='annualized_return')]
    if feasible:add(sorted(feasible,key=lambda r:(-r['metrics']['annualized_return'],r['candidate_id']))[0],'Other four original gates pass max return,ID tie-break')
    for cid,label in (('C0338','Exact center C337 control'),('C0339','Known gMF0 C336-equivalent axis'),('C0342','Natural gMF1 mechanical endpoint'),('C0343','First actual six-D model proposal')):
        if cid in lookup:add(lookup[cid],label)
    manifest={}
    for cid,row in sorted(selected.items()):
        if cid not in allrefs:raise ValueError('Missing original public result;never fallback evaluate: '+cid)
        rec=allrefs[cid];ref=EvidenceRef.from_dict(rec['evidence']);path=authenticate(rec['evidence']);env=read(path)
        if ref.sha256!=row['result_hash']:raise ValueError('Public result does not match original evaluated content')
        owned={(env[k]['kind'],env[k]['sha256']) for k in ('input_ref','candidate_ref','benchmark_ref')}
        def resolve(x):
            if (x['kind'],x['sha256']) not in owned:raise ValueError('Unowned public dependency')
            from hashlib import sha256
            raw=(path.parent/(x['sha256']+'.json')).read_bytes()
            if sha256(raw).hexdigest()!=x['sha256']:raise ValueError('Public dependency changed')
            return raw
        payload=materialize_equity(path.read_bytes(),resolve).payload
        if payload['request_hash']!=row['request_hash'] or payload['evaluation_identity']!=row['evaluation_identity'] or payload['evaluation_id']!=row['evaluation_id']:raise ValueError('Original request/actor identity mismatch')
        c,b,goals,_=assess(payload)
        if c!=row['metrics'] or b!=row['benchmark_metrics'] or goals!=row['goals']:raise ValueError('Full public account differs from compact family')
        manifest[cid]={**rec,'selection_reasons':reasons[cid],'new_compute':0,'public_original_evidence_reused':True}
    save(WORK/'others/evidence_selection.json',dict(selected=sorted(selected),selection_reasons=reasons,all_joint=[r['candidate_id'] for r in passed],financial_compute=0,no_checkpoint_or_evaluation_used=True))
    save(WORK/'others/accounts.json',manifest)
    save(WORK/'others/selected_public_stats.json',dict(candidate_compute=0,benchmark_compute=0,checkpoint_reads=0,evaluation_calls=0,source='all_accounts original public V4 only',selected_count=len(manifest)))
    save(WORK/'others/analysis.json',dict(status='PASS',summaries={cid:dict(parameters=lookup[cid]['parameters'],candidate=lookup[cid]['metrics'],benchmark=lookup[cid]['benchmark_metrics'],goals=lookup[cid]['goals'],all_goals_met=lookup[cid]['all_goals_met']) for cid in manifest},source_accounts=manifest,joint_pass_all_study=[r['candidate_id'] for r in passed],scope='Selected original public accounts;all actual unique COMPLETE five-AND qualifiers included,unqualified representatives explicit'))
    def runref(cid):
        rec=manifest[cid];identity=dict(rec['evaluation_identity']);identity['candidate']=CandidateKey(**identity['candidate'])
        return AccountRunRef(EvidenceRef.from_dict(rec['evidence']),EvaluationIdentity(**identity))
    diagnoses=[];research=context()
    for cid in sorted(manifest):
        if cid=='C0338':continue
        if cid not in {r['candidate_id'] for r in passed} and 'max return' not in ' '.join(reasons[cid]):continue
        value=diagnose_accounts(REPOSITORY,AccountDiagnosisRequest(runref('C0338'),runref(cid),EvaluationWindow('TRAIN_2024_2025',date(2024,1,2),date(2025,12,31))))
        if value.status.value!='COMPUTED' or any(abs(x.residual)>1e-6 for x in value.reconciliation):raise ValueError('Public matched account diagnosis failed')
        path=WORK/'others'/('diagnosis-'+cid+'.json');save(path,value.to_dict());diagnoses.append(dict(candidate=cid,reference=material(research,'diagnosis-'+cid,path).to_dict()))
    save(WORK/'others/diagnoses.json',diagnoses)
    print('SELECTED_ORIGINAL_PUBLIC_REFS_READY',sorted(manifest),flush=True)


if __name__=='__main__':main()
