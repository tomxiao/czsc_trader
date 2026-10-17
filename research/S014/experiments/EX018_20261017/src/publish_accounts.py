"""Publish the bounded diagnosis and six new fixed account comparisons."""
from hashlib import sha256
from pathlib import Path
import json
from strategy_runtime import StrategyCandidate, canonical_sha256
from strategy_manager import CandidateKey
from czsc_trader.application import (RepositoryContext, create_research_context, publish_evidence,
    register_candidate, CandidateRegistrationRequest, load_candidate, assemble_delivery,
    validate_delivery, update_research_intent, ResearchIntentUpdate)
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef, EvidenceRef, MaterialEvidenceWrite,
    DeliveryReference, DeliveryDefinition, DeliveryStage, DeliveryContent, DeliveryStatus,
    ValidationStatus, CandidateIdentityRef, CandidateEntry, CandidateSet, SearchSummary,
    EvaluationEvidenceRef, FactValue, FactStatus)

ROOT=Path(__file__).resolve().parents[5];EX=Path(__file__).resolve().parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8'))

def main():
    if (EX/'others/result.json').exists():raise RuntimeError('Preserve completed delivery')
    results=read(EX/'others/account_results.json');comparison=read(EX/'others/comparison.json')
    audit=read(EX/'others/account_audit_v2.json')
    assert audit['status']=='PASS' and comparison['all_targets_pass_count']==0
    assert len(results['records'])==6 and comparison['account_count']==8
    assert isinstance(comparison.get('conclusion'),str) and comparison['conclusion'].strip()
    assert (EX/'protocols/account_report.md').is_file()
    assert read(EX/'others/independent_review.json')['status']=='PASS'
    diagnostics=read(EX/'others/account_diagnostics.json')
    assert diagnostics['schema']=='s014_ex018_account_path_diagnostics_v1'
    assert len(diagnostics['reconciliation'])==6
    assert all(x['absolute_reconciliation_error']<2e-15 for x in diagnostics['reconciliation'])
    repo=RepositoryContext.discover(ROOT);ctx=create_research_context(repo,ResearchBatchRef('S014'))
    previous=DeliveryReference.from_dict(read(EX.parent/'EX017_20261017/others/result.json')['delivery'])
    previous_content=DeliveryContent.from_dict(read(ROOT/'research/S014/assets/deliveries/CANDIDATES/1/delivery.json')['content'])
    assert isinstance(previous_content.payload,CandidateSet)
    exp=ExperimentRef('S014',EX.name);refs={};entries=list(previous_content.payload.candidates)
    for index,ref in enumerate(previous_content.evidence):refs[f'prior-{index}']=ref
    for row in results['records']:
        assert row['status']=='SUCCEEDED'
        variant=row['variant'];ref=EvidenceRef.from_dict(row['evidence']);raw=read(ref.resolve(ROOT))
        payload=read(EX/f'protocols/payload_{variant}.json')
        candidate=StrategyCandidate('S014',row['candidate'].split('-')[-1],payload,EX/'src/strategy_runtime')
        registration=register_candidate(repo,CandidateRegistrationRequest(candidate,exp,(ref,),()))
        load_candidate(repo,CandidateKey('S014',candidate.candidate_id))
        summary=next(x for x in comparison['summaries'] if x['variant']==variant)
        entries.append(CandidateEntry(CandidateIdentityRef(registration.key,registration.content_sha256),
            f'{variant}：低开要求、环境筛选、持有3/6日固定构造；按锁定设计检验条件效应',
            f"年度收益通过{summary['annual_return_pass_count']}/7，回撤通过{summary['annual_drawdown_pass_count']}/7；频率{summary['frequency_per_60']:.6f}；全部目标达标={summary['all_targets_pass']}",
            (EvaluationEvidenceRef(ref,tuple(canonical_sha256(r['identity']) for r in raw['runs'])),)))
        refs[f'account-{variant}']=ref
    paths=set(EX.glob('src/**/*.py'))|set(EX.glob('src/**/*.csv'))|set(EX.glob('protocols/*.json'))
    paths|={EX/'protocols/account_report.md'}
    paths|={p for p in EX.glob('others/*.json') if p.name!='result.json'}
    paths|=set(EX.glob('others/*.csv'))
    # Preserve both the diagnostic-script failure and corrected independent audit.
    for filename in ('account_audit_full.json','account_audit_full_v2.json'):
        p=ROOT/'research/S014/assets/runs'/EX.name/filename
        if filename.endswith('_v2.json'):assert sha256(p.read_bytes()).hexdigest()==audit['full_audit']['sha256']
        refs[filename]=publish_evidence(ctx,MaterialEvidenceWrite(exp,filename.replace('_','-').replace('.','-'),
            p.read_bytes(),'application/json','json'))
    for p in sorted(paths):
        name='ex018-'+p.relative_to(EX).as_posix().replace('/','-').replace('.','-')
        mime={'.py':'text/x-python','.csv':'text/csv','.json':'application/json','.md':'text/markdown'}[p.suffix]
        refs[name]=publish_evidence(ctx,MaterialEvidenceWrite(exp,name,p.read_bytes(),mime,p.suffix[1:]))
    # Distinct logical names can resolve to the same published bytes; declare each identity once.
    evidence=tuple({canonical_sha256(ref.to_dict()):ref for ref in refs.values()}.values())
    search=SearchSummary('fixed-entry-environment-horizon',
        'Prelocked 2x2x2 factorial; six new continuous accounts plus two authenticated reused baseline accounts',
        '600722.SH; 2020-01-01..2026-10-15; same 1642 sessions, 0.001 each side, original execution and yearly targets',
        8,8,'Retain all six new valid outcomes and four prior candidates; no all-target passing candidate',
        ('All development data previously seen; comparison chosen after descriptive attribution',
         'Factor effects conditional on fixed constructions, not unique causal shares of all missed profits',
         'H6 is one predefined extension, not an optimized or independently validated holding period',
         'Two of eight accounts reused from fixed-four search; ten unique account candidates across both searches'),evidence)
    facts=tuple(FactValue(k,v,u,FactStatus.AVAILABLE,evidence) for k,v,u in (
        ('new-account-count',6,'accounts'),('comparison-count',8,'constructions'),('registered-account-count',10,'candidates'),
        ('target-pass-count',0,'accounts'),('evaluation-sessions',1642,'sessions'),('new-source-calls',0,'calls')))
    receipt=assemble_delivery(repo,DeliveryDefinition(ctx.batch,DeliveryStage.CANDIDATES,2,(previous,)),
        DeliveryContent(CandidateSet(tuple(entries),(),previous_content.payload.searches+(search,),comparison['conclusion']),
            DeliveryStatus.COMPLETE,facts,(),report=(EX/'protocols/account_report.md').read_text(encoding='utf-8'),evidence=evidence))
    validation=validate_delivery(repo,receipt.reference)
    assert validation.status is ValidationStatus.PASS,validation
    formal=ROOT/'research/S014/deliveries/CANDIDATES/2/report.md'
    assert formal.read_bytes()==(EX/'protocols/account_report.md').read_bytes()
    result={'status':'COMPLETE','experiment':exp.to_dict(),'delivery':receipt.reference.to_dict(),
        'validation':validation.to_dict(),'evidence':{k:v.to_dict() for k,v in refs.items()},
        'new_accounts':6,'reused_accounts':2,'comparison_accounts':8,'registered_candidates':10,
        'all_targets_pass_count':0,'new_source_calls':0,'remaining_prewindow_calls':7,
        'phase_four_approved':False,'conclusion':comparison['conclusion'],
        'report_sha256':sha256(formal.read_bytes()).hexdigest()}
    (EX/'others/result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    intent=read(ROOT/'research/registrations/S014/family.json')['research_intent']
    intent.update(stage='阶段三上涨缺口归因与针对性账户对照完成',strategy_accounts=10,
        candidates=receipt.reference.to_dict(),all_targets_pass_count=0,phase_four_approved=False,
        conclusion=comparison['conclusion'],pending=['当前构造均未达到年度目标；根据持仓延长与再入场归因决定下一轮，禁止事后年度切换。'])
    intent['stage_three_followup'].update(status='COMPLETE',new_accounts=6,reused_accounts=2,new_source_calls=0,
        delivery=receipt.reference.to_dict())
    update_research_intent(repo,ctx.batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',
        reason='完成获准上涨缺口归因、事前锁定六新增账户与独立逐日审计，保留年度失败和交互反证')
    print(json.dumps({'delivery':receipt.reference.to_dict(),'validation':validation.to_dict(),'evidence_count':len(evidence)},ensure_ascii=False))

if __name__=='__main__':main()
