"""Publish exact migration evidence and inspect the authorized native V4 candidate."""
from pathlib import Path
from datetime import date,datetime,timedelta
from dataclasses import replace
from decimal import Decimal,ROUND_HALF_EVEN
import json,sys
from run_s003_s007_accounts import native,s003,s007,ROOT,OUT,clock
from dataflows import ProviderConfig,PreparePolicy,TimeInterval,EquityDataRequest,EquityProduct
from strategy_manager import CandidateEvidence,freeze_contracts as f
from strategy_runtime import InspectionControl,EquityInputBinding,EquityAuxiliaryBinding,ExecutionInputBinding,DatasetObservationBinding
from czsc_trader.application import (RepositoryContext,create_research_context,create_experiment,ExperimentRequest,
 publish_evidence,register_candidate,CandidateRegistrationRequest,record_research_decision,CandidateInspectionRequest,
 EquityInspectionProtocol,FreezeTarget,InspectionDataKind,inspect_candidate,describe_inspection_environment)
from czsc_trader.application.equity_inspection import replay_account
from czsc_trader.research_tools import (ResearchBatchRef,ExperimentRef,EvidenceRef,MaterialEvidenceWrite,ResearchExecutionSession,EquitySources,EquityEvaluationRequest,EvaluationEvidenceWrite,EvaluationBenchmark,EquityBuyHold)
from paper_trading_engine.equity_inspection import (EquityPteDecision,EquityPteReport,EquityPteRestart,
 EquityPteReconcile,EquityPteScenario,EquityPteInspectionProtocol)

def main(family):
 technical_only="--technical-only" in sys.argv
 first=date(2026,9,10) if family=='S003' else date(2026,9,3)
 fee=Decimal('.00012' if family=='S003' else '.001');initial=Decimal('100000')
 candidate,flow,providers,replay=native(family,s003 if family=='S003' else s007,first,float(fee),prepare_only=True)
 context=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef(family),
   providers=ProviderConfig(env_file=ROOT/'.env',equity_bindings=providers),execution_spec=candidate.definition.execution_spec)
 expfile=OUT/(family+'-experiment.json')
 if expfile.exists():exp=ExperimentRef.from_dict(json.loads(expfile.read_text(encoding='utf-8')))
 else:
  exp=create_experiment(context,ExperimentRequest(f'{family}-v1 原生V4冻结实现等价迁移','保留冻结信号数学、输入可用时点、交易预算与成交规则；验证历史信号、真实增量账户和隔离PTE技术行为。',date(2026,11,6)))
  expfile.write_text(json.dumps(exp.to_dict(),indent=2),encoding='utf-8')
 home=exp.resolve(ROOT)
 # Prepare identical declared products in the owning research namespace.
 prepared=context.data.prepare(replay.requests,policy=PreparePolicy.REUSE)
 if not prepared.ready:raise ValueError([(str(x.request.dataset),str(x.error)) for x in prepared.items if not x.ready])
 for key,query in replay.input_binding.bind_requests(replay.requests):
  assert context.data.fetch(query,prepared=prepared.reference).identity.content_sha256 == replay.input_binding.expected_identities[key]
 replay=replace(replay,input_binding=replace(replay.input_binding,prepared=prepared.reference))
 refs=[]
 files=[OUT/'comparison.json',OUT/(family+'-native.json'),OUT/(family+'-binding.json'),OUT/(family+'-definition.json'),ROOT/'.tmp/rsch-frozen-v4-upgrade/s003_s007-equivalence.json',ROOT/'.tmp/rsch-frozen-v4-upgrade/s003_s007_data/real-signal-equivalence.json',ROOT/'.tmp/rsch-frozen-v4-upgrade/action_coverage.json']
 files += list(OUT.glob(family+'-legacy-*.csv'))
 if technical_only:
  refs=[EvidenceRef.from_dict(x) for x in json.loads((home/'others'/'evidence_refs.json').read_text(encoding='utf-8'))]
 else:
  for path in files:
   content=path.read_bytes();(home/'others'/path.name).write_bytes(content)
   refs.append(publish_evidence(context,MaterialEvidenceWrite(exp,'migration-'+path.stem,content,'application/json' if path.suffix=='.json' else 'text/csv',path.suffix[1:])))
  for path in sorted(candidate.source_root.glob('*')):
   if path.is_file() and path.suffix in ('.py','.csv','.json'):
    (home/'src'/path.name).write_bytes(path.read_bytes())
  refs=list(dict.fromkeys(refs))
 (home/'others'/'evidence_refs.json').write_text(json.dumps([r.to_dict() for r in refs],indent=2),encoding='utf-8')
 source=replay.input_binding.request_bindings[0][1].source
 accountfile=home/'others'/('account_ref_'+candidate.candidate_id+'.json')
 if accountfile.exists():accountref=EvidenceRef.from_dict(json.loads(accountfile.read_text()))
 else:
  with ResearchExecutionSession(context,experiment=exp) as execution:
   evaluation=EquityEvaluationRequest(exp,candidate,replay.interval if hasattr(replay,'interval') else replay.window,date(2026,8,1),EquitySources(source,source,source,source),100000.,float(fee),window_id='migration',scenario_id='STANDARD',measurement_tier='FORMAL',benchmark=EvaluationBenchmark(EquityBuyHold(candidate.definition.execution_spec)),drawdown_basis='SESSION_CLOSE',concentration_basis='TOP_DECILE')
   prepared_account=context.evaluation.prepare(evaluation,execution=execution)
   outcome,=context.evaluation.evaluate_many((prepared_account,),execution=execution)
   if outcome.result is None:raise ValueError(outcome.error)
   accountref=publish_evidence(context,EvaluationEvidenceWrite(exp,'migration-standard',prepared_account,outcome.result),execution=execution)
  (home/'others'/('account_ref_'+candidate.candidate_id+'.json')).write_text(json.dumps(accountref.to_dict(),indent=2),encoding='utf-8')
 registration=register_candidate(context.repository,CandidateRegistrationRequest(candidate,exp,(accountref,),candidate.definition.dependencies))
 auth={'user_messages':['不影响交付就先不管吧。切换RSCH，已冻结策略实现统一原地升级，适配当前PTE版本，并做等价性验证','继续'],
  'scope':'精确等价迁移候选的技术检验，不操作生产或应用冻结升级', 'strategy':family,'candidate':candidate.candidate_id,'content_sha256':registration.content_sha256}
 authref=publish_evidence(context,MaterialEvidenceWrite(exp,'upgrade-authorization',json.dumps(auth,ensure_ascii=False).encode(),'application/json','json'))
 selection=record_research_decision(context.repository,f.ResearchDecision('native-v4-upgrade-'+candidate.candidate_id,family,f.DecisionAction.APPROVE,
  f.CandidateSelectionSubject(candidate.key,registration.content_sha256,registration.record_sha256),CandidateEvidence(authref.repository_path,authref.sha256),'按用户授权选择精确等价迁移候选进行技术检验'))
 # Frozen technical target retains its original selection cutoff.
 techfirst,techend=(date(2026,8,25),date(2026,8,28)) if family=='S003' else (date(2026,8,4),date(2026,8,7))
 queries={}
 for role,parameters in replay.input_binding.request_bindings:
  query=replace(parameters.query,end=techend,start=date(2026,7,1) if role.startswith('auxiliary:') and family=='S007' else parameters.query.start)
  queries[role]=EquityDataRequest(parameters.instrument,parameters.source,query)
 observations={item.name:item.request(date(2026,8,1),techend,source_root=candidate.source_root) for item in candidate.definition.observation_inputs}
 queries.update({'observation:'+name:q for name,q in observations.items() if q is not None})
 requests=tuple(dict.fromkeys(queries.values()));prep=context.data.prepare(requests,policy=PreparePolicy.REUSE)
 if not prep.ready:raise ValueError([(str(x.request.dataset),str(x.error)) for x in prep.items if not x.ready])
 hashes={role:context.data.fetch(q,prepared=prep.reference).identity.content_sha256 for role,q in queries.items()}
 auxiliary=tuple(EquityAuxiliaryBinding(item,hashes[item.data_key(EquityProduct.BARS)],hashes[item.data_key(EquityProduct.SESSIONS)]) for item in candidate.definition.auxiliary_inputs)
 item=candidate.definition.execution_input
 execbinding=None if item is None else ExecutionInputBinding(item,hashes['execution:bars'],hashes['execution:sessions'])
 obs=tuple(DatasetObservationBinding(item,None,None,techend) if observations[item.name] is None else DatasetObservationBinding(item,observations[item.name],hashes[item.data_key()]) for item in candidate.definition.observation_inputs)
 binding=EquityInputBinding(prep.reference,candidate.instrument,candidate.execution_spec_hash,tuple((key,hashes[key]) for key in ('bars','actions','constraints','sessions')),candidate.warmup_bars,auxiliary,execbinding,tuple((role,q.parameters) for role,q in queries.items() if not role.startswith('observation:')),obs)
 replay=replace(replay,input_binding=binding,requests=requests,window=TimeInterval(clock(techfirst,9,30),clock(techend,15)))
 result=json.loads((OUT/(family+'-technical-ledger.json')).read_text(encoding='utf-8')) if technical_only else replay_account(candidate,context.data,replay)
 facts=result['facts'];orders=facts['orders'];fills=facts['fills']
 (OUT/(family+'-technical-ledger.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
 refs.append(publish_evidence(context,MaterialEvidenceWrite(exp,'migration-technical-ledger',json.dumps(result).encode(),'application/json','json')))
 refs=list(dict.fromkeys(refs))
 (home/'others'/'evidence_refs.json').write_text(json.dumps([r.to_dict() for r in refs],indent=2),encoding='utf-8')
 stamp=lambda value:datetime.fromisoformat(value.replace('Z','+00:00'))
 interval=lambda row:TimeInterval(stamp(row['valid_start']),stamp(row['valid_end']))
 buy=orders[0];entry=interval(buy);q=buy['quantity'];price=Decimal(str(fills[0]['price']));reserved=q*Decimal(str(buy['limit_price']))*(1+fee)
 reconcile=EquityPteReconcile(initial,0);partial=EquityPteReport(0,100,price,entry.start+timedelta(minutes=1),'FILLED_PART')
 base=(reconcile,EquityPteDecision(entry,entry.start),partial,partial,EquityPteRestart(),EquityPteReport(0,q,price,entry.start+timedelta(minutes=2),'FILLED_ALL'))
 if family=='S003':
  rotate=interval(orders[1]);rq=orders[1]['quantity'];rp=Decimal(str(fills[1]['price']));sp=Decimal(str(fills[2]['price']))
  steps=base+(EquityPteDecision(rotate,rotate.start),EquityPteReport(1,rq,rp,rotate.start+timedelta(minutes=1),'FILLED_ALL'),EquityPteRestart(),
   EquityPteDecision(rotate,rotate.start+timedelta(minutes=119)),EquityPteReport(2,rq,sp,rotate.start+timedelta(minutes=120),'FILLED_ALL'),EquityPteRestart())
  final_cash=initial-q*price*(1+fee)-rq*rp*(1+fee)+rq*sp*(1-fee);final_q=q
 else:
  sell=next(o for o in orders if o['side']=='SELL');exit_=interval(sell);sp=Decimal(str(next(x for x in fills if x['side']=='SELL')['price']))
  steps=base+(EquityPteDecision(exit_,exit_.start),EquityPteReport(1,q,sp,exit_.start+timedelta(minutes=1),'FILLED_ALL'),EquityPteRestart())
  final_cash=initial-q*price*(1+fee)+q*sp*(1-fee);final_q=0
 money=lambda value:value.quantize(Decimal('.0001'),rounding=ROUND_HALF_EVEN)
 if family=='S003':
  corecost=q*price+money(q*price*fee)
  final_cash=initial-corecost-rq*rp-money(rq*rp*fee)+rq*sp-money(rq*sp*fee)
 reserved=money(reserved)
 scenarios=[EquityPteScenario('partial-duplicate-restart-complete',steps,final_cash,final_q,Decimal(0)),
  EquityPteScenario('partial-cancel',(reconcile,EquityPteDecision(entry,entry.start),partial,EquityPteReport(0,100,price,entry.start+timedelta(minutes=2),'CANCELLED_PART'),EquityPteRestart()),initial-100*price-money(100*price*fee),100,Decimal(0))]
 for code,outcome,at in [('REJECTED','REJECTED',entry.start),('UNKNOWN','UNKNOWN',entry.start),('EXPIRED','ACCEPTED',entry.end)]:
  scenarios.append(EquityPteScenario(code,(reconcile,EquityPteDecision(entry,at,outcome,'NO_ORDER' if code=='EXPIRED' and family=='S003' else code)),initial if code=='REJECTED' or (code=='EXPIRED' and family=='S003') else initial-reserved,0,Decimal(0)))
 if family=='S003':
  partial_rotation=EquityPteReport(1,100,rp,rotate.start+timedelta(minutes=1),'FILLED_PART')
  cancel_steps=base+(EquityPteDecision(rotate,rotate.start),partial_rotation,EquityPteRestart(),
   EquityPteReport(1,100,rp,rotate.start+timedelta(minutes=2),'CANCELLED_PART'),
   EquityPteDecision(rotate,rotate.start+timedelta(minutes=119),expected='NO_ORDER'),EquityPteRestart())
  scenarios.append(EquityPteScenario('rotation-partial-cancel-blocks-exit',cancel_steps,
   initial-corecost-100*rp-money(100*rp*fee),q+100,Decimal(0)))
 scenarios.append(EquityPteScenario('reconciliation-blocked',(EquityPteReconcile(initial-1,0),EquityPteDecision(entry,entry.start,expected='RECONCILIATION_BLOCKED')),initial,0,Decimal(0)))
 protocol=EquityInspectionProtocol('candidate-inspection-v4','ECONOMIC_V1',0.,EquityPteInspectionProtocol(describe_inspection_environment(context.repository),tuple(scenarios)))
 version=json.loads((ROOT/f'strategies/{family}/versions/v1.json').read_text(encoding='utf-8'))
 target=FreezeTarget('v1',version.get('parent_version'),'原生V4等价迁移技术检验',date.fromisoformat(version['selection_data_cutoff']),date.fromisoformat(version['forward_start']))
 request=CandidateInspectionRequest(candidate.key,selection,context,exp,target,protocol,(replay,),InspectionDataKind.HISTORICAL,
  remaining_risks=('完整冻结seed区间验证信号数学和输入前缀一致；真实原生账户对比限于2026年9月至11月5日，无全历史V4账户通过声明。','生产依赖RAW行情及实际公司行动持续供给；本证据无公司行动覆盖仅2026-08-01至2026-11-05。'))
 (home/'protocols'/'technical_protocol.json').write_text(json.dumps(protocol.to_dict(),indent=2,default=str),encoding='utf-8')
 report=inspect_candidate(context.repository,request,control=InspectionControl(max_workers=1,timeout_seconds=600,on_progress=lambda p:print(str(p),flush=True)))
 (OUT/(family+'-inspection.json')).write_text(json.dumps(report.to_dict(),ensure_ascii=False,indent=2,default=str),encoding='utf-8')
 (home/'others'/'inspection.json').write_text(json.dumps(report.to_dict(),ensure_ascii=False,indent=2,default=str),encoding='utf-8')
 (OUT/(family+'-registered.json')).write_text(json.dumps({'experiment':exp.to_dict(),'registration':registration.to_dict() if hasattr(registration,'to_dict') else str(registration),'candidate':candidate.payload},ensure_ascii=False,indent=2,default=str),encoding='utf-8')
 print('INSPECTION',family,report.status,flush=True)

if __name__=='__main__':main(sys.argv[1])
