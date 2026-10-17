"""Publish two complementary reservation accounts and the ten-round conclusion."""
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
    assert len(results['records'])==2 and comparison['account_count']==4
    assert comparison['new_accounts']==2 and comparison['reused_accounts']==2
    assert isinstance(comparison.get('conclusion'),str) and comparison['conclusion'].strip()
    assert isinstance(comparison.get('next_step'),str) and comparison['next_step'].strip()
    assert (EX/'protocols/account_report.md').is_file()
    assert read(EX/'others/independent_review.json')['status']=='PASS'
    assert read(EX/'others/precheck.json')['status']=='PASS'
    assert read(EX/'others/path_diagnostics.json')['status']=='PASS'
    assert read(EX/'others/budget_summary.json')['status']=='PASS'
    assert read(EX/'others/budget_summary_review.json')['status']=='PASS'
    assert read(EX/'others/research_route_review.json')['status']=='PASS'
    assert isinstance(comparison.get('budget_conclusion'),str) and comparison['budget_conclusion'].strip()
    initial_budget=read(ROOT/'research/registrations/S014/family.json')['research_intent']['stage_three_autonomous_budget']
    assert initial_budget['total_rounds']==initial_budget['allocated_rounds']==10
    assert initial_budget['completed_rounds']==9 and initial_budget['remaining_unallocated_rounds']==0
    lock=read(EX/'protocols/comparison_lock.json')
    assert lock['autonomous_round']==10 and lock['total_round_budget']==10
    assert tuple(r['variant'] for r in results['records'])==tuple(lock['new_variants'])
    assert len({r['candidate'] for r in results['records']})==2
    trials=read(EX/'others/optuna_trials.json')['trials']
    assert len(trials)==2 and all(t['state']=='COMPLETE' for t in trials)
    assert tuple(t['params']['variant'] for t in trials)==tuple(lock['new_variants'])
    audit_path=ROOT/audit['full_audit']['path']
    assert sha256(audit_path.read_bytes()).hexdigest()==audit['full_audit']['sha256']
    for row in results['records']:
        assert row['status']=='SUCCEEDED'
        ref=EvidenceRef.from_dict(row['evidence'])
        assert sha256(ref.resolve(ROOT).read_bytes()).hexdigest()==ref.sha256
        assert read(ref.resolve(ROOT))['result_hash']==row['result_hash']
    repo=RepositoryContext.discover(ROOT);ctx=create_research_context(repo,ResearchBatchRef('S014'))
    previous=DeliveryReference.from_dict(read(EX.parent/'EX028_20261018/others/result.json')['delivery'])
    previous_content=DeliveryContent.from_dict(read(ROOT/'research/S014/assets/deliveries/CANDIDATES/12/delivery.json')['content'])
    assert isinstance(previous_content.payload,CandidateSet) and len(previous_content.payload.candidates)==64
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
            f'{variant}：所有支撑破坏仍提前卖出，仅以首次早退时已知浮盈的两个互补状态决定是否保留原E+10预约',
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
        name='ex029-'+p.relative_to(EX).as_posix().replace('/','-').replace('.','-')
        mime={'.py':'text/x-python','.csv':'text/csv','.json':'application/json','.md':'text/markdown'}[p.suffix]
        refs[name]=publish_evidence(ctx,MaterialEvidenceWrite(exp,name,p.read_bytes(),mime,p.suffix[1:]))
    # Distinct logical names can resolve to the same published bytes; declare each identity once.
    evidence=tuple({canonical_sha256(ref.to_dict()):ref for ref in refs.values()}.values())
    search=SearchSummary('fixed-complementary-reservation',
        'Two predeclared complementary profit/nonprofit reservation policies enqueued before results; no free sampling or pruning; original no-reservation C35 and all-reservation C56 endpoints reused',
        '600722.SH; same 1642 sessions, 0.001 each side, execution/yearly targets; original support entry and early support-break SELL, H10 deadline; first early known P selects reservation E+10, unchanged five-session support lookback',
        4,4,'Retain two new valid outcomes and sixty-four prior candidates; handoff only candidates satisfying every original target',
        ('Previously seen development data; both P>0 and P<=0 reservation directions are fixed hypotheses, not prior validated winners',
         'Conditional waiting changes later entries, cash and fees; four cells share seen data and are not independent',
         'Forty-six complete shared C/R diagnostic windows and six positive-state windows are not complete conditional-account evidence',
         'Two endpoint accounts overlap prior searches; sixty-six registered identities include fifty-two new accounts in this ten-round budget and fourteen preceding identities, not independent effective strategies'),evidence)
    facts=tuple(FactValue(k,v,u,FactStatus.AVAILABLE,evidence) for k,v,u in (
        ('new-account-count',2,'accounts'),('comparison-count',4,'constructions'),('registered-account-count',66,'candidates'),
        ('ten-round-new-account-count',52,'accounts'),('preceding-account-count',14,'candidates'),
        ('autonomous-round',10,'round'),('autonomous-round-budget',10,'rounds'),
        ('target-pass-count',comparison['all_targets_pass_count'],'accounts'),('evaluation-sessions',1642,'sessions'),('new-source-calls',0,'calls')))
    passing={x['candidate'] for x in comparison['summaries'] if x['all_targets_pass']}
    passed=tuple(e.identity.key for e in entries if f'{e.identity.key.strategy_id}-{e.identity.key.candidate_id}' in passing)
    receipt=assemble_delivery(repo,DeliveryDefinition(ctx.batch,DeliveryStage.CANDIDATES,13,(previous,)),
        DeliveryContent(CandidateSet(tuple(entries),passed,previous_content.payload.searches+(search,),comparison['budget_conclusion']),
            DeliveryStatus.COMPLETE,facts,(),report=(EX/'protocols/account_report.md').read_text(encoding='utf-8'),evidence=evidence))
    validation=validate_delivery(repo,receipt.reference)
    assert validation.status is ValidationStatus.PASS,validation
    formal=ROOT/'research/S014/deliveries/CANDIDATES/13/report.md'
    assert formal.read_bytes()==(EX/'protocols/account_report.md').read_bytes()
    result={'status':'COMPLETE','experiment':exp.to_dict(),'delivery':receipt.reference.to_dict(),
        'validation':validation.to_dict(),'evidence':{k:v.to_dict() for k,v in refs.items()},
        'new_accounts':2,'reused_accounts':2,'comparison_accounts':4,'registered_candidates':66,
        'autonomous_round':10,'total_round_budget':10,
        'all_targets_pass_count':comparison['all_targets_pass_count'],'new_source_calls':0,'remaining_prewindow_calls':7,
        'phase_four_approved':False,'conclusion':comparison['budget_conclusion'],
        'report_sha256':sha256(formal.read_bytes()).hexdigest()}
    (EX/'others/result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    intent=read(ROOT/'research/registrations/S014/family.json')['research_intent']
    intent.update(stage='阶段三自主10轮预算完成，等待下一阶段决策',strategy_accounts=66,
        candidates=receipt.reference.to_dict(),all_targets_pass_count=comparison['all_targets_pass_count'],phase_four_approved=False,
        conclusion=comparison['budget_conclusion'],pending=[comparison['next_step']])
    budget=intent['stage_three_autonomous_budget']
    assert budget['total_rounds']==10 and budget['allocated_rounds']==10 and budget['remaining_unallocated_rounds']==0 and budget['completed_rounds']==9
    budget.update(completed_rounds=budget['completed_rounds']+1,latest_delivery=receipt.reference.to_dict(),
        latest_result='NO_ALL_TARGET_PASS' if not passing else 'ORIGINAL_TARGET_PASS_REQUIRES_STAGE_FOUR_DECISION')
    update_research_intent(repo,ctx.batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',
        reason='完成阶段三自主预算第10轮两互补条件预约账户及两个端点基线复用，累计52新加14前序共66身份，交付10轮真实目标结论和完整年度缺口，不自动追加账户或进入阶段四')
    print(json.dumps({'delivery':receipt.reference.to_dict(),'validation':validation.to_dict(),'evidence_count':len(evidence)},ensure_ascii=False))

if __name__=='__main__':main()
