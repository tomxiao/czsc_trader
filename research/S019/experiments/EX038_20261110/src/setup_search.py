"""Prepare the approved third round through public research APIs."""
from datetime import date
import json
from pathlib import Path
from czsc_trader import research_tools as d
from czsc_trader.application import (
    RepositoryContext, create_research_context, create_experiment, ExperimentRequest,
    get_research_overview, update_research_intent, ResearchIntentUpdate,
)
from dataflows import ProviderConfig

root = Path.cwd()
batch = root / 'research/S019'
experiments = batch / 'experiments'
def read(path):
    return json.loads(path.read_bytes())
def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode())

repo = RepositoryContext.discover(root)
ref = d.ResearchBatchRef('S019')
context = create_research_context(repo, ref, providers=ProviderConfig(bindings={}, equity_bindings={}))
overview = get_research_overview(repo, ref).to_dict()
assert not (experiments / 'EX038_20261110').exists()
exp = create_experiment(context, ExperimentRequest('C0196短跨度与风险参数联合扩展',
    '缩短成交参与跨度并联合调整风险参数，能否达到NAR55%和Calmar5且保留交易频率？', date(2026,11,10)))
work = exp.resolve(root)
assert work.name == 'EX038_20261110'
parent = experiments / 'EX037_20261110'
center = read(parent / 'others/search_review.json')['frontier']['parameters']
assert read(parent / 'others/search_review.json')['frontier']['id'] == 'C0196'
config = read(parent / 'protocols/config.json')
controls = ['research/S019/experiments/EX037_20261110/others/trial046_account.json',
    'research/S019/experiments/EX036_20261110/others/trial033_account.json',
    'research/S019/experiments/EX035_20261110/others/threshold110_account.json']
config.update(round=3, candidates=[], controls=controls)
space = {
    'weak_fraction': {'kind':'float','low':.25,'high':.75,'step':.05},
    'trail_atr': {'kind':'float','low':2.,'high':3.5,'step':.1},
    'participation_days': {'kind':'int','low':3,'high':20,'step':1},
    'participation_threshold': {'kind':'float','low':.8,'high':1.5,'step':.05},
    'quiet_fraction': {'kind':'float','low':.2,'high':.6,'step':.05},
}
design = read(parent / 'protocols/search.json')
design.update(parent='C0196',round=3,candidate_start=198,seed=20261113,space=space,
    center=center,center_control=controls[0],storage='InMemoryStorage; JSON proposal and account checkpoints',
    fixed_parameters={'down_days':1,'hold_days':5},comparison_controls=controls)
save(work / 'protocols/config.json',config)
save(work / 'protocols/search.json',design)
save(work / 'others/opening_overview.json',overview)
for name, source in {
    'strategy.py': parent / 'src/strategy.py',
    'joint_search.py': experiments / 'EX036_20261110/src/joint_search.py',
    'review_search.py': experiments / 'EX036_20261110/src/review_search.py',
    'compare_parent.py': experiments / 'EX036_20261110/src/compare_parent.py',
    'semantic_audit.py': parent / 'src/semantic_audit.py',
    'search_importance.py': parent / 'src/search_importance.py',
}.items():
    (work / 'src' / name).write_bytes(source.read_bytes())
(work / 'src/setup_search.py').write_bytes(Path(__file__).read_bytes())
plan = '''# C0196短跨度联合扩展：事前方案

2026-11-10，阶段三；新增10轮授权第3轮，前两轮已用2轮，本轮完成后剩余7轮。
用户对“优先研究C0196，扩展短成交参与跨度并联合搜索仓位、阈值和ATR退出，保留C0135对照，保持原目标”的建议明确回复“同意”。沿用S019-JOINT-20261110授权及CANDIDATES/3结论，阶段四尚待批准。

问题是10日跨度下边界是否提示更短近期成交状态有用，以及它与缩仓强度和退出距离的配合能否改善完整账户。竞争解释为短跨度更及时地识别交易活跃变化，或仅对少数历史交易阈值有利。观察达标配置分布、年度路径、实际交易变化与反例，不凭最佳点单独决定稳健性。

固定下跌1日、持有5日和既有策略结构，联合搜索五项：季度弱势仓位0.25—0.75步长0.05；ATR距离2.0—3.5步长0.1；成交参与跨度3—20交易日步长1；参与阈值0.8—1.5步长0.05；低参与仓位0.2—0.6步长0.05。3日保留多观察中位数，20日覆盖原C0101参考；范围由本轮前的研究判断确定。短跨度阈值噪声及下边界影响如实报告。

Optuna4.9.0多变量约束TPE，固定seed=20261113、48次提议，16次启动包含C0196中心等价核验，随后32次自适应。每批4个完整账户，按trial顺序反馈，无剪枝、无按分数提前停。共享成熟搜索编排，不修改策略金融规则。InMemoryStorage与JSON检查点沿用前两轮；恢复按固定种子重建并验证提议，复用精确账户。4个TDR worker，每个原生线程数1。

目标最大化NAR，并同时约束NAR≥55%、Calmar≥5、MDD≤25%且≤同窗买持80%、60日闭合中位数≥6及至少90%窗口闭合≥3。按未舍入值检验，全部中心达标后按NAR降序。正式≥80%参数扰动、费用压力及阶段四五项自检另按授权执行。

沿用2021预热、2022-01-03至2026-10-30已见开发历史、HFQ整数单位、100000美元、每侧0.1%费用及既有买卖合同。复用C0196、C0101及C0135完整账户作对照；首项验证中心经济路径逐条一致，C0135用于收益与风险取舍参照。不同结构的账户对照按各自实现解释。

48次提议完成后收口；若出现中心达标配置，核验、登记并呈现阶段三成果，提出正式自检建议。若仍未达标，结合参数跨度分布、路径反例和改善幅度决定后续投入。保留全部失败与负面结果，后续研究继续使用剩余额度。
'''
(work / 'protocols/plan.md').write_bytes(plan.encode())
(work / 'report.md').write_bytes('# C0196短跨度联合扩展\n\nStatus: IN_PROGRESS\n\n事前设计见[方案](protocols/plan.md)。\n'.encode())
intent = read(root / 'research/registrations/S019/family.json')['research_intent']
intent.update(joint_search_status='ROUND_THREE_IN_PROGRESS',next_action='完成C0196五维短跨度联合搜索48次提议；原目标及样本保持。',
    active_experiment=exp.to_dict(),active_round_budget={'round':3,'trial_budget':48,'remaining_after_completion':7})
update_research_intent(repo,ref,ResearchIntentUpdate(research_intent=intent),actor='RSCH',
    reason='用户同意C0196短跨度联合扩展建议，使用现有授权第3轮。')
print('EX038_READY',flush=True)
