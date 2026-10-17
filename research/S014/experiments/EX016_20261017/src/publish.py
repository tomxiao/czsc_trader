"""Close stage two with explicit limited roles and no stage-three execution."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence,assemble_delivery,validate_delivery,update_research_intent,ResearchIntentUpdate
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,EvidenceRef,MaterialEvidenceWrite,DeliveryReference,DeliveryDefinition,DeliveryStage,DeliveryContent,DeliveryStatus,ValidationStatus,ComponentPanel,ComponentTestResult,ComponentTestStatus,FactValue,FactStatus
ROOT=Path(__file__).resolve().parents[5];EX=Path(__file__).resolve().parents[1]

def main():
    if (EX/'others/result.json').exists():raise RuntimeError('Preserve final delivery')
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    repo=RepositoryContext.discover(ROOT);ctx=create_research_context(repo,ResearchBatchRef('S014'));exp=ExperimentRef('S014',EX.name)
    prior=DeliveryReference.from_dict(read(ROOT/'research/S014/experiments/EX014_20261017/others/result.json')['delivery']);mandate=DeliveryReference.from_dict(read(ROOT/'research/S014/experiments/EX003_20261016/others/result.json')['delivery'])
    assert validate_delivery(repo,prior).status is ValidationStatus.PASS
    old=DeliveryContent.from_dict(read(ROOT/'research/S014/assets/deliveries/COMPONENTS/11/delivery.json')['content'])
    audit=read(EX/'others/final_audit.json');assert audit['status']=='PASS';refs={}
    for item in audit['manifest']:assert sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256'],item['path']
    paths={ROOT/x['path'] for x in audit['manifest']}
    paths|={EX/'others/final_audit.json',EX/'protocols/report.md',Path(__file__)}
    for p in sorted(paths):
        name='ex016-'+p.relative_to(ROOT).as_posix().split(EX.name+'/',1)[1].replace('/','-').replace('.','-');mime={'.py':'text/x-python','.json':'application/json','.csv':'text/csv','.md':'text/markdown'}[p.suffix]
        refs[name]=publish_evidence(ctx,MaterialEvidenceWrite(exp,name,p.read_bytes(),mime,p.suffix[1:]))
    first=read(ROOT/'research/S014/experiments/EX015_20261017/others/round_result.json');refs15={k:EvidenceRef.from_dict(v) for k,v in first['evidence'].items()}
    for ref in refs15.values():assert sha256(ref.resolve(ROOT).read_bytes()).hexdigest()==ref.sha256
    ev=tuple(refs[k] for k in ['ex016-others-annual_followup-json','ex016-others-annual_extension-csv','ex016-others-annual_matches-csv','ex016-others-annual_clusters-csv','ex016-others-annual_coverage-csv','ex016-others-computation-json','ex016-others-final_audit-json','ex016-protocols-report-md'])
    components=list(old.payload.components);idx=next(i for i,c in enumerate(components) if c.component_id=='gap-sequence-repair-h3-context');c=components[idx]
    components[idx]=replace(c,
        availability=c.availability+'；年度启动及更新由EX016 src/annual_followup.py::calibrate给出，再调用本定义gap_sequence_context；首次60条原有效队列H3成熟，2020-10-13可用；不是EX016滚动component.py',
        applicability=c.applicability+'；因果延伸早期2020—2022高低差很弱且低状态延长为正，启动前185日无状态；全期用途仅供机制对照',
        judgment=c.judgment+' EX016支持原年度定义可执行延伸和有限全期环境参考，不支持全期稳定避损；主要未决问题转交阶段三连续账户。',
        tests=(*c.tests,
            ComponentTestResult('entry-close-four-probes','EX015_20261017',refs15['protocols-design-json'],ComponentTestStatus.INEFFECTIVE,'四固定条件的H3收益变化均负，模型未优于原低环境短持有；不增加独立组件。',tuple(refs15.values())),
            ComponentTestResult('rolling-calibration-transfer','EX016_20261017',refs['ex016-protocols-design-json'],ComponentTestStatus.INSUFFICIENT_DATA,'252/126/504改变校准身份，主差及期限分层薄弱，不移植原支持。',ev),
            ComponentTestResult('annual-causal-extension-context','EX016_20261017',refs['ex016-protocols-annual_followup-json'],ComponentTestStatus.SUPPORTED,'仅有限环境参考：全期H3差1.6669pp，去2026 .9176pp，97匹配1.0717pp；原910状态复现，早期与年度反例保留。',ev),
            ComponentTestResult('all-period-universal-short-hold','EX016_20261017',refs['ex016-protocols-annual_followup-json'],ComponentTestStatus.INSUFFICIENT_DATA,'低状态延长全期-.6220pp但早期+.2557pp，同时区间跨0；仅为阶段三期限取舍假设，不是每年有效退出。',ev)))
    conclusion='阶段二完成并建议推进阶段三：保留26定义及2辅助/1环境参考，以原年度因果状态构建环境与期限四对照；早期反例和选择局限公开，未验证账户或年度绩效。'
    facts=old.facts+tuple(FactValue('ex016-'+k,v,u,FactStatus.AVAILABLE,ev) for k,v,u in [('rounds-used',2,'rounds'),('rounds-unused',8,'rounds'),('high-attempts',256,'attempts'),('low-attempts',104,'attempts'),('high-low-h3',.01666935687800478,'return'),('matched-pairs',97,'pairs'),('startup-unready',185,'sessions'),('calendar',1642,'sessions'),('schedulable-high-H3',146,'label_intervals'),('audit-checks',audit['total_checks'],'checks'),('source-calls',0,'calls'),('new-account-runs',0,'accounts')])
    receipt=assemble_delivery(repo,DeliveryDefinition(ctx.batch,DeliveryStage.COMPONENTS,12,(mandate,prior)),DeliveryContent(ComponentPanel(tuple(components),conclusion),DeliveryStatus.COMPLETE,facts=facts,explanations=(),incomplete_items=(),report=(EX/'protocols/report.md').read_text(encoding='utf-8'),evidence=tuple(dict.fromkeys((*old.evidence,*refs15.values(),*refs.values())))))
    validation=validate_delivery(repo,receipt.reference);assert validation.status is ValidationStatus.PASS
    formal=ROOT/'research/S014/deliveries/COMPONENTS/12/report.md';assert formal.read_bytes()==(EX/'protocols/report.md').read_bytes()
    (EX/'others/report.md').write_bytes(formal.read_bytes())
    copy={'status':'PASS','sha256':sha256(formal.read_bytes()).hexdigest(),'formal':formal.relative_to(ROOT).as_posix()}
    (EX/'protocols/report_copy_verification.json').write_text(json.dumps(copy,indent=2)+'\n',encoding='utf-8',newline='\n')
    result={'experiment':exp.to_dict(),'round':2,'delivery':receipt.reference.to_dict(),'validation':validation.to_dict(),'status':'COMPLETE','evidence':{k:v.to_dict() for k,v in refs.items()},'inherited_round1_evidence':[r.to_dict() for r in refs15.values()],'component_definitions':26,'new_component_definitions':0,'supported_auxiliary':2,'supported_return_context':1,'supported_return_entry':0,'phase_two_complete':True,'phase_three_recommended':True,'phase_three_approved':False,'source_calls':0,'remaining_source_calls':0,'strategy_accounts':0,'report_copy':copy,'conclusion':conclusion}
    for name in ['result','round_result']:(EX/f'others/{name}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    intent=read(ROOT/'research/registrations/S014/family.json')['research_intent'];budget=intent['autonomous_stage_two_budget']
    assert exp.to_dict() in budget['allocated_rounds'] and len(budget['completed_rounds'])==1
    budget['completed_rounds'].append({'experiment':exp.to_dict(),'result':'LIMITED_COMPONENT_EVIDENCE_SUFFICIENT_FOR_STAGE_THREE_PROPOSAL','evidence':[refs['ex016-others-final_audit-json'].to_dict(),refs['ex016-protocols-report-md'].to_dict()]})
    budget.update(goal_status='COMPLETE',remaining_unallocated=8,stop_reason='已形成有证据支持的可执行阶段三对照；不以耗尽额度或数量收口。')
    intent.update(stage='阶段二完成：建议阶段三，等待用户批准',components=receipt.reference.to_dict(),phase_two_complete=True,phase_three_ready=True,phase_three_approved=False,component_definitions=26,supported_components=3,supported_return_context_components=1,supported_return_entry_components=0,strategy_accounts=0,remaining_source_calls=0,announcement_tracing='PAUSED_BY_USER',pending=['请用户批准阶段三四组连续账户对照；批准前不执行。'],conclusion=conclusion)
    intent['phase_three_proposal']={'execution_authorized':False,'variants':['parent_H1','parent_H3','high_only_H3','high_H3_low_H1'],'calibration':'EX016 src/annual_followup.py::calibrate + EX013 src/component.py::gap_sequence_context','startup':'2020-10-13; retain full-year cash path and evaluation denominator','report':refs['ex016-protocols-report-md'].to_dict()}
    intent['diagnostic_feedback'].update(result=conclusion,judgment_update='环境信息有有限证据，主要未决问题为组合与账户兑现，归属阶段三；不要求组件先通过账户绩效。',closure_delivery=receipt.reference.to_dict(),routing_after_result='建议进入阶段三，待用户明确批准。',recommended_minimum_design='同启动定义下父H1、父H3、高H3、高H3低H1四对照；原经济目标、费用执行不变。',verified='EX015 47项及16复算，EX016 120项；COMPONENTS/12 COMPLETE/FULL/PASS。')
    update_research_intent(repo,ctx.batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',reason='使用2轮额度补齐因果环境、期限反例及机会规模，阶段二收口并提交阶段三建议，未启动下一阶段')
    print(json.dumps({'delivery':receipt.reference.to_dict(),'validation':validation.to_dict(),'new_refs':len(refs),'round1_refs':len(refs15),'components':26},ensure_ascii=False))

if __name__=='__main__':main()
