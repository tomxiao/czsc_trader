"""Publish the bounded original-announcement study without adding a feature."""
from hashlib import sha256
import json
from pathlib import Path
from czsc_trader.application import (RepositoryContext,create_research_context,publish_evidence,
    assemble_delivery,validate_delivery,update_research_intent,ResearchIntentUpdate)
from czsc_trader.research_tools import (ResearchBatchRef,ExperimentRef,EvidenceRef,MaterialEvidenceWrite,
    DeliveryReference,DeliveryDefinition,DeliveryStage,DeliveryContent,DeliveryStatus,ValidationStatus,
    ComponentPanel,FactValue,FactStatus)

ROOT=Path(__file__).resolve().parents[5]
EX=Path(__file__).resolve().parents[1]


def main():
    if (EX/'others/result.json').exists():raise RuntimeError('Preserve published result')
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    repo=RepositoryContext.discover(ROOT)
    context=create_research_context(repo,ResearchBatchRef('S014'))
    experiment=ExperimentRef('S014',EX.name)
    prior=read(ROOT/'research/S014/experiments/EX011_20261017/others/result.json')
    mandate=read(ROOT/'research/S014/experiments/EX003_20261016/others/result.json')
    prior_ref,mandate_ref=(DeliveryReference.from_dict(x['delivery']) for x in (prior,mandate))
    assert all(validate_delivery(repo,r).status is ValidationStatus.PASS for r in (prior_ref,mandate_ref))
    old=DeliveryContent.from_dict(read(ROOT/'research/S014/assets/deliveries/COMPONENTS/8/delivery.json')['content'])
    audit=read(EX/'others/audit.json');assert audit['status']=='PASS'
    for item in audit['manifest']:
        assert sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256'],item['path']
    refs={}
    for name in ('published_design','published_sample','published_documents','published_annotations'):
        refs.update({k:EvidenceRef.from_dict(v) for k,v in read(EX/f'protocols/{name}.json').items()})
    paths={ROOT/item['path'] for item in audit['manifest']}|{EX/'others/audit.json',Path(__file__)}
    for p in sorted(paths):
        rel=p.relative_to(ROOT).as_posix()
        name='ex012-'+rel.split('EX012_20261017/',1)[1].replace('/','-').replace('.','-')
        mime={'.json':'application/json','.py':'text/x-python','.pdf':'application/pdf','.md':'text/markdown'}[p.suffix]
        refs[name]=publish_evidence(context,MaterialEvidenceWrite(experiment,name,p.read_bytes(),mime,p.suffix[1:]))
    evidence=(refs['annotations'],refs['ex012-others-analysis-json'],refs['ex012-others-audit-json'])
    facts=old.facts+tuple(FactValue('ex012-'+name,value,unit,FactStatus.AVAILABLE,evidence) for name,value,unit in (
        ('cases',15,'cases'),('repair-pairs',5,'pairs'),('catalogue-windows',5,'windows'),('matched-catalogue-rows',62,'rows'),
        ('original-pdfs',32,'files'),('unread-catalogue-bodies',30,'files'),('shared-prior-report-pairs',3,'pairs'),
        ('same-day-time-unknown-cases',5,'cases'),('audit-checks',len(audit['checks']),'checks'),
        ('tushare-calls',0,'calls'),('remaining-tushare-calls',0,'calls'),('new-supported-return-components',0,'components'),('new-strategy-accounts',0,'accounts')))
    facts+=tuple(FactValue('ex012-'+name,None,unit,FactStatus.INSUFFICIENT_DATA,evidence,reason) for name,unit,reason in (
        ('first-publication-time','timestamp','目录日期一致但分钟、首次发布与修订未核实；同日公告不得用于主判。'),
        ('announcement-predictive-increment','effect','3组同财报、1组披露前后有反例、1组同日可知不明；未拟合公告模型或证明预测改善。'),
        ('full-period-catalogue-completeness','coverage','仅核验5个局部窗口当前目录返回，非2020至2026全期历史完整覆盖。')))
    conclusion=('原始公告具有非行情事实内容，但小样本未支持可交易收益增量：15例5配对，3组共享事前财报，'
        '2024前后差异有披露后亏损反例，2026主要正例同日时点未核实。保持不采购、不接平台；'
        '下一问题仅建议追溯风电项目首次披露链。25项定义和2项辅助不变，0新增收益组件，阶段二PARTIAL。')
    next_scope=('建议有界追溯同公司天玥设立、风电项目核准、增资及设备合同的首次披露链，先核验新增事实与实际公开时间；'
        '仅在证据成立后提出时间保守的增量检验，不先批量扩公告、采购或进入阶段三。')
    receipt=assemble_delivery(repo,DeliveryDefinition(context.batch,DeliveryStage.COMPONENTS,9,(mandate_ref,prior_ref)),
        DeliveryContent(ComponentPanel(old.payload.components,conclusion),DeliveryStatus.PARTIAL,facts=facts,explanations=(),
            incomplete_items=('公告首次公开分钟、历史修订及相对预期的新颖性未核实。','30份未选正文及长文未读页可能有其他信息。','原收益入场增量与2025隔夜亏损机制仍未充分区分。'),
            report=(EX/'protocols/report.md').read_text(encoding='utf-8'),evidence=tuple(dict.fromkeys((*old.evidence,*refs.values())))))
    validation=validate_delivery(repo,receipt.reference);assert validation.status is ValidationStatus.PASS
    report=ROOT/'research/S014/deliveries/COMPONENTS/9/report.md'
    assert report.read_bytes()==(EX/'protocols/report.md').read_bytes()
    (EX/'others/report.md').write_bytes(report.read_bytes())
    copy={'status':'PASS','sha256':sha256(report.read_bytes()).hexdigest(),'bytes':report.stat().st_size,
        'formal_report':report.relative_to(ROOT).as_posix(),'experiment_report':(EX/'others/report.md').relative_to(ROOT).as_posix()}
    (EX/'protocols/report_copy_verification.json').write_text(json.dumps(copy,indent=2)+'\n',encoding='utf-8',newline='\n')
    result={'experiment':experiment.to_dict(),'delivery':receipt.reference.to_dict(),'validation':validation.to_dict(),
        'status':'PARTIAL','evidence':{k:v.to_dict() for k,v in refs.items()},'inherited_evidence':[r.to_dict() for r in old.evidence],
        'report_copy':copy,'source_catalogue_rows':62,'original_pdfs':32,'cases':15,'repair_pairs':5,
        'new_tushare_calls':0,'remaining_source_calls':0,'component_definitions':25,'supported_auxiliary':2,
        'new_supported_return_components':0,'strategy_accounts':0,'phase_two_complete':False,'phase_three_recommended':False,
        'phase_three_approved':False,'next_scope_proposed':next_scope,'purchase_recommended':False}
    (EX/'others/result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    intent=read(ROOT/'research/registrations/S014/family.json')['research_intent']
    intent.update(stage='阶段二进行中：原始公告小样本核查完成，未支持收益增量，建议追溯首次披露',
        components=receipt.reference.to_dict(),phase_two_complete=False,phase_three_ready=False,phase_three_approved=False,
        component_definitions=25,supported_components=2,supported_return_entry_components=0,strategy_accounts=0,
        remaining_source_calls=0,pending=[next_scope],conclusion=conclusion)
    intent['resources']['remaining_source_calls']=0
    intent['current_data_authorization']={'source':'Current human conversation',
        'verbatim':'同意，暂不购买公告权限。先按你的建议开展小规模原始公告核查，判断是否有值得继续研究的信息增量，你自主推进。',
        'scope':'SSE/CNInfo公开原始公告小样本，15例5窗口32PDF关键页，分类后解盲，不含平台、账户或采购',
        'window':['2020-01-01','2026-10-15'],'actual_tushare_calls':0,'remaining_tushare_calls':0,
        'full_period_coverage':'UNVERIFIED','first_publication_time':'UNVERIFIED'}
    intent['original_announcement_study']={'experiment':experiment.to_dict(),'delivery':receipt.reference.to_dict(),
        'cases':15,'catalogue_rows':62,'original_pdfs':32,'new_supported_return_components':0,'formal_dataset_added':False,
        'annotations':refs['annotations'].to_dict(),'analysis':refs['ex012-others-analysis-json'].to_dict()}
    intent['diagnostic_feedback'].update(authorization=intent['current_data_authorization']['verbatim'],
        closure_delivery=receipt.reference.to_dict(),reviewed_delivery=receipt.reference.to_dict(),reviewed_commit='9e72e30f',
        execution_scope_this_turn='5窗口62条双源目录、32原文关键页、先分类后解盲15例，不新增Tushare调用或平台。',
        result=conclusion,judgment_update='公告有内容增量，但收益增量未获支持；先查首次披露，不能以购买目录替代时点和因果证据。',
        recommended_minimum_design=next_scope,routing_after_result='阶段二PARTIAL；本次小规模核查完成，后续首次披露链为建议未执行。',
        verified=f'COMPONENTS/9 PARTIAL/FULL/PASS；{len(audit["checks"])}项离线检查。',
        assessment=['3组共享事前财报，2024年差异存在普通亏损反例。','2026盈利信号当天公告时点不明，禁止计入主判。','风电业务进展是内容线索，首次披露与短期收益尚未验证。','原25项定义及2项辅助保持，新增收益用途0。'])
    update_research_intent(repo,context.batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',
        reason='完成用户批准原始公告小规模核查，保存非行情事实与时间反证；不采购、不扩平台，阶段二继续PARTIAL')
    print(json.dumps({'delivery':receipt.reference.to_dict(),'validation':validation.to_dict(),'new_evidence_refs':len(refs),
        'inherited_evidence':len(old.evidence),'audit_checks':len(audit['checks'])},ensure_ascii=False))


if __name__=='__main__':main()
