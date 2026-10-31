"""One Optuna study, public V4 accounts only, bounded sessions and compact family evidence."""
from dataclasses import asdict
from datetime import date
from hashlib import sha256
from pathlib import Path
import ctypes
import gc
import json
import math
import optuna
from optuna.trial import TrialState
from optuna.distributions import distribution_to_json
from common import ROOT,WORK,EXPERIMENT,REPOSITORY,read,save,digest,material,prepare_data,candidate,request
from metrics import summary
from czsc_trader.application import publish_evidence_many
from czsc_trader.research_tools import ResearchExecutionSession,ExecutionCheckpointRequest,EvaluationEvidenceWrite
from czsc_trader.research_tools.equity_replay import materialize_equity

KEYS=('alpha','initial_fraction','accepted_fraction','progress_protection')
FIELDS={'decisions':('observed_through','decision_at','execution_start','execution_end','target','reference_price','limit_price','quantity','side','signal_status'),'orders':('valid_start','valid_end','side','quantity','limit_price','status','reason'),'fills':('interval_start','interval_end','side','quantity','price','fees','time_precision'),'account_points':('time','cash','quantity','receivable','equity','close','session','valuation_stale'),'account_daily':('time','cash','quantity','receivable','equity','close','session','valuation_stale'),'trades':('entry_at','exit_at','cost','income','net_pnl','net_return','status')}

def working_set():
    class Counters(ctypes.Structure):
        _fields_=[('cb',ctypes.c_ulong),('PageFaultCount',ctypes.c_ulong)]+[(k,ctypes.c_size_t) for k in ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    value=Counters();value.cb=ctypes.sizeof(value)
    ctypes.windll.kernel32.GetCurrentProcess.restype=ctypes.c_void_p
    function=ctypes.windll.psapi.GetProcessMemoryInfo;function.argtypes=(ctypes.c_void_p,ctypes.POINTER(Counters),ctypes.c_ulong)
    if not function(ctypes.windll.kernel32.GetCurrentProcess(),ctypes.byref(value),value.cb):raise ctypes.WinError()
    return {k:round(getattr(value,k)/2**20,3) for k in ('WorkingSetSize','PeakWorkingSetSize','PagefileUsage')}

def params_hash(values):return sha256(json.dumps({k:float(values[k]) for k in KEYS},sort_keys=True,separators=(',',':')).encode()).hexdigest()

def compare(left,right):
    checks={}
    for kind in ('candidate','buy_hold'):
        for table,fields in FIELDS.items():
            a=left['runs'][kind][table];b=right['runs'][kind][table]
            checks[kind+'_'+table]=len(a)==len(b) and all(all(x[k]==y[k] for k in fields) for x,y in zip(a,b))
    return checks

def old_payload(control):
    from common import authenticate
    ref=read(WORK/'protocols/control_definitions.json')[control]['original_evidence'];p=authenticate(ref);env=read(p);allowed={(env[k]['kind'],env[k]['sha256']) for k in ('input_ref','candidate_ref','benchmark_ref')}
    def resolve(r):
        if (r['kind'],r['sha256']) not in allowed:raise ValueError('Unexpected old control dependency')
        return (p.parent/(r['sha256']+'.json')).read_bytes()
    return materialize_equity(p.read_bytes(),resolve).payload,ref

def assess(payload):
    c=summary(payload['runs']['candidate'],100000.);b=summary(payload['runs']['buy_hold'],100000.)
    target=1.5*b['annualized_return'];relative=.8*b['bar_max_drawdown']
    if target<=0 or not math.isclose(target,2.4763395557352264,abs_tol=1e-12) or not math.isclose(relative,.4281025159400212,abs_tol=1e-12):raise ValueError('Frozen benchmark targets changed')
    goals={'annualized_return':c['annualized_return']>=target,'relative_drawdown':c['bar_max_drawdown']<=relative,'absolute_drawdown':c['bar_max_drawdown']<=.25,'frequency_median':c['rolling_60_closed_cycle_median']>=6,'frequency_coverage':c['coverage_at_least_three']>=.9}
    constraints=[1-c['annualized_return']/target,c['bar_max_drawdown']/relative-1,c['bar_max_drawdown']/.25-1,1-c['rolling_60_closed_cycle_median']/6,1-c['coverage_at_least_three']/.9]
    return c,b,goals,constraints

def frontier(rows):
    values=[r for r in rows if r['status']=='SUCCEEDED']
    return [r for r in values if not any(s['metrics']['annualized_return']>=r['metrics']['annualized_return'] and s['metrics']['bar_max_drawdown']<=r['metrics']['bar_max_drawdown'] and (s['metrics']['annualized_return']>r['metrics']['annualized_return'] or s['metrics']['bar_max_drawdown']<r['metrics']['bar_max_drawdown']) for s in values)]

class Search:
    def __init__(self):
        self.settings=read(WORK/'protocols/search_space.json');self.research,self.prepared,_=prepare_data();self.rows=[];self.by_hash={};self.segments=[];self.memory=[];self.duplicates=[];self.segment_no=0;self.baseline_checked=False;self.source=digest(WORK/'src/strategy.py')
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        self.study=optuna.create_study(storage=optuna.storages.InMemoryStorage(),sampler=optuna.samplers.TPESampler(seed=17,n_startup_trials=15,multivariate=False,constant_liar=True,constraints_func=lambda t:t.user_attrs['constraint_vector']),directions=('maximize','minimize'))
    def persist(self,status='RUNNING'):
        trials=[{'number':t.number,'state':t.state.name,'params':t.params,'values':t.values,'distributions':{k:distribution_to_json(v) for k,v in t.distributions.items()},'user_attrs':t.user_attrs,'start':str(t.datetime_start),'complete':str(t.datetime_complete)} for t in self.study.get_trials(deepcopy=False)]
        passed=[r['candidate_id'] for r in self.rows if r.get('all_goals_met')]
        save(WORK/'others/search_progress.json',{'status':status,'unique_parameters':len(self.rows),'optuna_trials':len(trials),'duplicates':len(self.duplicates),'joint_pass':passed,'last_rows':self.rows[-4:],'segments':self.segments,'memory':self.memory[-6:]})
        save(WORK/'others/search_trials.json',{'status':status,'source_sha256':self.source,'settings':self.settings,'optuna_version':optuna.__version__,'trial_states':trials,'unique_results':self.rows,'duplicates':self.duplicates,'joint_pass_candidates':passed,'return_drawdown_frontier':[r['candidate_id'] for r in frontier(self.rows)],'segments':self.segments,'memory':self.memory,'baseline_checked':self.baseline_checked,'test_access':False,'new_data':False})
    def propose(self,stage,upper,scheduled):
        if scheduled:
            wanted=scheduled.pop(0);self.study.enqueue_trial(wanted);upper=max(upper,wanted['alpha'])
        t=self.study.ask();params={k:t.suggest_float(k,0.,upper if k=='alpha' else 1.) for k in KEYS};h=params_hash(params)
        t.set_user_attr('stage',stage);t.set_user_attr('parameter_hash',h)
        if h in self.by_hash:
            row=self.by_hash[h];t.set_user_attr('reused_unique_candidate',row['candidate_id']);self.duplicates.append({'trial':t.number,'candidate':row['candidate_id'],'parameter_hash':h})
            if row['status']=='SUCCEEDED':
                t.set_user_attr('constraint_vector',row['constraint_vector']);t.set_user_attr('goals',row['goals']);self.study.tell(t,(row['metrics']['annualized_return'],row['metrics']['bar_max_drawdown']))
            else:self.study.tell(t,state=TrialState.FAIL)
            return None
        key='C'+str(166+len(self.rows)).zfill(4);row={'trial_number':t.number,'candidate_id':key,'parameters':params,'parameter_hash':h,'stage':stage,'status':'PROPOSED','source_sha256':self.source};self.rows.append(row);self.by_hash[h]=row;t.set_user_attr('candidate_id',key)
        return t,row
    def run_stage(self,stage,count,upper,scheduled=None):
        scheduled=[] if scheduled is None else list(scheduled);done=0;attempts=0
        while done<count:
            allowance=min(16,count-done);run_id=f'EX053-search-{self.segment_no:03d}';self.segment_no+=1;segment={'run_id':run_id,'stage':stage,'unique_target':allowance,'unique_completed':0};self.segments.append(segment)
            with ResearchExecutionSession(self.research,experiment=EXPERIMENT,checkpoint=ExecutionCheckpointRequest(run_id),on_progress=lambda e:print('PHASE',stage,e.phase,e.completed,e.total,flush=True)) as execution:
                local=0
                while local<allowance:
                    size=3 if not self.baseline_checked else min(4,allowance-local);tasks=[]
                    while len(tasks)<size:
                        attempts+=1
                        if attempts>max(640,count*20):raise RuntimeError('Duplicate-proposal limit; report incomplete, no random fallback')
                        item=self.propose(stage,upper,scheduled)
                        if item is not None:tasks.append(item)
                    if digest(WORK/'src/strategy.py')!=self.source:raise ValueError('Frozen strategy changed during study')
                    self.persist();pairs=[]
                    if not self.baseline_checked:pairs.extend((None,None,candidate(k)) for k in ('C0163','C0164','C0165'))
                    pairs.extend((t,row,candidate(row['candidate_id'],row['parameters'])) for t,row in tasks)
                    for _,r,c in pairs:
                        if r is not None:r['definition']=c.definition.to_dict()
                    handles=tuple(self.research.evaluation.prepare(request(c,self.prepared),execution=execution) for _,_,c in pairs)
                    outcomes=self.research.evaluation.evaluate_many(handles,execution=execution);payloads={};publics=[]
                    for (t,row,c),h,o in zip(pairs,handles,outcomes,strict=True):
                        if o.status.value!='SUCCEEDED' or o.result is None:
                            if row is None:raise RuntimeError('Exact old control failed')
                            row.update(status=o.status.value,error=None if o.error is None else {'code':o.error.code,'message':o.error.message},checkpoint_run_id=run_id);self.study.tell(t,state=TrialState.FAIL);continue
                        payload=materialize_equity(o.result).payload;cmetrics,bmetrics,goals,constraints=assess(payload)
                        if not self.baseline_checked:payloads[c.candidate_id]=payload;publics.append((h,o.result,payload))
                        if row is not None:
                            row.update(status='SUCCEEDED',metrics=cmetrics,benchmark_metrics=bmetrics,goals=goals,all_goals_met=all(goals.values()),constraint_vector=constraints,request_hash=o.result.request_hash,result_hash=o.result.result_hash,candidate_artifact=payload['candidate_ref'],evaluation_identity=payload['evaluation_identity'],evaluation_id=payload['evaluation_id'],checkpoint_run_id=run_id,daily_equity=[{'session':v['session'],'equity':v['equity']} for v in payload['runs']['candidate']['account_daily']]);t.set_user_attr('constraint_vector',constraints);t.set_user_attr('goals',goals);t.set_user_attr('request_hash',o.result.request_hash)
                            if self.baseline_checked:self.study.tell(t,(cmetrics['annualized_return'],cmetrics['bar_max_drawdown']))
                        del payload
                    if not self.baseline_checked:
                        checks={};refs={};ok=True
                        for control,family in (('C0163','C0166'),('C0164','C0167'),('C0165','C0168')):
                            old,oldref=old_payload(control);legacy=compare(old,payloads[control]);zero=compare(payloads[control],payloads[family]);checks[family]={'old_source_control12':legacy,'g0_vs_control12':zero};refs[control]=oldref;ok=ok and all(legacy.values()) and all(zero.values());del old
                        save(WORK/'others/baseline_economic_comparison.json',{'status':'PASS' if ok else 'FAIL','three_paths':checks,'old_references':refs,'scope':'Three full12 economic paths plus exact prior source controls, not state-byte equality'})
                        if not ok:
                            for t,row in tasks:self.study.tell(t,state=TrialState.FAIL)
                            self.persist('BASELINE_EQUIVALENCE_FAILED');raise ValueError('Three g0 full economic paths mismatch')
                        pubs=publish_evidence_many(self.research,tuple(EvaluationEvidenceWrite(EXPERIMENT,'baseline-'+h.candidate.candidate_id,h,result) for h,result,_ in publics),execution=execution)
                        if any(p.status.value!='PUBLISHED' for p in pubs):raise RuntimeError('Baseline evidence publication failed')
                        save(WORK/'others/baseline_accounts.json',{h.candidate.candidate_id:{'evidence':p.reference.to_dict(),'evaluation_identity':payload['evaluation_identity'],'evaluation_id':payload['evaluation_id']} for (h,_,payload),p in zip(publics,pubs,strict=True)})
                        self.baseline_checked=True
                        for t,row in tasks:self.study.tell(t,(row['metrics']['annualized_return'],row['metrics']['bar_max_drawdown']))
                        print('THREE_G0_72_ECONOMIC_PROJECTIONS_PASS',flush=True)
                    local+=len(tasks);done+=len(tasks);segment['unique_completed']=local;self.memory.append({'stage':stage,'segment':run_id,'unique':len(self.rows),**working_set()});self.persist();print('TRIAL_BATCH',stage,len(self.rows),[(r['candidate_id'],r.get('metrics',{}).get('annualized_return'),r.get('metrics',{}).get('bar_max_drawdown'),r.get('all_goals_met')) for _,r in tasks],flush=True)
                    del outcomes,handles,pairs,publics,tasks,payloads;gc.collect()
                segment['stats']={'session':asdict(execution.stats),'equity':asdict(execution.equity_statistics)}
            self.persist();gc.collect()
        return scheduled
    def extension_plan(self):
        values=[r for r in self.rows if r['status']=='SUCCEEDED'];bound=[r for r in values if r['parameters']['alpha']>=.95];frontids={r['candidate_id'] for r in frontier(values)};trigger=[r for r in bound if r.get('all_goals_met') or r['candidate_id'] in frontids]
        axis1=next((r for r in values if r['parameters']=={'alpha':1.,'initial_fraction':0.,'accepted_fraction':0.,'progress_protection':0.}),None);axisHalf=next((r for r in values if r['parameters']=={'alpha':.5,'initial_fraction':0.,'accepted_fraction':0.,'progress_protection':0.}),None)
        if axis1 and axisHalf and axis1['metrics']['annualized_return']>=axisHalf['metrics']['annualized_return'] and axis1['metrics']['bar_max_drawdown']<=axisHalf['metrics']['bar_max_drawdown'] and (axis1['metrics']['annualized_return']>axisHalf['metrics']['annualized_return'] or axis1['metrics']['bar_max_drawdown']<axisHalf['metrics']['bar_max_drawdown']):trigger.append(axis1)
        selected=[]
        for row in sorted(trigger,key=lambda r:r['trial_number']):
            ab=(row['parameters']['initial_fraction'],row['parameters']['accepted_fraction'],row['parameters']['progress_protection'])
            if ab not in selected:selected.append(ab)
            if len(selected)==3:break
        plan=[]
        for a,b,g in selected:
            for alpha in (1.25,1.5):plan.append({'alpha':alpha,'initial_fraction':a,'accepted_fraction':b,'progress_protection':g})
        if selected:plan.insert(0,{'alpha':2.,'initial_fraction':selected[0][0],'accepted_fraction':selected[0][1],'progress_protection':selected[0][2]})
        decision={'triggered':bool(selected),'boundary_candidates':[r['candidate_id'] for r in trigger],'matched_plan':plan,'adaptive_alpha_upper':2.,'alpha2_note':'29 raw entries<necessary32 closed; endpoint negative bound only, no dense >2 search','domain_coverage':'No joint-feasible alpha>=2 in this fixed training by original frequency logic; outside returns not claimed worthless'};save(WORK/'others/alpha_extension_decision.json',decision);return plan
    def focal_rows(self):
        values=[r for r in self.rows if r['status']=='SUCCEEDED']
        if not values:return []
        passed=[r for r in values if r['all_goals_met']]
        if passed:return sorted(passed,key=lambda r:r['trial_number'])[:2]
        freq=[r for r in values if r['goals']['frequency_median'] and r['goals']['frequency_coverage']];risk=[r for r in freq if r['goals']['absolute_drawdown']];pool=risk or freq or values
        selected=[]
        for row in (max(pool,key=lambda r:r['metrics']['annualized_return']),min(pool,key=lambda r:r['metrics']['bar_max_drawdown'])):
            if row not in selected:selected.append(row)
        return selected
    def ablations(self):
        plan=[];comparisons=[]
        for focal in self.focal_rows():
            p=focal['parameters'];variants=[{**p,k:0.} for k in KEYS]
            for v in variants:
                h=params_hash(v);comparisons.append({'focal':focal['candidate_id'],'parameters':v,'parameter_hash':h})
                if h not in self.by_hash and not any(params_hash(x)==h for x in plan):plan.append(v)
        save(WORK/'others/matched_ablation_plan.json',{'focal_selection':'All feasible earliest-trial representatives (equal qualification); if none, diagnostic max return/min DD among frequency+DD pass if exists, else frequency pass, else all; not a qualification score','comparisons':comparisons,'new_unique':len(plan),'no_reoptimization':True});return plan[:8]

def freeze(research):
    result={}
    files=[*sorted((WORK/'src').glob('*.py')),*sorted((WORK/'protocols').glob('*.*'))]
    for i,p in enumerate(files):result[str(p.relative_to(WORK)).replace('\\','/')]=material(research,'pre-'+str(i),p).to_dict()
    external=[('runtime-api-precheck',WORK/'others/search_api_precheck.json',None),('financial-state-precheck',WORK/'others/precheck.json',None),('stage3-authorized',ROOT/'research/S017/materials/STAGE3_PROGRESS_PROTECTION_AUTHORIZATION_20261031.json',None),('old-c113-control-source',ROOT/'research/S017/experiments/EX051_20261031/src/strategy.py','54e864ab6a81c9f9dfa4bd6d68c426b3808d3da0f1738f4cfb23b647bf5397f0'),('old-three-parameter-source',ROOT/'research/S017/experiments/EX052_20261031/src/strategy.py','a4066ae7292f21edbe07e5dd40f6adae79c23ac81b5880c49a993c220fc8c288'),('prior-whole-study',ROOT/'research/S017/experiments/EX052_20261031/others/search_trials.json',None),('prior-family-report',ROOT/'research/S017/experiments/EX052_20261031/report.md',None),('causal-scale-script',ROOT/'.tmp/s017_c113_causal_scale_design.py','9efc1f1f83984c8de3722e9eadfafd1605bdd4e21979e721d9f99d6a47e6589d'),('causal-scale-result',ROOT/'.tmp/s017_c113_causal_scale_design.json','cc1869acab11521ec97041b639de6d76462d91e5e05910fdb734007004299163'),('frequency-bound-script',ROOT/'.tmp/s017_frequency_gate_bound.py','4402f82d936ba6fe4602c7de11a5ff9ef467f0d1f25ab096f32f70d5b815a0e0'),('frequency-bound-result',ROOT/'.tmp/s017_frequency_gate_bound.json','fcaa83e94c3da2703760c5c7ec85db52242393c12edf43421d4b515560bd86aa'),('optuna-api-precheck-source',ROOT/'.tmp/s017_ex053_optuna_api_precheck.py',None),('optuna-api-precheck',ROOT/'.tmp/s017_ex053_optuna_api_precheck.json',None)]
    for name,p,expected in external:
        if expected and digest(p)!=expected:raise ValueError('Predeclared source changed: '+name)
        result['external/'+name]=material(research,name,p).to_dict()
    save(WORK/'others/pre_run.json',result)

def main():
    if (WORK/'others/search_trials.json').exists():raise RuntimeError('Existing Study evidence: explicit reviewed recovery required, never silently restart seed17')
    checked=read(WORK/'others/precheck.json')
    if checked['status']!='PASS' or checked['strategy_sha256']!=digest(WORK/'src/strategy.py'):raise ValueError('Current public precheck required')
    s=Search()
    try:
        freeze(s.research);s.run_stage('INITIAL',36,1.,s.settings['initial_anchors']);extension=s.extension_plan()
        if extension:s.run_stage('ALPHA_EXTENSION',12,2.,extension)
        plans=s.ablations()
        if plans:s.run_stage('MATCHED_ABLATION',len(plans),2.,plans)
        s.persist('COMPLETED_PARAMETER_SEARCH');record=material(s.research,'complete-optuna-family',WORK/'others/search_trials.json');save(WORK/'others/search_publication.json',{'family':record.to_dict(),'all_joint_pass_retained':True,'all_trial_daily_equity_retained':True,'no_stage4_or_test':True});print('SEARCH_FINISHED',len(s.rows),[r['candidate_id'] for r in s.rows if r.get('all_goals_met')],flush=True)
    except BaseException as error:
        for row in s.rows:
            if row['status']=='PROPOSED':
                row.update(status='UNKNOWN',error={'type':type(error).__name__,'message':str(error)})
                t=next(t for t in s.study.get_trials(deepcopy=False) if t.number==row['trial_number'])
                if t.state is TrialState.RUNNING:s.study.tell(t.number,state=TrialState.FAIL)
        s.persist('STOPPED_WITH_EXPLICIT_ERROR_NO_AUTORETRY');raise

if __name__=='__main__':main()
