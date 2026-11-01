"""One public six-D Study; center+4axes+20model slots,16/9 sessions,at most27compute."""
from dataclasses import asdict
from hashlib import sha256
import ctypes
import gc
import json
import math
from common import ROOT,WORK,EXPERIMENT,read,save,digest,material,prepare_data,candidate,request,authenticate
import optuna
from optuna.trial import TrialState
from optuna.distributions import distribution_to_json
from metrics import summary
from sampler import KEYS,DOMAINS,new_sampler,suggest
from czsc_trader.application import publish_evidence_many
from czsc_trader.research_tools import ResearchExecutionSession,ExecutionCheckpointRequest,EvaluationEvidenceWrite
from czsc_trader.research_tools.equity_replay import materialize_equity


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


def old_payload(key):
    ref=read(WORK/'protocols/economic_reference.json')[key]['evidence'];path=authenticate(ref);env=read(path)
    owned={(env[k]['kind'],env[k]['sha256']) for k in ('input_ref','candidate_ref','benchmark_ref')}
    def resolve(x):
        if (x['kind'],x['sha256']) not in owned:raise ValueError('Unowned original economic dependency')
        p=path.parent/(x['sha256']+'.json')
        if digest(p)!=x['sha256']:raise ValueError('Original dependency changed')
        return p.read_bytes()
    return materialize_equity(path.read_bytes(),resolve).payload,ref


def rolling252(candidate_run,benchmark_run):
    sessions=[p['session'] for p in candidate_run['account_daily']];out=[]
    if len(sessions)!=502 or sessions!=[p['session'] for p in benchmark_run['account_daily']]:raise ValueError('Same502 sessions required')
    def window(run,start,end):
        opening=100000. if start==0 else run['account_daily'][start-1]['equity'];ending=run['account_daily'][end]['equity']
        allowed=set(sessions[start:end+1]);peak=opening;dd=0.
        for p in run['account_points']:
            if p['session'] in allowed:peak=max(peak,p['equity']);dd=max(dd,1-p['equity']/peak)
        return dict(return_net=ending/opening-1,bar_max_drawdown=dd,opening_equity=opening,ending_equity=ending)
    for start in range(0,len(sessions)-252+1,21):
        end=start+251;c=window(candidate_run,start,end);b=window(benchmark_run,start,end)
        out.append(dict(start_index=start,end_index=end,start_session=sessions[start],end_session=sessions[end],candidate=c,benchmark=b,excess_return=c['return_net']-b['return_net']))
    longest=0;current=0
    for row in out:
        current=current+1 if row['excess_return']<0 else 0;longest=max(longest,current)
    return dict(window_sessions=252,step_sessions=21,windows=out,max_consecutive_underperformance_windows=longest,diagnostic_only=True,no_reset_or_reentry=True)


class Search:
    def __init__(self):
        self.settings=read(WORK/'protocols/search_space.json');self.settings_sha=digest(WORK/'protocols/search_space.json')
        if optuna.__version__!='4.9.0' or self.settings['domains']!={k:list(v) for k,v in DOMAINS.items()}:raise ValueError('Prechecked Optuna/domain changed')
        self.research,self.prepared,_=prepare_data();self.source=digest(WORK/'src/strategy.py');self.helper=digest(WORK/'src/negative_run.py')
        if self.source!=self.settings['strategy_sha256'] or self.helper!=self.settings['helper_sha256']:raise ValueError('Source identity changed')
        self.rows=[];self.proposals=[];self.duplicates=[];self.by_hash={};self.segments=[];self.memory=[];self.calendar=None;self.guards={}
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        self.study=optuna.create_study(study_name='S017_EX072_MF_SIX_FLOAT_RETURN',storage=optuna.storages.InMemoryStorage(),sampler=new_sampler(),direction='maximize')
    def persist(self,status='RUNNING'):
        trials=[dict(number=t.number,state=t.state.name,params=t.params,values=t.values,distributions={k:distribution_to_json(v) for k,v in t.distributions.items()},user_attrs=t.user_attrs,system_attrs=t.system_attrs,start=str(t.datetime_start),complete=str(t.datetime_complete)) for t in self.study.get_trials(deepcopy=False)]
        passed=[r['candidate_id'] for r in self.rows if r['status']=='SUCCEEDED' and r.get('all_goals_met')]
        sampler=self.study.sampler
        out=dict(status=status,source_sha256=self.source,helper_sha256=self.helper,settings=self.settings,optuna_version=optuna.__version__,study_directions=[x.name for x in self.study.directions],trial_states=trials,proposals=self.proposals,unique_results=self.rows,duplicates=self.duplicates,joint_pass_candidates=passed,return_drawdown_frontier=[r['candidate_id'] for r in frontier(self.rows)],segments=self.segments,memory=self.memory,calendar_file='common_calendar.json',guards=self.guards,sampler_interface=dict(multivariate=True,independent_calls=sampler.independent_calls,last_relative_space=sampler.last_relative_space,relative_space_checks=sampler.relative_space_checks,model_samples=sampler.model_samples),test_access=False,new_data=False,extra_budget_or_domain_expansion=False)
        save(WORK/'others/search_trials.json',out)
        save(WORK/'others/search_progress.json',dict(status=status,proposal_count=len(self.proposals),unique_count=len(self.rows),duplicates=len(self.duplicates),succeeded=sum(r['status']=='SUCCEEDED' for r in self.rows),joint_pass=passed,last_rows=[{k:r.get(k) for k in ('candidate_id','parameters','status','metrics')} for r in self.rows[-4:]],segments=self.segments,memory=self.memory[-2:]))
    def propose(self,index):
        configs=self.settings['fixed_anchors'];fixed=configs[index] if index<5 else None
        if fixed is not None:self.study.enqueue_trial(fixed)
        trial=self.study.ask()
        if trial.number!=index:raise ValueError('One Study ordinal changed; never reset or recycle proposal slots')
        parameters=suggest(trial);ph=params_hash(parameters);cid=f'C{338+index:04d}';kind='CENTER_CONTROL' if index==0 else 'FIXED_MF_AXIS' if index<5 else 'JOINT_MODEL_TPE'
        row=dict(trial_number=trial.number,candidate_id=cid,parameters=parameters,parameter_hash=ph,stage=kind,proposal_kind=kind,status='PROPOSED',source_sha256=self.source,new_compute=0,known_economic_reference=self.settings['known_economic_equivalences'].get(cid))
        for key,value in dict(candidate_id=cid,stage=kind,parameter_hash=ph,source_sha256=self.source).items():trial.set_user_attr(key,value)
        self.proposals.append(row)
        prior=self.by_hash.get(ph)
        if prior is not None:
            row.update(status='DUPLICATE_NO_COMPUTE',reused_unique_candidate=prior['candidate_id']);trial.set_user_attr('reused_unique_candidate',prior['candidate_id']);self.duplicates.append(dict(trial=trial.number,candidate_id=cid,reused_candidate=prior['candidate_id'],parameter_hash=ph,new_compute=0));return trial,row,prior
        row['new_compute']=1;self.rows.append(row);self.by_hash[ph]=row;return trial,row,None
    def record(self,row,payload,result,run_id):
        c,b,goals,constraints=assess(payload)
        if payload['input_ref']['sha256']!=self.settings['input_sha256']:raise ValueError('Approved input identity changed')
        run=payload['runs']['candidate'];points=run['account_points'];daily=run['account_daily']
        calendar=dict(point_times=[p['time'] for p in points],point_sessions=[p['session'] for p in points],sessions=[p['session'] for p in daily])
        if self.calendar is None:self.calendar=calendar;save(WORK/'others/common_calendar.json',calendar)
        elif self.calendar!=calendar:raise ValueError('Shared actual training clock changed')
        closed=[t for t in run['trades'] if t['status']=='CLOSED'];closed_pnl=math.fsum(t['net_pnl'] for t in closed)
        sequences=dict(bar_equity=[p['equity'] for p in points],closed_exits=[{k:t.get(k) for k in ('cycle_id','entry_at','exit_at','cost','income','net_pnl')} for t in closed],final_point=points[-1],fees_from_fills=math.fsum(f['fees'] for f in run['fills']),closed_net_pnl=closed_pnl,nonclosed_equity_change=points[-1]['equity']-100000.-closed_pnl)
        row.update(status='SUCCEEDED',metrics=c,benchmark_metrics=b,goals=goals,all_goals_met=all(goals.values()),constraint_vector=constraints,original_constraint_vector=list(constraints),sampling_constraint_vector=list(constraints[1:]),request_hash=payload['request_hash'],result_hash=result.result_hash,candidate_artifact=payload['candidate_ref'],input_artifact=payload['input_ref'],benchmark_artifact=payload['benchmark_ref'],evaluation_identity=payload['evaluation_identity'],evaluation_id=payload['evaluation_id'],checkpoint_run_id=run_id,daily_equity=[dict(session=p['session'],equity=p['equity']) for p in daily],raw_statistics=sequences,rolling252=rolling252(run,payload['runs']['buy_hold']))
    def tell(self,trial,row):
        for key,value in dict(original_constraint_vector=row['original_constraint_vector'],sampling_constraint_vector=row['sampling_constraint_vector'],goals=row['goals'],all_goals_met=row['all_goals_met'],request_hash=row['request_hash'],observed_original_return_and_drawdown=[row['metrics']['annualized_return'],row['metrics']['bar_max_drawdown']],actual_actor_identity=row['evaluation_identity']).items():trial.set_user_attr(key,value)
        self.study.tell(trial,row['metrics']['annualized_return'])
        actual=self.study.get_trials(deepcopy=False)[trial.number]
        if list(actual.system_attrs['constraints'])!=row['sampling_constraint_vector'] or len(actual.values)!=1:raise ValueError('Actual sampler4/single-objective tell binding failed')
    def batch(self,execution,run_id,indices):
        if digest(WORK/'protocols/search_space.json')!=self.settings_sha:raise ValueError('Frozen search settings changed')
        for name,sha in self.settings['source_hashes'].items():
            if digest(WORK/name)!=sha:raise ValueError('Frozen source changed: '+name)
        tasks=[self.propose(i) for i in indices];active=[(t,r) for t,r,p in tasks if p is None]
        self.persist()
        if active:
            candidates=[candidate(r['candidate_id'],r['parameters']) for _,r in active]
            for (_,r),c in zip(active,candidates,strict=True):r['definition']=c.definition.to_dict()
            handles=tuple(self.research.evaluation.prepare(request(c,self.prepared),execution=execution) for c in candidates)
            outcomes=self.research.evaluation.evaluate_many(handles,execution=execution)
            publish=[]
            for (trial,row),handle,out in zip(active,handles,outcomes,strict=True):
                if out.status.value!='SUCCEEDED' or out.result is None:
                    row.update(status=out.status.value,error=None if out.error is None else dict(code=out.error.code,message=out.error.message),checkpoint_run_id=run_id);self.study.tell(trial,state=TrialState.FAIL);continue
                payload=materialize_equity(out.result).payload;self.record(row,payload,out.result,run_id)
                if row['candidate_id'] in ('C0338','C0339'):
                    old,oldref=old_payload(row['candidate_id']);checks=compare(old,payload);self.guards[row['candidate_id']]=dict(status='PASS' if all(checks.values()) else 'FAIL',original=oldref,checks=checks);del old
                    save(WORK/'others/baseline_economic_comparison.json',dict(status='PASS' if all(x['status']=='PASS' for x in self.guards.values()) else 'FAIL',paths=self.guards,scope='Each known point:full12 candidate+BH economic projections;no new old-source account'))
                    if not all(checks.values()):row['status']='ECONOMIC_EQUIVALENCE_FAILED';self.study.tell(trial,state=TrialState.FAIL);self.persist('ECONOMIC_EQUIVALENCE_FAILED');raise ValueError('Known economic equivalence failed;stop further search')
                publish.append((handle,out.result,row))
                self.tell(trial,row);del payload
            if publish:
                pubs=publish_evidence_many(self.research,tuple(EvaluationEvidenceWrite(EXPERIMENT,'formal-'+h.candidate.candidate_id,h,result) for h,result,_ in publish),execution=execution)
                if any(x.status.value!='PUBLISHED' for x in pubs):raise ValueError('Known-point V4 publication incomplete')
                path=WORK/'others/all_accounts.json';manifest=read(path) if path.exists() else {}
                for (_,_,row),pub in zip(publish,pubs,strict=True):
                    if pub.reference.sha256!=row['result_hash']:raise ValueError('Public V4 differs from exact evaluated result')
                    row['public_evidence']=pub.reference.to_dict()
                    manifest[row['candidate_id']]=dict(evidence=pub.reference.to_dict(),evaluation_identity=row['evaluation_identity'],evaluation_id=row['evaluation_id'],request_hash=row['request_hash'],parameters=row['parameters'],result_hash=row['result_hash'],new_compute=1)
                save(path,manifest)
                save(WORK/'others/baseline_accounts.json',{k:v for k,v in manifest.items() if k in ('C0338','C0339')})
            del outcomes,handles,candidates,publish
        for trial,row,prior in tasks:
            if prior is not None:
                if prior['status']=='SUCCEEDED':self.tell(trial,prior)
                else:self.study.tell(trial,state=TrialState.FAIL);row['status']='DUPLICATE_OF_FAILED_NO_COMPUTE'
        self.memory.append(dict(segment=run_id,proposals=len(self.proposals),unique=len(self.rows),**working_set()))
        self.persist();print('TRIAL_BATCH',indices,[(r['candidate_id'],r['status'],r.get('metrics',{}).get('annualized_return'),r.get('metrics',{}).get('bar_max_drawdown')) for _,r in active],flush=True);gc.collect()
    def run(self):
        for seg,ids in enumerate((list(range(16)),list(range(16,25)))):
            run_id=f'EX072-sixfloat-{seg:03d}';segment=dict(run_id=run_id,proposal_slots=ids,max_candidate_compute=len(ids));self.segments.append(segment)
            with ResearchExecutionSession(self.research,experiment=EXPERIMENT,checkpoint=ExecutionCheckpointRequest(run_id),on_progress=lambda e:print('PHASE',run_id,e.phase,e.completed,e.total,flush=True)) as execution:
                try:
                    if seg==0:
                        self.batch(execution,run_id,[0])
                        if self.guards.get('C0338',{}).get('status')!='PASS':raise ValueError('Center12 guard must PASS before axes/search')
                        self.batch(execution,run_id,[1,2,3,4])
                        if sum(t.state is TrialState.COMPLETE for t in self.study.get_trials(deepcopy=False))!=5:raise ValueError('Five COMPLETE anchors required for joint model;failed slots are not free-replaced')
                        remaining=list(range(5,16))
                    else:remaining=ids
                    while remaining:
                        chunk=remaining[:4];remaining=remaining[4:];self.batch(execution,run_id,chunk)
                finally:
                    segment['stats']=dict(session=asdict(execution.stats),equity=asdict(execution.equity_statistics))
                    save(WORK/'others/execution_stats.json',self.segments)
            self.persist();gc.collect()
    def boundary_report(self):
        values=[r for r in self.rows if r['status']=='SUCCEEDED'];front={r['candidate_id'] for r in frontier(values)}
        edge=[r for r in values if r['parameters']['alpha']>=self.settings['boundary']['near_upper_threshold']]
        triggers=[r for r in edge if r['candidate_id'] in front or r['all_goals_met']]
        save(WORK/'others/boundary_review.json',dict(status='BOUNDARY_EVIDENCE_WITH_APPROVED_COVERAGE_LIMIT' if triggers else 'NO_SAMPLED_UPPER_EDGE_IMPROVEMENT_TRIGGER',near_alpha_upper_threshold=1.9,near_edge_candidates=[r['candidate_id'] for r in edge],frontier_or_joint_edge_candidates=[r['candidate_id'] for r in triggers],extra_compute=0,domain_expansion_executed=False,reason='Approved alpha domain[0,2] and <=27compute are fixed;alpha>=2 has <=29 rawE0 but original dual frequency gates require>=32closed. Outside-domain joint feasibility is excluded by that necessary bound,not by a new gate;no claim domain-outside returns are worthless or finite within-domain search is exhaustive.',within_domain_coverage_limit='Twenty joint proposals are finite;any sampled edge improvement and untested combinations remain disclosed,never silently expand or claim full optimization.'))


def freeze(search):
    frozen={str(p.relative_to(WORK)).replace('\\','/'):material(search.research,'pre-'+str(i),p).to_dict() for i,p in enumerate([*sorted((WORK/'src').glob('*.py')),*sorted((WORK/'protocols').glob('*.*'))])}
    for name,path in [('source-precheck',WORK/'others/precheck.json'),('optimizer-api-precheck',WORK/'others/search_api_precheck.json'),('domain-helper-precheck',WORK/'others/domain_helper_precheck.json'),('domain-helper-source',ROOT/'.tmp/s017_ex072_run_domain_precheck.py'),('optimizer-api-source',ROOT/'.tmp/s017_ex072_sampler_api_precheck.py')]:frozen['external/'+name]=material(search.research,name,path).to_dict()
    for eid in ('EX071_20261101','EX059_20261031','EX070_20261101'):frozen['prior-report/'+eid]=read(ROOT/'research/S017/experiments'/eid/'others/publication.json')['report']
    prior=read(ROOT/'research/S017/experiments/EX057_20261031/others/pre_run.json')
    for key in ('external/alpha-frequency-bound-source','external/alpha-frequency-bound'):frozen['prior-frequency-proof/'+key]=prior[key]
    save(WORK/'others/pre_run.json',frozen)


def main():
    if (WORK/'others/search_trials.json').exists():raise RuntimeError('Existing Study evidence requires explicit reviewed recovery;never silently reset seed/storage')
    check=read(WORK/'others/precheck.json')
    if check['status']!='PASS' or check['strategy_sha256']!=digest(WORK/'src/strategy.py') or check['helper_sha256']!=digest(WORK/'src/negative_run.py') or check['precheck_sha256']!=digest(WORK/'src/precheck.py'):raise ValueError('Final financial source/precheck binding required')
    api=read(WORK/'others/search_api_precheck.json');domain=read(WORK/'others/domain_helper_precheck.json')
    if api['status']!='PASS' or api['source_sha256']!=digest(ROOT/'.tmp/s017_ex072_sampler_api_precheck.py') or api['sampler_source_sha256']!=digest(WORK/'src/sampler.py') or api['optuna_version']!=optuna.__version__:raise ValueError('Actual6D API precheck/source binding required')
    if domain['source_sha256']!=digest(ROOT/'.tmp/s017_ex072_run_domain_precheck.py') or domain['helper_sha256']!=digest(WORK/'src/negative_run.py') or check['domain_helper_precheck_sha256']!=digest(WORK/'others/domain_helper_precheck.json'):raise ValueError('Entire-domain helper proof binding required')
    search=Search()
    try:
        freeze(search);search.persist();search.run();search.boundary_report();search.persist('COMPLETED_PARAMETER_SEARCH')
        family=material(search.research,'complete-optuna-family',WORK/'others/search_trials.json');calendar=material(search.research,'common-calendar',WORK/'others/common_calendar.json')
        save(WORK/'others/search_publication.json',dict(family=family.to_dict(),calendar=calendar.to_dict(),all_joint_pass_retained=True,no_stage4_or_test=True))
        print('SEARCH_FINISHED',len(search.rows),[r['candidate_id'] for r in search.rows if r.get('all_goals_met')],flush=True)
    except BaseException as error:
        for row in search.rows:
            if row['status']=='PROPOSED':row['status']='UNKNOWN_INTERRUPTED'
        search.persist('INTERRUPTED_REVIEW_REQUIRED');save(WORK/'others/interruption.json',dict(type=type(error).__name__,message=str(error),no_automatic_restart=True));raise


if __name__=='__main__':main()
