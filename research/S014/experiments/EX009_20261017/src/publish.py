"""Publish verified index-access and bounded phase-two results as a successor."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from czsc_trader.application import (
    RepositoryContext,create_research_context,publish_evidence,assemble_delivery,validate_delivery,
    update_research_intent,ResearchIntentUpdate,
)
from czsc_trader.research_tools import (
    ResearchBatchRef,ExperimentRef,EvidenceRef,MaterialEvidenceWrite,DeliveryReference,DeliveryDefinition,
    DeliveryStage,DeliveryContent,DeliveryStatus,ValidationStatus,ComponentPanel,ComponentEntry,
    ComponentTestResult,ComponentTestStatus,ExperimentDefinitionRef,FactValue,FactStatus,
)
from inputs import ROOT,EXPERIMENT,RUN


def main():
    if (EXPERIMENT/'others/result.json').exists():
        raise RuntimeError('Preserve published result')
    repository=RepositoryContext.discover(ROOT)
    context=create_research_context(repository,ResearchBatchRef('S014'))
    experiment=ExperimentRef('S014',EXPERIMENT.name)
    prior=json.loads((ROOT/'research/S014/experiments/EX008_20261017/others/result.json').read_text(encoding='utf-8'))
    mandate=json.loads((ROOT/'research/S014/experiments/EX003_20261016/others/result.json').read_text(encoding='utf-8'))
    prior_ref,mandate_ref=(DeliveryReference.from_dict(x['delivery']) for x in (prior,mandate))
    for ref in (prior_ref,mandate_ref):
        if validate_delivery(repository,ref).status is not ValidationStatus.PASS:
            raise RuntimeError('Predecessor validation failed')
    previous=DeliveryContent.from_dict(json.loads((ROOT/'research/S014/assets/deliveries/COMPONENTS/5/delivery.json').read_text(encoding='utf-8'))['content'])
    audits=[json.loads((EXPERIMENT/f'others/{name}.json').read_text(encoding='utf-8')) for name in ('audit','followup_audit','summary_audit')]
    for audit in audits:
        if audit['status']!='PASS':
            raise RuntimeError('Research audit failed')
        for item in audit['manifest']:
            if sha256((ROOT/item['path']).read_bytes()).hexdigest()!=item['sha256']:
                raise RuntimeError(f'Audited material changed:{item["path"]}')
    refs={}
    publications=('published_design','implementation_published','attribution_published','followup_published','mechanism_published')
    for filename in publications:
        refs.update({n:EvidenceRef.from_dict(v) for n,v in json.loads((EXPERIMENT/f'protocols/{filename}.json').read_text(encoding='utf-8')).items()})
    provenance={'authorization':'用户批准同周期000001.SH日线，先验上游权限覆盖再自主继续阶段二。其他新增数据仍需批准。',
        'base_commit':'8a71392e','branch':'codex/s014-jinniu-research','window':['2020-01-01','2026-10-15'],
        'added_dataset':'index.domestic_daily','added_symbol':'000001.SH','new_source_calls':1,'remaining_source_calls':5,
        'new_fixed_fits':200,'reproduction_fits':32,'primary_contrasts':56,'followup_contrasts':56,'mechanism_contrasts':32,
        'nominal_history_contrasts':440,'selection_exposure':'Already-seen full development pool; extra annual/cell/attribution and adaptive proposals not exhaustively enumerated. No independent holdout.',
        'supported_return_entry_components':0,'supported_auxiliary_components':2,'strategy_accounts':0,
        'phase_two_complete':False,'phase_three_recommended':False,'phase_three_approved':False,
        'audit_checks':sum(len(a['checks']) for a in audits),'workers':2,'native_threads_per_worker':1,'seed':13,
        'scope_unapproved':'000813.SHchemicalindexsamewindowproposedonly;notingested. Noindustryclassification,companyevents,methanolfutures orotherbatches.',
        'publication_time_limit':'CompletedT marketclose convention; mathematical prefix causality verified; historical source publication/revision andHFQfactor availability not established.',
        'public_background':'CSI000813officialfactsheet/API docs read for nextscopeplanning only,including preview summary/chart exposure. Not historical numeric input or independentvalidation.'}
    (EXPERIMENT/'protocols/provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    materials={
        'upstream-verification':EXPERIMENT/'others/upstream_verification.json',
        'computation-result':EXPERIMENT/'others/computation_result.json','annual':EXPERIMENT/'others/annual.csv',
        'followup-result':EXPERIMENT/'others/followup_result.json','followup-annual':EXPERIMENT/'others/followup_annual.csv',
        'followup-contributions':EXPERIMENT/'others/followup_contributions.csv',
        'mechanism-result':EXPERIMENT/'others/mechanism_result.json','mechanism-annual':EXPERIMENT/'others/mechanism_annual.csv',
        'attribution-result':EXPERIMENT/'others/attribution_result.json','audit':EXPERIMENT/'others/audit.json',
        'audit-program':EXPERIMENT/'src/audit.py','followup-audit':EXPERIMENT/'others/followup_audit.json',
        'followup-audit-program':EXPERIMENT/'src/audit_followup.py','summary-audit':EXPERIMENT/'others/summary_audit.json',
        'summary-audit-program':EXPERIMENT/'src/audit_summary.py','report-program':EXPERIMENT/'src/report.py',
        'publication-program':Path(__file__),'provenance':EXPERIMENT/'protocols/provenance.json',
        'next-scope-proposal':EXPERIMENT/'protocols/next_scope_proposal.json',
    }
    materials.update({f'{n}-receipt':EXPERIMENT/f'protocols/{n}.json' for n in publications})
    materials.update({f'run-{p.stem.replace("_","-")}':p for p in RUN.glob('*.csv')})
    for name,path in materials.items():
        refs[name]=publish_evidence(context,MaterialEvidenceWrite(experiment,name,path.read_bytes(),
            {'json':'application/json','csv':'text/csv','py':'text/x-python'}[path.suffix[1:]],path.suffix[1:]))
    facts=tuple(replace(f,fact_id=f'prior-{f.fact_id}') for f in previous.facts)
    entries=[replace(e,tests=tuple(replace(t,fact_ids=tuple(f'prior-{x}' for x in t.fact_ids)) for t in e.tests)) for e in previous.payload.components]
    fact_ids=('current-source-calls','current-strategy-accounts','current-audit-checks')
    mechanism_refs=(refs['computation-result'],refs['annual'],refs['followup-result'],refs['followup-annual'],
        refs['followup-contributions'],refs['mechanism-result'],refs['mechanism-annual'],refs['attribution-result'],
        refs['audit'],refs['followup-audit'],refs['summary-audit'],refs['upstream-verification'])
    for i,entry in enumerate(entries):
        if entry.component_id=='gap-down-repair':
            test=ComponentTestResult('market-context-counterevidence',experiment.experiment_id,refs['design'],
                ComponentTestStatus.INSUFFICIENT_DATA,
                '上证指数真实覆盖已核验。2025后续隔夜亏损在过去60日beta市场代理下大部分仍为残差；原3日市场模型在A内选中33次反而更差，不能认定低开修复过滤器获支持。',mechanism_refs,fact_ids)
            entries[i]=replace(entry,judgment='低开修复保留短期相对线索；新增上证指数未充分解释2025隔夜亏损，原市场模型在该条件内反而筛出更差样本，尚不支持收益过滤器。',tests=(*entry.tests,test))
    for component,role,status,explanation in (
        ('market-context-ranking','已完成市场与个股相对变化，用于3日机会排序',ComponentTestStatus.INSUFFICIENT_DATA,
            '完整股票基线上原3日线性增量+.1745个百分点/信号日；更强股票基线及因果126日分数阈值后仍有正向线索，但普通区间、少数贡献、2026反例及MAE竞争解释未解决，不认定入场收益用途获支持。'),
        ('broad-market-recovery','市场前5日下跌后盘中修复对应后续收益',ComponentTestStatus.INEFFECTIVE,
            '固定定义在1/3/5/10日合并原始及强股票残差差均为负，本轮未支持预期方向，不推广为反向规律。'),
        ('common-market-liquidation','区分市场共同卖压与个股特有大跌',ComponentTestStatus.INSUFFICIENT_DATA,
            '部分期限原始相对优势正，但2023无事件、其余仅12/5/12次；强股票残差、年度和尾部反证不足，不因样本少直接否定。'),
        ('market-laggard-repair','市场上涨中相对落后个股收阳后的追赶',ComponentTestStatus.INSUFFICIENT_DATA,
            '3日原始差+.9669个百分点，强股票残差仅+.1744个百分点，2026选中均值负；同源修复与市场增量未充分区分。'),
        ('relative-strength-under-pressure','市场盘中弱时个股相对抗跌的延续',ComponentTestStatus.INSUFFICIENT_DATA,
            '在当前固定定义中相对差跨期限/年度不稳，2026控制更强；未形成明确入场或风险控制用途。'),
    ):
        explicit=component!='market-context-ranking'
        test=ComponentTestResult(f'{component}-increment-and-counterevidence',experiment.experiment_id,
            refs['mechanism-design'] if explicit else refs['design'],status,explanation,mechanism_refs,fact_ids)
        entries.append(ComponentEntry(component,
            ExperimentDefinitionRef(refs['mechanisms'] if explicit else refs['market_features'],
                'src/mechanisms.py::event_masks' if explicit else 'src/market_features.py::features'),
            role,'继承SRT/TXE实际股数双侧0.1%净现金/100000，未成交0，右截断不强平',
            'H1/3/5/10；市场排序重点H3及H1反证，最早T+2卖出',
            '完整股票15及增强19项基线、市场/相对表达、固定单位beta、滞后/因果分数阈值、原A/普通收阳和全部参与',
            '仅完成T及更早；beta严格截至T-1；训练标签实际到期早于年度测试起点；历史发布与修订时点未核验',
            '股票HFQ_RESEARCH归一化单位及原始价位折算；指数为官方点位，仅解释/条件输入，非交易或新基准',
            'S014已见池；新指数1642会话完整，首61会话形成可用历史；独立重叠尝试而非账户',explanation,(test,)))
    for name,value,unit in (
        ('current-source-calls',1,'calls'),('current-source-calls-remaining',5,'calls'),
        ('current-index-sessions',1642,'exchange sessions'),('current-strategy-accounts',0,'accounts'),
        ('current-audit-checks',provenance['audit_checks'],'checks'),('current-new-fixed-fits',200,'fits'),
        ('current-reproduction-fits',32,'fits'),('current-nominal-history',440,'nominal contrasts'),
        ('current-supported-return-entries',0,'components'),
    ):
        facts+=(FactValue(name,value,unit,FactStatus.AVAILABLE,(refs['provenance'],refs['upstream-verification'],refs['audit'],refs['followup-audit'],refs['summary-audit'])),)
    conclusion='阶段二继续：上证指数权限与1642交易日覆盖通过；市场3日条件排序有有限正向线索，但强基线、贡献集中和2025反例未解决，新增收益入场用途不认定。最小后续建议为同窗口000813.SH行业价格代理，获准后先验上游，不预先改平台或进入阶段三。'
    incomplete=('市场排序尚未形成与更强股票信息及少数贡献区分充分的净收益用途。',
        '2025隔夜残差不能由当前广义市场代理充分解释；行业共同因素与公司重定价仍未区分。',
        '最小新增000813.SH范围尚未批准，权限和实际覆盖未实测；不把这一未知归因于供应商缺失。')
    receipt=assemble_delivery(repository,DeliveryDefinition(context.batch,DeliveryStage.COMPONENTS,6,(mandate_ref,prior_ref)),
        DeliveryContent(ComponentPanel(tuple(entries),conclusion),DeliveryStatus.PARTIAL,facts=facts,explanations=(),
            incomplete_items=incomplete,report=(EXPERIMENT/'protocols/report.md').read_text(encoding='utf-8'),
            evidence=tuple(dict.fromkeys((*previous.evidence,*refs.values())))))
    validation=validate_delivery(repository,receipt.reference)
    if validation.status is not ValidationStatus.PASS:
        raise RuntimeError(validation.issues)
    public=ROOT/'research/S014/deliveries/COMPONENTS/6/report.md'
    copied=EXPERIMENT/'others/report.md';copied.write_bytes(public.read_bytes())
    assert public.read_bytes()==copied.read_bytes()==(EXPERIMENT/'protocols/report.md').read_bytes()
    verification={'formal_report':public.relative_to(ROOT).as_posix(),'experiment_report':copied.relative_to(ROOT).as_posix(),
        'sha256':sha256(public.read_bytes()).hexdigest(),'bytes':public.stat().st_size,'status':'PASS'}
    (EXPERIMENT/'protocols/report_copy_verification.json').write_text(json.dumps(verification,indent=2)+'\n',encoding='utf-8',newline='\n')
    result={'experiment':experiment.to_dict(),'delivery':receipt.reference.to_dict(),'validation':validation.to_dict(),
        'status':'PARTIAL','evidence':{n:v.to_dict() for n,v in refs.items()},'inherited_evidence':[v.to_dict() for v in previous.evidence],
        'report_copy':verification,'phase_two_complete':False,'phase_three_recommended':False,'phase_three_approved':False,
        'supported_auxiliary_components':2,'new_supported_return_components':0,'strategy_accounts':0,'new_source_calls':1,
        'remaining_source_calls':5,'next_scope_proposed':'000813.SH同窗口日线，行业价格代理；未批准、未取数。'}
    (EXPERIMENT/'others/result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    intent=json.loads((ROOT/'research/registrations/S014/family.json').read_text(encoding='utf-8'))['research_intent']
    intent.update(stage='阶段二进行中：上证指数核验与机制反证已交付，行业价格代理扩展待批准',
        components=receipt.reference.to_dict(),phase_two_complete=False,phase_three_approved=False,phase_three_ready=False,
        component_definitions=len(entries),supported_components=2,supported_return_entry_components=0,strategy_accounts=0,
        remaining_source_calls=5,approved_added_data={'dataset':'index.domestic_daily','symbol':'000001.SH','start':'2020-01-01','end':'2026-10-15'},
        pending=[result['next_scope_proposed']],conclusion=conclusion)
    intent['diagnostic_feedback'].update(authorization=provenance['authorization'],closure_delivery=receipt.reference.to_dict(),
        reviewed_delivery=receipt.reference.to_dict(),reviewed_commit='8a71392e',
        execution_scope_this_turn='EX009公开指数权限/覆盖实测、市场增量与强基线/阈值/直接机制反证；1次上游、无账户。',
        priority_question='剩余隔夜亏损是否仍是行业共同因素，何种已知条件可提供超越股票与广义市场的净收益增量？',
        result='1642完整通过；3日市场排序有正向线索但强基线/集中度反证不足；2025低开修复隔夜损失大部分仍是当前beta代理残差。',
        recommended_minimum_design='同窗口000813.SH固定行业价格代理，获批后先用公开DFLS实测权限覆盖，再验市场+行业相对市场单因子及强股票控制。',
        judgment_update='不因新源可得或模型局部显著而收口；保留线索与有效负面结果。当前广义市场代理不足不证明损失来自公司。',
        routing={'primary':'阶段二：行业/公司共同因素辨别与净收益用途','stage_three':'未批准且当前不建议进入'},
        routing_after_result='阶段二继续，最小行业代理范围待批准；既有范围暂不重复扫描。',
        verified=f'COMPONENTS/6 PARTIAL/FULL/PASS；{provenance["audit_checks"]}项检查，全部主要/补充模型与144个比较复算。')
    update_research_intent(repository,context.batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',
        reason='执行已批准指数上游验证和阶段二研究，发布有限增量及关键反证，不提前收口；提出未执行的最小行业代理范围')
    print(json.dumps({'delivery':receipt.reference.to_dict(),'validation':validation.to_dict(),'status':'PARTIAL',
        'audit_checks':provenance['audit_checks'],'new_source_calls':1,'remaining_source_calls':5},ensure_ascii=False))


if __name__=='__main__':
    main()
