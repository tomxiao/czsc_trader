"""Publish six shorter complete-cycle accounts with three original H10 baselines."""
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
    assert len(results['records'])==6 and comparison['account_count']==9
    assert comparison['new_accounts']==6 and comparison['reused_accounts']==3
    assert isinstance(comparison.get('conclusion'),str) and comparison['conclusion'].strip()
    assert isinstance(comparison.get('next_step'),str) and comparison['next_step'].strip()
    assert (EX/'protocols/account_report.md').is_file()
    assert read(EX/'others/independent_review.json')['status']=='PASS'
    assert read(EX/'others/precheck.json')['status']=='PASS'
    assert read(EX/'others/path_diagnostics.json')['status']=='PASS'
    assert read(EX/'others/research_route_review.json')['status']=='PASS'
    lock=read(EX/'protocols/comparison_lock.json')
    assert lock['autonomous_round']==7 and lock['total_round_budget']==10
    assert tuple(r['variant'] for r in results['records'])==tuple(lock['new_variants'])
    assert len({r['candidate'] for r in results['records']})==6
    trials=read(EX/'others/optuna_trials.json')['trials']
    assert len(trials)==6 and all(t['state']=='COMPLETE' for t in trials)
    assert tuple(t['params']['variant'] for t in trials)==tuple(lock['new_variants'])
    audit_path=ROOT/audit['full_audit']['path']
    assert sha256(audit_path.read_bytes()).hexdigest()==audit['full_audit']['sha256']
    for row in results['records']:
        assert row['status']=='SUCCEEDED'
        ref=EvidenceRef.from_dict(row['evidence'])
        assert sha256(ref.resolve(ROOT).read_bytes()).hexdigest()==ref.sha256
        assert read(ref.resolve(ROOT))['result_hash']==row['result_hash']
    repo=RepositoryContext.discover(ROOT);ctx=create_research_context(repo,ResearchBatchRef('S014'))
    previous=DeliveryReference.from_dict(read(EX.parent/'EX025_20261018/others/result.json')['delivery'])
    previous_content=DeliveryContent.from_dict(read(ROOT/'research/S014/assets/deliveries/CANDIDATES/9/delivery.json')['content'])
    assert isinstance(previous_content.payload,CandidateSet) and len(previous_content.payload.candidates)==51
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
            f'{variant}：原支撑入场不变，缩短完整持有和重新入场时钟至H3或H5，分别与B/R/P退出交叉',
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
        name='ex026-'+p.relative_to(EX).as_posix().replace('/','-').replace('.','-')
        mime={'.py':'text/x-python','.csv':'text/csv','.json':'application/json','.md':'text/markdown'}[p.suffix]
        refs[name]=publish_evidence(ctx,MaterialEvidenceWrite(exp,name,p.read_bytes(),mime,p.suffix[1:]))
    # Distinct logical names can resolve to the same published bytes; declare each identity once.
    evidence=tuple({canonical_sha256(ref.to_dict()):ref for ref in refs.values()}.values())
    search=SearchSummary('fixed-shorter-cycle-exit-interaction',
        'Six predeclared H3/H5 by B/R/P configurations enqueued before results; no free sampling or pruning; exact original H10 baseline accounts reused',
        '600722.SH; same 1642 sessions, 0.001 each side, execution/yearly targets; original support entry, deadline actualE+H-1 and reentry reservationE+H, unchanged five-session support lookback',
        9,9,'Retain six new valid outcomes and fifty-one prior candidates; handoff only candidates satisfying every original target',
        ('Previously seen development data; two coarse shorter horizons crossed with three predeclared exits, no per-integer optimization',
         'Shorter holding and reservation change exit opportunities, later entries, cash and fees; nine cells share seen data and are not independent',
         'Shorter cycles may cut winners or amplify repeated losses; H3 is a tested boundary, not an automatic optimal horizon or transferred alpha',
         'Three original H10 baselines overlap prior searches; fifty-seven unique account candidates; autonomous budget round seven of ten'),evidence)
    facts=tuple(FactValue(k,v,u,FactStatus.AVAILABLE,evidence) for k,v,u in (
        ('new-account-count',6,'accounts'),('comparison-count',9,'constructions'),('registered-account-count',57,'candidates'),
        ('autonomous-round',7,'round'),('autonomous-round-budget',10,'rounds'),
        ('target-pass-count',comparison['all_targets_pass_count'],'accounts'),('evaluation-sessions',1642,'sessions'),('new-source-calls',0,'calls')))
    passing={x['candidate'] for x in comparison['summaries'] if x['all_targets_pass']}
    passed=tuple(e.identity.key for e in entries if f'{e.identity.key.strategy_id}-{e.identity.key.candidate_id}' in passing)
    receipt=assemble_delivery(repo,DeliveryDefinition(ctx.batch,DeliveryStage.CANDIDATES,10,(previous,)),
        DeliveryContent(CandidateSet(tuple(entries),passed,previous_content.payload.searches+(search,),comparison['conclusion']),
            DeliveryStatus.COMPLETE,facts,(),report=(EX/'protocols/account_report.md').read_text(encoding='utf-8'),evidence=evidence))
    validation=validate_delivery(repo,receipt.reference)
    assert validation.status is ValidationStatus.PASS,validation
    formal=ROOT/'research/S014/deliveries/CANDIDATES/10/report.md'
    assert formal.read_bytes()==(EX/'protocols/account_report.md').read_bytes()
    result={'status':'COMPLETE','experiment':exp.to_dict(),'delivery':receipt.reference.to_dict(),
        'validation':validation.to_dict(),'evidence':{k:v.to_dict() for k,v in refs.items()},
        'new_accounts':6,'reused_accounts':3,'comparison_accounts':9,'registered_candidates':57,
        'autonomous_round':7,'total_round_budget':10,
        'all_targets_pass_count':comparison['all_targets_pass_count'],'new_source_calls':0,'remaining_prewindow_calls':7,
        'phase_four_approved':False,'conclusion':comparison['conclusion'],
        'report_sha256':sha256(formal.read_bytes()).hexdigest()}
    (EX/'others/result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    intent=read(ROOT/'research/registrations/S014/family.json')['research_intent']
    intent.update(stage='阶段三自主第7轮缩短完整交易周期对照完成，第8轮自然短周期边界对照执行中',strategy_accounts=57,
        candidates=receipt.reference.to_dict(),all_targets_pass_count=comparison['all_targets_pass_count'],phase_four_approved=False,
        conclusion=comparison['conclusion'],pending=[comparison['next_step']])
    budget=intent['stage_three_autonomous_budget']
    assert budget['total_rounds']==10 and budget['allocated_rounds']>=7
    budget.update(completed_rounds=budget['completed_rounds']+1,latest_delivery=receipt.reference.to_dict(),
        latest_result='NO_ALL_TARGET_PASS' if not passing else 'ORIGINAL_TARGET_PASS_REQUIRES_STAGE_FOUR_DECISION')
    update_research_intent(repo,ctx.batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',
        reason='完成阶段三自主预算第7轮H3/H5完整周期与B/R/P退出交互六个新账户及三个H10基线复用、逐日审计和路径归因，继承51个原候选，保留原目标和全部结果')
    print(json.dumps({'delivery':receipt.reference.to_dict(),'validation':validation.to_dict(),'evidence_count':len(evidence)},ensure_ascii=False))

if __name__=='__main__':main()
