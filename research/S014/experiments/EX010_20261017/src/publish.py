"""Publish the industry experiment without upgrading unsupported return claims."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence,assemble_delivery,validate_delivery,update_research_intent,ResearchIntentUpdate
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,EvidenceRef,MaterialEvidenceWrite,DeliveryReference,DeliveryDefinition,DeliveryStage,DeliveryContent,DeliveryStatus,ValidationStatus,ComponentPanel,ComponentEntry,ComponentTestResult,ComponentTestStatus,ExperimentDefinitionRef,FactValue,FactStatus
from inputs import ROOT,EXPERIMENT,RUN


def main():
    if (EXPERIMENT/'others/result.json').exists():
        raise RuntimeError('Preserve published result')
    repo=RepositoryContext.discover(ROOT);context=create_research_context(repo,ResearchBatchRef('S014'));ex=ExperimentRef('S014',EXPERIMENT.name)
    prior=json.loads((ROOT/'research/S014/experiments/EX009_20261017/others/result.json').read_text(encoding='utf-8'))
    mandate=json.loads((ROOT/'research/S014/experiments/EX003_20261016/others/result.json').read_text(encoding='utf-8'))
    prior_ref,mandate_ref=(DeliveryReference.from_dict(x['delivery']) for x in (prior,mandate))
    for ref in (prior_ref,mandate_ref):
        if validate_delivery(repo,ref).status is not ValidationStatus.PASS:
            raise RuntimeError('Predecessor failed')
    old=DeliveryContent.from_dict(json.loads((ROOT/'research/S014/assets/deliveries/COMPONENTS/6/delivery.json').read_text(encoding='utf-8'))['content'])
    audits=[json.loads((EXPERIMENT/f'others/{n}.json').read_text(encoding='utf-8')) for n in ('audit','followup_audit','stock_lag_audit','report_review')]
    for a in audits:
        assert a['status']=='PASS'
        for item in a['manifest']:
            assert sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256'],item['path']
    refs={};pubs=('published_design','identity_published','canonical_published','implementation_published','attribution_published','followup_published','stock_lag_published')
    for name in pubs:
        refs.update({n:EvidenceRef.from_dict(v) for n,v in json.loads((EXPERIMENT/f'protocols/{name}.json').read_text(encoding='utf-8')).items()})
    provenance={'authorization':'用户批准同周期细分化工000813.SH、剩余5次，先验上游再自主继续阶段二。',
        'requested_symbol':'000813.SH','canonical_vendor_symbol':'000813.CSI','identity_resolution':'Sameindexconfirmedbyrealindex_basiccatalogue;notanindexsubstitutionorplatformalias.',
        'base_commit':'d19738f9','branch':'codex/s014-jinniu-research','window':['2020-01-01','2026-10-15'],
        'source_calls':3,'source_call_sequence':['index_daily:000813.SH:EMPTY','index_basic:000813:CSI:IDENTITY','index_daily:000813.CSI:READY'],
        'remaining_source_calls':2,'total_authorized_recovery_calls_used':48,'new_fixed_fits':148,'prior_reproduction_fits':36,'all_fits':184,
        'main_contrasts':80,'followup_contrasts':42,'stock_lag_contrasts':12,'nominal_history':574,
        'selection_exposure':'Wholeseenpool;moredescriptives,proposalplanningandadaptivecontrolsnotindependentreplications. Noindependentholdout.',
        'audit_checks':sum(len(a['checks']) for a in audits),'strategy_accounts':0,'supported_auxiliary':2,'supported_return_entry_components':0,
        'phase_two_complete':False,'phase_three_recommended':False,'phase_three_approved':False,
        'workers':2,'native_threads_per_worker':1,'seed':13,
        'unverified':'Historicalsourcepublication/revisionsandHFQfactoravailability;companyannouncementpermission/coverage/timestampsnotqueried.',
        'next_proposal':'Only600722.SHannouncementupstreamfeasibilitysamewindow,atmostremaining2calls;notapproved/notqueried;platformworkseparateafterfeasibility.'}
    (EXPERIMENT/'protocols/provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    materials={
        'resolved-upstream':EXPERIMENT/'others/upstream_verification_resolved.json',
        'computation-result':EXPERIMENT/'others/computation_result.json','annual':EXPERIMENT/'others/annual.csv','participation':EXPERIMENT/'others/participation.csv',
        'attribution-result':EXPERIMENT/'others/attribution_result.json','followup-result':EXPERIMENT/'others/followup_result.json',
        'followup-annual':EXPERIMENT/'others/followup_annual.csv','followup-participation':EXPERIMENT/'others/followup_participation.csv',
        'stock-lag-result':EXPERIMENT/'others/stock_lag_result.json','stock-lag-annual':EXPERIMENT/'others/stock_lag_annual.csv',
        'audit':EXPERIMENT/'others/audit.json','audit-program':EXPERIMENT/'src/audit.py',
        'followup-audit':EXPERIMENT/'others/followup_audit.json','followup-audit-program':EXPERIMENT/'src/audit_followup.py',
        'stock-lag-audit':EXPERIMENT/'others/stock_lag_audit.json','stock-lag-audit-program':EXPERIMENT/'src/audit_stock_lag.py',
        'report-review':EXPERIMENT/'others/report_review.json','report-review-program':EXPERIMENT/'src/review_report.py',
        'report-program':EXPERIMENT/'src/report.py','publication-program':Path(__file__),'provenance':EXPERIMENT/'protocols/provenance.json',
        'next-scope-proposal':EXPERIMENT/'protocols/next_scope_proposal.json'}
    materials.update({f'{n}-receipt':EXPERIMENT/f'protocols/{n}.json' for n in pubs})
    materials.update({f'run-{p.stem.replace("_","-")}':p for p in RUN.glob('*.csv')})
    for name,p in materials.items():
        refs[name]=publish_evidence(context,MaterialEvidenceWrite(ex,name,p.read_bytes(),{'py':'text/x-python','json':'application/json','csv':'text/csv'}[p.suffix[1:]],p.suffix[1:]))
    facts=tuple(replace(x,fact_id=f'prior-{x.fact_id}') for x in old.facts)
    entries=[replace(x,tests=tuple(replace(t,fact_ids=tuple(f'prior-{n}' for n in t.fact_ids)) for t in x.tests)) for x in old.payload.components]
    evidence=tuple(refs[n] for n in ('resolved-upstream','vendor-identity','failed-upstream','computation-result','annual','attribution-result','followup-result','followup-annual','stock-lag-result','stock-lag-annual','audit','followup-audit','stock-lag-audit','report-review'))
    fact_ids=('current-source-calls','current-strategy-accounts','current-audit-checks')
    for i,entry in enumerate(entries):
        if entry.component_id=='gap-down-repair':
            test=ComponentTestResult('industry-explanation-and-increment',ex.experiment_id,refs['design'],ComponentTestStatus.INSUFFICIENT_DATA,
                '2025后段实际现金-0.4548%，市场+行业代理+0.0195%，残差未缩小；开盘子集一致。行业确认条件也未支持，不能证明公司原因或认定修复入场获支持。',evidence,fact_ids)
            entries[i]=replace(entry,judgment='短期修复线索保留；市场及化工行业代理未解决2025后续亏损，未确认收益入场用途。',tests=(*entry.tests,test))
    industry_tests=[ComponentTestResult('industry-model-increment',ex.experiment_id,refs['design'],ComponentTestStatus.INSUFFICIENT_DATA,
        '当前行业原值/双因素相对表达在H3多数相对强股票+市场增量负；部分H1收益线索另列滞后检验，不认定行业条件收益用途。',evidence,fact_ids)]
    for name,text,status in (
        ('sector-rebound','3日原始和残差有正向线索，1日不一致，控制与尾部证据不足。',ComponentTestStatus.INSUFFICIENT_DATA),
        ('sector-laggard-repair','3日原始相对差约+1.098个百分点，市场股票模型残差约+0.144，独立增量证据不足。',ComponentTestStatus.INSUFFICIENT_DATA),
        ('sector-confirms-stock-repair','原个股A内行业修复确认在H1/3原始及残差预期方向未支持；本固定确认定义判无效，不推广为反向规律。',ComponentTestStatus.INEFFECTIVE),
        ('sector-trend-with-stock-repair','1/3日方向和控制证据不稳定，未形成可用事前区分。',ComponentTestStatus.INSUFFICIENT_DATA),
        ('relative-leader-in-sector-pressure','原始相对强弱可能来自已有个股信息，扣除市场股票预测后的增量不足。',ComponentTestStatus.INSUFFICIENT_DATA),
        ('common-sector-selloff','缺组年份与稀少事件显式保留，原始/残差及期限方向不稳；不因稀少直接否定。',ComponentTestStatus.INSUFFICIENT_DATA),
    ):
        industry_tests.append(ComponentTestResult(name,ex.experiment_id,refs['design'],status,text,evidence,fact_ids))
    entries.append(ComponentEntry('industry-price-context',ExperimentDefinitionRef(refs['sector_features'],'src/sector_features.py::features,masks'),
        '已完成化工行业原值与去市场共同变化的条件信息；六项直接机制为同信息族测试',
        '原SRT/TXE净现金/100000，双侧0.1%，未成交0、截断不强平','H1/3，最早T+2卖出',
        '股票19+市场7+相对4强基线、当前/滞后/陈旧行业与直接机制残差',
        '完成T及以前，历史系数严格截至T-1过去60日；源发布/修订时点未验证',
        '股票HFQ_RESEARCH归一化实际数量与价位，行业官方点位仅条件信息',
        '同名指数已核验000813.CSI，1642交易日；非历史成员或甲醇利润代表，开发池已见',
        '行业数据完整可得，但收益用途整体证据不足；行业价格代理未充分解释2025隔夜亏损。',tuple(industry_tests)))
    test=ComponentTestResult('lagged-industry-direct-stock-countercontrol',ex.experiment_id,refs['followup-design'],ComponentTestStatus.INSUFFICIENT_DATA,
        'H1线性滞后行业有局部正向增量；加滞后大盘后frozen/rolling普通区间正，补充滞后股票直接控制后缩至+.0355/+.0167个百分点，贡献集中和阈值反证未解决。',evidence,fact_ids)
    entries.append(ComponentEntry('lagged-industry-context',ExperimentDefinitionRef(refs['stock_lag'],'src/stock_lag.py::augmented'),
        '前一日行业状态对H1净收益条件排序的可能增量','原实际股数净现金/100000，双侧费用不变','H1最早T+2卖出',
        '当前强股票/市场、滞后市场、滞后股票、去市场行业、波动与方向消融，三种选择规则',
        '行业输入T-1及更早；训练标签到期严格早于年初，126分数仅过去；全池已见',
        'HFQ_RESEARCH净现金标签；指数为原点位派生，不做行业交易或利润对冲',
        '共同队列62预热；H1开发池912测试尝试；表达和阈值敏感，非完整账户或独立验证',
        '保留局部线性排序正向证据和直接反证，目前不确认收益入场用途。',(test,)))
    for name,value,unit in [('current-source-calls',3,'calls'),('current-source-calls-remaining',2,'calls'),('current-index-sessions',1642,'sessions'),
        ('current-new-fixed-fits',148,'fits'),('current-prior-reproduction-fits',36,'fits'),('current-audit-checks',provenance['audit_checks'],'checks'),
        ('current-main-comparisons',134,'contrasts'),('current-strategy-accounts',0,'accounts'),('current-supported-return-entries',0,'components')]:
        facts+=(FactValue(name,value,unit,FactStatus.AVAILABLE,(refs['provenance'],refs['resolved-upstream'],refs['audit'],refs['followup-audit'],refs['stock-lag-audit'])),)
    conclusion='化工指数同名供应商代码000813.CSI已核验且1642交易日完整；市场+行业代理未缩小2025隔夜亏损。滞后行业有局部排序线索，但强股票滞后控制及贡献/阈值反证不足，不新增SUPPORTED收益组件。阶段二PARTIAL，建议下一步先核验同公司公告上游可用性及真实披露时点，未批准前不执行，不进入阶段三。'
    receipt=assemble_delivery(repo,DeliveryDefinition(context.batch,DeliveryStage.COMPONENTS,7,(mandate_ref,prior_ref)),
        DeliveryContent(ComponentPanel(tuple(entries),conclusion),DeliveryStatus.PARTIAL,facts=facts,explanations=(),
            incomplete_items=('行业滞后排序的独立收益用途尚未充分区别于自身历史信息与贡献集中。','市场+行业代理未解释原隔夜反例，真实公司信息、代理不匹配等解释仍未知。','公告数据的权限/历史/时点核验属于新范围，尚未批准或执行。'),
            report=(EXPERIMENT/'protocols/report.md').read_text(encoding='utf-8'),evidence=tuple(dict.fromkeys((*old.evidence,*refs.values())))))
    validation=validate_delivery(repo,receipt.reference)
    assert validation.status is ValidationStatus.PASS
    report=ROOT/'research/S014/deliveries/COMPONENTS/7/report.md';(EXPERIMENT/'others/report.md').write_bytes(report.read_bytes())
    assert report.read_bytes()==(EXPERIMENT/'protocols/report.md').read_bytes()
    copy={'formal_report':report.relative_to(ROOT).as_posix(),'experiment_report':(EXPERIMENT/'others/report.md').relative_to(ROOT).as_posix(),
        'sha256':sha256(report.read_bytes()).hexdigest(),'bytes':report.stat().st_size,'status':'PASS'}
    (EXPERIMENT/'protocols/report_copy_verification.json').write_text(json.dumps(copy,indent=2)+'\n',encoding='utf-8',newline='\n')
    result={'experiment':ex.to_dict(),'delivery':receipt.reference.to_dict(),'validation':validation.to_dict(),'status':'PARTIAL',
        'evidence':{n:v.to_dict() for n,v in refs.items()},'inherited_evidence':[x.to_dict() for x in old.evidence],'report_copy':copy,
        'new_source_calls':3,'remaining_source_calls':2,'canonical_symbol':'000813.CSI','requested_symbol':'000813.SH',
        'supported_auxiliary':2,'new_supported_return_components':0,'strategy_accounts':0,'phase_two_complete':False,'phase_three_recommended':False,'phase_three_approved':False,
        'next_scope_proposed':'600722.SH同窗口公司公告上游权限、事件覆盖和真实披露时间核验；最多剩余2次，未批准未查询。'}
    (EXPERIMENT/'others/result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    intent=json.loads((ROOT/'research/registrations/S014/family.json').read_text(encoding='utf-8'))['research_intent']
    context_data=[{'dataset':'index.domestic_daily','symbol':'000001.SH','start':'2020-01-01','end':'2026-10-15'},
        {'dataset':'index.domestic_daily','symbol':'000813.CSI','requested_symbol':'000813.SH','same_index_identity_evidence':refs['vendor-identity'].to_dict(),'start':'2020-01-01','end':'2026-10-15'}]
    intent.update(stage='阶段二进行中：化工指数检验与反证完成，公告上游可行性核验待批准',components=receipt.reference.to_dict(),
        phase_two_complete=False,phase_three_ready=False,phase_three_approved=False,component_definitions=len(entries),supported_components=2,supported_return_entry_components=0,
        strategy_accounts=0,remaining_source_calls=2,approved_context_data=context_data,approved_added_data=context_data[-1],pending=[result['next_scope_proposed']],conclusion=conclusion)
    intent['resources']['remaining_source_calls']=2
    intent['current_data_authorization']={'source':'Current human conversation','verbatim':'同意扩展同周期000813.SH日线，使用剩余5次调用额度，先验证上游权限和数据覆盖，再继续阶段二研究，你自主推进。',
        'requested_symbol':'000813.SH','canonical_symbol':'000813.CSI','same_index_verified':True,'window':['2020-01-01','2026-10-15'],'actual_calls':3,'remaining_calls':2}
    intent['diagnostic_feedback'].update(authorization=provenance['authorization'],closure_delivery=receipt.reference.to_dict(),reviewed_delivery=receipt.reference.to_dict(),reviewed_commit='d19738f9',
        execution_scope_this_turn='同化工指数代码核验与完整覆盖、市场行业双因素、前一日行业及滞后自身控制；3次源调用，无账户。',
        priority_question='决策前可知的公司披露信息能否区分持续负面重定价与暂时修复？先验证事件目录、权限与真实发布时间。',
        result='1642完整；2025市场+行业后段代理为正、损失残差未缩小；滞后行业局部线性增量在直接股票滞后控制后减弱，未确认新收益入场。',
        recommended_minimum_design='先核验600722.SH同周期公告anns_d及原始披露时间，最多剩余2次；不先实现平台、不做新事件收益分析。',
        judgment_update='当前行业价格代理未回答关键亏损解释，但不证明公司原因或所有行业信息无效。保留正向与反证，不按实验数或单一置信门收口。',
        routing={'primary':'阶段二：公司信息可得性与可证伪机制','stage_three':'当前不建议且未批准'},routing_after_result='公告上游可行性仅提案，待批准；不再无新问题地追加同类指数。',
        verified=f'COMPONENTS/7 PARTIAL/FULL/PASS；{provenance["audit_checks"]}项检查、184模型和134比较复算及427现金分解。',
        assessment=['同名化工指数代码已由目录确认000813.CSI，真实1642会话完整，3次计入原预算，剩余2。',
            '现有市场/化工双因素代理未缩小2025后续损失，不把残差直接叫公司原因。',
            '滞后行业存在受限线性排序线索；补充滞后股票后增量小、贡献集中和阈值反证未解决。',
            '辅助职责仍2项，新收益入场0；组件无需单独满足完整策略逐年经济目标。',
            '新增公告核验尚未获批，先验上游再申请必要DEV契约；不先开发或自动接入。'])
    update_research_intent(repo,context.batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',reason='交付已批准化工行业扩展的上游真实证据和阶段二机制结果，保留代码更正、正向线索和关键反证；后续公告核验仅提案')
    print(json.dumps({'delivery':receipt.reference.to_dict(),'validation':validation.to_dict(),'status':'PARTIAL','audit_checks':provenance['audit_checks'],'calls':3,'remaining':2},ensure_ascii=False))


if __name__=='__main__':
    main()
