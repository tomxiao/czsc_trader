"""EX084 root economic review, full component delivery and report copy."""
from pathlib import Path
import sys
from czsc_trader.application import assemble_delivery, validate_delivery
from czsc_trader.research_tools import delivery as m
from czsc_trader.research_tools.evidence import EvidenceRef

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp'))
import s013_probability_driver as d


def run():
    exp, plan = d.stage()
    path, c = exp.resolve(ROOT), d.base.common()
    ctx = c.context(1)
    refs = {**d.read(path / 'protocols/method_references.json'), **d.read(path / 'protocols/result_references.json'),
            'verification.json': d.read(path / 'protocols/audit_reference.json')}
    s, audit = d.read(d.public(refs['statistics.json'])), d.read(d.public(refs['verification.json']))
    assert audit['status'] == 'PASS' and audit['new_annual_models'] == s['new_annual_models'] == 12
    assert audit['new_accounts'] == s['new_accounts'] == 0
    assert audit['result_references'] == d.read(path / 'protocols/result_references.json')
    assert audit['plan_reference'] == refs['plan.json']
    kernel = d.base.load('probability_review_definition', d.WORK / 'kernel.py')
    core = s['bootstrap']['summary']
    assert tuple(core) == kernel.QUANTITIES and all(row['valid_replicates'] == 500 for row in core.values())
    assert core['confirmation_brier_improvement_vs_prior']['value'] > 0 and core['original14_brier_improvement_vs_prior']['value'] < 0
    assert core['confirmation_payoff_positive_mean']['value'] < 0 and core['original14_payoff_positive_mean']['value'] < 0
    assert core['original14_payoff_mse_improvement_vs_original14']['ci95'][0] > 0
    for model in kernel.MODELS[3:]:
        assert all(row['panels']['year_2022']['compound_net_proxy'] < 0 for row in s['schedules'][model].values())
    cf = s['schedules'][kernel.MODELS[3]]
    assert all(row['panels']['year_2023']['compound_net_proxy'] > 0 for row in cf.values())
    judgment = '原确认对扣费后盈利概率有有限线索，并改善2023选中机会；原14概率预测不如恒定历史频率。把概率乘成熟历史平均盈亏恢复净期望后，两表达全池选中均值仍负，2022全部六时钟亏损，没有足够依据进入原生账户。停止当前年度概率＋固定历史平均盈亏映射，不以胜率、MSE或一个好年份替代原四门。'
    pct = lambda v: '不可得' if v is None else f'{100*v:.4f}%'
    names = {'training_mean': '原历史均值', 'confirmation_only': '原确认均值', 'original14_joint': '原14项均值',
             'confirmation_probability_payoff': '确认概率×历史盈亏', 'original14_probability_payoff': '14项概率×历史盈亏'}
    probability_names = {'training_probability': '恒定历史盈利比例', 'confirmation_logit': '原确认概率', 'original14_logit': '原14项概率'}
    report = f'''# EX084：把盈利概率与盈亏幅度分开是否有用

{judgment}

通俗说，“更经常赚钱”不一定“赚得更多”：可能每次只赚一点，偶尔却亏很多。本轮先预测四日扣费后盈利的概率，再用当时已成熟的平均盈利、平均亏损换算净收益余量，不把50%胜率直接当买入理由。确认信息在2023有值得保留的支持，但年度历史盈亏结构并未识别2022的亏损风险；两种新表达仍不足以实现当前目标。

## 事前方法、范围与最强反证

仅原510500.SH已见开发池、原1635T、原14共同完整行、固定锚后复权、无现金分红叠加；原资金费用整手与固定1%执行合同、只做多及原四门保持。原标签为Open[T+5]/Open[T+1]×.999/1.001−1，正为盈利事件、零或负为非盈利事件，不调盈亏分界或持有期限。

原确认单列和原14列分别用年度训练CDF中点秩−0.5，固定二元logistic总损失与L2斜率惩罚10，截距不惩罚。只用2020起、早于测试年、标签结束严格早于该年首T的成熟训练，至少40且正/非正各20；实际六年都可用，共12个新年度模型。数值Newton梯度收敛要求1e-10、最多100迭代，失败明确拒绝，无单类别兜底。数值求解不是参数或模型搜索。

每年从同一成熟训练估计G=平均正净收益、L=平均非正净收益及历史盈利比例。模型概率p映射为pG+(1−p)L，仅当其严格>0才选；盈亏平衡概率q=−L/(G−L)由当时历史确定，不以50%或事后收益挑阈值。恒定历史盈利比例的映射数值必须与原training_mean完全一致。

原均值/确认/14项净收益预测全部精确复用。最强反证是原14均值表达没有优势、原确认独立账户只过频率，日期/方向表达无稳定增量；更高胜率可遗漏大涨、无法消除大亏，且平均盈亏结构会变化。本开发池长期反复使用，本轮不是封存验证。没有扫描正则、损失函数、特征子集、日期、期限或阈值。

2020无预测，尾部未来标签未成熟仍保存当T预测，无未来全年测试样本数门。合成8类检查/4类拒绝通过，独立标量CDF/Newton/正规方程/盈亏映射、全部年份、30种固定机会时钟及5000个bootstrap量复算通过，严格正预测判定一致。三个旧对照全部时钟结果与EX083逐字段精确相同。真实统计1次，0新账户、0provider、0新增市场数据。

## 盈利概率预测：改善大小和反证

同1388个成熟预测T。Brier和logloss衡量盈利事件概率预测的误差，越小越好；数值不代表利润或成功概率证明。

|概率表达|Brier|logloss|平均预测概率|实际盈利比例|
|---|---:|---:|---:|---:|
'''
    for name, row in s['probability_quality']['all'].items():
        report += f"|{probability_names[name]}|{row['brier']:.8f}|{row['logloss']:.8f}|{pct(row['mean_probability'])}|{pct(row['observed_positive_fraction'])}|\n"
    report += '''
确认概率相对恒定历史频率的Brier改善约0.5523%、logloss改善约0.3998%，两个条件性区间都含零，是有限线索。原14概率的两个误差约恶化1.2531%、0.9494%，区间同样含零，不支持复杂概率表达更有效。

原14概率映射后的净收益MSE相对原14均值改善约1.9997%，条件性区间约[0.0862%,4.5572%]为正；这是有利反证，必须保留。但它没有带来正的全池选择收益，不能用预测误差改善冒充经济达标。该区间未校正研究历史或多重比较。

## 全部十项事前诊断

共享原1635T轴500次重叠40日块、seed13，固定年度预测不重拟合；原始及重抽样至少20、至少400有效才报LINEAR95%区间。全部500次有效。两个均值差的百分数表述表示百分点，其他误差改善为相对比例。

|固定数量|点估计|条件性95%区间|
|---|---:|---:|
'''
    for key in kernel.QUANTITIES:
        row = core[key]
        report += f"|{key}|{pct(row['value'])}|[{pct(row['ci95'][0])}, {pct(row['ci95'][1])}]|\n"
    report += '''
## 换算经济余量后的全部选择结果

允许信号重叠的四日净OPEN价格代理，非真实账户。

|表达|正预测数|成熟正预测数|选中平均净代理|实际盈利比例|
|---|---:|---:|---:|---:|
'''
    for name, row in s['panels']['all'].items():
        report += f"|{names[name]}|{row['positive_forecasts']}|{row['mature_positive']}|{pct(row['positive_mean'])}|{pct(row['hit_rate'])}|\n"
    report += '''
两个新表达分别选648和693个成熟机会，均值−0.0315%、−0.0214%，比各自原均值表达更差。整体命中比例略高于50%仍可亏损，说明本轮没有解决盈利频率和盈亏幅度共同决定净收益的问题。

## 全部年份的净机会余量

表内是成熟正预测数量/净代理均值；少于20均值不可得，非自然年账户收益。

|年份|原确认均值表达|确认概率映射|原14项均值表达|14项概率映射|
|---|---:|---:|---:|---:|
'''
    for year in range(2020, 2027):
        cells = []
        for name in ('confirmation_only', kernel.MODELS[3], 'original14_joint', kernel.MODELS[4]):
            row = s['panels']['year_' + str(year)][name]
            cells.append(f"{row['mature_positive']} / {pct(row['positive_mean'])}")
        report += f'|{year}|' + '|'.join(cells) + '|\n'
    report += '''
2023确认概率映射挑中26个成熟机会，平均净代理约+0.6545%、盈利比例69.23%，优于原确认90个机会的约+0.0067%，这是真实的有利探索结果。但2022确认概率映射选择全部242个成熟机会，均值−0.4354%、盈利比例44.21%；没有识别这一年下跌中的净亏损风险。两个表达2026选中均值仍负。不能只保留2023或2024的好均值。

## 历史盈亏结构和年度校准

训练幅度均为已成熟原h4净代理，未使用测试结果择阈值。

|测试年|训练盈利/非盈利数|历史盈利比例|平均盈利|平均非盈利|盈亏平衡概率|
|---|---:|---:|---:|---:|---:|
'''
    for year, row in s['fit_years'].items():
        p = row['payoffs']
        report += f"|{year}|{row['win_n']} / {row['nonpositive_n']}|{pct(p['win_fraction'])}|{pct(p['mean_positive'])}|{pct(p['mean_nonpositive'])}|{pct(p['break_even_probability'])}|\n"
    report += '''
|测试年|所有成熟预测T数|历史恒定概率|确认平均预测概率|14项平均预测概率|实际盈利比例|
|---|---:|---:|---:|---:|---:|
'''
    for year in range(2020, 2027):
        rows = s['probability_quality']['year_' + str(year)]
        report += f"|{year}|{rows['training_probability']['n']}|{pct(rows['training_probability']['mean_probability'])}|{pct(rows['confirmation_logit']['mean_probability'])}|{pct(rows['original14_logit']['mean_probability'])}|{pct(rows['training_probability']['observed_positive_fraction'])}|\n"
    report += '''
2022所用历史盈利比例约52.16%，盈亏平衡约48.60%，确认概率映射因而对该年全部机会给出正的期望。但该年实际盈利比例约44.21%，实际均值负。年度固定历史结构和弱确认分辨力无法及时识别当前变化；这不是证明只要更新均值就能成功，后续必须检验新的当前状态信息及增量，而不是按已见结果移动概率阈值。

## 原贪心与全部五组入场控制

30种安排复用EX083冻结实现，不搜索起点。原贪心空仓后正预测接受入场，四日到期优先、同T不重入；五组固定i%5=k。各组机会数/持仓不同，非等笔数比较、非标准5%扰动。

|新表达/时钟|成熟代理数|全窗复合|2020|2021|2022|2023|2024|2025|2026|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
'''
    clock_summary = {}
    for name in kernel.MODELS[3:]:
        values = []
        for clock, row in s['schedules'][name].items():
            a = row['panels']['all']
            values.append(a['compound_net_proxy'])
            report += f"|{names[name]} / {clock}|{a['mature']}|{pct(a['compound_net_proxy'])}|" + '|'.join(pct(row['panels']['year_' + str(y)]['compound_net_proxy']) for y in range(2020, 2027)) + '|\n'
        clock_summary[name] = {'compound_min': min(values), 'compound_max': max(values),
            'positive_2022': sum(r['panels']['year_2022']['compound_net_proxy'] > 0 for r in s['schedules'][name].values()),
            'positive_2023': sum(r['panels']['year_2023']['compound_net_proxy'] > 0 for r in s['schedules'][name].values())}
    report += '''
确认概率映射原贪心全窗约+60.08%，是有利代理，相比原确认+13.00%明显更好；但2022约−13.25%，全部六时钟均负，2023六时钟均正。六组复用同一批预测和大量重叠机会，并非六次独立复现，不能据此说2023已获独立验证。

14项概率映射原贪心全窗约−4.33%，2022/2023代理均负；五组只有个别有正全窗，不能挑最好组替代整体经济判断。所有旧对照、30时钟、全部年度利润集中及事后删项结果在正式statistics.json中保留。

确认新表达原贪心收益折算全1636日约7.52%年化描述，仍未证明原10.829%年化门。它不是账户上限或账户失败证明；价格代理省略限价未成交、整手现金及最后持仓浮盈亏，不计为原生闭合交易。

## 判断、保留与下一步

保留确认对盈利事件概率的有限线索、2023经济余量改善，以及14项净收益MSE改善的有利反证。停止当前年度固定概率＋历史平均盈亏映射作为完整账户候选；不是所有分类或确认信息普遍无效的证明。不以一个好年份、MSE或胜率替代原四项硬门，也不新增置信区间经济否决门。

下一步先检验决策时已成熟的近期净机会盈亏结构，是否能提供超出原14项价量的当前状态信息，再考虑更新概率或盈亏幅度。依据是当前年度历史先验无法识别2022变化，必须检验当前状态的增量；不能直接假设短窗口或更频繁更新必然有效，也不补扫当前分类阈值、alpha或期限。该下一方向尚未执行，不称新增独立样本。

本轮0新完整账户，原四门及五项策略自检没有新证明，收益Q10、回撤Q90、32点逐项/联合达标率和双费自检均不可得，不填0或写通过。总体目标尚未达成，保持完整目标。

追加额度已完成6/10（EX079–EX084），剩余4轮，最后EX088；额度用完暂停，不启动EX089。正式报告完整副本保存在本实验others/report.md，并逐字节及SHA256校验。
'''
    review = {'status': 'ROOT_SCIENTIFIC_REVIEWED', 'judgment': judgment, 'objective_achieved': False,
              'original_four_hard_gates_changed': False, 'new_economic_hard_gates': False, 'new_accounts': 0,
              'new_annual_models': 12, 'append_account': False, 'clock_summary': clock_summary,
              'favorable_counterevidence': 'Confirmation mild probability improvement and2023positive six clocks; original14 net MSE2percent improvement with conditional CIpositive; not suppressed',
              'next_direction': 'Causal recent matured net opportunity payoff state incremental to original14, before adaptive mapping or account',
              'evidence_references': {k: refs[k] for k in ('plan.json', 'statistics.json', 'verification.json')}, 'report_markdown': report}
    d.write(d.OUT / 'root_review.json', review)
    refs['root_review.json'] = d.put(ctx, exp, d.OUT / 'root_review.json')
    refs['closeout_driver.py'] = d.put(ctx, exp, Path(__file__))
    budget = {'status': 'ROUND6_COMPLETED_SUBJECT_TO_FULL_CLOSEOUT', 'authorization_reference': plan['continuation_budget_reference'],
              'maximum_additional_experiments': 10, 'started': 6, 'completed': 6, 'remaining': 4,
              'completed_experiment': exp.to_dict(), 'next_allowed': 'EX085', 'last_allowed': 'EX088',
              'pause_after_EX088': True, 'new_accounts_this_round': 0, 'objective_achieved': False}
    d.write(d.OUT / 'budget_receipt.json', budget)
    refs['budget_receipt.json'] = d.put(ctx, exp, d.OUT / 'budget_receipt.json')
    for value in (*refs.values(), *plan['input_references'].values(), plan['continuation_budget_reference']):
        d.public(value)
    tests = tuple(m.ComponentTestResult('PROBABILITY-PAYOFF-' + name, exp.experiment_id, EvidenceRef.from_dict(refs['plan.json']),
        m.ComponentTestStatus.INEFFECTIVE, explanation,
        tuple(EvidenceRef.from_dict(refs[k]) for k in ('statistics.json', 'verification.json', 'root_review.json')))
        for name, explanation in (
            ('CONFIRMATION', '确认概率有有限改善和2023经济线索，但全池净均值负、2022全部六时钟亏损；不把胜率作为收益达标'),
            ('ORIGINAL14', '14项概率误差更差，净期望MSE改善的有利反证保留；选中均值负、原贪心2022/23均负，未获可执行支持')))
    entry = m.ComponentEntry('NET-PROFIT-PROBABILITY-HISTORICAL-PAYOFF',
        m.ExperimentDefinitionRef(EvidenceRef.from_dict(refs['.tmp/s013-profit-probability/kernel.py']), 'forecasts'),
        '原确认/14项价量的扣费后盈利事件概率与历史盈亏幅度职责对照',
        '原h4 HFQ Open[T+5]/Open[T+1]×.999/1.001−1，事件>0，非账户', '固定h4',
        '原均值三个对照精确复用、年度固定L2logistic两个表达，成熟历史盈亏换算净期望',
        'T原特征、只用严格早于本年首T成熟标签训练，无未来测试数门；尾部预测保留',
        '原510500已见开发池HFQ固定锚、无分红叠加、原费用资金/1%合同保持；0账户',
        '历史盈亏幅度未条件化，已见样本选择偏差，概率与价格代理不替代经济门/五自检',
        judgment, tests)
    evidence = tuple(dict.fromkeys(EvidenceRef.from_dict(v) for v in (*refs.values(), *plan['input_references'].values(), plan['continuation_budget_reference'])))
    report += '\n\n正式证据：\n\n' + ''.join(f'- [{name}]({EvidenceRef.from_dict(ref).path})\n' for name, ref in refs.items())
    predecessors = tuple(m.DeliveryReference.from_dict(v) for v in plan['predecessors'])
    receipt = assemble_delivery(ctx.repository,
        m.DeliveryDefinition(m.ResearchBatchRef('S013'), m.DeliveryStage.COMPONENTS, 18, predecessors),
        m.DeliveryContent(m.ComponentPanel((entry,), judgment), m.DeliveryStatus.COMPLETE, (), (), report=report, evidence=evidence))
    d.write(path / 'protocols/delivery_reference.json', receipt.reference.to_dict())
    validation = validate_delivery(ctx.repository, receipt.reference, scope=m.DeliveryValidationScope.FULL)
    d.write(path / 'protocols/delivery_validation.json', validation.to_dict())
    d.write(path / 'protocols/closeout_references.json', refs)
    if validation.status.value != 'PASS':
        raise RuntimeError(validation.to_dict())
    formal, copy = ROOT / 'research/S013/deliveries/COMPONENTS/18/report.md', path / 'others/report.md'
    with copy.open('xb') as stream:
        stream.write(formal.read_bytes())
    assert formal.read_bytes() == copy.read_bytes()
    d.write(path / 'protocols/report_copy_verification.json', {'status': 'PASS', 'formal_report': formal.relative_to(ROOT).as_posix(),
            'experiment_report': copy.relative_to(ROOT).as_posix(), 'formal_sha256': d.digest(formal), 'copy_sha256': d.digest(copy),
            'exact_bytes': True, 'human_instruction': 'RSCH，请在后续的每个实验目录下保存一份report副本'})
    with (path / 'src/closeout_driver.py').open('xb') as stream:
        stream.write(Path(__file__).read_bytes())
    assert not c.SOURCE_CALLS
    print({'experiment': exp.experiment_id, 'COMPONENTS': 18, 'FULL': 'PASS', 'report_copy': 'EXACT', 'completed': 6, 'remaining': 4})


if __name__ == '__main__':
    run()
