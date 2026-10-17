"""Publish the bounded diagnosis and four conditional-extension account comparisons."""
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
    audit=read(EX/'others/account_audit.json')
    assert audit['status']=='PASS'
    assert len(results['records'])==4 and comparison['account_count']==6
    assert isinstance(comparison.get('conclusion'),str) and comparison['conclusion'].strip()
    assert isinstance(comparison.get('next_step'),str) and comparison['next_step'].strip()
    assert (EX/'protocols/account_report.md').is_file()
    assert read(EX/'others/independent_review.json')['status']=='PASS'
    assert read(EX/'others/state_diagnostics_v2.json')['status']=='PASS'
    assert read(EX/'others/path_diagnostics.json')['status']=='PASS'
    repo=RepositoryContext.discover(ROOT);ctx=create_research_context(repo,ResearchBatchRef('S014'))
    previous=DeliveryReference.from_dict(read(EX.parent/'EX018_20261017/others/result.json')['delivery'])
    previous_content=DeliveryContent.from_dict(read(ROOT/'research/S014/assets/deliveries/CANDIDATES/2/delivery.json')['content'])
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
            f'{variant}：原退出决策当晚可知状态一次决定H3或H6；按锁定设计检验条件延长',
            f"年度收益通过{summary['annual_return_pass_count']}/7，回撤通过{summary['annual_drawdown_pass_count']}/7；频率{summary['frequency_per_60']:.6f}；全部目标达标={summary['all_targets_pass']}",
            (EvaluationEvidenceRef(ref,tuple(canonical_sha256(r['identity']) for r in raw['runs'])),)))
        refs[f'account-{variant}']=ref
    paths=set(EX.glob('src/**/*.py'))|set(EX.glob('src/**/*.csv'))|set(EX.glob('protocols/*.json'))
    paths|={EX/'protocols/account_report.md'}
    paths|={p for p in EX.glob('others/*.json') if p.name!='result.json'}
    paths|=set(EX.glob('others/*.csv'))
    p=ROOT/'research/S014/assets/runs'/EX.name/'account_audit_full.json'
    assert sha256(p.read_bytes()).hexdigest()==audit['full_audit']['sha256']
    refs['full-account-audit']=publish_evidence(ctx,MaterialEvidenceWrite(exp,'full-account-audit',p.read_bytes(),'application/json','json'))
    for p in sorted(paths):
        name='ex019-'+p.relative_to(EX).as_posix().replace('/','-').replace('.','-')
        mime={'.py':'text/x-python','.csv':'text/csv','.json':'application/json','.md':'text/markdown'}[p.suffix]
        refs[name]=publish_evidence(ctx,MaterialEvidenceWrite(exp,name,p.read_bytes(),mime,p.suffix[1:]))
    # Distinct logical names can resolve to the same published bytes; declare each identity once.
    evidence=tuple({canonical_sha256(ref.to_dict()):ref for ref in refs.values()}.values())
    search=SearchSummary('fixed-close-state-extension',
        'Four predeclared P, D, AND, OR one-time extension rules plus two authenticated reused H3/H6 baselines',
        '600722.SH; same 1642 sessions, 0.001 each side, original entry/environment/execution/yearly targets',
        6,6,'Retain four new valid outcomes and ten prior candidates; handoff only candidates satisfying every original target',
        ('Previously seen development data; current state definition follows earlier hindsight diagnosis',
         'All original H3 entries diagnosed; subsequent continuous accounts may displace different entries',
         'Strict zero boundaries and H3/H6 fixed; no threshold or holding-period optimization',
         'Two reused baselines overlap prior searches; fourteen unique account candidates across all rounds'),evidence)
    facts=tuple(FactValue(k,v,u,FactStatus.AVAILABLE,evidence) for k,v,u in (
        ('new-account-count',4,'accounts'),('comparison-count',6,'constructions'),('registered-account-count',14,'candidates'),
        ('target-pass-count',comparison['all_targets_pass_count'],'accounts'),('evaluation-sessions',1642,'sessions'),('new-source-calls',0,'calls')))
    passing={x['candidate'] for x in comparison['summaries'] if x['all_targets_pass']}
    passed=tuple(e.identity.key for e in entries if f'{e.identity.key.strategy_id}-{e.identity.key.candidate_id}' in passing)
    receipt=assemble_delivery(repo,DeliveryDefinition(ctx.batch,DeliveryStage.CANDIDATES,3,(previous,)),
        DeliveryContent(CandidateSet(tuple(entries),passed,previous_content.payload.searches+(search,),comparison['conclusion']),
            DeliveryStatus.COMPLETE,facts,(),report=(EX/'protocols/account_report.md').read_text(encoding='utf-8'),evidence=evidence))
    validation=validate_delivery(repo,receipt.reference)
    assert validation.status is ValidationStatus.PASS,validation
    formal=ROOT/'research/S014/deliveries/CANDIDATES/3/report.md'
    assert formal.read_bytes()==(EX/'protocols/account_report.md').read_bytes()
    result={'status':'COMPLETE','experiment':exp.to_dict(),'delivery':receipt.reference.to_dict(),
        'validation':validation.to_dict(),'evidence':{k:v.to_dict() for k,v in refs.items()},
        'new_accounts':4,'reused_accounts':2,'comparison_accounts':6,'registered_candidates':14,
        'all_targets_pass_count':comparison['all_targets_pass_count'],'new_source_calls':0,'remaining_prewindow_calls':7,
        'phase_four_approved':False,'conclusion':comparison['conclusion'],
        'report_sha256':sha256(formal.read_bytes()).hexdigest()}
    (EX/'others/result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    intent=read(ROOT/'research/registrations/S014/family.json')['research_intent']
    intent.update(stage='阶段三当晚可知状态与条件延长对照完成',strategy_accounts=14,
        candidates=receipt.reference.to_dict(),all_targets_pass_count=comparison['all_targets_pass_count'],phase_four_approved=False,
        conclusion=comparison['conclusion'],pending=[comparison['next_step']])
    intent['stage_three_followup'].update(status='COMPLETE',new_accounts=4,reused_accounts=2,new_source_calls=0,
        delivery=receipt.reference.to_dict())
    update_research_intent(repo,ctx.batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',
        reason='完成退出当晚可知状态诊断、四种条件延长连续账户和独立逐日审计，保持原年度目标及负面证据')
    print(json.dumps({'delivery':receipt.reference.to_dict(),'validation':validation.to_dict(),'evidence_count':len(evidence)},ensure_ascii=False))

if __name__=='__main__':main()
