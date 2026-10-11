"""Summarize verified fixed diagnostics, preserving necessary counterevidence."""
import sys
from pathlib import Path
ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp'))
import s013_net_research as driver
from czsc_trader.research_tools.context import ExperimentRef

plan = driver.read(driver.OUT / 'plan.json')
exp = ExperimentRef.from_dict(plan['experiment'])
protocols = exp.resolve(ROOT) / 'protocols'
refs = {**driver.read(protocols / 'method_references.json'), **driver.read(protocols / 'result_references.json'), **driver.read(protocols / 'audit_references.json')}
s = driver.read(driver.public(refs['statistics.json']))
audit = driver.read(driver.public(refs['verification.json']))
if audit['status'] != 'PASS':
    raise ValueError('Independent verification required')
models = s['method']['models']
names = dict(training_mean='过去均值', confirmation_only='仅买入确认分数', original14_joint='原14项联合预测')


def pct(x):
    return '不可用' if x is None else f'{x * 100:+.6f}%'


lines = [
    '# EX079：原信息是否能挑出扣费后值得买的机会', '',
    '结论：买入确认分数有有限的筛选线索；固定14项联合表达未证明更好。两者都没有建立稳定的净盈利能力，不能据此宣称原四项硬门或标准32点达标。', '',
    '本轮是新增10轮额度的第1轮，EX079–EX088最多10轮，EX088完成后暂停，不启动EX089。原四门、只做多、HFQ及固定1%执行合同均未更改；本轮0新账户、0新数据请求。', '',
    '## 方法与复用', '',
    '固定四日全额小数份价格代理：T决定，下一OPEN买入，第5个未来OPEN卖出，每侧0.1%成本。三表达用相同14项完整特征、成熟历史训练：过去均值、买入确认单分数、原14项联合。年度外推2021–2026，2020仅训练；训练标签在测试年度首信号日前成熟。训练ECDF秩、ridge10、阈值预测净收益>0均固定，无扫描或翻向。', '',
    'EX066的1388条成熟均值/14项联合预测逐条复用；四个未成熟尾日期保留因果预测、不虚造真实收益。只有确认单分数新增六个年度拟合。此前均值/联合模型的误差不是新发现。2020无事前预测，不能称完整原窗口账户比较。', '',
    '原全轴1635T先定义五相位再筛选。旧EX066 opportunity.csv是entry_eligible，不能直接当空仓机会；本轮辅助组取完整C8880原政策confirmation_opportunity，含2019anchor历史前缀，147个事前机会，不使用未来成交或实际持仓替代政策状态。辅助组仅报告、不训练。', '',
    '## 主池：预测为正的机会', '',
    '| 表达 | 有真实结果的入选数 | 扣费后四日均值 | 胜率 | 误判比例 | 比全池提高 |',
    '|---|---:|---:|---:|---:|---:|',
]
for model in models:
    p = s['panels']['all'][model]['positive']
    lines.append(f"|{names[model]}|{p['evaluation_n']}|{pct(p['true_net_mean'])}|{pct(p['positive_truth_rate'])}|{pct(p['false_positive_rate_among_positive_predictions'])}|{pct(s['paired_mean_bootstrap']['summary'][model + '_positive_minus_all']['original'])}|")
lines += ['', '全部同口径1388条成熟机会平均净收益为 ' + pct(s['panels']['all']['training_mean']['all']['true_net_mean']) + '。确认有1392个可预测日期，694个正预测，其中691个结果成熟；它的691个机会重叠，绝不是691笔闭合交易。', '', '## 固定500×40共享时间块区间', '', '| 数量 | 原值 | 95%区间 | 有效重采样 |', '|---|---:|---|---:|']
for key, item in s['paired_mean_bootstrap']['summary'].items():
    ci = item['ci95']
    interval = '不可用' if ci is None else f'[{pct(ci[0])}, {pct(ci[1])}]'
    lines.append(f"|{key}|{pct(item['original'])}|{interval}|{item['valid_replicates']}/500|")
lines += ['', '8个固定区间全部跨零。确认正组比全池提高约0.208个百分点，但差值下界仍略负；确认正组本身的净均值区间也跨亏损。因此是有限线索，不能把平均为正说成稳定盈利。区间保留全500次记录，不重拟合、不挑组；未校正同池反复研究。', '', '## 年份与五相位反证', '', '| 时段 | 确认正组n/均值 | 联合正组n/均值 | 全池均值 |', '|---|---|---|---|']
for panel in [*[f'year_{year}' for year in range(2020, 2027)], *[f'phase_{phase}' for phase in range(5)], 'original_policy_flat_confirmation_opportunity']:
    a = s['panels'][panel]['confirmation_only']['positive']
    b = s['panels'][panel]['original14_joint']['positive']
    allmean = s['panels'][panel]['training_mean']['all']['true_net_mean']
    lines.append(f"|{panel}|{a['evaluation_n']} / {pct(a['true_net_mean'])}|{b['evaluation_n']} / {pct(b['true_net_mean'])}|{pct(allmean)}|")
lines += ['', '2022确认正组仍亏损，2026也亏；2023确认有改善而联合组仍亏。五相位确认有正有负，不能选择有利相位。2024/2025表现好，需完整保留：2024低胜率但均值为正，说明少量较大涨幅也可能影响均值。辅助空仓组是旧策略内生选择、样本小，不能直接推广成新策略。', '', '## 误差与最强竞争解释', '', '| 表达 | MSE相对均值的改善 | 秩相关 |', '|---|---:|---:|']
for model in models:
    q = s['quality'][model]
    relative = q['mse_improvement'] / q['baseline_mse']
    lines.append(f"|{names[model]}|{pct(relative)}|{q['ic']:.8f}|")
lines += ['', '确认误差比均值小约0.945%，联合模型误差反而大约2.437%；确认正组平均收益高于联合组，但组间区间跨零。更多信息在这个固定线性秩表达中没有自动变成更好筛选。过去均值正组平均亏损，单靠过去整体上涨不能识别未来机会。', '', '## 下一步与限制', '',
    '建议保留确认分数作为有待验证的信息，而不是直接保留所有确认规则；停止本轮固定14联合表达的阈值/邻参数救援。有限正面线索只支持进一步核对“机会如何被原限价与资金约束兑现”，不支持马上做大范围账户搜索。需要分清预测错、执行损耗与退出机会成本。', '',
    '四日重叠价格代理忽略1%限价实际成交、整手、同时只能持一仓、真实退出与现金路径，不能推算账户年化/回撤/闭合次数，也未形成32点Q10/Q90。下跌年正收益仍是原硬门，不放宽。没有改进策略达标结论；当前研究目标未达成。', '',
    '独立核验通过：1635T输入、原147空仓机会、1388旧预测精确复用、三个表达数学重建、全部年份/相位/辅助描述及500×8=4000重采样数值和状态。复算用于核验，不增加研究表达或额度。', '',
    '正式报告保存于deliveries；本实验others/report.md保存逐字节副本，另留SHA256一致性凭据。文中证据路径按项目根目录解释。',
]
roles = {
    'confirmation_only': {'status': 'SUPPORTED', 'judgment': '有限筛选线索：正组均值及MSE优于均值，但所有固定CI跨零，2022/2026负、相位混合，不能证明稳定净盈利；仅保留信息核对兑现。'},
    'original14_joint': {'status': 'INEFFECTIVE', 'judgment': '本固定14项秩ridge10表达未支持稳定净机会筛选或优于确认；MSE更差，正组均值薄、CI跨零，停止邻参数救援，不宣称14项所有用途无效。'},
    'training_mean': {'status': 'INEFFECTIVE', 'judgment': '固定均值正组实际平均亏损，不能仅凭训练均值为正提供入场依据；这是比较基准而非新发现。'},
}
driver.write(driver.OUT / 'root_review.json', {'status': 'ROOT_REVIEWED', 'objective_achieved': False, 'original_four_hard_gates_changed': False, 'new_accounts': 0, 'roles': roles, 'judgment': '确认分数有限线索、联合表达未支持更好，原目标未达成；下一步只核有限机会的兑现，禁止把代理均值当账户绩效。', 'report_markdown': '\n'.join(lines), 'evidence_references': {name: refs[name] for name in ('plan.json', 'statistics.json', 'verification.json')}})
print({'status': 'ROOT_REVIEWED', 'objective_achieved': False, 'quota_completed_after_closeout': 1})
