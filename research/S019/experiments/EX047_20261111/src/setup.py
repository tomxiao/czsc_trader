"""Open the user-authorized new ten-round stage-three allocation."""
from datetime import date
from hashlib import sha256
import json
import sys
from pathlib import Path
from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, create_research_context, create_experiment,
    ExperimentRequest, get_research_overview, publish_evidence, record_research_decision,
    update_research_intent, ResearchIntentUpdate)
from dataflows import ProviderConfig
from strategy_manager import CandidateEvidence
from strategy_manager import freeze_contracts as f

ROOT = Path.cwd()
BATCH = ROOT/'research/S019'
WORK = BATCH/'experiments/EX047_20261111'
OLD = BATCH/'experiments/EX046_20261111'

def read(path):
    return json.loads(path.read_bytes())

def save(path, obj):
    path.write_bytes((json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode())

recover = sys.argv[1:] == ['--resume-prepublication']
assert recover or not WORK.exists(), 'Inspect existing experiment before explicit recovery'
repo = RepositoryContext.discover(ROOT)
batch = d.ResearchBatchRef('S019')
intent = read(ROOT/'research/registrations/S019/family.json')['research_intent']
assert intent['stage'] == 'STAGE_TWO' and intent['mechanism_research_status'] == 'STAGE_TWO_COMPLETE'
assert not intent.get('active_experiment')
assert intent['joint_search_budget']['used_rounds'] == 8
ctx = create_research_context(repo, batch, providers=ProviderConfig(bindings={}, equity_bindings={}))
overview = get_research_overview(repo, batch)
if recover:
    assert WORK.is_dir() and not (WORK/'others/authorization.json').exists()
    assert not (BATCH/'decisions/S019-STAGE3-CONTINUOUS-20261111.json').exists()
    exp = d.ExperimentRef('S019', WORK.name)
else:
    exp = create_experiment(ctx, ExperimentRequest('连续退出三族联合扩域优化',
        '承接C0804/C0801/C0720，扩大贴边参与参数域并联合优化全部有效连续参数，比较原硬门下的达标能力。', date(2026,11,11)))
assert exp.resolve(ROOT) == WORK
save(WORK/'others/opening_overview.json', overview.to_dict())
(WORK/'src/setup.py').write_bytes(Path(__file__).read_bytes())
authorization = '''# 阶段三新授权

用户在理解渐进ATR退出、恢复仓位和阶段三建议后明确批准：“批准你的建议。重新授权 10 轮实验额度，你自主推进阶段三”。

本次按新的10轮额度单独计数，不叠加旧额度剩余2轮；旧授权和已用8轮完整保留。继续当前 codex/mu-independent-research 分支，沿用已获准12账户进程、每进程1原生线程。以PROTOTYPES/3的C0804、C0801为主要优化对象，C0720为硬退出对照；RSCH根据每轮证据自主安排下一轮与停止条件。额度为上限，研究收获充分时可提前收口。

中心NAR≥55%、Calmar≥5、日末MDD≤25%且≤同费用买持80%；滚动60日闭合中位数≥6，至少3笔窗口覆盖≥90%。原完整邻域80%与费用压力标准保持。数据为2021预热、2022-01-03至2026-10-30连续已见历史；下一阶段另行取得用户批准。
'''
(WORK/'protocols/authorization.md').write_bytes(authorization.encode())
approval = publish_evidence(ctx, d.MaterialEvidenceWrite(exp, 'stage-three-new-ten-rounds', authorization.encode(), 'text/markdown','md'))
receipt = BATCH/'deliveries/PROTOTYPES/3/receipt.json'
decision = record_research_decision(repo, f.ResearchDecision('S019-STAGE3-CONTINUOUS-20261111','S019',f.DecisionAction.APPROVE,
    f.StageAdvanceSubject(CandidateEvidence(receipt.relative_to(ROOT).as_posix(),sha256(receipt.read_bytes()).hexdigest()),'CANDIDATES'),
    CandidateEvidence(approval.resolve(ROOT).relative_to(ROOT).as_posix(),approval.sha256),
    '用户批准以C0804/C0801与C0720对照自主推进阶段三，重新授权10轮实验，保持原目标。'))
save(WORK/'others/authorization.json', {'approval':approval.to_dict(),'decision':decision.to_dict()})
prior = read(OLD/'others/results.json')['accounts']
old_search = read(BATCH/'experiments/EX045_20261111/protocols/search.json')
domains = {'weak_fraction':(.15,.55), 'quiet_fraction':(.15,.85),
    'participation_threshold':(.75,1.5), 'participation_width':(.05,.65),
    'trail_atr':(1.8,3.2), 'exit_width':(.1,1.25)}
families, imports = [], {}
(WORK/'others/imports').mkdir()
for name, policy, key in [('hard_linear','hard','qualified_linear_hard_center'),
        ('ramp_linear','ramp','qualified_linear_ramp_center'),
        ('rebuild_linear','ramp_rebuild','qualified_linear_ramp_rebuild_center')]:
    row = prior[key]
    p = row['parameters']
    space = {k:{'kind':'float','low':lo,'high':hi,'step':None} for k,(lo,hi) in domains.items()
             if k != 'exit_width' or policy != 'hard'}
    fixed = {k:v for k,v in p.items() if k not in space}
    families.append({'name':name,'fixed':fixed,'space':space,
        'control_account':(OLD/f'others/{key}_account.json').relative_to(ROOT).as_posix()})
    imports[name] = []
    for label, r in prior.items():
        params = r['parameters']
        if any(params[k] != v for k,v in fixed.items()) or params == p:
            continue
        if not all(b['low'] <= params[k] <= b['high'] for k,b in space.items()):
            continue
        item = {'id':r['candidate_id'],'parameters':params,'definition':r['definition'],
            'account':r['account_ref'],'candidate':r['candidate'],'buy_hold':r['benchmark'],
            'content_hash':r['content_hash'], 'origin':{'experiment':OLD.name,'label':label,
            'result_sha256':sha256((OLD/'others/results.json').read_bytes()).hexdigest()}}
        path = WORK/f'others/imports/{name}_{label}.json'
        save(path,item)
        imports[name].append(path.relative_to(ROOT).as_posix())
config = {'families':families,'state_schema':old_search['state_schema'],'base_candidate':'C0355',
    'parameter_schema':old_search['parameter_schema'],'candidate_start':807,
    'round_budget':{'allocated_rounds':10,'round_index':1,'total_round':1,'remaining_after_completion':9},
    'seed':20261121,'trial_budget':48,'startup_trials':16,'batch_size':4,'imported_observations':imports}
save(WORK/'protocols/search.json',config)
(WORK/'src/strategy.py').write_bytes((OLD/'src/strategy.py').read_bytes())
plan = '''# 新授权第1轮：三族联合扩域

阶段三，目标为原六门约束下提高NAR。承接PROTOTYPES/3；相同入场、3日成交参考与5日持有上限。

主要问题：原参与配置q接近下界、阈值t接近下界、过渡半宽h接近上界，扩大这些边界并联合优化仓位与ATR退出，是否可形成更有余量的达标区域？三族各48次提议，硬退出5维、两渐进族6维。weak[.15,.55]、q[.15,.85]、t[.75,1.5]、h[.05,.65]、k[1.8,3.2]、w[.1,1.25]。h<1、q和weak在[0,1]、最小k-w/2>0，保持参与单调与正减仓起点。边界是探索域，后续按贴边改善线索决定扩展。硬退出的w无效，保持原值并剔除搜索轴。

优先使用现有Optuna4.9.0约束多变量TPE，独立种子20261121/22/23，各16条启动观察（包含已核验导入观察）、constant_liar=True，无剪枝；每族4提议，所有族完成当前反馈后进入下一批。12账户进程各1原生线程，同一TDR会话共享输入与买持。单协调进程InMemoryStorage，实际导入、ask/result/tell及检查点留证；固定反馈顺序重建。导入EX046同源码、同固定参数、域内观察，排除将复算的原中心，分别记录导入和新提议数。

首先精确复算C0798/C0801/C0804控制的逐柱、逐日、目标与成交经济路径。完整账户由TDR公共evaluate_many产生。所有账户核对身份、时序、现金与整数成交。独立业务重建选每族控制、六门达标最高NAR（无合格则约束缺口最小诊断）、最低Calmar及全局最大MDD，去重审计。

主要比较为各族达标数量、最高NAR、对应MDD与Calmar、旧域内外分布和边界位置。六门后NAR排序保持；敏感性和宽度用于后续问题选择，不加入新评分或新门槛。保留全部达标与负面配置，统计新提议、精确复用、导入、实际账户分别计数。

结果若显示扩域获益且有连续区域，则下一轮优先检验参数交互与开发性扰动；若改善集中在窄ATR/近零退出宽度，检查集中退出是否重现；若无增益，缩回有证据区域并对比原因。局部诊断仅用于阶段三开发，完整正式邻域及压力验收归阶段四。已见历史不恢复独立性，最终前瞻样本未启用。
'''
(WORK/'protocols/plan.md').write_bytes(plan.encode())
budget = {'authorization_decision':'S019-STAGE3-CONTINUOUS-20261111','authorized_rounds':10,
    'used_rounds':0,'remaining_rounds':10,'candidate_accounts':0,'benchmark_accounts':0,'rounds':[]}
intent.update(stage='STAGE_THREE',continuous_stage3_status='ROUND_PREPARING',continuous_stage3_budget=budget,
    continuous_stage3_decision=decision.to_dict(),active_experiment=exp.to_dict(),
    active_round_budget={'round':1,'allocated_rounds':10,'remaining_after_completion':9},
    next_action='三族同预算Optuna联合扩域，逐轮复核硬门、边界与敏感性线索。')
update_research_intent(repo,batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',
    reason='按用户明确批准进入阶段三；新10轮独立记账，原历史额度保留。')
print('STAGE_THREE_OPENED',WORK.name,'budget 0/10','imports', {k:len(v) for k,v in imports.items()})
