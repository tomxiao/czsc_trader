"""Publish the supplementary report and cumulative candidate handoff, preserving revision one."""
import json
from hashlib import sha256
from czsc_trader.application import (RepositoryContext,create_research_context,publish_evidence,
    assemble_delivery,validate_delivery,validate_experiment)
from czsc_trader.research_tools import (ResearchBatchRef,EvidenceRef,MaterialEvidenceWrite,
    ExperimentReportWrite,ExperimentOutcome,ExperimentValidationRequest,ExperimentValidationScope,
    CandidateEntry,CandidateIdentityRef,CandidateSet,EvaluationEvidenceRef,SearchSummary,
    DeliveryReference,DeliveryDefinition,DeliveryStage,DeliveryContent,DeliveryStatus,FactValue,FactStatus)
from strategy_manager import CandidateKey
from run_supplement import ROOT,EROOT,WORK,EXPERIMENT,save


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    repo=RepositoryContext.discover(ROOT)
    batch=ResearchBatchRef('S015')
    ctx=create_research_context(repo,batch)
    rows=sum((read(WORK/f'{phase}_results.json') for phase in ('initial','followup','boundary')),[])
    analysis=read(WORK/'analysis.json')
    assert analysis['published_snapshot_complete'] and analysis['count']==len(rows)
    regs=read(EROOT/'others/registrations.json')
    oldroot=ROOT/'research/S015/experiments/EX003_20261021'
    oldwork=ROOT/'research/S015/assets/runs/EX003_20261021/strategy_study'
    oldrows=read(oldwork/'grid_results.json')+read(oldwork/'extension_results.json')
    oldregs=read(oldroot/'others/registrations.json')
    refs={}
    for name,file in [('authorization','state'),('protocol','protocol_ref'),('control_addendum','control_addendum_ref'),
                      ('followup_prior','followup_prior_ref'),('followup','followup_ref'),('boundary','boundary_ref')]:
        raw=read(EROOT/'others'/f'{file}.json')
        refs[name]=EvidenceRef.from_dict(raw['authorization'] if name=='authorization' else raw)
    def material(name,path):
        suffix=path.suffix[1:]
        media={'py':'text/x-python','json':'application/json','md':'text/markdown'}[suffix]
        refs[name]=publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,name,path.read_bytes(),media,suffix))
    for path in sorted((EROOT/'src').rglob('*.py')):
        material('source_'+path.stem,path)
    for name in ('initial_results','initial_proposals','followup_results','followup_proposals',
                 'boundary_results','boundary_proposals','optuna_boundary_trials',
                 'optuna_initial_trials','optuna_followup_trials','analysis','account_diagnostics','precheck'):
        material(name,WORK/f'{name}.json')
    for name in ('strategy_checks','input_continuity','registrations','final_checks','interpretation'):
        material(name,EROOT/'others'/f'{name}.json')
    old_report_ref=EvidenceRef.from_dict(read(oldroot/'report_ref.json')['report'])
    old_account_refs=tuple(EvidenceRef.from_dict(r['evidence']) for r in oldrows if r['candidate_id'] in {x['candidate_id'] for x in oldregs})
    new_account_refs=tuple(EvidenceRef.from_dict(r['evidence']) for r in rows)
    precheck=EvidenceRef.from_dict(read(WORK/'precheck.json')['evidence'])
    evidence=tuple(refs.values())+new_account_refs+old_account_refs+(precheck,old_report_ref)
    report=(EROOT/'report.md').read_text(encoding='utf-8')
    report_ref=publish_evidence(ctx,ExperimentReportWrite(EXPERIMENT,
        sha256((EROOT/'report.md').read_bytes()).hexdigest(),ExperimentOutcome.COMPLETED,evidence))
    entries=[]
    for registrations,records,old in ((oldregs,oldrows,True),(regs,rows,False)):
        by_id={r['candidate_id']:r for r in records}
        for reg in registrations:
            r=by_id[reg['candidate_id']]
            entries.append(CandidateEntry(CandidateIdentityRef(CandidateKey('S015',r['candidate_id']),reg['content_sha256']),
                '沿用原阶段三候选与不可变账户。' if old else '反转信号周期下的振幅分档、反向或恒定权益仓位对照。',
                '当前中心经济及双频率达标，阶段四待验证。' if r['passed'] else '中心未全部达标，保留收益回撤前沿证据。',
                (EvaluationEvidenceRef(EvidenceRef.from_dict(r['evidence']),(r['evaluation_id'],)),)))
    handoff=tuple(CandidateKey('S015',r['candidate_id']) for r in oldrows+rows if r['passed'])
    searches=(SearchSummary('EX003_carried_forward','原阶段三84点，原件保留','同一434日开发池',84,84,
        '原25达标及前沿完整保留',('继承阶段二和EX003选择历史，不是独立检验。',),(old_report_ref,)),)+tuple(
        SearchSummary('EX004_'+phase,'Optuna预先排定配置、公共TDR完整账户',
            '固定434日、标准单侧0.1%费用；不含阶段四扰动或费用压力',len(read(WORK/f'{phase}_results.json')),len(read(WORK/f'{phase}_results.json')),
            '全部中心达标及收益回撤前沿，未正式排序',
            ('包含重复经济路径、已见代表选择及事后平均仓位对照，不以配置数当独立假设数。',),
            (refs[f'{phase}_results'],refs[f'optuna_{phase}_trials'])) for phase in ('initial','followup','boundary'))
    interpretation=read(EROOT/'others/interpretation.json')
    payload=CandidateSet(tuple(entries),handoff,searches,interpretation['conclusion'])
    facts=(FactValue('supplement_configurations',len(rows),'configurations',FactStatus.AVAILABLE,(refs['analysis'],)),
        FactValue('supplement_center_passed',analysis['passed'],'configurations',FactStatus.AVAILABLE,(refs['analysis'],)),
        FactValue('cumulative_handoff',len(handoff),'candidate_identities',FactStatus.AVAILABLE,(refs['registrations'],old_report_ref)),
        FactValue('robustness_acceptance',None,'not_evaluated',FactStatus.NOT_APPLICABLE,(refs['protocol'],),'阶段四未授权。'))
    prior=DeliveryReference.from_dict(read(ROOT/'research/S015/deliveries/CANDIDATES/1/receipt.json')['reference'])
    delivery_report=report.replace('](protocols/','](../../../experiments/EX004_20261022/protocols/').replace('](others/','](../../../experiments/EX004_20261022/others/')
    delivery_report=delivery_report.replace('](../../deliveries/','](../../')
    receipt=assemble_delivery(repo,DeliveryDefinition(batch,DeliveryStage.CANDIDATES,2,(prior,)),
        DeliveryContent(payload,DeliveryStatus.COMPLETE,facts,(),report=delivery_report,evidence=(*evidence,report_ref)))
    check=validate_delivery(repo,receipt.reference)
    expcheck=validate_experiment(repo,ExperimentValidationRequest(EXPERIMENT,ExperimentValidationScope.REPORT_PUBLICATION))
    save(EROOT/'others/delivery_validation.json',{'delivery':receipt.reference.to_dict(),'validation':check.to_dict(),
        'experiment':expcheck.to_dict(),'report':report_ref.to_dict(),'material_refs':{k:v.to_dict() for k,v in refs.items()}})
    assert check.status.value=='PASS' and expcheck.status.value=='PASS'
    print(json.dumps({'delivery':receipt.reference.to_dict(),'validation':check.status.value,'experiment':expcheck.status.value},ensure_ascii=False))


if __name__=='__main__':
    main()
