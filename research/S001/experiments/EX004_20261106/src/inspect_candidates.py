"""Register exact native upgrade candidates and inspect isolated final packages."""
from pathlib import Path
from datetime import date,datetime,timedelta
from dataclasses import replace
from decimal import Decimal
import json,sys
from strategy_manager import CandidateEvidence,freeze_contracts as f
from strategy_runtime import InspectionControl
from czsc_trader.application import (register_candidate,CandidateRegistrationRequest,record_research_decision,
    CandidateInspectionRequest,EquityInspectionReplay,EquityInspectionProtocol,FreezeTarget,
    InspectionDataKind,inspect_candidate,describe_inspection_environment,publish_evidence)
from czsc_trader.research_tools import EvidenceRef,MaterialEvidenceWrite
from czsc_trader.research_tools.equity_replay import materialize_equity
from paper_trading_engine.equity_inspection import (EquityPteDecision,EquityPteReport,EquityPteRestart,
    EquityPteReconcile,EquityPteScenario,EquityPteInspectionProtocol)

def inspect(context,candidate,exp,prepared,reference,materialized,revision):
 root=Path.cwd();out=root/'.tmp/s001-v4-correction/accounts';family='S001'
 assert reference is not None, 'formal account evidence required'
 spec=candidate.definition.execution_spec
 new=materialized['runs']['candidate'];buy=next(o for o in new['orders'] if o['side']=='BUY' and o['status']=='FILLED');sell=next(o for o in new['orders'] if o['side']=='SELL')
 stamp=lambda text:datetime.fromisoformat(text.replace('Z','+00:00'))
 from dataflows import TimeInterval; entry=TimeInterval(stamp(buy['valid_start']),stamp(buy['valid_end']));exit_=TimeInterval(stamp(sell['valid_start']),stamp(sell['valid_end']))
 quantity=int(buy['quantity']);price=Decimal(str(next(x['price'] for x in new['fills'] if x['side']=='BUY')));sellprice=Decimal(str(next(x['price'] for x in new['fills'] if x['side']=='SELL')))
 money=lambda amount:amount.quantize(Decimal('.0001'))
 initial=Decimal('100000');fee=Decimal('.0005');reserved=(quantity*Decimal(str(buy['limit_price']))*(1+fee)).quantize(Decimal('.0001'))
 reconcile=EquityPteReconcile(initial,0)
 partial=EquityPteReport(0,100,price,entry.start+timedelta(minutes=1),'FILLED_PART')
 scenarios=[EquityPteScenario('cycle-partial-duplicate-restart',(
   reconcile,EquityPteDecision(entry,entry.start),partial,partial,EquityPteRestart(),
   EquityPteReport(0,quantity,price,entry.start+timedelta(minutes=2),'FILLED_ALL'),
   EquityPteDecision(exit_,exit_.start),EquityPteReport(1,quantity,sellprice,exit_.start+timedelta(minutes=1),'FILLED_ALL'),EquityPteRestart()),
   initial-quantity*price-money(quantity*price*fee)+quantity*sellprice-money(quantity*sellprice*fee),0,Decimal(0)),
   EquityPteScenario('partial-cancel-exit',(
   reconcile,EquityPteDecision(entry,entry.start),partial,
   EquityPteReport(0,100,price,entry.start+timedelta(minutes=2),'CANCELLED_PART'),EquityPteRestart(),
   EquityPteDecision(exit_,exit_.start),EquityPteReport(1,100,sellprice,exit_.start+timedelta(minutes=1),'FILLED_ALL')),
   initial-100*price-money(100*price*fee)+100*sellprice-money(100*sellprice*fee),0,Decimal(0))]
 for code,outcome,at in [('REJECTED','REJECTED',entry.start),('UNKNOWN','UNKNOWN',entry.start),('EXPIRED','ACCEPTED',entry.end)]:
  scenarios.append(EquityPteScenario(code,(reconcile,EquityPteDecision(entry,at,outcome,code)),initial if code=='REJECTED' else initial-reserved,0,Decimal(0)))
 scenarios.append(EquityPteScenario('reconciliation-blocked',(EquityPteReconcile(initial-1,0),EquityPteDecision(entry,entry.start,expected='RECONCILIATION_BLOCKED')),initial,0,Decimal(0)))
 auth={'role':'RSCH','scope':'按原设计已完成周修正S001两版，推进本地原地V4升级；不操作生产',
   'authorization':'主会话明确转授用户本轮S001原设计已完成周纠偏和本地升级授权',
   'mapping':{'strategy':family,'candidate':candidate.candidate_id,'content_sha256':candidate.content_identity.content_sha256},
   'note':'本候选恢复原设计的已完成周口径，其他冻结参数及执行规则保持；仅用于已授权本地同版本纠偏升级，不构成生产生效。'}
 authref=publish_evidence(context,MaterialEvidenceWrite(exp,'upgrade-authorization',json.dumps(auth,ensure_ascii=False,indent=2).encode(),'application/json','json'))
 registration=register_candidate(context.repository,CandidateRegistrationRequest(candidate,exp,(reference,),candidate.definition.dependencies))
 selection=record_research_decision(context.repository,f.ResearchDecision('native-v4-upgrade-'+candidate.candidate_id,family,f.DecisionAction.APPROVE,
   f.CandidateSelectionSubject(candidate.key,registration.content_sha256,registration.record_sha256),CandidateEvidence(authref.repository_path,authref.sha256),'按用户授权选择原设计已完成周纠偏实现，仅用于同版本升级检验'))
 replay=EquityInspectionReplay(f.InspectionCoordinate('technical','standard'),prepared.input_binding,prepared.requests(spec),prepared.window,100000.,.0005)
 protocol=EquityInspectionProtocol('candidate-inspection-v4','ECONOMIC_V1',0.,EquityPteInspectionProtocol(describe_inspection_environment(context.repository),tuple(scenarios)))
 version=json.loads((root/f'strategies/{family}/versions/{revision}.json').read_text(encoding='utf-8'))
 target=FreezeTarget(revision,version.get('parent_version'),'按原设计已完成周纠偏并迁移原生V4',date.fromisoformat(version['selection_data_cutoff']),date.fromisoformat(version['forward_start']))
 request=CandidateInspectionRequest(candidate.key,selection,context,exp,target,protocol,(replay,),InspectionDataKind.HISTORICAL,remaining_risks=('检验使用已认证留存历史数据源；未来生产持续供数绑定及覆盖范围尚未验证，PASS 不代表当前可部署或生产生效。',))
 report=inspect_candidate(context.repository,request,control=InspectionControl(max_workers=1,timeout_seconds=600,on_progress=lambda p:print(str(p),flush=True)))
 payload=report.to_dict();(out/f'{revision}-inspection.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
 (out/f'{revision}-registration.json').write_text(json.dumps({'content_sha256':registration.content_sha256,'record_sha256':registration.record_sha256,'selection':selection.to_dict()},ensure_ascii=False,indent=2,default=str),encoding='utf-8')
 print('INSPECTION',family,revision,report.status,flush=True)


def main():
 from s001_context import build_context,build_request
 from czsc_trader.research_tools import ExperimentRef,ResearchExecutionSession,EvaluationEvidenceWrite
 from run_accounts import save
 for revision in ('v1','v2'):
  out=Path.cwd()/'.tmp/s001-v4-correction/accounts'
  context,candidate=build_context(revision)
  exp=ExperimentRef.from_dict(json.loads((out/f'{revision}-experiment.json').read_text(encoding='utf-8')))
  with ResearchExecutionSession(context,experiment=exp) as execution:
   request=build_request(context,candidate,exp,start=date(2026,8,4),end=date(2026,8,18),window_id='PRESELECTION_TECHNICAL')
   prepared=context.evaluation.prepare(request,execution=execution)
   if '--inspect-only' in sys.argv:
    materialized=json.loads((out/f'{revision}-technical-account.json').read_text(encoding='utf-8'))
    reference=EvidenceRef.from_dict(json.loads((out/f'{revision}-technical-reference.json').read_text(encoding='utf-8')))
   else:
    outcome,=context.evaluation.evaluate_many((prepared,),execution=execution)
    if outcome.result is None:raise RuntimeError(str(outcome.error))
    materialized=materialize_equity(outcome.result).payload
    reference=publish_evidence(context,EvaluationEvidenceWrite(exp,'corrected-preselection-technical-account',prepared,outcome.result),execution=execution)
    save(out/f'{revision}-technical-account.json',materialized)
    save(out/f'{revision}-technical-reference.json',reference.to_dict())
  inspect(context,candidate,exp,prepared.request,reference,materialized,revision)

if __name__=='__main__':main()
