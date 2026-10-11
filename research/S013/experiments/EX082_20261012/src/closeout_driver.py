"""Root EX082 scientific review, full component delivery and exact report copy."""
from pathlib import Path
import sys
import numpy as np
from czsc_trader.application import assemble_delivery, validate_delivery
from czsc_trader.research_tools import delivery as m
from czsc_trader.research_tools.evidence import EvidenceRef

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp'))
import s013_calendar_driver as d


def run():
    exp, plan = d.stage()
    path, ctx = exp.resolve(ROOT), d.base.common().context(1)
    refs = {**d.read(path / 'protocols/method_references.json'), **d.read(path / 'protocols/result_references.json'),
            'verification.json': d.read(path / 'protocols/audit_reference.json')}
    s = d.read(d.public(refs['statistics.json']))
    audit = d.read(d.public(refs['verification.json']))
    assert audit['status'] == 'PASS' and audit['annual_models'] == 18 and s['new_annual_models'] == 18
    assert audit['new_accounts'] == s['new_accounts'] == 0
    assert audit['result_references'] == d.read(path / 'protocols/result_references.json')
    assert audit['plan_reference'] == refs['plan.json']
    kernel = d.base.load('calendar_review_definition', d.WORK / 'kernel.py')
    core = s['bootstrap']['summary']
    assert tuple(core) == kernel.QUANTITIES
    assert all(core[k]['value'] < 0 and core[k]['ci95'][0] < 0 < core[k]['ci95'][1] for k in kernel.QUANTITIES[:3])
    assert all(row['valid_replicates'] == 500 and row['ci95'][0] < 0 < row['ci95'][1] for row in core.values())
    proxy = s['nonoverlap_proxies']
    assert proxy['calendar_only']['compound_proxy'] > proxy['confirmation_only']['compound_proxy']
    assert proxy['original14_calendar']['compound_proxy'] > proxy['original14_joint']['compound_proxy']
    judgment = '当前自然月内第一谐波没有稳定的后续四日预测增量；非重叠价格代理有值得保留的有利线索，需先归因入场时钟和集中盈利，尚未证明可执行策略或原硬门达标。本轮按事前约定0账户，不做日期窗口/谐波/期限救援。'
    pct = lambda v: '不可得' if v is None else f'{100 * v:.4f}%'
    titles = {'training_mean': '历史均值（复用）', 'confirmation_only': '原确认（复用）',
              'original14_joint': '原14项（复用）', 'calendar_only': '自然日期',
              'confirmation_calendar': '原确认＋日期', 'original14_calendar': '原14项＋日期'}
    quantity_titles = ('日期 vs 历史均值：误差改善', '确认＋日期 vs 确认：误差改善',
                       '14项＋日期 vs 14项：误差改善', '日期选中机会均值', '确认＋日期选中机会均值',
                       '14项＋日期选中机会均值', '日期选中均值减全池均值（百分点）',
                       '确认＋日期选中均值减确认（百分点）', '14项＋日期选中均值减14项（百分点）',
                       '14项＋日期 vs 历史均值：误差改善')
    report = f'''# EX082：自然月内位置是否补充原价量信号

{judgment}

通俗说，“今天是这个月的什么位置”是一种事先知道、不同于涨跌和成交量的信息。本轮不用事后挑最好的买入日，也不假定月末资金流入已经得到证明，只检验一个固定而平滑的月内周期。它没让整体预测更准确，但在固定持有时钟选出的少量互不重叠机会中出现了有利表现；两种结果必须同时保留。

## 机制依据与最强反证

McConnell与Xu的2008年[原论文摘要](https://rpc.cfainstitute.org/research/financial-analysts-journal/2008/equity-returns-at-the-turn-of-the-month)及[作者所在大学保存的原论文](https://business.purdue.edu/faculty/mcconnell/publications/Equity-Returns-at-the-Turn-of-the-Month.pdf)提供历史月度交替附近收益分布异常的线索。论文并未确认成交量和股票基金净流量可以解释它。这里据此提出时间结构假设，属于研究员推论；未把异地、异期结果当作510500可交易机会，也未接入其市场数据。

论文是月末实际交易日及次月前三交易日的窄窗口。本轮是自然日期的一阶平滑周期，不是其直接复现：平滑项可能漏掉窄效应，失败不能否定所有月内规律。自然日期选择避免了用事后完整交易日历识别未来最后交易日的问题，尤其不可预知的停市或延长假期。

已有强反证是：原确认四日净机会线索有限、2022/2026均值为负；EX080确认单独执行只过交易频率，真实年化2.4529%、全窗回撤30.8919%；EX081确认与涨跌主效应/交互没有稳定增量。本开发池已反复用于适应性研究，增加模型表达并不自动增加信息或证明抗扰动。

## 事前设计与因果核验

仅原510500.SH已见开发池，后复权固定锚、无现金分红叠加、原资金费用整手及固定1%执行合同保持。共1635个信号T，与EX079相同原14共同完整行。日期相位固定为(T自然日序号−1)/当月自然天数；新列为0.5sin(2π相位)与0.5cos(2π相位)，只用T已知日期，包括已知闰年，不看未来实际交易安排，不拟合相位和尺度，不扫描日期窗口或谐波阶数。

三个固定嵌套对照：日期单独表达对历史训练均值；原确认＋日期对原确认；原14项＋日期对原14项。原三模型全部预测精确复用，新三模型每年拟合一次，2021–2026共18个年度模型。原价量列使用年度成熟训练ECDF中点秩−0.5，日期保留固定幅度，ridge10、截距不惩罚。

标签固定原四日Open[T+5]/Open[T+1]×.999/1.001−1。训练仅用2020起且早于测试年度、标签结束严格早于该年首个T的原始数据，至少40个训练样本。2020无预测，尾部标签尚未成熟时仍保存预测。不以未来全年测试样本数控制当下能否预测。原四项硬门不变，统计指标与区间均未变为新硬门。

合成因果前缀、仅一个当前测试T、未来特征/标签扰动、日期闰年与月长、异常输入拒绝、原四日时钟核验通过。独立实现用calendar.monthrange、标量三角函数、bisect训练CDF、fsum及标量正规方程复算18个模型、全部分组、严格正预测、5000个统计记录与持有时钟，通过。真实统计1次，0新账户、0数据拉取、0新增市场数据资产。

## 全部事前统计量

共同成熟预测1388个T，可预测1392个T。误差改善正数表示更准确；后三个均值差是百分点，不是账户收益。所有95%区间采用共享完整1635T轴500次重叠40日块、seed13，至少20个有效样本、至少400次有效，LINEAR分位数；年度模型不重拟合。本轮全部500次有效，但十项区间均跨零。区间仅是固定预测下探索诊断，未校正整个研究历史及多重比较。

|预声明比较|点估计|条件性95%区间|
|---|---:|---:|
'''
    for title, key in zip(quantity_titles, kernel.QUANTITIES):
        row = core[key]
        report += f"|{title}|{pct(row['value'])}|[{pct(row['ci95'][0])}, {pct(row['ci95'][1])}]|\n"
    report += '''
加入日期后，三个固定对照的点估计误差均增加约0.37%–0.49%，没有稳定预测改善。确认＋日期的选中均值反而低于原确认；14项＋日期的选中均值略改善，但区间包含零。不能用MSE替代经济硬门，也不能据此断言其账户一定更差。

## 允许重叠的正预测机会

这些是四日扣费OPEN价格代理，不是真实账户。

|模型|正预测数|成熟正预测数|选中平均净代理收益|误报比例|
|---|---:|---:|---:|---:|
'''
    for name, title in titles.items():
        row = s['panels']['all'][name]
        report += f"|{title}|{row['positive_forecasts']}|{row['mature_positive']}|{pct(row['positive_mean'])}|{pct(row['false_positive_rate'])}|\n"
    report += '''
## 全部年份的净盈利余量

表内为成熟正预测数量/四日净代理均值；少于20个时不可得，非自然年账户收益。

|年份|原确认|原14项|日期|确认＋日期|14项＋日期|
|---|---:|---:|---:|---:|---:|
'''
    for year in range(2020, 2027):
        cells = []
        for name in list(titles)[1:]:
            row = s['panels']['year_' + str(year)][name]
            cells.append(f"{row['mature_positive']} / {pct(row['positive_mean'])}")
        report += f'|{year}|' + '|'.join(cells) + '|\n'
    report += '''
日期单独表达2022机会均值约+0.0092%，余量非常薄，2023仍为负。两个增广模型2022/2023的重叠选中均值也都为负，未稳定修复下跌年份的问题。2025日期模型稀释了原价量信号选中的高收益；2026又有改善14项的有利线索，不能只挑好年份。

## 必须保留的有利线索：非重叠时钟

按相同四日贪心时钟，预测严格>0时接受入场意图，到期优先、同T不重入。最终未成熟意图保留，不末期强平。这些意图不等于真实成交或闭合交易。

|表达|意图/成熟代理数|平均净代理收益|完整区间复合代理|按1636日折算年化描述|
|---|---:|---:|---:|---:|
'''
    for name, row in proxy.items():
        cagr = (1 + row['compound_proxy']) ** (252 / 1636) - 1
        report += f"|{titles[name]}|{row['accepted']} / {row['mature']}|{pct(row['mean_proxy'])}|{pct(row['compound_proxy'])}|{pct(cagr)}|\n"
    report += '''
日期和14项＋日期的非重叠代理明显更好；14项＋日期约51.33%复合代理折算年化约6.59%，仍未证明原整体10.829%收益硬门。它不是账户上限、不是原门失败证明，也未包含限价未成交、真实整手、现金余额和最终浮盈亏。

以下从相同完整意图记录直接按入场年份分组，显示成熟代理的几何复合收益；跨年按入场年归组，明确不同于连续账户自然年收益和回撤。零意图记不可得，非零且少于20也保留描述的几何复合值和数量，不能作为有效均值统计。

|入场年|原确认数量/复合|原14项数量/复合|日期数量/复合|确认＋日期数量/复合|14项＋日期数量/复合|
|---|---:|---:|---:|---:|---:|
'''
    annual = {}
    for year in range(2020, 2027):
        annual[str(year)] = {}
        cells = []
        for name, row in proxy.items():
            values = [r['proxy_return'] for r in row['records'] if r['signal_date'].startswith(str(year)) and r['proxy_return'] is not None]
            compound = float(np.prod(1 + np.asarray(values)) - 1) if values else None
            annual[str(year)][name] = {'mature_n': len(values), 'compound_proxy': compound, 'continuous_account_year_return': None}
            cells.append(f'{len(values)} / {pct(compound)}')
        report += f'|{year}|' + '|'.join(cells) + '|\n'
    report += '''
日期单独表达的固定时钟代理在2022、2023分别约+3.66%、+7.01%，这是值得继续归因的线索；同一表达2026约−13.67%也必须保留。14项＋日期的整体优势没有解决2022/2023代理亏损，且2024约46.65%的大收益贡献需要进一步检查。允许重叠样本与真实能持有的互斥机会不是同一问题；不能因为前者误差不佳就删掉后者有利结果，也不能把一个有利时钟视为新增稳定信息。

## 训练系数及全部状态

日期余弦系数在三个表达的六个年度训练中均为正；正弦方向变化。这是月初/月末较强的训练形状线索。年度训练为扩展窗口、样本高度重叠，18次系数不是18次独立验证，更不是后续年份获利证据。

|测试年|日期sin/cos|确认＋日期sin/cos|14项＋日期sin/cos|
|---|---:|---:|---:|
'''
    for year, row in s['fit_years'].items():
        report += f'|{year}|' + '|'.join('/'.join(f'{v:.6f}' for v in row['coefficients'][name][-2:]) for name in kernel.NEW_MODELS) + '|\n'
    report += '''
全部自然相位四等分、涨跌/零方向、原信号mod5的五组与所有年份均在正式statistics.json中保留；无按分组表现挑阈值或交易时段。日期输入和训练系数在相同源代码、标签、预测及独立核验中可复算。

## 收口与下一步

本轮三个固定日期表达没有稳定的重叠四日预测增量，组件检验记INEFFECTIVE，判断仅限该检验。非重叠代理存在有限经济线索，保留为待归因证据；不扩展为“所有时间机制无效”，也不宣布组件已稳定有效。

遵守事前约定，本轮不追加账户，不挑日期窗口、相位、谐波阶数、期限或alpha救援。下一步在原数据及剩余额度内，针对日期单独表达的固定时钟做机会归因和起点敏感性对照，判断2022/2023正代理是否来自可重复选择，是否由少数机会支撑；有依据再进入原生可执行账户。该下一步源于本轮有利线索，属于适应性后续，不伪称独立新样本。

没有新完整账户，原硬门、五项策略自检状态没有新证明；参数收益Q10、回撤Q90、32点逐项/联合达标率和双费结果均不可得，不填0、不声称通过。总体目标仍未达成，保持原四门、数据与只做多约束。

新增额度已完成4/10（EX079–EX082），剩余6轮，最后允许EX088；额度使用完暂停，不启动EX089。正式报告完整副本保存在本实验others/report.md，逐字节与SHA256核对。
'''
    review = {'status': 'ROOT_SCIENTIFIC_REVIEWED', 'judgment': judgment, 'objective_achieved': False,
              'original_four_hard_gates_changed': False, 'new_economic_hard_gates': False, 'new_accounts': 0,
              'component_test_status': 'INEFFECTIVE', 'economic_proxy_clue': 'LIMITED_REQUIRES_CLOCK_ATTRIBUTION',
              'append_account_this_round': False, 'annual_entry_grouped_proxies': annual,
              'next_action': 'Original calendar-only fixed-clock attribution and starting-phase sensitivity; no date window/harmonic/horizon rescue',
              'evidence_references': {k: refs[k] for k in ('plan.json', 'statistics.json', 'verification.json')},
              'report_markdown': report}
    d.write(d.OUT / 'root_review.json', review)
    refs['root_review.json'] = d.put(ctx, exp, d.OUT / 'root_review.json')
    refs['closeout_driver.py'] = d.put(ctx, exp, Path(__file__))
    budget = {'status': 'ROUND4_COMPLETED_SUBJECT_TO_FULL_CLOSEOUT', 'authorization_reference': plan['continuation_budget_reference'],
              'maximum_additional_experiments': 10, 'started': 4, 'completed': 4, 'remaining': 6,
              'completed_experiment': exp.to_dict(), 'next_allowed': 'EX083', 'last_allowed': 'EX088',
              'pause_after_EX088': True, 'new_accounts_this_round': 0, 'objective_achieved': False}
    d.write(d.OUT / 'budget_receipt.json', budget)
    refs['budget_receipt.json'] = d.put(ctx, exp, d.OUT / 'budget_receipt.json')
    for value in (*refs.values(), *plan['input_references'].values(), plan['continuation_budget_reference']):
        d.public(value)
    tests = tuple(m.ComponentTestResult('CIVIL-MONTH-' + name, exp.experiment_id, EvidenceRef.from_dict(refs['plan.json']),
                  m.ComponentTestStatus.INEFFECTIVE, explanation,
                  tuple(EvidenceRef.from_dict(refs[k]) for k in ('statistics.json', 'verification.json', 'root_review.json')))
                  for name, explanation in (
                      ('ALONE', '日期单独误差未改善，重叠2023净均值负；固定非重叠2022/23正代理与2026损失同时保留，待时钟归因'),
                      ('CONFIRMATION-INCREMENT', '确认＋日期未增加稳定预测增量，选中净均值较原确认降低，2022/23重叠净均值均负'),
                      ('ORIGINAL14-INCREMENT', '14项＋日期未改善预测误差；净均值与非重叠代理有有利反证，未解决下跌年代理亏损或证明原门')))
    entry = m.ComponentEntry('KNOWN-CIVIL-MONTH-FIRST-HARMONIC',
        m.ExperimentDefinitionRef(EvidenceRef.from_dict(refs['.tmp/s013-calendar-phase/kernel.py']), 'calendar'),
        '已知自然月内时间结构对原价量信息的增量对照',
        '原HFQ Open[T+5]/Open[T+1]×.999/1.001−1；净价格代理', '固定h4',
        '原历史均值/确认/14项预测精确复用，固定日期两个基函数、年度成熟ridge10',
        '仅T已知自然日期、原T价量，严格成熟标签训练，不看未来实际交易日历',
        '原510500开发池HFQ固定锚、无分红叠加、原资金费用/1%执行合同保持；0账户',
        '适应性已见样本、平滑日期不是窄交易日窗口复现；非重叠代理不等于真实账本，未校正研究族选择',
        judgment, tests)
    evidence = tuple(dict.fromkeys(EvidenceRef.from_dict(v) for v in (*refs.values(), *plan['input_references'].values(), plan['continuation_budget_reference'])))
    report += '\n\n正式证据：\n\n' + ''.join(f'- [{name}]({EvidenceRef.from_dict(ref).path})\n' for name, ref in refs.items())
    predecessors = tuple(m.DeliveryReference.from_dict(x) for x in plan['predecessors'])
    receipt = assemble_delivery(ctx.repository,
        m.DeliveryDefinition(m.ResearchBatchRef('S013'), m.DeliveryStage.COMPONENTS, 16, predecessors),
        m.DeliveryContent(m.ComponentPanel((entry,), judgment), m.DeliveryStatus.COMPLETE, (), (), report=report, evidence=evidence))
    d.write(path / 'protocols/delivery_reference.json', receipt.reference.to_dict())
    validation = validate_delivery(ctx.repository, receipt.reference, scope=m.DeliveryValidationScope.FULL)
    d.write(path / 'protocols/delivery_validation.json', validation.to_dict())
    d.write(path / 'protocols/closeout_references.json', refs)
    if validation.status.value != 'PASS':
        raise RuntimeError(validation.to_dict())
    formal, copy = ROOT / 'research/S013/deliveries/COMPONENTS/16/report.md', path / 'others/report.md'
    with copy.open('xb') as stream:
        stream.write(formal.read_bytes())
    assert formal.read_bytes() == copy.read_bytes()
    d.write(path / 'protocols/report_copy_verification.json', {'status': 'PASS', 'formal_report': formal.relative_to(ROOT).as_posix(),
            'experiment_report': copy.relative_to(ROOT).as_posix(), 'formal_sha256': d.digest(formal),
            'copy_sha256': d.digest(copy), 'exact_bytes': True,
            'human_instruction': 'RSCH，请在后续的每个实验目录下保存一份report副本'})
    with (path / 'src/closeout_driver.py').open('xb') as stream:
        stream.write(Path(__file__).read_bytes())
    print({'experiment': exp.experiment_id, 'COMPONENTS': 16, 'FULL': 'PASS', 'report_copy': 'EXACT', 'completed': 4, 'remaining': 6})


if __name__ == '__main__':
    run()
