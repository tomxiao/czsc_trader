from pathlib import Path
import json
from hashlib import sha256
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,ExecutionResources,MaterialEvidenceWrite

root=Path.cwd(); ex=ExperimentRef('S015','EX067_20261024'); home=ex.resolve(root)
assert (home/'experiment.json').exists()
ctx=create_research_context(RepositoryContext.discover(root),ResearchBatchRef('S015'),resources=ExecutionResources(1,1,13))
plan={
 'authorization':'同意。授权20轮实验额度，请你根据新的指南自主执行并完成阶段二',
 'stage':2,'maximum_rounds':20,'round':1,'first_experiment':ex.to_dict(),
 'goal':'由有依据组件构成符合金融逻辑的完整策略原型；允许有充分依据的负面交付，不以预算耗尽或数值过线替代研究判断。',
 'mandate':'MANDATE/5；原434/415窗口、标的、数据、经济及频率目标、资金周期合同不变。当前授权更新为阶段二20轮，不跨阶段。',
 'sequence':['1-2轮持有状态、修复语义与机会代价诊断','至多两条可区分机制的最小完整原型及必要账户对照','组件删项、结构反证、代表定义与时间分布检查','必要费用压力和阶段二原型交付；证据不支持时停止或转向已声明备选机制'],
 'reserve':'20轮上限不是必须用完；每轮按一个研究问题和事前主要对照计数，技术修正不新计轮。剩余额度不自动跨阶段。',
 'resources':{'max_account_processes':8,'native_threads_per_worker':1,'seed':13},
 'questions':[
  '实际利润是价格回升修复折让、中心继续抬升，还是时间/再许可造成的队列差异？',
  '移动中心修复中有多少价格未回到入场信号固定中心？',
  '修复后与背景失效后的下一可执行时段收益如何，入场亏损有多少最终恢复？'],
 'predeclared_labels':{
  'background':'signal-day center_gain>0 vs <=0; mean3 primary, median3 and daily_mid3 representative alternatives; existing lookback only for comparability, not economic truth',
  'dynamic_repair':'signal-day p>=m',
  'anchored_repair':'signal-day p>=center_at_intent_entry; fixed entry reference, not moving target',
  'holding_account':'Next execution-session equity increment grouped by prior completed signal state; distinguish entry days from carried inventory; includes actual fills, fees and terminal marking; descriptive accounting, not causal attribution.',
  'opportunities':'Reuse EX026 authenticated h1/h3/h5 standalone limit-entry event labels; overlapping opportunities are not a portfolio or independent samples. h1 primary for next holding decision; longer horizons diagnostic.',
  'time':'all,2025,2026; remove largest positive/negative contributions only as concentration diagnosis, not repaired equity curve or new strategy.'},
 'support_and_refutation':{
  'repair':'Price-return contribution mainly before anchored repair; remaining return weak after repair and adverse after background failure. Moving-center repair without price recovery weakens old repair semantics.',
  'continuation':'Positive background after repair retains net opportunities; immediate repair exits truncate later gains. State-based continuation then deserves complete-account test.',
  'queue':'Improvement concentrated in isolated dates with no repeatable state distinction; stop tuning the old family.'},
 'controls':['EX061:C6102','EX061:C6105','EX059:C5919','EX059:C5920','EX059:C5921','EX059:C5922'],
 'unknowns':'Data repeatedly selected; no independent validation. Source price centers do not identify fair value, fund flows or participant motives. No new economic hard gates.',
 'next':'Follow evidence with prospectively defined entry-hold-exit logic; do not repeat failed repair/guard/hold grids without a different observable question.',
 'source_hashes':{s:sha256((root/s).read_bytes()).hexdigest() for s in ['research/RSCH_AGENT.md','research/S015/experiments/EX051_20261024/src/study.py','research/S015/experiments/EX061_20261024/src/strategy_runtime/strategies/price_process.py','research/S015/experiments/EX061_20261024/src/account_audit.py']},
}
path=home/'protocols/plan.json'; assert not path.exists()
path.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
refs={}
for p in (path,home/'src/diagnose.py',home/'src/prepare.py'):
 r=publish_evidence(ctx,MaterialEvidenceWrite(ex,p.stem,p.read_bytes(),'application/json' if p.suffix=='.json' else 'text/x-python',p.suffix[1:]));refs[str(p.relative_to(root))]=r.to_dict()
(home/'others/protocol_refs.json').write_text(json.dumps(refs,indent=2)+'\n',encoding='utf-8')
print('EX067 protocol published')
