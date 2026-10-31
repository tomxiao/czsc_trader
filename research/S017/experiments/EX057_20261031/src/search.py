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

KEYS=('alpha','initial_fraction','accepted_fraction','g_when_u','g_when_other')
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
        self.settings=read(WORK/'protocols/search_space.json');self.research,self.prepared,_=prepare_data()
        self.source=digest(WORK/'src/strategy.py');self.rows=[];self.warm=[];self.by_hash={};self.duplicates=[];self.segments=[];self.memory=[];self.calendar=None
        if self.source!=self.settings['raw_source_sha256']:raise ValueError('Frozen raw strategy identity differs from search contract')
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        self.study=optuna.create_study(study_name='S017_EX057_BACKGROUND_JOINT',storage=optuna.storages.InMemoryStorage(),sampler=optuna.samplers.TPESampler(seed=17,n_startup_trials=16,multivariate=False,constant_liar=True,constraints_func=lambda t:t.user_attrs['constraint_vector']),directions=('maximize','minimize'))
    def all_rows(self):return self.warm+self.rows
    def compact(self,payload):
        run=payload['runs']['candidate'];points=run['account_points'];daily=run['account_daily']
        calendar={'point_times':[p['time'] for p in points],'point_sessions':[p['session'] for p in points],'sessions':[p['session'] for p in daily]}
        if self.calendar is None:self.calendar=calendar;save(WORK/'others/common_calendar.json',calendar)
        elif calendar!=self.calendar:raise ValueError('Common training calendar changed')
        return {'bar_equity':[p['equity'] for p in points],'closed_exits':[{'cycle_id':p.get('cycle_id'), 'exit_at':p['exit_at']} for p in run['trades'] if p['status']=='CLOSED'],'final_point':points[-1],'fees_from_fills':sum(p['fees'] for p in run['fills'])}
    def record_payload(self,row,payload,result_hash,checkpoint):
        c,b,goals,constraints=assess(payload)
        if payload['input_ref']['sha256']!=self.settings['input_sha256']:raise ValueError('Main input identity changed')
        row.update(status='SUCCEEDED',metrics=c,benchmark_metrics=b,goals=goals,all_goals_met=all(goals.values()),constraint_vector=constraints,request_hash=payload['request_hash'],result_hash=result_hash,candidate_artifact=payload['candidate_ref'],input_artifact=payload['input_ref'],benchmark_artifact=payload['benchmark_ref'],evaluation_identity=payload['evaluation_identity'],evaluation_id=payload['evaluation_id'],checkpoint_run_id=checkpoint,daily_equity=[{'session':v['session'],'equity':v['equity']} for v in payload['runs']['candidate']['account_daily']],raw_statistics=self.compact(payload))
    def tell(self,t,row):
        t.set_user_attr('constraint_vector',row['constraint_vector']);t.set_user_attr('goals',row['goals']);t.set_user_attr('all_goals_met',row['all_goals_met']);t.set_user_attr('request_hash',row['request_hash']);self.study.tell(t,(row['metrics']['annualized_return'],row['metrics']['bar_max_drawdown']))
    def warm_start(self):
        from common import authenticate
        for key,old in read(WORK/'protocols/warm_start.json').items():
            current=candidate(key,old['parameters']).definition
            if json.loads(json.dumps(current.to_dict()))!=old['definition'] or current.to_dict()['source_sha256']!=self.settings['aggregate_source_hash']:raise ValueError('Warm definition/source/graph/schema/parameters/spec identity mismatch')
            if current.content_identity.content_sha256!=old['evaluation_identity']['content_sha256']:raise ValueError('Warm actor definition content mismatch')
            path=authenticate(old['evidence']);envelope=read(path);allowed={(envelope[k]['kind'],envelope[k]['sha256']) for k in ('input_ref','candidate_ref','benchmark_ref')}
            def resolve(ref):
                if (ref['kind'],ref['sha256']) not in allowed:raise ValueError('Unexpected warm dependency')
                return (path.parent/(ref['sha256']+'.json')).read_bytes()
            payload=materialize_equity(path.read_bytes(),resolve).payload
            self.study.enqueue_trial(old['parameters']);t=self.study.ask();pars={k:t.suggest_float(k,0.,2. if k=='alpha' else 1.) for k in KEYS}
            if pars!=old['parameters']:raise ValueError('Warm effective parameters differ')
            h=params_hash(pars);row={'trial_number':t.number,'candidate_id':key,'parameters':pars,'parameter_hash':h,'stage':'WARM_IMPORTED','source_sha256':self.source,'definition':old['definition'],'original_evidence':old['evidence'],'original_experiment':'EX056_20261031','new_compute':0}
            self.record_payload(row,payload,old['evidence']['sha256'],None);self.warm.append(row);self.by_hash[h]=row
            for name,value in {'stage':'WARM_IMPORTED','prior_experiment':'EX056_20261031','prior_candidate':key,'prior_evidence':old['evidence'],'source_sha256':self.source,'parameter_hash':h,'new_compute':0}.items():t.set_user_attr(name,value)
            self.tell(t,row);del payload
        save(WORK/'others/warm_authentication.json',{'status':'PASS','new_compute':0,'source_sha256':self.source,'aggregate_source_hash':self.settings['aggregate_source_hash'],'input_sha256':self.settings['input_sha256'],'old_refs':[r['original_evidence'] for r in self.warm],'full_definition_semantic_equality':True,'original_actor_identity_preserved':True})
    def persist(self,status='RUNNING'):
        trials=[{'number':t.number,'state':t.state.name,'params':t.params,'values':t.values,'distributions':{k:distribution_to_json(v) for k,v in t.distributions.items()},'user_attrs':t.user_attrs,'start':str(t.datetime_start),'complete':str(t.datetime_complete)} for t in self.study.get_trials(deepcopy=False)]
        allrows=self.all_rows();passed=[r['candidate_id'] for r in allrows if r.get('all_goals_met')]
        data={'status':status,'source_sha256':self.source,'settings':self.settings,'optuna_version':optuna.__version__,'trial_states':trials,'warm_imported_results':self.warm,'unique_results':self.rows,'duplicates':self.duplicates,'joint_pass_candidates':passed,'return_drawdown_frontier':[r['candidate_id'] for r in frontier(allrows)],'segments':self.segments,'memory':self.memory,'calendar_file':'common_calendar.json','test_access':False,'new_data':False,'initial_unique_shortfall':max(0,40-sum(r['stage']=='INITIAL' for r in self.rows)) if status=='COMPLETED_PARAMETER_SEARCH' else None}
        save(WORK/'others/search_trials.json',data);save(WORK/'others/search_progress.json',{'status':status,'imported':len(self.warm),'new_unique':len(self.rows),'optuna_trials':len(trials),'duplicates':len(self.duplicates),'joint_pass':passed,'last_rows':[{k:r.get(k) for k in ('candidate_id','parameters','status','metrics')} for r in self.rows[-4:]],'segments':self.segments,'memory':self.memory[-3:]})
    def propose(self,stage,scheduled=None):
        if scheduled is not None:self.study.enqueue_trial(scheduled)
        t=self.study.ask();pars={k:t.suggest_float(k,0.,2. if k=='alpha' else 1.) for k in KEYS};h=params_hash(pars)
        kind='FIXED_ANCHOR' if stage=='INITIAL' and scheduled is not None else ('MODEL_TPE' if stage=='INITIAL' else 'FIXED_MATCHED')
        for name,value in {'stage':stage,'proposal_kind':kind,'parameter_hash':h,'source_sha256':self.source}.items():t.set_user_attr(name,value)
        if h in self.by_hash:
            old=self.by_hash[h];self.duplicates.append({'trial':t.number,'stage':stage,'candidate':old['candidate_id'],'parameter_hash':h,'new_compute':0});t.set_user_attr('reused_unique_candidate',old['candidate_id']);return t,None,old
        key='C'+str(223+len(self.rows)).zfill(4);row={'trial_number':t.number,'candidate_id':key,'parameters':pars,'parameter_hash':h,'stage':stage,'proposal_kind':kind,'status':'PROPOSED','source_sha256':self.source,'new_compute':1};self.rows.append(row);self.by_hash[h]=row;t.set_user_attr('candidate_id',key);return t,row,None
    def batch(self,execution,run_id,stage,count,scheduled=None):
        tasks=[self.propose(stage,None if scheduled is None else scheduled.pop(0)) for _ in range(count)];active=[(t,r) for t,r,_ in tasks if r is not None]
        if digest(WORK/'src/strategy.py')!=self.source:raise ValueError('Frozen strategy changed during Study')
        self.persist()
        if active:
            candidates=[candidate(r['candidate_id'],r['parameters']) for _,r in active]
            for (_,r),c in zip(active,candidates,strict=True):r['definition']=c.definition.to_dict()
            handles=tuple(self.research.evaluation.prepare(request(c,self.prepared),execution=execution) for c in candidates)
            outcomes=self.research.evaluation.evaluate_many(handles,execution=execution)
            for (t,row),out in zip(active,outcomes,strict=True):
                if out.status.value!='SUCCEEDED' or out.result is None:
                    row.update(status=out.status.value,error=None if out.error is None else {'code':out.error.code,'message':out.error.message},checkpoint_run_id=run_id);self.study.tell(t,state=TrialState.FAIL);continue
                payload=materialize_equity(out.result).payload;self.record_payload(row,payload,out.result.result_hash,run_id);self.tell(t,row);del payload
            del outcomes,handles,candidates
        for t,row,old in tasks:
            if old is not None:
                if old['status']=='SUCCEEDED':self.tell(t,old)
                else:self.study.tell(t,state=TrialState.FAIL)
        self.memory.append({'stage':stage,'segment':run_id,'new_unique':len(self.rows),**working_set()});self.persist();print('TRIAL_BATCH',stage,len(self.rows),[(r['candidate_id'],r.get('metrics',{}).get('annualized_return'),r.get('metrics',{}).get('bar_max_drawdown'),r.get('all_goals_met')) for _,r in active],flush=True);gc.collect()
    def matched_plan(self):
        pool=[r for r in self.all_rows() if r['status']=='SUCCEEDED' and all(v for k,v in r['goals'].items() if k!='annualized_return')]
        if not pool:
            save(WORK/'others/matched_ablation_plan.json',{'winner':None,'comparisons':[],'new_unique':0,'reason':'No COMPLETE other-four-original-gates-pass;no fallback score or substitute winner'});return []
        winner=sorted(pool,key=lambda r:(-r['metrics']['annualized_return'],r['candidate_id']))[0];p=winner['parameters'];plan=[];comparisons=[]
        for label,gu,gn in [('STATIC0',0.,0.),('STATIC075',.75,.75),('STATIC1',1.,1.),('STATIC_WINNER_U',p['g_when_u'],p['g_when_u']),('STATIC_WINNER_OTHER',p['g_when_other'],p['g_when_other']),('SWAPPED',p['g_when_other'],p['g_when_u'])]:
            v={**p,'g_when_u':gu,'g_when_other':gn};h=params_hash(v);prior=self.by_hash.get(h);comparisons.append({'label':label,'winner':winner['candidate_id'],'parameters':v,'parameter_hash':h,'reused_candidate':None if prior is None else prior['candidate_id']})
            if prior is None and all(params_hash(x)!=h for x in plan):plan.append(v)
        save(WORK/'others/matched_ablation_plan.json',{'winner':winner['candidate_id'],'selection':'All COMPLETE other-four-original-gates-pass max annualized return,tie candidate_id lexicographic;all joint retained separately','comparisons':comparisons,'new_unique':len(plan),'same_alpha_a_b':True,'no_reoptimization':True});assert len(plan)<=6;return plan
    def run(self):
        anchors=list(self.settings['initial_anchors'])
        for segment_no,proposal_count in enumerate((16,16,8)):
            run_id=f'EX057-search-{segment_no:03d}';segment={'run_id':run_id,'initial_proposal_target':proposal_count};self.segments.append(segment)
            with ResearchExecutionSession(self.research,experiment=EXPERIMENT,checkpoint=ExecutionCheckpointRequest(run_id),on_progress=lambda e:print('PHASE',run_id,e.phase,e.completed,e.total,flush=True)) as execution:
                done=0
                while done<proposal_count:
                    size=min(4,proposal_count-done)
                    if anchors:
                        fixed=anchors[:size];del anchors[:size];self.batch(execution,run_id,'INITIAL',size,fixed)
                    else:self.batch(execution,run_id,'INITIAL',size)
                    done+=size
                if segment_no==2:
                    plans=self.matched_plan()
                    while plans:self.batch(execution,run_id,'MATCHED_ABLATION',min(4,len(plans)),plans)
                segment['stats']={'session':asdict(execution.stats),'equity':asdict(execution.equity_statistics)}
            self.persist();gc.collect()

def freeze(s):
    frozen={str(p.relative_to(WORK)).replace('\\','/'):material(s.research,'pre-'+str(i),p).to_dict() for i,p in enumerate([*sorted((WORK/'src').glob('*.py')),*sorted((WORK/'protocols').glob('*.*'))])}
    old=ROOT/'research/S017/experiments/EX056_20261031'
    for name,path in [('same-source-original',old/'src/strategy.py'),('same-source-original-precheck',old/'others/precheck.json'),('warm-authentication',WORK/'others/warm_authentication.json'),('copied-source-precheck-reuse',WORK/'others/precheck.json'),('search-api-precheck',WORK/'others/search_api_precheck.json'),('alpha-frequency-bound-source',ROOT/'.tmp/s017_ex057_alpha_frequency_bound.py'),('alpha-frequency-bound',ROOT/'.tmp/s017_ex057_alpha_frequency_bound.json')]:frozen['external/'+name]=material(s.research,name,path).to_dict()
    save(WORK/'others/pre_run.json',frozen)

def main():
    if (WORK/'others/search_trials.json').exists():raise RuntimeError('Existing Study evidence requires explicit reviewed recovery;never silently restart')
    check=read(WORK/'others/precheck.json')
    if check['status']!='PASS' or check['strategy_sha256']!=digest(WORK/'src/strategy.py'):raise ValueError('Same source precheck reuse required')
    s=Search()
    try:
        s.warm_start();freeze(s);s.persist();s.run();s.persist('COMPLETED_PARAMETER_SEARCH')
        family=material(s.research,'complete-optuna-family',WORK/'others/search_trials.json');calendar=material(s.research,'common-calendar',WORK/'others/common_calendar.json');save(WORK/'others/search_publication.json',{'family':family.to_dict(),'calendar':calendar.to_dict(),'all_joint_pass_retained':True,'no_stage4_or_test':True});print('SEARCH_FINISHED',len(s.rows),[r['candidate_id'] for r in s.all_rows() if r.get('all_goals_met')],flush=True)
    except BaseException as error:
        for row in s.rows:
            if row['status']=='PROPOSED':row['status']='UNKNOWN_INTERRUPTED'
        s.persist('INTERRUPTED_REVIEW_REQUIRED');save(WORK/'others/interruption.json',{'type':type(error).__name__,'message':str(error),'no_automatic_restart':True});raise

if __name__=='__main__':main()

