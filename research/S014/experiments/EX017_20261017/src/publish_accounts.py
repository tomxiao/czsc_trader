"""Register the fixed prototypes and publish an evidence-complete comparison."""
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
    assert len(results['records'])==comparison['account_count']==4
    repo=RepositoryContext.discover(ROOT);ctx=create_research_context(repo,ResearchBatchRef('S014'))
    exp=ExperimentRef('S014',EX.name);refs={};entries=[]
    for row in results['records']:
        assert row['status']=='SUCCEEDED'
        variant=row['variant'];ref=EvidenceRef.from_dict(row['evidence']);raw=read(ref.resolve(ROOT))
        payload=read(EX/f'protocols/payload_v3_{variant}.json')
        candidate=StrategyCandidate('S014',row['candidate'].split('-')[-1],payload,EX/'src/strategy_runtime')
        registration=register_candidate(repo,CandidateRegistrationRequest(candidate,exp,(ref,),()))
        load_candidate(repo,CandidateKey('S014',candidate.candidate_id))
        summary=next(x for x in comparison['summaries'] if x['variant']==variant)
        entries.append(CandidateEntry(CandidateIdentityRef(registration.key,registration.content_sha256),
            f'{variant}：既定环境/持有期限固定对照，非参数优化',
            f"年度收益通过{summary['annual_return_pass_count']}/7，回撤通过{summary['annual_drawdown_pass_count']}/7；频率{summary['frequency_per_60']:.6f}；全部目标达标={summary['all_targets_pass']}",
            (EvaluationEvidenceRef(ref,tuple(canonical_sha256(r['identity']) for r in raw['runs'])),)))
        refs[f'account-{variant}']=ref
    # Include the prior preparation, actual acquisition, source closure and all new checks.
    paths=set(EX.glob('src/**/*.py'))|set(EX.glob('src/**/*.csv'))|set(EX.glob('protocols/*.json'))
    paths|={EX/'protocols/account_report.md'}
    paths|={p for p in EX.glob('others/*.json') if p.name!='result.json'}
    paths|=set(EX.glob('others/*.csv'))
    full_audit=ROOT/'research/S014/assets/runs'/EX.name/'account_audit_full.json'
    assert sha256(full_audit.read_bytes()).hexdigest()==audit['full_audit']['sha256']
    refs['full-account-audit']=publish_evidence(ctx,MaterialEvidenceWrite(exp,'full-account-audit',
        full_audit.read_bytes(),'application/json','json'))
    for p in sorted(paths):
        name='ex017-'+p.relative_to(EX).as_posix().replace('/','-').replace('.','-')
        mime={'.py':'text/x-python','.csv':'text/csv','.json':'application/json','.md':'text/markdown'}[p.suffix]
        refs[name]=publish_evidence(ctx,MaterialEvidenceWrite(exp,name,p.read_bytes(),mime,p.suffix[1:]))
    source=DeliveryReference.from_dict(read(ROOT/'research/S014/experiments/EX016_20261017/others/result.json')['delivery'])
    mandate=DeliveryReference.from_dict(read(ROOT/'research/S014/experiments/EX003_20261016/others/result.json')['delivery'])
    conclusion=comparison['conclusion']
    passed=tuple(entry.identity.key for entry,s in zip(entries,comparison['summaries'],strict=True) if s['all_targets_pass'])
    evidence=tuple(refs.values())
    search=SearchSummary('fixed-four','Four predeclared fixed constructions, no parameter search',
        '600722.SH; 2020-01-01..2026-10-15; daily continuous accounts; fixed costs and execution',4,4,
        'Retain all four comparisons; no automatic stage-four advance',
        ('Entire period previously seen; no independent holdout','Historical HFQ publication/revision timestamps unverified',
         '4 completed accounts plus 4 failed observation-contract attempts; 1 earlier input-contract preparation failure; no economic-parameter search'),evidence)
    facts=tuple(FactValue(k,v,u,FactStatus.AVAILABLE,evidence) for k,v,u in (
        ('account-count',4,'accounts'),('target-pass-count',comparison['all_targets_pass_count'],'accounts'),
        ('evaluation-sessions',1642,'sessions'),('source-calls',8,'calls'),('remaining-approved-calls',7,'calls')))
    receipt=assemble_delivery(repo,DeliveryDefinition(ctx.batch,DeliveryStage.CANDIDATES,1,(mandate,source)),
        DeliveryContent(CandidateSet(tuple(entries),passed,(search,),conclusion),DeliveryStatus.COMPLETE,
            facts,(),report=(EX/'protocols/account_report.md').read_text(encoding='utf-8'),evidence=evidence))
    validation=validate_delivery(repo,receipt.reference)
    assert validation.status is ValidationStatus.PASS,validation
    formal=ROOT/'research/S014/deliveries/CANDIDATES/1/report.md'
    assert formal.read_bytes()==(EX/'protocols/account_report.md').read_bytes()
    value={'status':'COMPLETE','experiment':exp.to_dict(),'delivery':receipt.reference.to_dict(),
        'validation':validation.to_dict(),'evidence':{k:v.to_dict() for k,v in refs.items()},
        'account_count':4,'all_targets_pass_count':comparison['all_targets_pass_count'],'source_calls':8,
        'remaining_source_calls':7,'phase_four_approved':False,'conclusion':conclusion,
        'report_sha256':sha256(formal.read_bytes()).hexdigest()}
    (EX/'others/result.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    intent=read(ROOT/'research/registrations/S014/family.json')['research_intent']
    intent.update(stage='阶段三四方案账户对照完成，待用户决定后续研究',strategy_accounts=4,
        candidates=receipt.reference.to_dict(),all_targets_pass_count=comparison['all_targets_pass_count'],
        remaining_source_calls=7,phase_four_approved=False,conclusion=conclusion,
        pending=['根据四方案账户证据决定继续阶段三优化或回退阶段二；不自动进入阶段四。'])
    intent['stage_three_preparation']['status']='ACCOUNT_COMPARISON_COMPLETE'
    intent['stage_three_preparation']['actual_account_runs']=4
    intent['stage_three_prewindow_authorization'].update(actual_calls=8,remaining_calls=7,status='COMPLETE')
    update_research_intent(repo,ctx.batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',
        reason='完成获准四方案连续账户、逐年硬门及独立账本审计，交付真实结果并保留未达标反证')
    print(json.dumps({'delivery':receipt.reference.to_dict(),'validation':validation.to_dict(),'refs':len(refs)},ensure_ascii=False))

if __name__=='__main__':main()
