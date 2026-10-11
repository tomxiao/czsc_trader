"""Before-real-data prospective EX083 attribution definition."""
from pathlib import Path
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp'))
import s013_clock_driver as d

checks = d.read(d.WORK / 'focused_checks.json')
assert checks['status'] == 'PASS' and checks['real_inputs'] == 0
for name, expected in checks['files'].items():
    assert d.digest(d.WORK / name) == expected
p82 = ROOT / 'research/S013/experiments/EX082_20261012/protocols'
assert d.read(p82 / 'delivery_validation.json')['status'] == 'PASS'
previous = d.read(p82 / 'plan.json')
refs82 = d.read(p82 / 'closeout_references.json')
kernel = d.base.load('clock_freeze_definition', d.WORK / 'kernel.py')
sources = ['.tmp/s013-calendar-clock/' + name for name in ('kernel.py', 'audit.py', 'focused_checks.py', 'focused_checks.json')]
sources += ['.tmp/s013_clock_driver.py', '.tmp/s013_clock_freeze.py', '.tmp/s013_confirm_execution.py',
            'research/S013/experiments/EX058_20261011/src/common.py']
plan = {
    'status': 'ROOT_FROZEN_BEFORE_REAL_STUDY', 'role': 'RSCH', 'stage': 2, 'quota_slot': 5,
    'authorization': '原自主研究及EX079–EX088十轮额度；每轮保存正式report副本',
    'original_four_hard_gates_changed': False, 'new_economic_hard_gates': False,
    'question': '日期表达的有利非重叠代理是否稳定跨预设入场时钟，是否集中在少数净盈利机会？',
    'basis': 'EX082日期单独固定贪心代理2022/2023为正、全窗42.04%，同时重叠2023均值负；14项＋日期全窗代理51.33%，仍2022/23负。这种差异需要把时钟抽样和少数大赚机会归因，而非因为MSE无增量就否定可执行价值，或直接宣布时间信息有效。',
    'strongest_prior_counter': 'EX082全部十个诊断区间跨零，日期净利润余量薄、日期贪心2026代理−13.67%；14项＋日期可能依赖2024大赚；原EX080实际账户只过频率。未新增独立样本，不能把代理收益当账户硬门。',
    'fixed_design': {
        'forecasts': 'EX082已审计六列原预测逐字节读取，不改特征/参数/预测/阈值，不重拟合或重新选择模型。原均值/确认/14项/日期/确认＋日期/14项＋日期全保留。',
        'axis': '原1635T完整轴，2020无预测；原h4净OPEN标签及成熟结束日。',
        'clocks': list(kernel.CLOCKS),
        'greedy': '原空仓后正预测入场，T+4到期优先，同T不重入，保留缺未来truth尾部意图；与EX082全记录精确复现。',
        'phase_controls': '对原完整T位置i，固定i%5=k,k=0..4全部组；仅该组有正预测才接受入场。相邻候选间隔5，4日持有＋次T才能重入，相同期限与机会互斥。全轴因果计数，不每年重新起点，不由未来标签/未来交易日选相位。不是初次等待1–4天后恢复原贪心，也不是参数5%自检；不挑最好组。',
        'new_schedules': '六个模型×六个时钟=36个OPEN代理，无原生账户/实际闭合笔数；原greedy五组已知结果只用于身份对照，新期望不预判。',
        'attribution': '每模型每时钟完整池及2020–2026各年，入场年归组的成熟代理数量/均值/几何复合、正盈利数量、最佳一笔和topceil10%正盈利之和/全部正盈利、反事实去最佳/去top10%正盈利后其余（含亏损）复合，收益相同按原T位置早者排序。少于20均值不可得，但非空复合描述保留数量；空组复合不可得。',
        'concentration_not_five_check': '等研究单位OPEN净价格代理，非真实账户闭合利润贡献，省略交易为事后归因而非可执行规则；不改交易门、不计为正式五项策略自检。',
        'selection_partition': '每时钟正预测集合=接受+跳过，成熟接受/跳过均值与差异；跳过仍是有正预测的重叠机会，不当可同时成交的账户。',
        'bootstrap': '共享完整1635T轴500重叠40日块seed13，固定预测与入场掩码，不重拟合、不重放策略。每量原始/重抽样至少20有效；至少400有效才报告LINEAR95CI，否则不可得，九个事前数量全部500记录留存。条件性区间未校正历史研究与多重比较；最差相位均值是五组诊断不是32点Q10。',
        'quantities': list(kernel.QUANTITIES),
        'primary': '原日期贪心与五组固定机会时钟的全窗/2022/2023/2026利润符号及余量、正盈利集中和删项变化；三个原嵌套表达全部呈现。不按MSE/CI单项作经济否决。',
    },
    'scope': previous['scope'],
    'selection_history': '根据EX082不同代理表现适应性归因，仍同一已见开发池；无需新信息组件/训练，不因一组好结果补扫起点或频率，不把同样的重叠样本称作独立复现。',
    'stopping': '本轮0账户。若有利代理对五组时钟不稳定或靠少量机会，交付反证、不将其直接升级为账户方案；若利润余量可解释且维持下跌年机会，则后续额度再考虑严格原生账户。事后删赢家不作为新硬门，不由此宣称所有时间机制无效。',
    'source_files': {name: d.digest(ROOT / name) for name in sources},
    'input_references': {'forecasts.csv': refs82['forecasts.csv'], 'labels.csv': previous['input_references']['labels.csv'],
                         'prices.csv': previous['input_references']['prices.csv'], 'prior_statistics.json': refs82['statistics.json'],
                         'prior_verification.json': refs82['verification.json'], 'prior_review.json': refs82['root_review.json'],
                         'prior_budget.json': refs82['budget_receipt.json'], 'prior_plan.json': refs82['plan.json']},
    'continuation_budget_reference': previous['continuation_budget_reference'], 'predecessors': previous['predecessors'],
    'report_copy': previous['report_copy'], 'resources': {'new_models': 0, 'new_accounts': 0, 'provider_calls': 0,
                                                       'schedules': 36, 'bootstrap': 500}, 'objective_achieved': False,
}
d.check(plan)
d.write(d.WORK / 'prospective.json', plan)
print({'status': plan['status'], 'slot': 5, 'new_models': 0, 'new_accounts': 0})
