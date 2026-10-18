"""Publish local EX035 evidence and the immutable COMPONENTS revision."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.application import (RepositoryContext, ResearchIntentUpdate, assemble_delivery,
    create_research_context, publish_evidence, update_research_intent, validate_delivery)
from czsc_trader.research_tools import (ComponentPanel, DeliveryContent, DeliveryDefinition,
    DeliveryReference, DeliveryStage, DeliveryStatus, EvidenceRef, ExperimentRef, FactStatus,
    FactValue, MaterialEvidenceWrite, ResearchBatchRef, ValidationStatus)

ROOT=Path(__file__).resolve().parents[5]
EX=Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write(path,value):
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')


def main():
    assert not (EX/'others/result.json').exists()
    summary=read(EX/'others/summary.json')
    audit=read(EX/'others/independent_audit.json')
    review=read(EX/'others/report_review.json')
    judgment=read(EX/'others/judgment.json')
    assert summary['status']==audit['status']==review['status']=='PASS'
    assert summary['counts']['eligible']==145 and summary['counts']['account_success']==69
    assert summary['counts']['failed']==0
    assert audit['checked_nodes']==145
    assert digest(EX/'src/audit_results.py')==audit['audit_source_sha256']
    assert digest(EX/'src/audit_identity.py')==audit['identity_audit_source_sha256']
    assert digest(EX/'others/summary.json')==audit['summary_sha256']
    assert digest(EX/'others/events.csv')==audit['events_sha256']
    assert digest(EX/'src/analyze.py')==summary['source_sha256']
    assert digest(EX/'others/events.csv')==summary['events_sha256']
    assert digest(EX/'protocols/report.md')==review['report_sha256']
    assert digest(EX/'others/judgment.json')==review['judgment_sha256']
    design=read(EX/'protocols/design.json')
    assert design['execution_authorized'] and design['current_authorization']=='批准执行'
    lock=read(EX/'protocols/execution_lock.json')
    for relative,expected in lock['source_hashes'].items():
        assert digest(EX/relative)==expected,relative
    assert EvidenceRef.from_dict(read(EX/'protocols/published_design.json')).resolve(ROOT).read_bytes()==(EX/'protocols/design.json').read_bytes()
    family=ROOT/'research/registrations/S014/family.json'
    intent=read(family)['research_intent']
    protected={k:deepcopy(v) for k,v in intent.items() if k not in {'stage','pending','conclusion','components','e9_extension_test'}}
    assert 'e9_extension_test' not in intent
    assert intent['strategy_accounts']==66 and intent['all_targets_pass_count']==0
    previous=DeliveryReference.from_dict(intent['components'])
    assert previous.stage is DeliveryStage.COMPONENTS and previous.revision==17
    old=DeliveryContent.from_dict(read(ROOT/'research/S014/assets/deliveries/COMPONENTS/17/delivery.json')['content'])
    assert len(old.payload.components)==26
    repo=RepositoryContext.discover(ROOT)
    ctx=create_research_context(repo,ResearchBatchRef('S014'))
    experiment=ExperimentRef('S014',EX.name)
    refs={}
    media={'.py':'text/x-python','.json':'application/json','.md':'text/markdown','.csv':'text/csv'}
    for path in sorted(EX.rglob('*')):
        if not path.is_file() or path.suffix not in media or '__pycache__' in path.parts:
            continue
        name=path.relative_to(EX).as_posix()
        ref=publish_evidence(ctx,MaterialEvidenceWrite(experiment,'ex035-'+name.replace('/','-').replace('.','-'),
            path.read_bytes(),media[path.suffix],path.suffix[1:]))
        assert ref.resolve(ROOT).read_bytes()==path.read_bytes()
        refs[name]=ref
    accounts=tuple(EvidenceRef.from_dict(r['evidence']) for r in summary['authenticated_accounts'])
    supporting=tuple(refs[k] for k in ('protocols/design.json','others/summary.json',
        'others/independent_audit.json','others/judgment.json','others/report_review.json'))
    facts=old.facts+tuple(FactValue('ex035-'+key,value,unit,FactStatus.AVAILABLE,supporting)
        for key,value,unit in (
            ('nodes',145,'nodes'),('account-diagnostics',69,'accounts'),('cash-reuse',77,'nodes'),
            ('new-calls',0,'calls'),('new-fits',0,'fits'),('new-supported-components',0,'components'),
            ('new-qualified-candidates',0,'candidates'),
            ('A6-A9-sign-reversals',summary['all']['A6_to_A9']['strict_opposite_n'],'nodes'),
            ('L6-A9-sign-reversals',summary['all']['L6_to_A9']['strict_opposite_n'],'nodes')))
    source_refs=tuple(EvidenceRef.from_dict(x) for x in summary['source_refs'].values())
    print(json.dumps({'phase':'LOCAL_EVIDENCE_SAVED','material_files':len(refs),'diagnostic_accounts':len(accounts)}),flush=True)
    # Component definitions/tests/facts retain their own evidence references. The
    # immutable predecessor retains historical supplemental files; do not copy
    # every unrelated historical evidence item into each successive revision.
    delivery=assemble_delivery(repo,DeliveryDefinition(ctx.batch,DeliveryStage.COMPONENTS,18,(previous,)),
        DeliveryContent(ComponentPanel(old.payload.components,judgment['conclusion']),DeliveryStatus.COMPLETE,
            facts=facts,explanations=(),incomplete_items=(),report=(EX/'protocols/report.md').read_text(encoding='utf-8'),
            evidence=tuple(dict.fromkeys((*refs.values(),*accounts,*source_refs)))))
    print(json.dumps({'phase':'DELIVERY_ASSEMBLED','reference':delivery.reference.to_dict()}),flush=True)
    check=validate_delivery(repo,delivery.reference)
    assert check.status is ValidationStatus.PASS,check
    formal=ROOT/'research/S014/deliveries/COMPONENTS/18/report.md'
    payload=formal.read_bytes()
    assert payload==(EX/'protocols/report.md').read_bytes()
    with (EX/'others/report.md').open('xb') as stream:
        stream.write(payload)
    write(EX/'protocols/report_copy_verification.json',{'status':'PASS','formal':formal.relative_to(ROOT).as_posix(),
        'copy':(EX/'others/report.md').relative_to(ROOT).as_posix(),'source':'research/S014/experiments/EX035_20261018/protocols/report.md',
        'bytes':len(payload),'sha256':sha256(payload).hexdigest(),'byte_identical':True})
    intent=read(family)['research_intent']
    assert all(intent.get(k)==v for k,v in protected.items())
    intent.update(stage='阶段二固定E9延伸检验完成：方法诊断，不新增合格策略',
        conclusion=judgment['conclusion'],pending=[judgment['next_step']],components=delivery.reference.to_dict())
    intent['e9_extension_test']={'status':'COMPLETE','authorization':'批准执行','experiment':experiment.to_dict(),
        'design':refs['protocols/design.json'].to_dict(),'result':refs['others/summary.json'].to_dict(),
        'judgment':refs['others/judgment.json'].to_dict(),'delivery':delivery.reference.to_dict(),
        'caps':design['proposed_caps'],'actual_budget':summary['actual_budget'],'remaining_account_runs':0,
        'diagnostic_accounts':69,'new_supported_components':0,'new_qualified_candidates':0,
        'future_execution_authorized':False,'pause_authorized':False,'fees_execution_annual_targets':'UNCHANGED',
        'next_step':judgment['next_step']}
    update_research_intent(repo,ctx.batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',
        reason='完成已批准69次诊断账户和145组固定E9对照，留存完整负面及敏感性证据；不增加预测组件、不变更历史候选资格和经济约定')
    assert all(read(family)['research_intent'].get(k)==v for k,v in protected.items())
    write(EX/'others/result.json',{'status':'COMPLETE','experiment':experiment.to_dict(),'delivery':delivery.reference.to_dict(),
        'validation':check.to_dict(),'evidence':{k:v.to_dict() for k,v in refs.items()},
        'account_evidence':[r.to_dict() for r in accounts],'actual_budget':summary['actual_budget'],
        'conclusion':judgment['conclusion'],'next_step':judgment['next_step'],
        'new_supported_components':0,'historical_component_definitions':26,'historical_strategy_accounts':66,
        'new_diagnostic_accounts':69,'all_targets_pass_count':0,'future_execution_authorized':False})
    print(json.dumps({'phase':'COMPLETE','validation':check.to_dict()}),flush=True)


if __name__=='__main__':
    main()
