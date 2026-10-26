"""Inspect and apply the exact authorized same-version observation packages."""
from datetime import date
from hashlib import sha256
import argparse,cloudpickle
import upgrade_batch as v
from czsc_trader.application import (CandidateInspectionRequest,FreezeTarget,InspectionDataKind,InspectionProtocol,InspectionReplay,describe_inspection_environment,inspect_candidate,prepare_frozen_runtime_upgrade,apply_frozen_runtime_upgrade,FrozenRuntimeUpgradeRequest)
from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.delivery import EvaluationEvidenceRef
from strategy_runtime.inspection import InspectionControl
from strategy_manager import CandidateKey,canonical_sha256,freeze_contracts as f
from paper_trading_engine.inspection import PteInspectionProtocol

def inspect(ref):
 item,ex,home,out,ctx,old,child,original=v.setup(ref)
 request=cloudpickle.loads(EvidenceRef.from_dict(v.read(out/'request_ref.json')).resolve(v.ROOT).read_bytes())
 ev=EvidenceRef.from_dict(v.read(out/'account_ref.json'));runs=v.read(ev.resolve(v.ROOT))['runs'];replays=[]
 for run in runs:
  window=run['window_id'];scenario=run['scenario_id'];cost=next(x.one_way_cost for x in request.costs if x.scenario_id==scenario)
  replays.append(InspectionReplay(f.InspectionCoordinate(window,scenario),request.input_bindings[window],request.execution_data,request.initial_cash,cost,EvaluationEvidenceRef(ev,(canonical_sha256(run['identity']),))))
 pte=PteInspectionProtocol.from_dict(v.read(home/'others/pte_protocol.json'));env=describe_inspection_environment(ctx.repository);assert pte.environment.platform_build_sha256==env.platform_build_sha256
 stored=item['original'];target=FreezeTarget(stored['version'],stored['parent_version'],'仅升级策略观察为v4信号解释；保持原交易规则、参数、版本号和研究日期。',date.fromisoformat(stored['selection_data_cutoff']),date.fromisoformat(stored['forward_start']))
 spec=CandidateInspectionRequest(CandidateKey(ex.strategy_id,child.candidate_id),f.DecisionReference.from_dict(v.read(out/'selection_ref.json')),ctx,ex,target,InspectionProtocol('candidate-inspection-v2','ECONOMIC_V1',0.,pte),tuple(replays),InspectionDataKind.HISTORICAL,remaining_risks=('技术历史回放不新增收益普适性或未见样本证据。','PTE渠道为合成事件，不是生产执行；本轮不改账户、部署和资格。','观察解释由RSCH按实际分支复核，历史旧观察不补造。'))
 def progress(event):print(ref,event,flush=True)
 report=inspect_candidate(ctx.repository,spec,control=InspectionControl(timeout_seconds=1200,max_workers=2,on_progress=progress))
 v.save(out/'inspection_report.json',report.to_dict());v.save(out/'inspection_ref.json',report.reference.to_dict());print(ref,'INSPECTED',report.status.value,flush=True)
 if report.plan:v.save(out/'freeze_plan.json',report.plan.to_dict())
 assert report.status.value=='PASS'

def apply(ref):
 item,ex,home,out,ctx,old,child,original=v.setup(ref)
 inspection=f.ResearchEvidenceRef.from_dict(v.read(out/'inspection_ref.json'));auth=EvidenceRef.from_dict(v.read(out/'authorization_ref.json'));confirmation=f.ResearchEvidenceRef(f.ResearchEvidenceOwner(ex.strategy_id,ex.experiment_id),auth.evidence_id,auth.sha256)
 decision=f.ResearchDecision.from_dict(v.read(f.DecisionReference.from_dict(v.read(out/'selection_ref.json')).evidence.resolve(v.ROOT)))
 assert decision.confirmation_source.sha256==confirmation.sha256
 confirmation=decision.confirmation_source
 plan=prepare_frozen_runtime_upgrade(ctx.repository,FrozenRuntimeUpgradeRequest(original,CandidateKey(ex.strategy_id,child.candidate_id),inspection,confirmation,v.WORK/'staged'/ref))
 v.save(out/'upgrade_prepared.json',{'plan_path':plan.plan_path.relative_to(v.ROOT).as_posix(),'plan_sha256':plan.plan_sha256,'original':plan.original.to_dict(),'migrated':plan.migrated.to_dict()})
 receipt=apply_frozen_runtime_upgrade(ctx.repository,plan);v.save(out/'upgrade_receipt.json',receipt);print(ref,'UPGRADED',receipt,flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('inspect','apply'));p.add_argument('reference');a=p.parse_args();{'inspect':inspect,'apply':apply}[a.mode](a.reference)
