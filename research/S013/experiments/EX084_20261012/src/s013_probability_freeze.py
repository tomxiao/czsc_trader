"""Prospective EX084 fixed net profitability responsibility contrast."""
from pathlib import Path
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp'))
import s013_probability_driver as d

checks = d.read(d.WORK / 'focused_checks.json')
assert checks['status'] == 'PASS' and checks['real_inputs'] == 0
for name, expected in checks['files'].items():
    assert d.digest(d.WORK / name) == expected
p83 = ROOT / 'research/S013/experiments/EX083_20261012/protocols'
assert d.read(p83 / 'delivery_validation.json')['status'] == 'PASS'
previous = d.read(p83 / 'plan.json')
refs83 = d.read(p83 / 'closeout_references.json')
p79 = ROOT / 'research/S013/experiments/EX079_20261012/protocols'
refs79 = d.read(p79 / 'result_references.json')
refs66 = d.read(ROOT / 'research/S013/experiments/EX066_20261011/protocols/result_references.json')
kernel = d.base.load('probability_freeze_definition', d.WORK / 'kernel.py')
clock = 'research/S013/experiments/EX083_20261012/src/kernel.py'
clock_audit = 'research/S013/experiments/EX083_20261012/src/audit.py'
sources = ['.tmp/s013-profit-probability/' + name for name in ('kernel.py', 'audit.py', 'focused_checks.py', 'focused_checks.json')]
sources += ['.tmp/s013_probability_driver.py', '.tmp/s013_probability_freeze.py', '.tmp/s013_confirm_execution.py',
            'research/S013/experiments/EX058_20261011/src/common.py', clock, clock_audit]
plan = {
    'status': 'ROOT_FROZEN_BEFORE_REAL_STUDY', 'role': 'RSCH', 'stage': 2, 'quota_slot': 6,
    'authorization': '原自主研究及EX079–EX088十轮额度；每轮保存正式report副本',
    'original_four_hard_gates_changed': False, 'new_economic_hard_gates': False,
    'question': '原确认或14项价量是否能识别扣费后盈利概率，而非只有不稳定的收益均值预测？',
    'basis': 'EX083说明原均值/日期代理收益受机会时钟与少量大盈利影响。直接预测收益均值失败不等于盈利事件概率没有信息；用自然的net return>0事件作为不同职责，暂时剥离收益幅度对训练损失的影响，再以成熟历史平均盈亏恢复经济选择。',
    'strongest_prior_counter': '原14均值联合没有优势，原确认独立账户只过频率，日期与方向重表达均缺稳定增量；同一开发池已长期反复使用。只提高胜率可能错失大涨或选中小赢大亏，历史平均盈亏可随状态/年份变化，分类器不是经济目标替代或效果保证。',
    'fixed_design': {
        'scope_rows': '原14共同完整行、1635T、原h4净HFQ OPEN标签，原2020起成熟年度训练；不使用日期表达。',
        'probability_target': 'binary=1 if原双侧0.1%扣费四日return_4>0 else0；零归非盈利，阈值0为经济盈亏分界，不扫描。',
        'models': list(kernel.PROBABILITIES),
        'classifier': '原确认单列与原14列分别年度训练CDF中点秩-.5，二元logistic加固定10的L2斜率惩罚、截距不惩罚；总logloss而非按样本归一。Newton最大100迭代，最大梯度1e-10，固定Armijo/40回溯，仅数值收敛不作科学优化，失败明确拒绝，无one-class兜底。',
        'training': '2020<=Tyear<testyear、h4label_end严格早于本测试年首T、所有14有限、target有限；至少40样本且正/非正各至少20才可拟合/估计幅度，否则明确不可得。没有未来全年测试样本数门。',
        'economic_mapping': '同年度训练估计gain=mean(y>0)、loss=mean(y<=0)、prior=nwin/n；每个概率p映射net=p*gain+(1-p)*loss，只在net>0选择。盈亏平衡q=-loss/(gain-loss)仅由成熟训练决定，不以.5或事后收益择阈值。恒定prior映射必须数值等于原training_mean。不条件训练盈亏幅度，不新增第三类模型。',
        'controls': '原training_mean/confirmation_only/original14_joint全部预测精确复用；相同特征但职责改变为两新概率模型，2021–2026最多12次年度拟合。报告Brier及logloss相对恒定历史盈利概率、净期望相对原均值表达，不能以概率指标替代原硬门。',
        'forecast': '2020无预测、未来truth缺失的尾部只要T有特征仍预测；测试标签只事后评价，严格正选择，不按未来数据决定模型或训练样本数。',
        'reports': '全部年份2020–26、原T五组、全部池：概率预测/真实比例与两个proper损失、净期望正选择的净均值/命中误报、成熟训练盈亏幅度及q、两新表达及三个原对照全保留，不挑年或起点。',
        'clocks': '精确复用已冻结EX083六种机会时钟及独立标量归因，实现原贪心＋i%5所有五组，五个net表达共30代理；旧三个原对照全部时钟结果必须逐字段精确相同。不是原生账户或标准32点自检，不选择最好组。',
        'bootstrap': '共享原1635T轴500次重叠40日块seed13，固定预测不重拟合，原始/重抽样至少20、至少400有效才报LINEAR95CI，全500×10记录保留；区间条件性未校正历史选择及多重比较。',
        'quantities': list(kernel.QUANTITIES),
    },
    'scope': previous['scope'], 'selection_history': '同已见开发池，根据已披露均值/时钟反证更改预测职责；没有封存新样本、不称独立复现，不扫描分类损失/惩罚/阈值/期限/特征子集或相位。',
    'stopping': '本轮组件0账户；如果概率诊断改善仍不能带来净收益余量/下跌年支持，完整交付反证、不以更高胜率推进账户。只有新的经济机制依据才在后续额度考虑原生账户。各项诊断均报告，不新增经济否决门。',
    'source_files': {name: d.digest(ROOT / name) for name in sources},
    'input_references': {'features.csv': refs79['features.csv'], 'labels.csv': refs79['labels.csv'], 'prices.csv': refs66['prices.csv'],
                         'original_return_scores.json': refs79['statistics.json'], 'prior_clock_statistics.json': refs83['statistics.json'],
                         'prior_verification.json': refs83['verification.json'], 'prior_review.json': refs83['root_review.json'],
                         'prior_budget.json': refs83['budget_receipt.json']},
    'clock_source': clock, 'clock_audit_source': clock_audit,
    'continuation_budget_reference': previous['continuation_budget_reference'], 'predecessors': previous['predecessors'], 'report_copy': previous['report_copy'],
    'resources': {'new_annual_models_maximum': 12, 'new_accounts': 0, 'provider_calls': 0, 'schedules': 30, 'bootstrap': 500},
    'objective_achieved': False,
}
d.check(plan)
d.write(d.WORK / 'prospective.json', plan)
print({'status': plan['status'], 'slot': 6, 'annual_models_maximum': 12, 'new_accounts': 0})
