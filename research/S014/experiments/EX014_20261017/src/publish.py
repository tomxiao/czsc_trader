"""Append role-bounded evidence to an existing component; never duplicate definition."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence,assemble_delivery,validate_delivery,update_research_intent,ResearchIntentUpdate
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,EvidenceRef,MaterialEvidenceWrite,DeliveryReference,DeliveryDefinition,DeliveryStage,DeliveryContent,DeliveryStatus,ValidationStatus,ComponentPanel,ComponentTestResult,ComponentTestStatus,FactValue,FactStatus
ROOT=Path(__file__).resolve().parents[5];EX=Path(__file__).resolve().parents[1]

def main():
    if (EX/'others/result.json').exists():raise RuntimeError('Preserve delivery')
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    repo=RepositoryContext.discover(ROOT);ctx=create_research_context(repo,ResearchBatchRef('S014'));exp=ExperimentRef('S014',EX.name)
    previous=read(ROOT/'research/S014/experiments/EX013_20261017/others/result.json');prior=DeliveryReference.from_dict(previous['delivery'])
    mandate=DeliveryReference.from_dict(read(ROOT/'research/S014/experiments/EX003_20261016/others/result.json')['delivery'])
    assert validate_delivery(repo,prior).status is ValidationStatus.PASS
    old=DeliveryContent.from_dict(read(ROOT/'research/S014/assets/deliveries/COMPONENTS/10/delivery.json')['content'])
    audit=read(EX/'others/audit.json');assert audit['status']=='PASS';refs={}
    for item in audit['manifest']:assert sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256'],item['path']
    for p in sorted((EX/'protocols').glob('published_*.json')):refs.update({k:EvidenceRef.from_dict(v) for k,v in read(p).items()})
    paths={ROOT/x['path'] for x in audit['manifest']}|{EX/'others/audit.json',EX/'protocols/report.md',Path(__file__)}
    for p in sorted(paths):
        name='ex014-'+p.relative_to(ROOT).as_posix().split('EX014_20261017/',1)[1].replace('/','-').replace('.','-')
        mime={'.py':'text/x-python','.json':'application/json','.csv':'text/csv','.md':'text/markdown'}[p.suffix]
        refs[name]=publish_evidence(ctx,MaterialEvidenceWrite(exp,name,p.read_bytes(),mime,p.suffix[1:]))
    ev=tuple(refs[k] for k in ['ex014-others-computation-json','ex014-others-risk_matching-csv','ex014-others-duration_check-json',
        'ex014-others-duration_increment_ci_corrected-csv','ex014-others-audit-json','ex014-protocols-report-md'])
    components=list(old.payload.components);idx=next(i for i,c in enumerate(components) if c.component_id=='gap-sequence-repair-h3-context');c=components[idx]
    components[idx]=replace(c,role=c.role+'；补充信号日低状态下H1延长H3的风险参考',
        horizon=c.horizon+'；同一入场H1对H3配对净现金差作为补充期限标签',
        control=c.control+'；60次/39簇、删簇、43次实际区间去重、剔除最差3笔、非修复低状态对照',
        applicability=c.applicability+'；补充用途锁定信号日状态，2023反向及2026匹配微正，不适用于H1动态重判后的卖出',
        judgment=c.judgment+' EX014支持低状态延长持有的有限历史风险参考；不证实修复独有因果、每年成立或最优退出。',
        tests=(*c.tests,ComponentTestResult('low-state-h1-h3-extension-risk','EX014_20261017',refs['duration_falsification'],ComponentTestStatus.SUPPORTED,
            '60次均差-1.2656pp；去2026、簇等权/删簇、去重/删最负3仍负。2023反向、2026匹配微正；普通区间未经全研究选择校正，支持限定参考职责。',ev),
            ComponentTestResult('risk-screen-and-optimal-duration','EX014_20261017',refs['design-json'],ComponentTestStatus.INSUFFICIENT_DATA,
            '共同转弱风险匹配集中、严格去重反号；高状态各相邻延长差区间跨0。未支持新增风险筛选或最优持有期。',ev)))
    conclusion='固定H3环境的均差约94%来自正收益；四风险假设未形成新增有效组件。补强原组件的低状态H1延长H3风险参考证据，26定义不变，未证明最优退出，阶段二PARTIAL。'
    facts=old.facts+tuple(FactValue('ex014-'+k,v,u,FactStatus.AVAILABLE,ev) for k,v,u in [
        ('h3-parent',216,'attempts'),('duration-common',211,'attempts'),('low-extension',-.0126561645,'return'),
        ('low-extension-cluster',-.01123742653846153,'return'),('low-clusters',39,'clusters'),('low-nonoverlap',43,'attempts'),
        ('new-definitions',0,'components'),('enhanced-existing',1,'components'),('audit-checks',68,'checks'),('source-calls',0,'calls')])
    receipt=assemble_delivery(repo,DeliveryDefinition(ctx.batch,DeliveryStage.COMPONENTS,11,(mandate,prior)),
        DeliveryContent(ComponentPanel(tuple(components),conclusion),DeliveryStatus.PARTIAL,facts=facts,explanations=(),
            incomplete_items=('没有新增获支持入场筛选器或稳健下行损失分层。','原环境的期限风险参考尚未转化为完整策略与年度账户验收。','全开发池已见，历史选择和年度异质性仍限制外推。'),
            report=(EX/'protocols/report.md').read_text(encoding='utf-8'),evidence=tuple(dict.fromkeys((*old.evidence,*refs.values())))))
    valid=validate_delivery(repo,receipt.reference);assert valid.status is ValidationStatus.PASS
    formal=ROOT/'research/S014/deliveries/COMPONENTS/11/report.md';assert formal.read_bytes()==(EX/'protocols/report.md').read_bytes()
    (EX/'others/report.md').write_bytes(formal.read_bytes())
    copy={'status':'PASS','sha256':sha256(formal.read_bytes()).hexdigest(),'bytes':formal.stat().st_size,'formal':formal.relative_to(ROOT).as_posix()}
    (EX/'protocols/report_copy_verification.json').write_text(json.dumps(copy,indent=2)+'\n',encoding='utf-8',newline='\n')
    result={'experiment':exp.to_dict(),'delivery':receipt.reference.to_dict(),'validation':valid.to_dict(),'evidence':{k:v.to_dict() for k,v in refs.items()},
        'inherited_evidence':[v.to_dict() for v in old.evidence],'status':'PARTIAL','component_definitions':26,'new_component_definitions':0,'enhanced_existing_components':1,
        'supported_auxiliary':2,'supported_return_context':1,'supported_return_entry':0,'phase_two_complete':False,'phase_three_recommended':False,'phase_three_approved':False,
        'new_source_calls':0,'remaining_source_calls':0,'strategy_accounts':0,'announcement_tracing':'PAUSED_BY_USER','report_copy':copy,
        'next_scope_proposed':'既有数据内区分低环境H1至H3损失的隔夜/盘中来源及事前互补条件；不重扫窗口，不自动进入策略组合或账户。'}
    (EX/'others/result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    intent=read(ROOT/'research/registrations/S014/family.json')['research_intent'];authorization=read(EX/'protocols/design.json')['authorization']
    intent.update(stage='阶段二进行中：H3环境下行和持续时间验证，补强既有组件期限风险参考',components=receipt.reference.to_dict(),phase_two_complete=False,phase_three_ready=False,
        phase_three_approved=False,component_definitions=26,supported_components=3,supported_return_context_components=1,supported_return_entry_components=0,
        strategy_accounts=0,remaining_source_calls=0,announcement_tracing='PAUSED_BY_USER',pending=[result['next_scope_proposed']],conclusion=conclusion)
    intent['current_data_authorization']={'source':'Current human conversation','verbatim':authorization,'scope':'现有数据内H3损失与持续时间；费用/执行不变，公告暂停','window':['2020-01-01','2026-10-15'],'actual_source_calls':0,'remaining_source_calls':0}
    intent['h3_downside_duration']={'experiment':exp.to_dict(),'delivery':receipt.reference.to_dict(),'enhanced_existing':1,'new_definitions':0,'risk_screening':'INSUFFICIENT_DATA','optimal_duration':'INSUFFICIENT_DATA'}
    intent['diagnostic_feedback'].update(authorization=authorization,closure_delivery=receipt.reference.to_dict(),reviewed_delivery=receipt.reference.to_dict(),reviewed_commit='623ce4f1',
        execution_scope_this_turn='固定H3环境收益分解、四风险假设、同入场五期限与定向反证；0源调用。',result=conclusion,
        recommended_minimum_design=result['next_scope_proposed'],routing_after_result='继续阶段二；阶段三未推荐/批准。',verified='COMPONENTS/11 PARTIAL/FULL/PASS；68项检查，4次年度复算；26定义不变。',
        assessment=['H3差主要来自正收益贡献，最差一成损失反而更深。','共同转弱风险匹配集中且去重反号，不新登记。','低状态延长H1至H3均差-1.2656pp，簇/去重/剔极值保持；保留2023及2026匹配反例。','补充既有环境组件的期限风险参考，不构成最优退出或账户达标。'])
    update_research_intent(repo,ctx.batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',reason='完成授权H3损失与持续时间研究，补强原组件用途证据并保留风险筛选反证')
    print(json.dumps({'delivery':receipt.reference.to_dict(),'validation':valid.to_dict(),'new_refs':len(refs),'old_refs':len(old.evidence)}))
if __name__=='__main__':main()
