"""Create the explicitly approved two-candidate stage-four study."""
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, create_research_context, create_experiment,
    ExperimentRequest, get_research_overview, CandidateRegistrationRequest, register_candidate,
    load_candidate, assemble_delivery, publish_evidence, record_research_decision,
    update_research_intent, ResearchIntentUpdate)
from dataflows import ProviderConfig
from strategy_runtime import EquityStrategyCandidate, EquityStrategyDefinition
from strategy_manager import CandidateKey, CandidateEvidence
from strategy_manager import freeze_contracts as f

ROOT = Path.cwd()
BATCH = ROOT/'research/S019'
WORK = BATCH/'experiments/EX039_20261110'

def read(p):
    return json.loads(p.read_bytes())

def save(p,v):
    p.write_bytes((json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())

repo = RepositoryContext.discover(ROOT)
batch = d.ResearchBatchRef('S019')
ctx = create_research_context(repo,batch,providers=ProviderConfig(bindings={},equity_bindings={}))
assert not WORK.exists(), 'Inspect any existing study before retry'
exp = create_experiment(ctx,ExperimentRequest('C0135与C0224阶段四稳健性自检',
    '按原目标完整评价两个用户指定对象的参数、时间、集中性、费用和统计不确定性。',date(2026,11,10)))
assert exp.resolve(ROOT)==WORK
save(WORK/'others/opening_overview.json',get_research_overview(repo,batch).to_dict())
(WORK/'src/setup.py').write_bytes(Path(__file__).read_bytes())
authorization='''# 阶段四实际授权

2026-11-10，用户原文：“批准C0224和C0135进入阶段四，执行稳健性自检并对比成绩”。之后用户要求“暂停”，暂停期间仅完成只读协议与接口核对，0新增账户。用户随后将RSCH指南默认参数扰动通过率修订为80%，再明确指示：“继续完成阶段四”。

指定范围为C0224及C0135，明确承接两者现有实现。两者当前Calmar低于5，进入本次自检遵循用户明确指定，原经济和频率门槛保持。阶段五、冻结、生产操作及新样本使用未包含在本次任务中。

本次自检独立于剩余7轮优化搜索额度：预先固定完整8点和80点邻域，各一项中心费用压力；复用两中心标准账户和其余历史账本，不追加优化搜索。预计新增90策略账户、标准/压力各一共享买持，最多4账户进程，每进程1原生线程。实际数量及失败状态据结果核对。
'''
(WORK/'protocols/authorization.md').write_bytes(authorization.encode())
approval=publish_evidence(ctx,d.MaterialEvidenceWrite(exp,'stage-four-authorization',authorization.encode(),'text/markdown','md'))
entries,centers=[],[]
for candidate_id,number,name in (('C0135',36,'trial033'),('C0224',38,'trial026')):
    old=BATCH/f'experiments/EX{number:03}_20261110'
    definition=EquityStrategyDefinition.from_dict(read(old/f'others/{name}_definition.json'))
    ref=d.EvidenceRef.from_dict(read(old/f'others/{name}_account.json'))
    raw=ref.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest()==ref.sha256
    head=json.loads(raw)
    candidate=EquityStrategyCandidate('S019',candidate_id,definition,old/'src')
    registration=register_candidate(repo,CandidateRegistrationRequest(candidate,d.ExperimentRef('S019',old.name),
        (ref,),tuple(definition.dependencies)))
    loaded=load_candidate(repo,CandidateKey('S019',candidate_id))
    assert loaded.content_identity.content_sha256==head['request']['content_sha256']
    center={'id':candidate_id,'account_ref':ref.to_dict(),'definition':definition.to_dict(),
        'content_hash':head['request']['content_sha256'],'original_experiment':old.name,
        'source_account_path':f'research/S019/experiments/{old.name}/others/{name}_account.json',
        'registration':registration.to_dict(),'candidate':read(old/'others/summary.json')[name]['candidate']}
    centers.append(center)
    entries.append(d.CandidateEntry(d.CandidateIdentityRef(candidate.key,center['content_hash']),
        '下跌后的开盘恢复与条件仓位；用户指定进入稳健性诊断',
        '中心Calmar未达到5，原目标保持；依据明确用户授权进入阶段四自检。',
        (d.EvaluationEvidenceRef(ref,(head['evaluation_id'],)),)))
save(WORK/'protocols/centers.json',centers)
predecessor=d.DeliveryReference.from_dict(read(BATCH/'deliveries/PROTOTYPES/2/receipt.json')['reference'])
handoff=assemble_delivery(repo,d.DeliveryDefinition(batch,d.DeliveryStage.CANDIDATES,5,(predecessor,)),
    d.DeliveryContent(d.CandidateSet(tuple(entries),tuple(x.identity.key for x in entries),(),
        '用户指定C0135和C0224进入阶段四；中心失败状态保持，未扩大达标集合。'),
        d.DeliveryStatus.COMPLETE,(),(),report='用户明确批准C0224与C0135进入阶段四。两者中心Calmar仍低于5，原目标保持。本修订交接两个指定对象的精确实现和原账户，供完整稳健性诊断与成绩比较。',evidence=(approval,)))
assert handoff.validation.status is d.ValidationStatus.PASS
save(WORK/'others/candidate_handoff.json',handoff.to_dict())
receipt=BATCH/'deliveries/CANDIDATES/5/receipt.json'
decision=record_research_decision(repo,f.ResearchDecision('S019-STAGE4-20261110','S019',f.DecisionAction.APPROVE,
    f.StageAdvanceSubject(CandidateEvidence(receipt.relative_to(ROOT).as_posix(),sha256(receipt.read_bytes()).hexdigest()),'ASSESSMENT'),
    CandidateEvidence(approval.resolve(ROOT).relative_to(ROOT).as_posix(),approval.sha256),
    '用户指定C0224和C0135进行阶段四稳健性自检，暂停后明确继续，原目标和80%通过率保持。'))
save(WORK/'others/authorization.json',{'evidence':approval.to_dict(),'decision':decision.to_dict()})
intent=read(ROOT/'research/registrations/S019/family.json')['research_intent']
intent.update(stage='STAGE_FOUR',stage_four_approval=decision.to_dict(),stage_four_status='IN_PROGRESS',
    stage_four_candidates=['C0135','C0224'],active_experiment=exp.to_dict(),
    next_action='执行完整8/80点参数邻域及各一费用压力，复用原中心完成时间、集中性和统计不确定性。')
update_research_intent(repo,batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',reason='用户明确恢复指定两个对象的阶段四自检。')
(WORK/'report.md').write_bytes('# C0135与C0224阶段四稳健性自检\n\nStatus: IN_PROGRESS\n\n按用户明确批准执行，原目标与80%参数扰动通过率保持。\n'.encode())
print('STAGE_FOUR_CREATED',WORK.name,flush=True)
