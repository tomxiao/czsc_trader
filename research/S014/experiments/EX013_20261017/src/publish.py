"""Publish the census and one narrowly supported conditional-environment component."""
from hashlib import sha256
import json
from pathlib import Path
from czsc_trader.application import (RepositoryContext,create_research_context,publish_evidence,assemble_delivery,
    validate_delivery,update_research_intent,ResearchIntentUpdate)
from czsc_trader.research_tools import (ResearchBatchRef,ExperimentRef,EvidenceRef,MaterialEvidenceWrite,
    DeliveryReference,DeliveryDefinition,DeliveryStage,DeliveryContent,DeliveryStatus,ValidationStatus,ComponentPanel,
    ComponentEntry,ComponentTestResult,ComponentTestStatus,ExperimentDefinitionRef,FactValue,FactStatus)

ROOT=Path(__file__).resolve().parents[5]
EX=Path(__file__).resolve().parents[1]


def main():
    if (EX/'others/result.json').exists():raise RuntimeError('Preserve delivery')
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    repo=RepositoryContext.discover(ROOT);ctx=create_research_context(repo,ResearchBatchRef('S014'));experiment=ExperimentRef('S014',EX.name)
    prior=read(ROOT/'research/S014/experiments/EX012_20261017/others/result.json');mandate=read(ROOT/'research/S014/experiments/EX003_20261016/others/result.json')
    prior_ref,mandate_ref=(DeliveryReference.from_dict(x['delivery']) for x in (prior,mandate))
    assert all(validate_delivery(repo,r).status is ValidationStatus.PASS for r in (prior_ref,mandate_ref))
    old=DeliveryContent.from_dict(read(ROOT/'research/S014/assets/deliveries/COMPONENTS/9/delivery.json')['content'])
    audit=read(EX/'others/final_audit.json');assert audit['status']=='PASS'
    for item in audit['manifest']:assert sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256'],item['path']
    refs={}
    for p in sorted((EX/'protocols').glob('published_*.json')):
        refs.update({k:EvidenceRef.from_dict(v) for k,v in read(p).items()})
    paths={ROOT/x['path'] for x in audit['manifest']}|{EX/'others/final_audit.json',EX/'protocols/report.md',Path(__file__)}
    for p in sorted(paths):
        name='ex013-'+p.relative_to(ROOT).as_posix().split('EX013_20261017/',1)[1].replace('/','-').replace('.','-')
        mime={'.py':'text/x-python','.json':'application/json','.csv':'text/csv','.md':'text/markdown'}[p.suffix]
        refs[name]=publish_evidence(ctx,MaterialEvidenceWrite(experiment,name,p.read_bytes(),mime,p.suffix[1:]))
    ev=tuple(refs[k] for k in ('ex013-others-session_result-json','ex013-others-session_annual-csv','ex013-others-session_matches-csv',
        'ex013-others-cluster_result-json','ex013-others-direct_result-json','ex013-others-operational_result-json','ex013-others-final_audit-json'))
    component=ComponentEntry('gap-sequence-repair-h3-context',
        ExperimentDefinitionRef(refs['ex013-src-component-py'],'src/component.py::gap_sequence_context'),
        role='低开收阳条件下的H3相对收益环境参考；仅条件分层，不输出买入指令',
        label='原真实股数净现金/100000，单边0.1%；未成交0、右截断排除',horizon='H3：T+1入场后3交易日计划退出，实际退出遵循既有约束',
        control='原价格/市场/行业强基线、T-1状态、邻窗、年度、同年价格匹配、事件簇及双腿去重；模型用途另检验',
        availability='T日完成OHLCV，20日缺口自相关；年度阈值仅来自年初已成熟H3训练队列；缺阈值或窗口明确不可用',
        price_basis='HFQ_RESEARCH及原固定执行标签；原始限价和股数费用口径不变',
        applicability='S014已见开发池、低开且收盘高于开盘、H3；高于负的训练中位不等于正自相关；不是其他证券或任意期限',
        judgment='SUPPORTED仅限历史条件收益环境参考。匹配覆盖34.6%、2023反例及宽区间限制外推；强基线筛选增量未获支持，2025高组仍亏。',
        tests=(ComponentTestResult('environment-context','EX013_20261017',refs['session-design'],ComponentTestStatus.SUPPORTED,
            '主差跨年、T-1/去2026保持；匹配及删任一簇全期差仍正，支持狭义环境分层，非独立确认或因果。',ev),
            ComponentTestResult('selection-utility','EX013_20261017',refs['operational-design'],ComponentTestStatus.INSUFFICIENT_DATA,
                '加连续或二元状态及交互后父条件内岭模型分配增量负、树不变；未支持收益筛选或完整账户用途。',ev)))
    facts=old.facts+tuple(FactValue('ex013-'+name,value,unit,FactStatus.AVAILABLE,ev) for name,value,unit in (
        ('mechanism-families',7,'families'),('supported-new-context',1,'components'),('supported-new-entry',0,'components'),
        ('high-state-attempts',156,'attempts'),('low-state-attempts',60,'attempts'),('primary-h3-difference',.027757,'return'),
        ('matched-pairs',54,'pairs'),('matched-high-clusters',34,'clusters'),('both-legs-nonoverlap-pairs',29,'pairs'),
        ('cluster-equal-difference',.011339030465686292,'return'),('leave-one-cluster-min',.0039004805882353333,'return'),
        ('numerical-fits-including-revisions',900,'fits'),('audit-refits',528,'fits'),('audit-checks',24,'checks'),
        ('source-calls',0,'calls'),('remaining-source-calls',0,'calls'),('new-strategy-accounts',0,'accounts')))
    facts+=(FactValue('ex013-entry-usefulness',None,'effect',FactStatus.INSUFFICIENT_DATA,ev,'环境分层支持不等于强基线筛选或连续账户增益，后者未获支持。'),)
    conclusion=('七族数值机制完成覆盖盘点、批量及反证；新增1项有限SUPPORTED的H3低开收阳缺口序列环境参考，'
        '原2项辅助保留，共26项定义。该状态模型筛选用途未获支持，直接入场收益组件仍0；公告暂停，0源调用，阶段二PARTIAL。')
    receipt=assemble_delivery(repo,DeliveryDefinition(ctx.batch,DeliveryStage.COMPONENTS,10,(mandate_ref,prior_ref)),
        DeliveryContent(ComponentPanel((*old.payload.components,component),conclusion),DeliveryStatus.PARTIAL,facts=facts,explanations=(),
            incomplete_items=('环境分层尚未转化为有稳定增量的收益筛选用途。','2025父条件高状态仍亏，互补信息缺口未解决。','全池已见，独立确认与完整账户年度目标尚未验收。'),
            report=(EX/'protocols/report.md').read_text(encoding='utf-8'),evidence=tuple(dict.fromkeys((*old.evidence,*refs.values())))))
    validation=validate_delivery(repo,receipt.reference);assert validation.status is ValidationStatus.PASS
    report=ROOT/'research/S014/deliveries/COMPONENTS/10/report.md';assert report.read_bytes()==(EX/'protocols/report.md').read_bytes()
    (EX/'others/report.md').write_bytes(report.read_bytes())
    copy={'status':'PASS','sha256':sha256(report.read_bytes()).hexdigest(),'bytes':report.stat().st_size,
        'formal_report':report.relative_to(ROOT).as_posix(),'experiment_report':(EX/'others/report.md').relative_to(ROOT).as_posix()}
    (EX/'protocols/report_copy_verification.json').write_text(json.dumps(copy,indent=2)+'\n',encoding='utf-8',newline='\n')
    result={'experiment':experiment.to_dict(),'delivery':receipt.reference.to_dict(),'validation':validation.to_dict(),'status':'PARTIAL',
        'evidence':{k:v.to_dict() for k,v in refs.items()},'inherited_evidence':[r.to_dict() for r in old.evidence],'report_copy':copy,
        'component_definitions':26,'supported_auxiliary':2,'supported_return_context':1,'supported_return_entry':0,
        'new_supported_return_components':1,'new_supported_role':'CONDITIONAL_ENVIRONMENT_REFERENCE_ONLY',
        'strategy_accounts':0,'new_source_calls':0,'remaining_source_calls':0,'phase_two_complete':False,'phase_three_recommended':False,'phase_three_approved':False,
        'announcement_tracing':'PAUSED_BY_USER','next_scope_proposed':'保持阶段二与已有数据，锁定新环境组件；优先查2025等高状态仍亏时的互补信息，不再优化同一自相关窗口。'}
    (EX/'others/result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    intent=read(ROOT/'research/registrations/S014/family.json')['research_intent']
    intent.update(stage='阶段二进行中：数值机制优先普查，新增有限收益环境参考，筛选用途待补',components=receipt.reference.to_dict(),
        phase_two_complete=False,phase_three_ready=False,phase_three_approved=False,component_definitions=26,supported_components=3,
        supported_return_context_components=1,supported_return_entry_components=0,strategy_accounts=0,remaining_source_calls=0,
        pending=[result['next_scope_proposed']],conclusion=conclusion)
    intent['resources']['remaining_source_calls']=0
    intent['current_data_authorization']={'source':'Current human conversation','verbatim':'同意，暂缓公告追溯，优先普查数值类收益机制。先梳理已有证据和未覆盖方向，再利用现有数据批量验证，你自主推进，以有证据支持的有效组件为目标。',
        'scope':'仅S014既有股票/市场/行业数据及标签的数值机制研究；公告暂停，无源调用或平台、账户操作','window':['2020-01-01','2026-10-15'],'actual_source_calls':0,'remaining_source_calls':0}
    intent['numerical_census']={'experiment':experiment.to_dict(),'delivery':receipt.reference.to_dict(),'families':7,
        'supported_new_role':'H3低开收阳相对收益环境参考','entry_screening':'NOT_SUPPORTED','new_sources':0}
    intent['announcement_tracing']='PAUSED_BY_USER'
    intent['diagnostic_feedback'].update(authorization=intent['current_data_authorization']['verbatim'],closure_delivery=receipt.reference.to_dict(),
        reviewed_delivery=receipt.reference.to_dict(),reviewed_commit='d25037e7',execution_scope_this_turn='已有证据盘点、七族数值批量、直接条件、匹配/簇反证、用途检验；零上游调用。',
        result=conclusion,judgment_update='相对环境分层得到限定支持；对强筛选和账户用途保持证据边界，不在反证后追加无关硬门。',
        recommended_minimum_design=result['next_scope_proposed'],routing_after_result='继续阶段二数值机制互补研究；阶段三尚未推荐/批准。',
        verified='COMPONENTS/10 PARTIAL/FULL/PASS；24项检查、528次审核复算，原25定义保持。',
        assessment=['新状态H3主差+2.7757个百分点，T-1、去2026及事件去重仍正。','匹配34簇等权+1.1339个百分点，删任一簇全期仍正；匹配覆盖及2023反例限制推广。',
            '强基线加入状态后筛选未改善，高状态2025仍亏；只支持环境参考职责。','公告暂停、不扩源，原2辅助加1环境参考，阶段二未完成。'])
    update_research_intent(repo,ctx.batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',reason='按用户指令优先数值机制，完成覆盖与增量反证，保存一个有限环境组件及筛选反证；阶段二仍PARTIAL')
    print(json.dumps({'delivery':receipt.reference.to_dict(),'validation':validation.to_dict(),'new_refs':len(refs),'old_refs':len(old.evidence),'components':26},ensure_ascii=False))


if __name__=='__main__':main()
