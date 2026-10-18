"""Publish the fixed interaction result, preserving historical research assets."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
from czsc_trader.application import (
    RepositoryContext,create_research_context,publish_evidence,assemble_delivery,
    validate_delivery,update_research_intent,ResearchIntentUpdate,
)
from czsc_trader.research_tools import (
    ResearchBatchRef,ExperimentRef,MaterialEvidenceWrite,DeliveryContent,DeliveryDefinition,
    DeliveryReference,DeliveryStage,DeliveryStatus,ComponentPanel,FactValue,FactStatus,
    ValidationStatus,EvidenceRef,
)

ROOT=Path(__file__).resolve().parents[5]
EX=Path(__file__).resolve().parents[1]


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def write(p,obj):
    with p.open('x',encoding='utf-8',newline='\n') as h:
        h.write(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def main():
    assert not (EX/'others/result.json').exists()
    a=read(EX/'others/analysis.json')
    fit=read(EX/'others/fit_receipt.json')
    audit=read(EX/'others/independent_audit.json')
    stats=read(EX/'others/independent_statistics_audit.json')
    review=read(EX/'others/report_review.json')
    judgment=read(EX/'others/judgment.json')
    assert a['status']==fit['status']=='COMPLETE'
    assert audit['status']==stats['status']==review['status']=='PASS'
    assert fit['fits_reserved']==fit['fits_completed']==12 and fit['failed_fits']==0
    assert fit['fits_remaining']==0 and judgment['new_supported_components']==0
    assert len(list((EX/'others/fits').glob('reserved_*.json')))==12
    assert len(list((EX/'others/fits').glob('fit_*.json')))==12
    for rel,digest in audit['source_sha256'].items():
        assert sha256((ROOT/rel).read_bytes()).hexdigest()==digest,rel
    for rel,digest in stats['source_sha256'].items():
        assert sha256((EX/rel).read_bytes()).hexdigest()==digest,rel
    assert review['report_sha256']==sha256((EX/'protocols/report.md').read_bytes()).hexdigest()
    assert review['judgment_sha256']==sha256((EX/'others/judgment.json').read_bytes()).hexdigest()
    for lock in ['published_design','run_lock']:
        for rel,ref in read(EX/f'protocols/{lock}.json').items():
            assert EvidenceRef.from_dict(ref).resolve(ROOT).read_bytes()==(ROOT/rel).read_bytes()
    family=ROOT/'research/registrations/S014/family.json'
    intent=read(family)['research_intent']
    permitted={'stage','pending','conclusion','components','methanol_interaction_test'}
    protected={k:deepcopy(v) for k,v in intent.items() if k not in permitted}
    assert intent['strategy_accounts']==66 and intent['all_targets_pass_count']==0
    assert intent['stage_three_autonomous_budget']['remaining_unallocated_rounds']==0
    assert intent['methanol_information_test']['fits_remaining']==0
    repo=RepositoryContext.discover(ROOT)
    ctx=create_research_context(repo,ResearchBatchRef('S014'))
    experiment=ExperimentRef('S014',EX.name)
    previous=DeliveryReference.from_dict(read(EX.parent/'EX031_20261018/others/result.json')['delivery'])
    old=DeliveryContent.from_dict(read(ROOT/'research/S014/assets/deliveries/COMPONENTS/14/delivery.json')['content'])
    assert isinstance(old.payload,ComponentPanel) and len(old.payload.components)==26
    refs={}
    for path in sorted(p for p in EX.rglob('*') if p.is_file() and p.suffix in {'.py','.json','.csv','.md'} and '__pycache__' not in p.parts):
        name=path.relative_to(EX).as_posix()
        ref=publish_evidence(ctx,MaterialEvidenceWrite(experiment,'ex032-'+name.replace('/','-').replace('.','-'),
            path.read_bytes(),{'.py':'text/x-python','.json':'application/json','.csv':'text/csv','.md':'text/markdown'}[path.suffix],path.suffix[1:]))
        assert ref.resolve(ROOT).read_bytes()==path.read_bytes()
        refs[name]=ref
    evidence=tuple(dict.fromkeys((*old.evidence,*refs.values())))
    facts=old.facts+tuple(FactValue('ex032-'+name,value,unit,FactStatus.AVAILABLE,tuple(refs.values())) for name,value,unit in [
        ('fixed-fits',12,'fits'),('new-calls',0,'calls'),('new-labels',0,'labels'),('new-accounts',0,'accounts'),
        ('new-supported-components',0,'components'),('parent-opportunities',216,'attempts'),
        ('D',a['main']['D'],'net_fraction'),('M2-minus-M1',a['main']['allocation_M2_minus_M1'],'net_fraction'),
        ('simple-rule-all-triggers',51,'attempts')])
    print(json.dumps({'phase':'EVIDENCE_PUBLISHED','files':len(refs)}),flush=True)
    delivery=assemble_delivery(repo,DeliveryDefinition(ctx.batch,DeliveryStage.COMPONENTS,15,(previous,)),
        DeliveryContent(ComponentPanel(old.payload.components,judgment['conclusion']),DeliveryStatus.COMPLETE,
            facts=facts,explanations=(),incomplete_items=(),report=(EX/'protocols/report.md').read_text(encoding='utf-8'),evidence=evidence))
    print(json.dumps({'phase':'DELIVERY_ASSEMBLED','reference':delivery.reference.to_dict()}),flush=True)
    check=validate_delivery(repo,delivery.reference)
    assert check.status is ValidationStatus.PASS,check
    formal=ROOT/'research/S014/deliveries/COMPONENTS/15/report.md'
    assert formal.read_bytes()==(EX/'protocols/report.md').read_bytes()
    write(EX/'protocols/report_copy_verification.json',dict(status='PASS',formal=formal.relative_to(ROOT).as_posix(),
        source=(EX/'protocols/report.md').relative_to(ROOT).as_posix(),sha256=sha256(formal.read_bytes()).hexdigest(),byte_identical=True))
    write(EX/'others/result.json',dict(status='COMPLETE',research_readiness='PARTIAL',experiment=experiment.to_dict(),
        delivery=delivery.reference.to_dict(),validation=check.to_dict(),evidence={k:v.to_dict() for k,v in refs.items()},
        formal_fits=12,failed_fits=0,remaining_fits=0,new_supported_components=0,component_definitions=26,
        new_accounts=0,new_data_calls=0,new_labels=0,historical_candidates=66,all_targets_pass_count=0,
        primary_hypothesis=judgment['primary_hypothesis'],conclusion=judgment['conclusion'],next_step=judgment['next_step']))
    intent=read(family)['research_intent']
    assert all(intent.get(k)==v for k,v in protected.items())
    intent.update(stage='阶段二固定交互检验完成：关闭该分支，受限停止建议待用户决定',components=delivery.reference.to_dict(),
        conclusion=judgment['conclusion'],pending=[judgment['next_step']])
    intent['methanol_interaction_test'].update(status='COMPLETE_BRANCH_CLOSED',delivery=delivery.reference.to_dict(),
        result=refs['others/judgment.json'].to_dict(),fits_used=12,fits_remaining=0,failed_fits=0,
        new_supported_components=0,primary_hypothesis=judgment['primary_hypothesis'],next_step=judgment['next_step'])
    update_research_intent(repo,ctx.batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',
        reason='完成获准12次固定交互拟合及反证，交互未获支持并按预案关闭，保留有限加法正面结果；无新增数据标签账户，历史目标与额度不变')
    after=read(family)['research_intent']
    assert all(after.get(k)==v for k,v in protected.items())
    print(json.dumps({'phase':'COMPLETE','delivery':delivery.reference.to_dict(),'validation':check.to_dict(),
        'new_components':0,'new_accounts':0,'fits':12,'failed_fits':0,'remaining_fits':0,'published_evidence':len(refs)}),flush=True)


if __name__=='__main__':
    main()
