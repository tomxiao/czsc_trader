"""Record the explicitly approved three-center stage-four scope."""
from datetime import date
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader import research_tools as d
from czsc_trader.application import (
    RepositoryContext, create_research_context, create_experiment, ExperimentRequest,
    get_research_overview, load_candidate, publish_evidence, record_research_decision,
    update_research_intent, ResearchIntentUpdate,
)
from dataflows import ProviderConfig
from strategy_manager import CandidateKey, CandidateEvidence
from strategy_manager import freeze_contracts as f

ROOT = Path.cwd()
BATCH = ROOT / 'research/S019'
WORK = BATCH / 'experiments/EX041_20261110'


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode())


assert not WORK.exists(), 'Inspect existing experiment before retry'
repo = RepositoryContext.discover(ROOT)
batch = d.ResearchBatchRef('S019')
ctx = create_research_context(repo, batch, providers=ProviderConfig(bindings={}, equity_bindings={}))
exp = create_experiment(ctx, ExperimentRequest('C0367、C0355、C0264首批阶段四完整稳健性自检',
    '按用户批准的三候选范围检验参数、时间、集中性、费用与统计不确定性，比较通过全部原目标后的NAR。', date(2026,11,10)))
assert exp.resolve(ROOT) == WORK
(WORK / 'src/setup.py').write_bytes(Path(__file__).read_bytes())
save(WORK / 'others/opening_overview.json', get_research_overview(repo, batch).to_dict())
authorization = '''# 首批三候选阶段四授权

用户询问是否有必要让21个候选全部进入阶段四。RSCH建议首批选择最高达标NAR的C0367、最高Calmar的C0355及最低MDD的C0264，各自完整执行80个参数邻点及一个费用压力场景，其余18个保留待检。用户明确答复：“批准，请自主推进完成阶段四”。

本次按此明确范围承接CANDIDATES/6的21个完整达标集合，只评价上述三个精确实现，其余18个标记未检，原集合与历史自检失败记录保持。三个候选仍执行全部适用自检，80%通过率、中心NAR≥55%和Calmar≥5及原MDD/频率/压力标准保持。完成后提交结论及下一阶段建议；阶段五、冻结和生产操作另需明确授权。

现有优化10轮额度已用4轮、剩余6轮；本次为固定阶段四验收，新增优化搜索0轮。沿用当前研究分支、既定MU/SOXX已见历史和执行合同，4账户进程各1原生线程。去重及复用前最多243个策略场景，预计约90—130分钟含账户、统计及交付，实际新增账户、共享基准与分段耗时据执行记录报告。
'''
(WORK / 'protocols/authorization.md').write_bytes(authorization.encode())
approval = publish_evidence(ctx, d.MaterialEvidenceWrite(exp, 'three-center-stage-four-authorization', authorization.encode(), 'text/markdown', 'md'))
selected = ['C0367', 'C0355', 'C0264']
qualified = read(BATCH / 'experiments/EX040_20261110/others/qualified_candidates.json')
centers = []
for cid in selected:
    row = next(x for x in qualified if x['id'] == cid)
    candidate = load_candidate(repo, CandidateKey('S019', cid))
    assert candidate.content_identity.content_sha256 == row['content_hash']
    ref = d.EvidenceRef.from_dict(row['account'])
    raw = ref.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest() == ref.sha256
    head = json.loads(raw)
    assert head['request']['candidate_id'] == cid and head['request']['content_sha256'] == row['content_hash']
    assert row['candidate']['eligible'] and all(row['candidate']['gates'].values())
    path = WORK / f'others/{cid}_center_ref.json'
    save(path, row['account'])
    centers.append({'id': cid, 'account_ref': row['account'], 'definition': row['definition'],
        'content_hash': row['content_hash'], 'original_experiment': ref.experiment.experiment_id,
        'source_account_path': path.relative_to(ROOT).as_posix(), 'candidate': row['candidate']})
save(WORK / 'protocols/centers.json', centers)
save(WORK / 'protocols/scope.json', {'selected': selected, 'deferred': [r['id'] for r in qualified if r['id'] not in selected],
    'predecessor': read(BATCH / 'deliveries/CANDIDATES/6/receipt.json')['reference'],
    'complete_original_set_retained': True, 'scope_basis': 'Explicit user approval of the proposed first three candidates'})
receipt = BATCH / 'deliveries/CANDIDATES/6/receipt.json'
decision = record_research_decision(repo, f.ResearchDecision('S019-STAGE4-THREE-20261110', 'S019', f.DecisionAction.APPROVE,
    f.StageAdvanceSubject(CandidateEvidence(receipt.relative_to(ROOT).as_posix(), sha256(receipt.read_bytes()).hexdigest()), 'ASSESSMENT'),
    CandidateEvidence(approval.resolve(ROOT).relative_to(ROOT).as_posix(), approval.sha256),
    '用户批准首批C0367、C0355、C0264完整阶段四，其余18待检，原门槛及剩余6轮优化额度保持。'))
save(WORK / 'others/authorization.json', {'evidence': approval.to_dict(), 'decision': decision.to_dict()})
intent = read(ROOT / 'research/registrations/S019/family.json')['research_intent']
assert intent['joint_search_budget']['remaining_rounds'] == 6
intent.update(stage='STAGE_FOUR', stage_four_approval=decision.to_dict(), stage_four_status='IN_PROGRESS',
    stage_four_candidates=selected, stage_four_deferred_candidates=[r['id'] for r in qualified if r['id'] not in selected],
    active_experiment=exp.to_dict(), next_stage_four_approval='APPROVED_THREE_CANDIDATES',
    next_action='执行三个指定候选完整邻域、压力及其余自检，按全部原目标核验后比较NAR；其余18待检，6轮优化额度保留。')
update_research_intent(repo, batch, ResearchIntentUpdate(research_intent=intent), actor='RSCH', reason='用户批准首批三个达标候选自主完成阶段四。')
for filename in ('strategy.py', 'semantic_audit.py'):
    (WORK / 'src' / filename).write_bytes((BATCH / 'experiments/EX040_20261110/src' / filename).read_bytes())
(WORK / 'report.md').write_bytes('# S019首批三个达标候选阶段四自检\n\nStatus: IN_PROGRESS\n\n按用户明确批准的三候选范围执行，原目标和80%通过率保持。\n'.encode())
print('EX041_CREATED', selected, flush=True)
