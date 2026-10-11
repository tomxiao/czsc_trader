"""EX082 prospective definition after synthetic checks and before real study."""
from pathlib import Path
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp'))
import s013_calendar_driver as d

checks = d.read(d.WORK / 'focused_checks.json')
assert checks['status'] == 'PASS' and checks['real_inputs'] == 0
for name, expected in checks['files'].items():
    assert d.digest(d.WORK / name) == expected
p81 = ROOT / 'research/S013/experiments/EX081_20261012/protocols'
assert d.read(p81 / 'delivery_validation.json')['status'] == 'PASS'
previous = d.read(p81 / 'plan.json')
refs81 = d.read(p81 / 'closeout_references.json')
quota = d.read(d.public(refs81['budget_receipt.json']))
assert (quota['started'], quota['completed'], quota['next_allowed']) == (3, 3, 'EX082')
kernel = d.base.load('calendar_freeze_definition', d.WORK / 'kernel.py')
literature = {
    'status': 'PRIMARY_LITERATURE_REVIEWED_BEFORE_REAL_CALENDAR_STATISTICS',
    'title': 'Equity Returns at the Turn of the Month', 'authors': ['John J. McConnell', 'Wei Xu'],
    'year': 2008, 'journal': 'Financial Analysts Journal 64(2),49-64', 'doi': '10.2469/faj.v64.n2.11',
    'abstract_url': 'https://rpc.cfainstitute.org/research/financial-analysts-journal/2008/equity-returns-at-the-turn-of-the-month',
    'author_pdf_url': 'https://business.purdue.edu/faculty/mcconnell/publications/Equity-Returns-at-the-Turn-of-the-Month.pdf',
    'accessed': '2026-10-12', 'paraphrase': '作者在历史股票样本中发现月度交替附近的收益分布异常，并指出成交量及股票基金流量不足以解释它。该结论提供时间结构线索，不证明其成因，更不证明原510500开发池存在可交易的同类效应。',
    'proposal_is_inference': True,
    'difference_from_paper': '论文以月末实际交易日及次月前三交易日定义窄窗口；本轮不复刻该窗口，采用当天已知自然日的一阶平滑月内周期，不使用未来实际交易日历，不择日/调整持有期限。平滑项可能捕捉不到窄效应，失败不能否定所有月内机制。',
    'market_data_from_literature': 0,
}
d.write(d.WORK / 'literature_basis.json', literature)
sources = ['.tmp/s013-calendar-phase/' + name for name in ('kernel.py', 'audit.py', 'focused_checks.py', 'focused_checks.json', 'literature_basis.json')]
sources += ['.tmp/s013_calendar_driver.py', '.tmp/s013_calendar_freeze.py', '.tmp/s013_build_calendar.py',
            '.tmp/s013_confirm_execution.py', 'research/S013/experiments/EX058_20261011/src/common.py']
refs = {k: v for k, v in previous['input_references'].items() if k not in ('prior_budget.json',)}
refs.update({'EX081_review.json': refs81['root_review.json'], 'EX081_verification.json': refs81['verification.json'],
             'prior_budget.json': refs81['budget_receipt.json']})
plan = {
    'status': 'ROOT_FROZEN_BEFORE_REAL_STUDY', 'role': 'RSCH', 'stage': 2, 'quota_slot': 4,
    'authorization': '原自主研究及EX079–EX088十轮额度；后续每个实验保存report副本',
    'original_four_hard_gates_changed': False, 'new_economic_hard_gates': False,
    'question': '决策T已知的自然月内位置，能否对四日净价格机会提供超出原价量信号的增量信息？',
    'basis': '前轮价格方向重表达无效，转向不同信息通道。原14控制项没有自然日期的位置；历史论文提供月内时间结构线索。成因未知，不声称月末资金流入已获证明。先验证原开发池，不能直接搬用外部市场的效果或日期窗口。',
    'strongest_prior_counter': 'EX079确认支持有限且2022/2026净均值负，原14线性联合无优势；EX080真实账户只过频率；EX081确认与方向相加/交互无稳定增量。旧样本长期反复使用、模型复杂度和薄净盈利余量均是主要反证。文献是异地/异期研究，且自然周期与窄交易日窗口不同。',
    'fixed_design': {
        'common_rows': '与EX079/81完全相同原14完整行，1635T 2020-01-02..2026-09-29，不选择有利年份或新数据',
        'calendar': 'phase=(T自然日序号-1)/T所在自然月天数，固定一阶(.5sin(2pi phase),.5cos(2pi phase))；闰年可知，幅度.5固定，仅用T日期，不查看未来交易是否开放',
        'new_models': list(kernel.NEW_MODELS),
        'controls': 'calendar_only对training_mean；confirmation_calendar对原confirmation_only；original14_calendar对原original14_joint。三个旧模型全部原预测精确复用；新模型只增同样两个日期基函数，目的为机制增量对照，非事后挑赢家。',
        'scale': '原价量每列年度成熟训练ECDF中点秩-.5；日期直接固定±.5，不训练日期CDF/相位/尺度；ridge10，截距不惩罚。',
        'label': previous['fixed_design']['label'], 'training': previous['fixed_design']['training'],
        'forecast': previous['fixed_design']['forecast'],
        'reports': '全部年度2020–26、原涨跌/零状态、原位置mod5全五相位，新增自然phase四等分全部组；仅描述，不挑组训练/交易。',
        'primary': '新日期项在三个嵌套对照的后续年度配对误差与正预测净均值增量；完整报告误报、年度尤其2022/2023盈利余量、非重叠代理及训练系数。不以单个MSE或CI作新硬门。',
        'bootstrap': previous['fixed_design']['bootstrap'], 'quantities': list(kernel.QUANTITIES),
        'policy_proxy': previous['fixed_design']['policy_proxy'],
    },
    'scope': '仅原510500.SH已见开发池/HFQ固定锚/无现金分红叠加/原资金费用整手固定1%执行合同；0账户/0provider/0新增市场数据。文献仅机制依据，不引入其数据。',
    'selection_history': '同一已见开发池适应性探索。自然月信息通道未做过本轮统计，引用文献不构成独立样本；固定仅第一谐波，不扫描相位、谐波阶数、窗口、年份、h、alpha、阈值。',
    'stopping': '本轮只做预声明组件对照，不追加账户。若新增日期信息不能改善净机会且下跌年份余量不足，完整交付反证并停止当前平滑表达。若有一致经济线索，后续额度再验证可执行账户；不根据事后日期图择日救援。不推断所有月内规律均无效，不新增经济硬门。',
    'source_files': {p: d.digest(ROOT / p) for p in sources}, 'input_references': refs,
    'continuation_budget_reference': previous['continuation_budget_reference'],
    'predecessors': previous['predecessors'], 'report_copy': previous['report_copy'],
    'resources': {'new_annual_models': 18, 'new_accounts': 0, 'provider_calls': 0, 'bootstrap': 500},
    'objective_achieved': False,
}
d.check(plan)
d.write(d.WORK / 'prospective.json', plan)
print({'status': plan['status'], 'slot': 4, 'new_annual_models': 18, 'new_accounts': 0})
