"""Open the approved six-round mechanism research allocation."""
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

ROOT = Path.cwd()
BATCH = ROOT / 'research/S019'
WORK = BATCH / 'experiments/EX042_20261110'

def read(path):
    return json.loads(path.read_bytes())

def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode())

assert not WORK.exists(), 'Inspect current experiment before retry'
repo = RepositoryContext.discover(ROOT)
batch = d.ResearchBatchRef('S019')
ctx = create_research_context(repo, batch, providers=ProviderConfig(bindings={}, equity_bindings={}))
intent = read(ROOT / 'research/registrations/S019/family.json')['research_intent']
assert intent['joint_search_budget']['used_rounds'] == 4
assert intent['joint_search_budget']['remaining_rounds'] == 6
overview = get_research_overview(repo, batch).to_dict()
exp = create_experiment(ctx, ExperimentRequest('退出机制辨别：硬触线、确认与连续减仓',
    '固定C0355入场与参与仓位，区分ATR敏感性来自触线全退、时点还是波动尺度，保留全部反例。', date(2026,11,10)))
assert exp.resolve(ROOT) == WORK
(WORK / 'src/setup.py').write_bytes(Path(__file__).read_bytes())
save(WORK / 'others/opening_overview.json', overview)
authorization = '''# 恢复阶段二的用户授权

RSCH在EX041正式完成后建议：“回阶段二，以C0355为对照，优先研究ATR退出机制与参与阈值引发的仓位跳变，保持原硬门目标。是否批准使用剩余6轮额度推进？”用户明确答复：“同意，请继续”。

据此自主推进剩余6轮范围内的机制研究，沿用当前研究分支及此前批准的12账户进程、各1原生线程。原总额度10轮已用4轮，EX042为总第5轮、本次授权第1轮，完成后剩5轮。后续轮次根据结果形成事前问题与对照，避免重复或为用完额度而追加。原阶段四失败证据及其余18个未检候选保持；新阶段交付与后续阶段批准分别处理。

原中心NAR≥55%、Calmar≥5、原MDD及双频率目标保持；邻域80%及原费用压力标准保持。数据继续使用2021预热、2022-01-03至2026-10-30已见历史；生产、冻结和新增数据无本次变更。
'''
(WORK / 'protocols/authorization.md').write_bytes(authorization.encode())
approval = publish_evidence(ctx, d.MaterialEvidenceWrite(exp, 'stage-two-six-rounds-authorization', authorization.encode(), 'text/markdown', 'md'))
receipt = BATCH / 'deliveries/ASSESSMENT/2/receipt.json'
decision = record_research_decision(repo, f.ResearchDecision('S019-RESUME-MECHANISMS-20261110', 'S019', f.DecisionAction.APPROVE,
    f.StageAdvanceSubject(CandidateEvidence(receipt.relative_to(ROOT).as_posix(), sha256(receipt.read_bytes()).hexdigest()), 'COMPONENTS'),
    CandidateEvidence(approval.resolve(ROOT).relative_to(ROOT).as_posix(), approval.sha256),
    '用户批准回阶段二，以C0355为对照自主使用剩余6轮研究ATR退出和参与阈值仓位跳变，原目标保持。'))
save(WORK / 'others/authorization.json', {'approval': approval.to_dict(), 'decision': decision.to_dict()})
center = next(x for x in read(BATCH / 'experiments/EX041_20261110/protocols/centers.json') if x['id']=='C0355')
base = json.loads(center['definition']['parameters_json'])
specs = []
def add(label, policy, atr, width=.5, control=None):
    row = {'label': label, 'parameters': {**base, 'exit_policy': policy, 'exit_width': width, 'confirm_bars': 2, 'trail_atr': atr}}
    if control:
        row['control_account'] = control
    specs.append(row)
controls = ['research/S019/experiments/EX041_20261110/others/C0355_P002_account.json',
    'research/S019/experiments/EX041_20261110/others/C0355_center_ref.json',
    'research/S019/experiments/EX041_20261110/others/C0355_P005_account.json']
atrs = [base['trail_atr']*.95, base['trail_atr'], base['trail_atr']*1.05]
for label, atr, control in zip(('low','center','high'), atrs, controls, strict=True):
    add('hard_'+label, 'hard', atr, control=control)
add('time_only', 'none', base['trail_atr'])
for policy in ('confirm', 'daily_close', 'rolling_atr'):
    for label, atr in zip(('low','center','high'), atrs, strict=True):
        add(policy+'_'+label, policy, atr)
for width in (.5, 1.):
    for label, atr in zip(('low','center','high'), atrs, strict=True):
        add(f'ramp{width:g}_'+label, 'ramp', atr, width)
assert len(specs)==19
save(WORK / 'protocols/specs.json', {'base_candidate':'C0355', 'candidate_start':622,
    'round_budget':{'allocated_rounds':6, 'round_index':1, 'total_round':5, 'remaining_after_completion':5},
    'parameter_schema':{'exit_policy':{'type':'string'}, 'exit_width':{'type':'number'}, 'confirm_bars':{'type':'integer'}},
    'specs':specs})
plan = '''# 第5轮／本次第1轮：退出机制事前对照

问题：少量临界价格穿越导致完整清仓，是否使原ATR表达过于依赖阈值？固定C0355入场、参与仓位与5日上限，比较六类有不同金融含义的退出表达。全部评价原中心六门，另报告同结构ATR三档的绩效跨度与交易路径；三档诊断只针对当前问题，完整阶段四另行开展。

1. hard：原触线即退出，ATR取中心2.42与相对上下5%；三条新实现控制必须与原中心/原纯ATR点完整经济路径严格等价。
2. none：取消ATR，保留5日退出，辨别该风控组件整体作用。
3. confirm：连续两个已完成30分钟价格均穿过各自当时跟踪线才退出；检查短时穿越噪声与延迟损失。
4. daily_close：仅每个交易日首个决定使用前日完成收盘判断跟踪退出，最高价参照也仅在该时点更新；5日退出保持。检验日内噪声与更慢响应的取舍。
5. rolling_atr：仍每30分钟硬退出，以最新可得完整14日ATR替代入场锁定ATR，观察波动尺度更新的作用。
6. ramp：以从周期峰值回落的ATR距离z为依据，保留比例clip((k+w/2-z)/w,0,1)，w取0.5或1.0ATR。周期内比例取历史最小值，只减仓、不因价格反弹加回；归零后退出，5日期限保持。该表达将一次全退分散为价格区间上的风险削减，并接受更早减仓与额外成交成本。

除none单点外各表达取同一ATR三档，共19账户。ramp的初始基数为原入场配置，目标继续按当前账户权益表达，整数执行与再平衡沿原合同。每个决定只读已经完成的柱和日线，所有状态以实际持仓周期为准；退出锁存防止待成交时重新开仓。

固定结构机制对照采用明确配对而非自动搜索，以保留组件变化的可解释性；后续需要参数适配的结构比较优先用Optuna同等预算。本轮复用公共TDR/DFLS/SRT/EC/SE完整账户与NumPy基础运算，不重写通用回放或指标计算。12进程、每进程1原生线程，控制三点通过后普通12/4批次，公共会话和检查点。标准每侧费用0.1%，10万美元，HFQ整数单位，原限买市卖合同与统一已见样本保持。

保留依据：比较原六门、收益回撤取舍、ATR三档反应以及实际退出与成本路径，观察改善是否同时覆盖多档而非另造窄峰。否定依据：减仓/确认持续损失收益，风险未改善或延迟扩大损失，且三档敏感性无缓解。机制具有价值但中心不足时如实保留缺口；不以自定义加权分数替代原门槛。预计19策略与1共享买持，按实际记录披露；完成即结算1轮，之后根据结果决定参与仓位表达对照。
'''
(WORK / 'protocols/plan.md').write_bytes(plan.encode())
(WORK / 'report.md').write_bytes('# S019退出机制辨别\n\nStatus: IN_PROGRESS\n'.encode())
intent.update(stage='STAGE_TWO', mechanism_resume_decision=decision.to_dict(),
    mechanism_research_status='ROUND_ONE_PREPARING', active_experiment=exp.to_dict(),
    active_round_budget={'round':5, 'allocated_mechanism_rounds':6, 'mechanism_round':1, 'remaining_after_completion':5},
    next_action='固定C0355入场与仓位，比较硬退出、取消、确认、连续减仓和日线/滚动ATR表达，随后按证据自主安排剩余轮次。')
update_research_intent(repo, batch, ResearchIntentUpdate(research_intent=intent), actor='RSCH', reason='用户明确批准回阶段二使用剩余6轮研究机制。')
print('EX042_CREATED',len(specs),flush=True)
