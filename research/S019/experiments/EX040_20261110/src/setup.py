"""Open the authorized return to center-target optimization."""
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, create_research_context, create_experiment,
    ExperimentRequest, get_research_overview, publish_evidence, record_research_decision,
    update_research_intent, ResearchIntentUpdate)
from dataflows import ProviderConfig
from strategy_manager import CandidateEvidence
from strategy_manager import freeze_contracts as f

ROOT=Path.cwd()
BATCH=ROOT/'research/S019'
WORK=BATCH/'experiments/EX040_20261110'

def read(path):
    return json.loads(path.read_bytes())

def save(path,value):
    path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())

repo=RepositoryContext.discover(ROOT)
batch=d.ResearchBatchRef('S019')
ctx=create_research_context(repo,batch,providers=ProviderConfig(bindings={},equity_bindings={}))
assert not WORK.exists()
intent=read(ROOT/'research/registrations/S019/family.json')['research_intent']
assert intent['joint_search_budget']['remaining_rounds']==7
overview=get_research_overview(repo,batch).to_dict()
exp=create_experiment(ctx,ExperimentRequest('回到中心硬门：C0300四维联合优化',
    '复用自检暴露的中心达标组合，联合优化仓位、成交参与阈值和ATR退出，争取提高原NAR与Calmar达标余量。',date(2026,11,10)))
assert exp.resolve(ROOT)==WORK
(WORK/'src/setup.py').write_bytes(Path(__file__).read_bytes())
save(WORK/'others/opening_overview.json',overview)
old=BATCH/'experiments/EX039_20261110'
source=read(old/'others/account_results.json')
assert source['status']=='COMPLETE'
points=[(key,row) for key,row in source['accounts'].items() if row['parent']=='C0224' and row['label']!='STRESS']
assert len(points)==80
eligible=sorted([row for _,row in points if row['candidate']['eligible']],key=lambda r:r['candidate']['nar'],reverse=True)
assert len(eligible)==9 and eligible[0]['candidate_id']=='C0300'
save(WORK/'others/prior_center_eligible.json',eligible)
base=read(old/'protocols/centers.json')[1]
prior=[{'name':key,**row} for key,row in points]
prior.append({'name':'C0224_CENTER','parent':'C0224','label':'CENTER','candidate_id':'C0224',
    'content_hash':base['content_hash'],'parameters':json.loads(base['definition']['parameters_json']),
    'definition':base['definition'],'account_ref':base['account_ref'],'candidate':base['candidate']})
save(WORK/'protocols/prior_observations.json',prior)
parent=BATCH/'experiments/EX038_20261110'
config=read(parent/'protocols/config.json')
config.update(round=4,candidates=[],controls=[
    'research/S019/experiments/EX039_20261110/others/C0224_P046_account.json',
    'research/S019/experiments/EX038_20261110/others/trial026_account.json',
    'research/S019/experiments/EX036_20261110/others/trial033_account.json'])
save(WORK/'protocols/config.json',config)
design=read(parent/'protocols/search.json')
design.update(parent='C0300',round=4,candidate_start=334,seed=20261114,center=eligible[0]['parameters'],
    center_control=config['controls'][0],trial_budget=48,startup_trials=16,batch_size=4,
    space={'weak_fraction':{'kind':'float','low':.20,'high':.60,'step':.005},
           'trail_atr':{'kind':'float','low':2.16,'high':2.64,'step':.01},
           'participation_threshold':{'kind':'float','low':1.,'high':1.5,'step':.0125},
           'quiet_fraction':{'kind':'float','low':.35,'high':.75,'step':.0025}},
    prior_observations=81,prior_path='protocols/prior_observations.json',
    fixed_parameters={'down_days':1,'hold_days':5,'participation_days':3},
    comparison_controls=config['controls'],storage='InMemoryStorage; imported observations and deterministic JSON checkpoints')
save(WORK/'protocols/search.json',design)
for name in ('strategy.py','semantic_audit.py'):
    (WORK/'src'/name).write_bytes((parent/'src'/name).read_bytes())
authorization='''# 恢复阶段三的实际授权

用户在阶段四完成后先讨论ATR敏感性，随后要求暂停。暂停期间新增实验0轮，7轮额度完整保留。
用户最新指令：“既然两个候选都没通过自检，那请你回过头头继续优化硬门指标”。据此恢复阶段三，以提高实际账户绩效满足原硬门为目标。NAR≥55%、Calmar≥5、原MDD和双频率目标保持。
沿用S019-JOINT-20261110的10轮总额度；前三轮已用，本轮为第4轮，完成后剩余6轮。沿用当前研究分支及MANDATE/2已见样本，阶段四原失败交付保留；费用压力门槛在此前讨论后尚无修改指令，继续保留原约定。
'''
(WORK/'protocols/authorization.md').write_bytes(authorization.encode())
approval=publish_evidence(ctx,d.MaterialEvidenceWrite(exp,'resume-center-target-optimization',authorization.encode(),'text/markdown','md'))
receipt=BATCH/'deliveries/ASSESSMENT/1/receipt.json'
decision=record_research_decision(repo,f.ResearchDecision('S019-RESUME-CENTER-20261110','S019',f.DecisionAction.APPROVE,
    f.StageAdvanceSubject(CandidateEvidence(receipt.relative_to(ROOT).as_posix(),sha256(receipt.read_bytes()).hexdigest()),'CANDIDATES'),
    CandidateEvidence(approval.resolve(ROOT).relative_to(ROOT).as_posix(),approval.sha256),
    '用户在暂停后明确要求回头继续优化硬门指标，恢复阶段三并沿用剩余7轮额度，原目标保持。'))
save(WORK/'others/authorization.json',{'approval':approval.to_dict(),'decision':decision.to_dict()})
plan='''# C0300四维联合优化：事前方案

阶段三，已授权10轮中的第4轮。先满足全部原中心硬门，再按未舍入NAR降序。目标、数据、执行合同保持；方案承接用户恢复指令及EX039全部负面证据。

EX039的C0224邻域有9个点通过全部中心硬门，其中C0300为NAR68.7761%、MDD13.5740%、Calmar5.066744。它们此前只承担自检点角色，本轮在用户恢复优化后纳入搜索证据与中心达标交接。原C0224的完整邻域53.75%通过率和两旧中心自检失败结论保持。

固定下跌1日、持有5日、成交参与跨度3日及完整策略结构；联合搜索弱势仓位[0.20,0.60]步长0.005、ATR倍数[2.16,2.64]步长0.01、成交参与阈值[1.0,1.5]步长0.0125、低参与仓位[0.35,0.75]步长0.0025。域覆盖已见中心及上下5%扰动，允许阈值与仓位更宽协作；搜索网格只控制提议精度，不改变参数真实连续业务域，也不缩减未来正式邻域。

优先使用Optuna4.9.0多变量约束TPE，导入80个同结构邻域及C0224中心共81个历史完整观察；逐项核对源码、参数、账户引用及原中心指标。随后固定48次新提议，seed20261114，每4个一批按固定顺序反馈，4个账户worker各1原生线程，InMemoryStorage加JSON检查点，无剪枝。首个新提议固定C0300并重新回放核对中心经济路径；其他精确重复尽量复用已核验账户。历史观察与本轮提议、实际新增账户分开统计。

约束为NAR≥55%、Calmar≥5、日末MDD≤25%且≤同费用买持80%、滚动60日闭合中位数≥6、至少3笔覆盖率≥90%。不把自检条件改成优化评分，不因本轮达标而宣称通过阶段四。搜索目标仍为约束下最大化NAR，关注达标配置数量、ATR位置、余量及收益回撤取舍；命中边界或改善集中在单一退出阈值时披露并据证据决定后续轮次。

2021预热，2022-01-03至2026-10-30连续已见历史，HFQ整数单位，10万美元，每侧0.1%费用，现有买限价与卖市价合同。历史数据和完整账户经公共TDR/DFLS复用；pandas/NumPy用于明确的汇总与路径对齐。预计最多48策略加1共享买持，约20—30分钟；正式自检另经阶段授权。

完成48提议后核对全部中心达标配置并按NAR排序；登记与交接覆盖9个已见达标点及本轮所有达标配置。至少对原中心经济等价、最高NAR、最高Calmar及最差Calmar新账户作业务核验，保留全部失败。先达成阶段三中心目标后提交具体候选及完整比较，请用户决定后续自检范围，余下额度保留。
'''
(WORK/'protocols/plan.md').write_bytes(plan.encode())
intent.update(stage='STAGE_THREE',center_optimization_decision=decision.to_dict(),
    joint_search_status='ROUND_FOUR_IN_PROGRESS',active_experiment=exp.to_dict(),
    active_round_budget={'round':4,'trial_budget':48,'remaining_after_completion':6},
    next_action='复用81个同结构观察，执行C0300四维联合搜索，优先达到原中心硬门并提高NAR。')
update_research_intent(repo,batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',reason='用户明确恢复中心硬门优化。')
print('EX040_READY',flush=True)
