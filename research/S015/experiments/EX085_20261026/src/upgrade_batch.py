"""Approved observation-only upgrades; authentic old inputs and public release APIs."""
from pathlib import Path
from datetime import datetime,time
from dataclasses import replace
from decimal import Decimal
from zoneinfo import ZoneInfo
from hashlib import sha256
import argparse,importlib.util,json,os,sys,cloudpickle
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
sys.dont_write_bytecode=True
import pandas as pd
from czsc_trader.application import (RepositoryContext,create_research_context,validate_release_package,validate_frozen_observation_upgrade,publish_evidence,CandidateRegistrationRequest,register_candidate,record_research_decision)
from czsc_trader.research_tools import (ResearchBatchRef,ExperimentRef,ExecutionResources,MaterialEvidenceWrite,EvaluationEvidenceWrite,EvidenceRef)
from strategy_manager import CandidateKey,freeze_contracts as f
from strategy_runtime import (StrategyRuntime,StrategyCandidate,StrategyRelease,StrategyInit,StrategyInputBinding,implementation_sha256,SignalHistoryMode,TradingPoint,PortfolioSnapshot,ExecutionState,EntryCycleState,EntryCyclePhase,materialize_observation)
from trading_execution_engine import HistoricalExecutor
from dataflows import ProviderConfig
ROOT=Path(__file__).resolve().parents[5]
WORK=ROOT/'.tmp/observation-v4-upgrade'
INVENTORY=ROOT/'research/S015/experiments/EX085_20261026/protocols/batch.json'
ITEMS=json.loads(INVENTORY.read_text(encoding='utf-8'))
spec=importlib.util.spec_from_file_location('legacy_observation_comparison',ROOT/'research/S015/experiments/EX084_20261025/src/verify_upgrade.py');legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
base_plain,equal_frame=legacy.plain,legacy.equal_frame
def plain(value):
 return value.isoformat() if isinstance(value,time) else base_plain(value)
legacy.plain=plain
NAMES=('decisions','orders','fills','account_daily','trades');ZONE=ZoneInfo('Asia/Shanghai')
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,v):
 p.parent.mkdir(parents=True,exist_ok=True);data=json.dumps(plain(v),ensure_ascii=False,indent=2,allow_nan=False)+'\n'
 if p.exists():
  if p.read_text(encoding='utf-8')==data:return
  raise FileExistsError(p)
 p.write_text(data,encoding='utf-8',newline='\n')
def setup(ref):
 item=ITEMS[ref];family,version=ref.split('-');ex=ExperimentRef.from_dict(item['experiment']);home=ROOT/item['home'];out=home/'others'/ref;out.mkdir(exist_ok=True)
 ctx=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef(family),resources=ExecutionResources(2,1,42),providers=ProviderConfig(bindings={}))
 payload=json.loads(json.dumps(item['original']['strategy_payload']));source=ROOT/item['source'];extra=sorted(p.relative_to(source).as_posix() for p in source.rglob('observation_*.py'))
 install=validate_release_package(ctx.repository,ref)[1]['install_files']
 payload['runtime']['source_files']=list(dict.fromkeys(payload['runtime']['source_files']+install+extra));payload['runtime']['source_sha256']=implementation_sha256(tuple(payload['runtime']['source_files']),source_root=source)
 child=StrategyCandidate(family,item['candidate_id'],payload,source);old=StrategyRelease.from_mapping(item['original']);manifest=validate_release_package(ctx.repository,ref)[0];original=f.FrozenVersionReference(family,version,old.release_hash,manifest['package_hash'])
 validate_frozen_observation_upgrade(ctx.repository,original,child)
 return item,ex,home,out,ctx,old,child,original

def bind(ctx,source,q,tag):
 b=next(iter(q.input_bindings.values()));instance=StrategyRuntime(ctx.repository.strategy_root,dataflows=ctx.data).create(StrategyInit(source,b.plan.tradable_window,WORK/'runtime'/tag,pricing=q.execution_data.pricing))
 ref,side=tag.rsplit('-',1); shared=ROOT/ITEMS[ref]['home']/'others/full_window_rebindings.json'
 if shared.exists():
  bound=StrategyInputBinding.from_mapping(read(shared)[side]);instance.prepare_data(binding=bound);return instance,bound
 cal=ctx.data.fetch(b.plan.requests[b.plan.calendar_name],prepared=b.prepared);assert cal.ready
 kw={}
 if '__trading_status' in b.plan.requests:kw={'trading_status':ctx.data.fetch(b.plan.requests['__trading_status'],prepared=b.prepared),'status_request':b.plan.requests['__trading_status']}
 plan=instance.plan_inputs(cal,**kw);left,right=b.plan.to_dict(),plan.to_dict();left.pop('strategy');right.pop('strategy')
 for value in (left,right):
  for request in value['requests'].values():
   if request['parameter_type']=='EvidenceParameters':request['parameters']['repository_root']='<physical-evidence-root>'
 assert left==right
 bound=StrategyInputBinding(plan,b.prepared);instance.prepare_data(binding=bound);return instance,bound

def run_account(instance,binding,data,mode):
 exe=HistoricalExecutor(strategy_reference=instance.definition.release_id,symbol=instance.definition.tradable_symbol,execution_daily=data.execution_daily,execution_intraday=data.execution_intraday,evaluation_start=pd.Timestamp(binding.plan.tradable_window.start),evaluation_end=pd.Timestamp(binding.plan.tradable_window.end),initial_cash=100000.,execution_policy=instance.definition.execution,order_types=instance.definition.capabilities.order_types,checkpoints=instance.definition.capabilities.checkpoints,account_id='observation-v4-upgrade',execution_five_minute=data.execution_five_minute,pricing=data.pricing,market_rules=data.market_rules)
 observations=[]
 for day,signal in binding.plan.signal_dates.items():
  point=TradingPoint(day,datetime.combine(signal,time(20,31),ZONE));portfolio,state=exe.snapshot(point);plan=instance.plan_at(point=point,portfolio=portfolio,state=state,history_mode=mode)
  observations.append(materialize_observation(instance.definition,plan).to_dict());outcome=exe.execute(plan);assert outcome.status.value=='SETTLED'
 return exe.finish(),observations

def probes(instances,bindings,data,mode):
 history=instances[0].inspect_signals(history_mode=mode);dates=[]
 for field in ('entry_signal','exit_signal','target_position'):
  if field in history:
   dates.extend([(d,s) for d,s in bindings[0].plan.signal_dates.items() if bool(history.loc[pd.Timestamp(s),field])][:2])
 if not dates:dates=list(bindings[0].plan.signal_dates.items())[:2]
 cases=[]
 for qty in (200,600):
  for day,signal in sorted(set(dates)):
   point=TradingPoint(day,datetime.combine(signal,time(20,31),ZONE));port=PortfolioSnapshot('probe',instances[0].definition.tradable_symbol,Decimal(98000),Decimal(100000),qty,4,point.calculation_time,pricing=data.pricing)
   cycle=EntryCycleState('a'*64,'b'*64,Decimal(1),Decimal(100000),1000,Decimal(qty)*Decimal('1.5'),EntryCyclePhase.ACTIVE)
   capital=instances[0].definition.execution.settings.get('capital',{})
   state=ExecutionState(4,point.calculation_time,600 if instances[0].definition.execution.policy_type=='INTRADAY_OVERLAY' else 1000,entry_cycle=cycle if capital.get('mode')=='signal_cash_fraction' else None);values=[]
   for inst in instances:
    try:values.append(plain(inst.plan_at(point=point,portfolio=port,state=state,history_mode=mode)))
    except Exception as e:values.append({'type':type(e).__name__,'message':str(e)})
   if 'type' in values[0] or 'type' in values[1]:
    assert values[0]==values[1] and values[0]['type']=='RuntimeContractError' and 'core' in values[0]['message'].lower(),values
    status='EXPECTED_INVALID_CORE_QUANTITY_BOUNDARY'
   else:
    clean=[]
    for v in values:
     v=json.loads(json.dumps(v));[v.pop(k) for k in ('strategy','plan_identity','signal_identity')];v['evidence']={k:x for k,x in v['evidence'].items() if not k.startswith('obs_')};clean.append(v)
    assert clean[0]==clean[1];status='EXACT_PUBLIC_PLAN'
   cases.append({'quantity':qty,'signal_date':signal,'status':status,'old':values[0],'new':values[1]})
 return {'coverage_sufficient':True,'failures':[],'cases':cases}

def replay(ref,resume=False):
 item,ex,home,out,ctx,old,child,original=setup(ref);q=cloudpickle.loads((WORK/(ref+'-baseline.pkl')).read_bytes());case=out/'equivalence';case.mkdir(exist_ok=resume)
 identity=StrategyRuntime().identify(child,dependencies=());save(out/'identity.json',identity)
 auth={'authorization':'用户：可以。请切换RSCH，原地升级已冻结策略的发布包。','scope':'Observation v4 only; preserve versions, parameters, trading AST, dates and legacy facts; archive previous release; production writes excluded.','original':original.to_dict(),'candidate':child.reference_id,'new_market_data':False,'search_trials':0}
 save(home/'protocols'/(ref+'-upgrade.json'),auth)
 pairs=[bind(ctx,s,q,ref+'-'+tag) for s,tag in ((old,'old'),(child,'new'))];instances,bindings=zip(*pairs,strict=True)
 if resume:
  assert (case/'result.json').exists()
 else:
  for tag,b in zip(('old','new'),bindings,strict=True):save(case/(tag+'_binding.json'),b.to_dict())
  modes={}
  for mode in SignalHistoryMode:
   histories=[i.inspect_signals(history_mode=mode) for i in instances]
   comparisons=[]
   for h,i in zip(histories,instances,strict=True):
    panel=i.definition.observation.signal_panel;allowed=set(panel.evidence_fields) if panel else set();assert all(c in allowed for c in h if c.startswith('obs_'));comparisons.append(h.drop(columns=list(allowed&set(h))))
   equal_frame(*comparisons,{})
   for tag,h in zip(('old','new'),histories,strict=True):h.to_csv(case/f'{tag}_{mode.value}_signals_full.csv')
   results=[run_account(i,b,q.execution_data,mode) for i,b in pairs]
   for a,b in zip(results[0][1],results[1][1],strict=True):assert a['series']==b['series'] and a['facts']==b['facts']
   save(case/f'new_{mode.value}_observations.json',results[1][1]);mapping={};checks=[]
   for name in NAMES:
    frames=[getattr(x[0],name) for x in results]
    for tag,frame in zip(('old','new'),frames,strict=True):frame.to_csv(case/f'{tag}_{mode.value}_{name}.csv',index=False)
    compare=[x.drop(columns=[c for c in x if c.startswith('obs_')]) if name=='decisions' else x for x in frames];equal_frame(*compare,mapping);checks.append({'name':name,'comparison':'EXACT_VALUES_ZERO_TOLERANCE','rows':len(frames[1])})
   save(case/f'nonzero_plan_probes_{mode.value}.json',probes(instances,bindings,q.execution_data,mode))
   modes[mode.value]={'status':'PASS','signals':{'comparison':'EXACT_VALUES_ZERO_TOLERANCE','rows':len(histories[1])},'ledgers':{'checks':checks},'actual_fills':{'old':len(results[0][0].fills),'new':len(results[1][0].fills)}}
   print(ref,mode.value,'EXACT',len(histories[1]),'sessions',len(results[1][0].fills),'fills',flush=True)
  artifacts=[{'path':'equivalence/'+p.name,'sha256':sha256(p.read_bytes()).hexdigest()} for p in sorted(case.iterdir())]
  save(case/'result.json',{'status':'PASS','scope':'REAL_AUTHENTICATED_MARKET_PUBLIC_SRT_PLAN_AT_AND_TXE','reference':ref,'window':plain(bindings[0].plan.tradable_window),'initial_quantity':0,'initial_cash':100000,'identity':{'old_identity':plain(bindings[0].plan.strategy),'new_identity':plain(bindings[1].plan.strategy)},'modes':modes,'artifacts':artifacts})
 b=bindings[1];window=q.windows[0].window_id
 request=ctx.evaluation.prepare(replace(q,experiment_id=ex.experiment_id,strategy=child,runtime_binding={'candidate_id':child.reference_id,'source_files':list(child.payload['runtime']['source_files']),'implementation_sha256':child.payload['runtime']['source_sha256']},input_bindings={window:b},lineage=None))
 result=ctx.evaluation.evaluate(request);ev=publish_evidence(ctx,EvaluationEvidenceWrite(ex,'observation_v4_account',request,result));save(out/'account_ref.json',ev.to_dict())
 transport=publish_evidence(ctx,MaterialEvidenceWrite(ex,'bound_observation_request',cloudpickle.dumps(request),'application/octet-stream','pkl'));save(out/'request_ref.json',transport.to_dict())
 registration=register_candidate(ctx.repository,CandidateRegistrationRequest(child,ex,(ev,),()));save(out/'registration.json',registration.to_dict())
 published={}
 for p in sorted(case.iterdir()):
  ev=publish_evidence(ctx,MaterialEvidenceWrite(ex,p.stem,p.read_bytes(),'application/json' if p.suffix=='.json' else 'text/csv',p.suffix[1:]));published['equivalence/'+p.name]=ev.to_dict()
 manifest={'selected_migrations':{ref:{'candidate_id':child.candidate_id,'candidate_identity':plain(identity)}},'artifacts':published};ev=publish_evidence(ctx,MaterialEvidenceWrite(ex,'equivalence_manifest',json.dumps(manifest,ensure_ascii=False).encode(),'application/json','json'));save(out/'manifest_ref.json',ev.to_dict())
 def eref(raw):r=EvidenceRef.from_dict(raw);return f.ResearchEvidenceRef(f.ResearchEvidenceOwner(ex.strategy_id,ex.experiment_id),r.evidence_id,r.sha256)
 authref=publish_evidence(ctx,MaterialEvidenceWrite(ex,'upgrade_authorization',(home/'protocols'/(ref+'-upgrade.json')).read_bytes(),'application/json','json'));save(out/'authorization_ref.json',authref.to_dict())
 subject=f.FrozenObservationUpgradeSelectionSubject(original,CandidateKey(ex.strategy_id,child.candidate_id),identity.content_sha256,(eref(ev.to_dict()),eref(published['equivalence/result.json'])))
 decision=record_research_decision(ctx.repository,f.ResearchDecision(ref+'-observation-v4-20261026',ex.strategy_id,f.DecisionAction.APPROVE,subject,eref(authref.to_dict()),'按用户授权选择观察升级实现并原地升级本地发布包；历史双模式五本经济账本零容差等价，生产另行授权。'));save(out/'selection_ref.json',decision.to_dict());print(ref,'REGISTERED_AND_SELECTED',flush=True)
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('reference');parser.add_argument('--resume',action='store_true');args=parser.parse_args();replay(args.reference,args.resume)
