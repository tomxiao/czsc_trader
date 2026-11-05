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

def main(family):
 root=Path.cwd();out=root/'.tmp/rsch-frozen-v4-upgrade'/family
 script=root/'.tmp/rsch-frozen-v4-upgrade'/('run_s015_accounts.py' if family=='S015' else 'run_s011_account.py')
 ns={'__file__':str(script)};code=script.read_text(encoding='utf-8');prefix=code[:code.index('with ResearchExecutionSession')]
 prefix='\n'.join(line for line in prefix.splitlines() if 'write_text(' not in line and 'shutil.copyfile(' not in line)
 # The builder loads the same source closure; no helper replacement or historical replay.
 if family=='S011':prefix=prefix.replace("module_spec=importlib", "source_root=ROOT/'research/S011/runtime_upgrade_v4'\nmodule_spec=importlib")
 exec(prefix,ns)
 context,candidate,exp,sources,spec=[ns[k] for k in ('context','candidate','exp','sources','spec')]
 assert json.loads(json.dumps(candidate.payload)) == json.loads((out/'candidate.json').read_text(encoding='utf-8')), 'candidate identity drift'
 print('VERIFIED_CANDIDATE',family,candidate.content_identity.content_sha256,flush=True)
 summary=json.loads((out/'account_STANDARD.json').read_text(encoding='utf-8'))
 reference=EvidenceRef.from_dict(summary['new_reference']);path=reference.resolve(root)
 materialized=materialize_equity(path.read_bytes(),lambda r:(path.parent/(r['sha256']+'.json')).read_bytes()).payload
 assert json.loads(json.dumps(materialized['request']['candidate_definition'])) == json.loads(json.dumps(candidate.definition.to_dict())), 'account definition drift'
 new=materialized['runs']['candidate'];buy=next(o for o in new['orders'] if o['side']=='BUY');sell=next(o for o in new['orders'] if o['side']=='SELL')
 stamp=lambda text:datetime.fromisoformat(text.replace('Z','+00:00'))
 TimeInterval=ns['TimeInterval'];entry=TimeInterval(stamp(buy['valid_start']),stamp(buy['valid_end']));exit_=TimeInterval(stamp(sell['valid_start']),stamp(sell['valid_end']))
 quantity=int(buy['quantity']);price=Decimal(str(next(x['price'] for x in new['fills'] if x['side']=='BUY')));sellprice=Decimal(str(next(x['price'] for x in new['fills'] if x['side']=='SELL')))
 initial=Decimal('100000');fee=Decimal('.001');reserved=quantity*Decimal(str(buy['limit_price']))*(1+fee)
 reconcile=EquityPteReconcile(initial,0)
 partial=EquityPteReport(0,100,price,entry.start+timedelta(minutes=1),'FILLED_PART')
 scenarios=[EquityPteScenario('cycle-partial-duplicate-restart',(
   reconcile,EquityPteDecision(entry,entry.start),partial,partial,EquityPteRestart(),
   EquityPteReport(0,quantity,price,entry.start+timedelta(minutes=2),'FILLED_ALL'),
   EquityPteDecision(exit_,exit_.start),EquityPteReport(1,quantity,sellprice,exit_.start+timedelta(minutes=1),'FILLED_ALL'),EquityPteRestart()),
   initial-quantity*price*(1+fee)+quantity*sellprice*(1-fee),0,Decimal(0)),
   EquityPteScenario('partial-cancel-exit',(
   reconcile,EquityPteDecision(entry,entry.start),partial,
   EquityPteReport(0,100,price,entry.start+timedelta(minutes=2),'CANCELLED_PART'),EquityPteRestart(),
   EquityPteDecision(exit_,exit_.start),EquityPteReport(1,100,sellprice,exit_.start+timedelta(minutes=1),'FILLED_ALL')),
   initial-100*price*(1+fee)+100*sellprice*(1-fee),0,Decimal(0))]
 for code,outcome,at in [('REJECTED','REJECTED',entry.start),('UNKNOWN','UNKNOWN',entry.start),('EXPIRED','ACCEPTED',entry.end)]:
  scenarios.append(EquityPteScenario(code,(reconcile,EquityPteDecision(entry,at,outcome,code)),initial if code=='REJECTED' else initial-reserved,0,Decimal(0)))
 scenarios.append(EquityPteScenario('reconciliation-blocked',(EquityPteReconcile(initial-1,0),EquityPteDecision(entry,entry.start,expected='RECONCILIATION_BLOCKED')),initial,0,Decimal(0)))
 auth={'role':'RSCH','scope':'原地升级全部冻结策略适配当前PTE并验证等价性；不操作生产',
   'user_messages':['不影响交付就先不管吧。切换RSCH，已冻结策略实现统一原地升级，适配当前PTE版本，并做等价性验证','继续'],
   'mapping':{'strategy':family,'candidate':candidate.candidate_id,'content_sha256':candidate.content_identity.content_sha256},
   'note':'本候选保持当前冻结金融规则；该选型只用于已授权同版本升级技术检验，不构成生产生效。'}
 authref=publish_evidence(context,MaterialEvidenceWrite(exp,'upgrade-authorization',json.dumps(auth,ensure_ascii=False,indent=2).encode(),'application/json','json'))
 registration=register_candidate(context.repository,CandidateRegistrationRequest(candidate,exp,(reference,),candidate.definition.dependencies))
 selection=record_research_decision(context.repository,f.ResearchDecision('native-v4-upgrade-'+candidate.candidate_id,family,f.DecisionAction.APPROVE,
   f.CandidateSelectionSubject(candidate.key,registration.content_sha256,registration.record_sha256),CandidateEvidence(authref.repository_path,authref.sha256),'按用户授权选择等价迁移实现，仅用于同版本升级检验'))
 with ns['ResearchExecutionSession'](context,experiment=exp) as execution:
  request=ns['EquityEvaluationRequest'](exp,candidate,TimeInterval(entry.start,exit_.end),date(2024,9,9) if family=='S015' else date(2024,12,26),sources,100000.,.001,
    window_id='technical',scenario_id='STANDARD',measurement_tier='FORMAL',benchmark=ns['EvaluationBenchmark'](ns['EquityBuyHold'](spec)),drawdown_basis='SESSION_CLOSE',concentration_basis='TOP_DECILE')
  prepared=context.evaluation.prepare(request,execution=execution).request
 replay=EquityInspectionReplay(f.InspectionCoordinate('technical','standard'),prepared.input_binding,prepared.requests(spec),prepared.window,100000.,.001)
 protocol=EquityInspectionProtocol('candidate-inspection-v4','ECONOMIC_V1',0.,EquityPteInspectionProtocol(describe_inspection_environment(context.repository),tuple(scenarios)))
 version=json.loads((root/f'strategies/{family}/versions/v1.json').read_text(encoding='utf-8'))
 target=FreezeTarget('v1',version.get('parent_version'),'原生V4等价迁移技术检验',date.fromisoformat(version['selection_data_cutoff']),date.fromisoformat(version['forward_start']))
 request=CandidateInspectionRequest(candidate.key,selection,context,exp,target,protocol,(replay,),InspectionDataKind.HISTORICAL,remaining_risks=('检验使用已认证留存历史数据源；未来生产持续供数绑定及覆盖范围尚未验证，PASS 不代表当前可部署或生产生效。',))
 report=inspect_candidate(context.repository,request,control=InspectionControl(max_workers=1,timeout_seconds=600,on_progress=lambda p:print(str(p),flush=True)))
 payload=report.to_dict();(out/'inspection.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
 print('INSPECTION',family,report.status,flush=True)

if __name__=='__main__':main(sys.argv[1])
