"""One-session three-policy formal comparison; baseline 12-table guard precedes new arms."""
from dataclasses import asdict
from datetime import date
import json
from time import perf_counter
from common import ROOT,WORK,EXPERIMENT,REPOSITORY,PARAMETERS,prepare_data,candidate,request,save,read,digest,material,authenticate
from metrics import summary
from strategy_manager import CandidateKey
from czsc_trader.application import publish_evidence,publish_evidence_many,diagnose_accounts
from czsc_trader.research_tools import ResearchExecutionSession,ExecutionCheckpointRequest,EvaluationEvidenceWrite,AccountRunRef,AccountDiagnosisRequest,EvaluationIdentity,EvaluationWindow,EvidenceRef,MaterialEvidenceWrite
from czsc_trader.research_tools.equity_replay import materialize_equity

FIELDS={'decisions':('observed_through','decision_at','execution_start','execution_end','target','reference_price','limit_price','quantity','side','signal_status'),'orders':('valid_start','valid_end','side','quantity','limit_price','status','reason'),'fills':('interval_start','interval_end','side','quantity','price','fees','time_precision'),'account_points':('time','cash','quantity','receivable','equity','close','session','valuation_stale'),'account_daily':('time','cash','quantity','receivable','equity','close','session','valuation_stale'),'trades':('entry_at','exit_at','cost','income','net_pnl','net_return','status')}


def control(payload):
    originals=read(WORK/'protocols/economic_reference.json')
    path=authenticate(originals['C0335']['evidence']);envelope=read(path)
    owned={(envelope[n]['kind'],envelope[n]['sha256']) for n in ('input_ref','candidate_ref','benchmark_ref')}
    def resolve(item):
        if (item['kind'],item['sha256']) not in owned:raise ValueError('Unowned historical dependency')
        target=path.parent/(item['sha256']+'.json')
        if digest(target)!=item['sha256']:raise ValueError('Historical dependency hash changed')
        return target.read_bytes()
    old=materialize_equity(path.read_bytes(),resolve).payload
    checks={}
    for kind in ('candidate','buy_hold'):
        for table,fields in FIELDS.items():
            a=old['runs'][kind][table];b=payload['runs'][kind][table]
            checks['C0335_'+kind+'_'+table]=len(a)==len(b) and all(all(x[k]==y[k] for k in fields) for x,y in zip(a,b))
    save(WORK/'others/control_comparison.json',dict(status='PASS' if all(checks.values()) else 'FAIL',originals=originals,checks=checks,scope='All 12 candidate/BH economic projections; identity and explanation differ'))
    if not all(checks.values()):raise ValueError('KEEP multi-full C222 exact economic control failed; do not evaluate new arms')


def main():
    started=perf_counter();checked=read(WORK/'others/precheck.json')
    if checked['status']!='PASS' or any(checked[k]!=digest(WORK/'src'/p) for k,p in (('strategy_sha256','strategy.py'),('helper_sha256','negative_run.py'),('precheck_sha256','precheck.py'))):raise ValueError('Current exact source/precheck binding required')
    if checked['context_branch_counts_sha256']!=digest(WORK/'others/context_branch_counts.json'):raise ValueError('Prechecked branch-count source changed')
    if set(PARAMETERS)!={'C0335','C0336','C0337'}:raise ValueError('Only three predeclared policies permitted')
    if (WORK/'others/accounts.json').exists():raise ValueError('Already evaluated: no silent second account run')
    research,prepared,_=prepare_data();candidates={k:candidate(k) for k in PARAMETERS}
    save(WORK/'protocols/definitions.json',{k:v.definition.to_dict() for k,v in candidates.items()})
    frozen={str(p.relative_to(WORK)).replace('\\','/'):material(research,'pre-'+str(i),p).to_dict() for i,p in enumerate([*sorted((WORK/'src').glob('*.py')),*sorted((WORK/'protocols').glob('*.*'))])}
    for name in ('precheck','context_branch_counts','reused_entry_census'):
        frozen['pre-account/'+name]=material(research,name,WORK/'others'/(name+'.json')).to_dict()
    path=ROOT/'.tmp/s017_ex071_context_count.py'
    frozen['pre-account/feasibility-source']=material(research,'baseline-trigger-feasibility-source',path).to_dict()
    for exp in ('EX054_20261031','EX055_20261031','EX056_20261031','EX057_20261031','EX058_20261031','EX059_20261031','EX066_20261101','EX069_20261101','EX070_20261101'):
        frozen['prior-report/'+exp]=read(ROOT/'research/S017/experiments'/exp/'others/publication.json')['report']
    for name,sha in {'s017_ex071_branch_count_audit.py':'e2a7144003ab026ef042f58efa4755b232c943083fb7b9992301bf25b267f729','s017_ex071_branch_count_audit_result.json':'8342a8276926c53c77f816631481f1c2d4a2c131a0cb16a0458ce1b65d51b7c9'}.items():
        p=ROOT/'.tmp'/name
        if digest(p)!=sha:raise ValueError('Independent branch-count audit bytes changed')
        frozen['independent-branch/'+name]=material(research,name,p).to_dict()
    save(WORK/'others/pre_run.json',frozen)
    payloads={};manifest={};statuses=[]
    with ResearchExecutionSession(research,experiment=EXPERIMENT,checkpoint=ExecutionCheckpointRequest(EXPERIMENT.experiment_id+'-one-session-multifull-risk'),on_progress=lambda e:print('PHASE',str(e.phase),e.completed,e.total,flush=True)) as execution:
        def evaluate(keys):
            handles=tuple(research.evaluation.prepare(request(candidates[k],prepared),execution=execution) for k in keys)
            outcomes=research.evaluation.evaluate_many(handles,execution=execution)
            statuses.extend({'candidate':h.candidate.candidate_id,'status':o.status.value,'error':None if o.error is None else {'code':o.error.code,'message':o.error.message}} for h,o in zip(handles,outcomes,strict=True))
            save(WORK/'others/execution_status.json',statuses)
            if any(o.result is None or o.status.value!='SUCCEEDED' for o in outcomes):raise ValueError('Formal account failed; preserve real failed status')
            for h,o in zip(handles,outcomes,strict=True):payloads[h.candidate.candidate_id]=materialize_equity(o.result).payload
            pubs=publish_evidence_many(research,tuple(EvaluationEvidenceWrite(EXPERIMENT,'formal-'+h.candidate.candidate_id,h,o.result) for h,o in zip(handles,outcomes,strict=True)),execution=execution)
            if any(x.status.value!='PUBLISHED' for x in pubs):raise ValueError('Formal publication incomplete')
            for h,o,pub in zip(handles,outcomes,pubs,strict=True):
                p=payloads[h.candidate.candidate_id]
                manifest[h.candidate.candidate_id]=dict(evidence=pub.reference.to_dict(),evaluation_identity=p['evaluation_identity'],evaluation_id=p['evaluation_id'],request_hash=o.result.request_hash)
            save(WORK/'others/accounts.json',manifest)
            save(WORK/'others/execution_stats.json',dict(session=asdict(execution.stats),equity=asdict(execution.equity_statistics)))
        evaluate(('C0335',))
        control(payloads['C0335'])
        evaluate(('C0336','C0337'))
        save(WORK/'others/execution_stats.json',dict(session=asdict(execution.stats),equity=asdict(execution.equity_statistics)))
    fresh={};summaries={}
    for key,p in payloads.items():
        if p['request']['initial_cash']!=100000.:raise ValueError('Fresh 100000 initial cash required')
        for kind in ('candidate','buy_hold'):
            run=p['runs'][kind];first=run['decisions'][0]
            if first['portfolio_revision']!=0 or any(x['interval_start'][:10]<'2024-01-02' for x in run['fills']) or any(x['entry_at'][:10]<'2024-01-02' for x in run['trades']):raise ValueError('Inherited account state refused')
            if kind=='candidate':
                f={x['key']:x['text'] for x in first['explanation']['basis']}
                if f['portfolio_quantity']!='0' or float(f['portfolio_cash'])!=100000. or f['cycle_present']!='False':raise ValueError('Initial source portfolio must be empty')
            fresh[key+'_'+kind]=dict(initial_revision=0,no_pre_training_fills=True)
        c=summary(p['runs']['candidate'],100000.);b=summary(p['runs']['buy_hold'],100000.)
        goals=dict(annualized_return=c['annualized_return']>=1.5*b['annualized_return'] if b['annualized_return']>0 else c['annualized_return']>0,relative_drawdown=c['bar_max_drawdown']<=.8*b['bar_max_drawdown'],absolute_drawdown=c['bar_max_drawdown']<=.25,frequency_median=c['rolling_60_closed_cycle_median']>=6,frequency_coverage=c['coverage_at_least_three']>=.9)
        summaries[key]=dict(parameters=PARAMETERS[key],candidate=c,benchmark=b,goals=goals,all_goals_met=all(goals.values()))
        print('RESULT',key,json.dumps({k:c[k] for k in ('annualized_return','bar_max_drawdown','closed_cycles','rolling_60_closed_cycle_median','coverage_at_least_three')}),flush=True)
    save(WORK/'others/fresh_start_validation.json',dict(status='PASS',checks=fresh,first_completed_point_may_hold=True))
    save(WORK/'others/analysis.json',dict(status='PASS',summaries=summaries,source_accounts=manifest,source_sha256=digest(WORK/'src/run.py'),elapsed_seconds=perf_counter()-started,sample='Fixed C222 all209 entries; entry-frozen MF context selects original/0/.75 progress protection; 2024-25 only, 2026 sealed'))
    def ref(key):
        identity=dict(payloads[key]['evaluation_identity']);identity['candidate']=CandidateKey(**identity['candidate'])
        return AccountRunRef(EvidenceRef.from_dict(manifest[key]['evidence']),EvaluationIdentity(**identity))
    diagnoses=[]
    for a,b in (('C0335','C0336'),('C0335','C0337'),('C0336','C0337')):
        d=diagnose_accounts(REPOSITORY,AccountDiagnosisRequest(ref(a),ref(b),EvaluationWindow('TRAIN_2024_2025',date(2024,1,2),date(2025,12,31))))
        if d.status.value!='COMPUTED' or any(abs(x.residual)>1e-6 for x in d.reconciliation):raise ValueError('Public diagnosis failed')
        diagnoses.append(publish_evidence(research,MaterialEvidenceWrite(EXPERIMENT,'diagnosis-'+a+'-'+b,json.dumps(d.to_dict(),ensure_ascii=False).encode(),'application/json','json')).to_dict())
    save(WORK/'others/diagnoses.json',diagnoses)
    print('ECONOMIC_EVIDENCE_READY_FOR_RESEARCH_REPORT',flush=True)


if __name__=='__main__':main()
