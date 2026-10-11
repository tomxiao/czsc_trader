"""Before-data prospective root definition of single EX081 mechanism contrast."""
from pathlib import Path
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp'))
import s013_context_driver as d

work = d.WORK
checks = d.read(work / 'focused_checks.json')
if checks['status'] != 'PASS':
    raise ValueError('Synthetic checks first')
for name, value in checks['files'].items():
    if d.digest(work / name) != value:
        raise ValueError('Synthetic source drift')
p80 = ROOT / 'research/S013/experiments/EX080_20261012/protocols'
if d.read(p80 / 'delivery_validation.json')['status'] != 'PASS':
    raise ValueError('EX080 FULL first')
refs80 = d.read(p80 / 'closeout_references.json')
quota = d.read(d.public(refs80['budget_receipt.json']))
if (quota['started'], quota['completed'], quota['next_allowed']) != (2, 2, 'EX081'):
    raise ValueError('Exact third slot')
p79 = ROOT / 'research/S013/experiments/EX079_20261012/protocols'
refs79 = d.read(p79 / 'result_references.json')
refs66 = d.read(ROOT / 'research/S013/experiments/EX066_20261011/protocols/result_references.json')
previous = d.read(p80 / 'plan_v2.json')
sources = ['.tmp/s013-confirm-context/' + x for x in ('kernel.py', 'audit.py', 'focused_checks.py', 'focused_checks.json')]
sources += ['.tmp/s013_context_driver.py', '.tmp/s013_context_freeze.py', '.tmp/s013_confirm_execution.py', 'research/S013/experiments/EX058_20261011/src/common.py']
plan = {
    'status': 'ROOT_FROZEN_BEFORE_REAL_STUDY', 'role': 'RSCH', 'stage': 2, 'quota_slot': 3,
    'authorization': '原自主研究及EX079–EX088十轮额度；后续每个实验保存report副本',
    'original_four_hard_gates_changed': False, 'new_economic_hard_gates': False,
    'question': '原确认信息在上涨与下跌状态下是否具有不同的四日净收益作用，而非仅需加一个涨跌过滤器？',
    'basis': '原确认包括20日自相关(延续性)及成交活跃程度，但本身不编码价格上涨还是下跌；相同延续性在上涨/下跌背景下对只做多的意义可能相反。原策略确认参与有条件入场；EX079全局单分数只有有限线索，EX080单独兑现原四门3项失败，支持检验职责/作用关系缺失而非调阈值救援。',
    'strongest_prior_counter': 'EX079所有净均值/增量区间跨零，2022/2026选中机会均值负；原14线性联合比历史均值MSE更差；EX080真实CAGR2.4529%、DD30.8919%、2022/23负，只过频率。复杂表达并不自动改善；本轮若关系增量不清楚则不追加账户。',
    'fixed_design': {
        'common_rows': '原14全部有限，原1635T 2020-01-02..2026-09-29，共用与EX079相同训练/预测支持，不删除其他特征缺失门',
        'information': '原ADJUSTED120确认分数及原momentum20字段；涨跌状态s=sign(momentum20)，零为0，不从样本拟合分界',
        'confirmation': '年度成熟训练样本ECDF midpoint rank - .5，测试只用同训练CDF；raw confirmation保留原定义',
        'control': 'confirmation_trend = intercept + b1*c + b2*s',
        'mechanism': 'confirmation_trend_interaction = intercept + b1*c + b2*s + b3*c*s；仅增加一个交互项，预期b3正：确认较强时延续当前价格方向',
        'alternatives': '旧training_mean、confirmation_only、original14_joint所有预测精确复用，仅描述；新对照与交互各6次年度拟合，共12，无模型/方向/期限/阈值扫描',
        'label': '原HFQ native Open[T+5]/Open[T+1]*(.999/1.001)-1，固定h4、双侧0.1%净价格代理；不是真实账户',
        'training': '2020<=Tyear<testyear，label_end严格早于本测试年首T，全14有限且truth有限，至少40；年度2021..2026、ridge10、非惩罚截距；不以未来测试全年样本数控制当前可用性',
        'forecast': '全完整T包括缺少未来truth的尾部，2020无预测；选择阈值严格>0，其他<=0；test标签只用于事后检验',
        'reports': '所有年度2020–26、全部池、上涨/下跌/零状态、原位置mod5全五相位；正预测覆盖/实际均值/命中与误报。均为描述，不分组训练或挑年相位做策略',
        'primary': '交互相对两个主效应对照的配对OOS MSE改善；并对旧确认/历史均值报告误差及正净均值增量，系数和各年经济反证完整呈现',
        'bootstrap': '共享完整1635T索引500次重叠块40、seed13、每量原始及重抽样有效n>=20、至少400有效才报LINEAR95区间，全部500记录/10事前数量；既有年度预测不重拟合，条件性区间未校正历史选择偏差',
        'quantities': ['interaction_mse_improvement_vs_control', 'control_mse_improvement_vs_confirmation', 'interaction_mse_improvement_vs_confirmation', 'interaction_mse_improvement_vs_mean', 'control_mse_improvement_vs_mean', 'interaction_positive_mean', 'control_positive_mean', 'interaction_positive_mean_minus_control', 'interaction_positive_mean_minus_confirmation', 'interaction_positive_mean_minus_all'],
        'policy_proxy': '全T按预测>0贪心接受四日episode、到期优先/次T才可重入，保留未成熟最后episode；只描述非重叠OPEN代理，不计作真实闭合交易/硬门或实盘账户',
    },
    'scope': '仅原510500.SH已见开发池/HFQ固定锚/no dividend overlay/原1million/.001/lot100/固定1%执行合同；本轮0账户/0provider/0新增数据',
    'selection_history': '同一已见开发池上根据EX079/80反证作新的功能表达，未封存验证，不称新数据/独立复现；两个新模型只为嵌套机制对照，不按事后表现挑分界或模型',
    'stopping': '关系增量、错误改善和下跌年份利润余量缺乏支持时，交付全部反证，停止此表达；不凭复杂度、一个好年份或正样本均值追加账户，不调20/h4/alpha/符号/阈值救援。不新增经济硬门。',
    'source_files': {p: d.digest(ROOT / p) for p in sources},
    'input_references': {'features.csv': refs79['features.csv'], 'labels.csv': refs79['labels.csv'], 'prior_scores.json': refs79['statistics.json'],
                         'prior_input_checks.json': refs79['input_checks.json'], 'prices.csv': refs66['prices.csv'],
                         'EX080_review.json': refs80['root_review.json'], 'EX080_verification.json': refs80['verification.json'], 'prior_budget.json': refs80['budget_receipt.json']},
    'continuation_budget_reference': previous['continuation_budget_reference'], 'predecessors': previous['predecessors'],
    'report_copy': previous['report_copy'], 'resources': {'new_annual_models': 12, 'new_accounts': 0, 'provider_calls': 0, 'bootstrap': 500},
    'objective_achieved': False,
}
d.check(plan)
d.write(work / 'prospective.json', plan)
print({'status': plan['status'], 'slot': 3, 'new_accounts': 0}, flush=True)
