"""EX083 root review and full delivery of clock/concentration counterevidence."""
from pathlib import Path
import sys
from czsc_trader.application import assemble_delivery, validate_delivery
from czsc_trader.research_tools import delivery as m
from czsc_trader.research_tools.evidence import EvidenceRef

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp'))
import s013_clock_driver as d


def run():
    exp, plan = d.stage()
    path = exp.resolve(ROOT)
    c = d.base.common()
    ctx = c.context(1)
    refs = {**d.read(path / 'protocols/method_references.json'), **d.read(path / 'protocols/result_references.json'),
            'verification.json': d.read(path / 'protocols/audit_reference.json')}
    s, audit = d.read(d.public(refs['statistics.json'])), d.read(d.public(refs['verification.json']))
    assert audit['status'] == 'PASS' and audit['schedules'] == s['schedule_count'] == 36
    assert audit['new_accounts'] == s['new_accounts'] == s['new_annual_models'] == 0
    assert audit['result_references'] == d.read(path / 'protocols/result_references.json')
    assert audit['plan_reference'] == refs['plan.json']
    kernel = d.base.load('clock_review_definition', d.WORK / 'kernel.py')
    schedules, core = s['schedules'], s['bootstrap']['summary']
    assert tuple(core) == kernel.QUANTITIES
    cal = schedules['calendar_only']
    phase_compounds = [cal[clock]['panels']['all']['compound_net_proxy'] for clock in kernel.CLOCKS[1:]]
    both_positive = [clock for clock in kernel.CLOCKS[1:] if all(cal[clock]['panels']['year_' + str(y)]['compound_net_proxy'] > 0 for y in (2022, 2023))]
    greedy = cal['greedy']['panels']['all']
    assert sum(v > 0 for v in phase_compounds) == 3 and both_positive == ['phase_3']
    assert greedy['compound_without_best_positive'] > 0 > greedy['compound_without_top10pct_positive']
    assert cal['greedy']['panels']['year_2022']['compound_without_best_positive'] < 0
    assert cal['greedy']['panels']['year_2023']['compound_without_top10pct_positive'] > 0
    assert all(row['valid_replicates'] == 500 and row['ci95'][0] < 0 < row['ci95'][1] for row in core.values())
    judgment = '日期第一谐波的固定四日净机会路线未获得足够稳健支持：有利代理对预设入场时钟不稳定，2022利润余量依赖一笔较大盈利；2023有利结果保留。停止把当前日期/确认＋日期/14项＋日期表达升级为账户，不按最好相位或事后删项优化。总体目标未达成，转向区别于均值预测的新职责表达。'
    pct = lambda v: '不可得' if v is None else f'{100 * v:.4f}%'
    names = {'training_mean': '历史均值', 'confirmation_only': '原确认', 'original14_joint': '原14项',
             'calendar_only': '日期', 'confirmation_calendar': '确认＋日期', 'original14_calendar': '14项＋日期'}
    report = f'''# EX083：日期机会是否依赖入场时钟和少数盈利

{judgment}

通俗说，上一轮“日期信息不错”的迹象，主要出现在特定方式挑出的互不重叠机会里。本轮不改预测，只把允许入场的时点固定为五组，看看好结果能否重复；同时拆开大赚机会对收益的贡献。结果是，换入场组就可能从赚变亏。原2022的正代理去掉最大一笔盈利便转负，2023则仍有一定余量，不能笼统说全靠一笔，也不能宣布已找到稳健策略。

## 原范围、方法和技术证据

沿用原510500.SH已见开发池、固定锚后复权、无现金分红叠加、原资金/费用/整手/1%执行合同、原四门和只做多约束。原1635T 2020-01-02..2026-09-29、原四日净Open[T+5]/Open[T+1]×.999/1.001−1标签。全部EX082六列预测精确复用，0新模型、0新账户、0provider、0新增市场数据；没有改预测正阈值、持有期限或日期定义。

每个表达有六种固定机会时钟：原贪心（空仓且正预测时接受入场，四日到期优先，同T不重入）；原完整T位置i%5=0..4的五组（只有本组且正预测时接受入场）。五组相邻候选间隔五交易日，均保留四日持有和机会互斥，不每年重启计数，不按未来标签选相位，也不是初次等待几天后恢复贪心。原2020无预测和尾部缺少未来标签的意图保留。

五组是入场安排的机制对照，不是同一参数的标准5%联合扰动，不替代32点自检；各组机会数量略不同，亦非等笔数或等持仓天数配对，因此不能把全部收益差解释成纯粹的单日起点效果。原贪心全部意图与EX082逐条精确复现。六列×六时钟共36个代理，全部均报告、不挑最好组。

贡献计算用等研究单位的净价格代理：严格正盈利按金额由大到小，相同金额按原T位置早者优先；前ceil10%正盈利之和/全部正盈利之和。反事实去最佳一笔或前10%正盈利，保留其余盈利及所有亏损机会。它是事后归因，无法事先知道哪笔最大，不是可交易规则，也不是真实账户闭合利润集中性自检。

所有年度按入场T年份归组，跨年按入场年计算，明确不同于连续账户的自然年收益、回撤。均值至少20才报；非空复合描述即使少于20仍保留数量，空组不可得。原生闭合交易数和账户收益均不可得。

合成7类检查、4类拒绝通过；独立状态机、标量log1p几何复合、完整正机会接受/跳过分区、全部36时钟/288面板、4500个bootstrap量复算通过。原生完整账户与策略五项自检没有执行，不声称其通过。

## 日期表达的全部固定时钟

以下为成熟OPEN代理复合收益，非账户收益。

|时钟|成熟数|全窗|2020|2021|2022|2023|2024|2025|2026|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
'''
    for clock, row in cal.items():
        a = row['panels']['all']
        cells = [pct(row['panels']['year_' + str(y)]['compound_net_proxy']) for y in range(2020, 2027)]
        report += f"|{clock}|{a['mature']}|{pct(a['compound_net_proxy'])}|" + '|'.join(cells) + '|\n'
    report += f'''
五组全窗范围{pct(min(phase_compounds))}到{pct(max(phase_compounds))}，3/5为正；同时2022/2023为正仅1/5。phase_3的两个下跌年份为正是有利反证，完整保留，不能因为它有利就登记为优化结果。原贪心全窗约42.04%，2026却−13.67%，未修复总体目标。

## 其他五种表达也不隐藏

全部六种表达都采用相同时钟。下表仅汇总五组范围与符号，完整逐时钟/全部年度面板及意图在正式statistics.json。

|表达|五组成熟数范围|五组全窗复合范围|全窗正组数|2022/2023均正组数|原贪心全窗|
|---|---:|---:|---:|---:|---:|
'''
    family_summary = {}
    for name, clocks in schedules.items():
        rows = [clocks[clock] for clock in kernel.CLOCKS[1:]]
        values = [r['panels']['all']['compound_net_proxy'] for r in rows]
        counts = [r['panels']['all']['mature'] for r in rows]
        both = sum(all(r['panels']['year_' + str(y)]['compound_net_proxy'] is not None and r['panels']['year_' + str(y)]['compound_net_proxy'] > 0 for y in (2022, 2023)) for r in rows)
        family_summary[name] = {'phase_compound_min': min(values), 'phase_compound_max': max(values),
                                'positive_full': sum(v > 0 for v in values), 'positive_2022_and_2023': both}
        report += f"|{names[name]}|{min(counts)}–{max(counts)}|{pct(min(values))}–{pct(max(values))}|{sum(v > 0 for v in values)}/5|{both}/5|{pct(clocks['greedy']['panels']['all']['compound_net_proxy'])}|\n"
    report += '''
14项＋日期的五组全窗也从亏损到较高盈利，但2022代理五组均负。确认单分数有两组较高全窗代理，仍无一组兼顾两个下跌年。不能只将日期表达的最差组与旧表达的最好组比较，或把某一组代理误称为真实策略赢家。

## 原贪心收益集中与事后删项

|表达|成熟数/正盈利数|前10%正盈利数量|前10%正盈利贡献|最大盈利贡献|原复合|去最大盈利后|去前10%正盈利后|
|---|---:|---:|---:|---:|---:|---:|---:|
'''
    for name, clocks in schedules.items():
        a = clocks['greedy']['panels']['all']
        report += f"|{names[name]}|{a['mature']} / {a['positive_count']}|{a['top_positive_count']}|{pct(a['top_positive_contribution'])}|{pct(a['best_positive_contribution'])}|{pct(a['compound_net_proxy'])}|{pct(a['compound_without_best_positive'])}|{pct(a['compound_without_top10pct_positive'])}|\n"
    report += '''
日期155个成熟代理中80个盈利，最大一笔贡献全部正盈利的13.52%；去掉后全窗仍约+12.97%，所以不应说只靠一笔。最大的8个正盈利贡献36.82%，去掉后全窗约−26.27%。14项＋日期去掉最大一笔后仍约+11.51%，去掉10个最大盈利后约−35.38%。

这些反事实说明利润余量与一部分大盈利有关，但删除盈利本来就会降低几乎所有策略的收益，其他对照也如此；不能把删赢家后为负设成硬门或普遍无效判据。更关键的是五组机会时序不稳定、下跌年份余量薄及EX082整体信息增量未获支持的合并证据。

## 两个下跌年份和2024/2026的最强正反证

|日期原贪心入场年|成熟数|原复合|去本年最大盈利后|去本年前10%正盈利后|
|---|---:|---:|---:|---:|
'''
    for year in (2022, 2023, 2024, 2026):
        a = cal['greedy']['panels']['year_' + str(year)]
        report += f"|{year}|{a['mature']}|{pct(a['compound_net_proxy'])}|{pct(a['compound_without_best_positive'])}|{pct(a['compound_without_top10pct_positive'])}|\n"
    report += '''
2022只去掉本年最大一笔，正代理约3.66%便变为−1.70%；这笔入场信号为2022-10-31。2023去掉本年两个最大盈利后仍约+2.00%，表明这一年的支持更分散，不能删去此有利反证。2024最大机会入场为2024-09-25，单笔占本年全部正盈利41.42%；去本年前两大盈利后该年代理转负。2026只有19个成熟代理，均值不可得，复合亏损仍作为数量明确的描述保留。

## 被原时钟接受与跳过的正预测

这些机会仍可能重叠，跳过的不能在同一账户同时成交。

|表达|成熟接受/跳过正预测数|接受平均净代理|跳过平均净代理|
|---|---:|---:|---:|
'''
    for name, clocks in schedules.items():
        row = clocks['greedy']
        report += f"|{names[name]}|{row['panels']['all']['mature']} / {row['mature_blocked_positive']}|{pct(row['accepted_mean'])}|{pct(row['blocked_positive_mean'])}|\n"
    report += '''
日期原时钟接受平均约+0.2814%，跳过约+0.0444%，明显高于其重叠全部机会均值；但配对条件性区间包含零，尚不能说明时钟有可重复的择机能力。原确认接受均值还略低于被跳过机会，说明非重叠改善不是所有表达天然一样。

## 全部九项条件性区间

共享完整1635T轴，500次重叠40日块、seed13，原固定预测及入场掩码不重放、不重拟合。至少20有效样本、至少400次有效才报告LINEAR95%区间。本轮全部500次有效，九项区间均含零。相位均值最小值是五组诊断，不是标准32点Q10，不是未来成功概率；未校正研究历史与多重比较。

|预声明统计量|点估计|条件性95%区间|
|---|---:|---:|
'''
    for key in kernel.QUANTITIES:
        row = core[key]
        report += f"|{key}|{pct(row['value'])}|[{pct(row['ci95'][0])}, {pct(row['ci95'][1])}]|\n"
    report += '''
## 收口和下一步

原四项硬门不变；此轮没有新完整账户、没有新增硬门状态证明。年化收益Q10、回撤Q90、32点逐项/联合达标率、正式收益集中性和双费压力自检均不可得，不以代理代填。

当前日期第一谐波＋四日正均值预测路线不升级为账户。不挑phase_3，不调日期窗口、持有期、阈值或谐波救援；五组入场控制的敏感结果不是所有时间信息普遍无效的证明。原确认有限线索和日期2023有利余量仍作为历史事实保留。

下一步值得研究的是区分“是否扣费后盈利”与“盈利幅度有多大”的预测职责：收益均值很容易被少数大涨影响，而当前价量信息是否能辨别净盈利概率仍未由均值预测失败直接回答。先在相同成熟年度和原h4标签下做最小职责对照，同时呈现盈利概率、盈亏幅度和经济余量；若有新依据，再进入完整账户。此为后续研究方向，尚未执行，也不以胜率代替收益或原硬门。

总体目标仍未达成。追加额度已完成5/10（EX079–EX083），剩余5轮，最后EX088；使用完毕暂停，不启动EX089。正式报告完整副本保存在本实验others/report.md，逐字节及SHA256校验。
'''
    review = {'status': 'ROOT_SCIENTIFIC_REVIEWED', 'judgment': judgment, 'objective_achieved': False,
              'original_four_hard_gates_changed': False, 'new_economic_hard_gates': False,
              'new_accounts': 0, 'new_models': 0, 'family_clock_summary': family_summary,
              'append_account': False, 'favorable_counterevidence': 'Calendar2023 remains positive after top2winner omission; calendar full remains positive after best winner removal; phase3 positive2022/2023; all retained',
              'next_direction': 'Distinguish net profit probability and win/loss magnitude in mature annual forecasting; no classification executed this round',
              'evidence_references': {key: refs[key] for key in ('plan.json', 'statistics.json', 'verification.json')},
              'report_markdown': report}
    d.write(d.OUT / 'root_review.json', review)
    refs['root_review.json'] = d.put(ctx, exp, d.OUT / 'root_review.json')
    refs['closeout_driver.py'] = d.put(ctx, exp, Path(__file__))
    budget = {'status': 'ROUND5_COMPLETED_SUBJECT_TO_FULL_CLOSEOUT', 'authorization_reference': plan['continuation_budget_reference'],
              'maximum_additional_experiments': 10, 'started': 5, 'completed': 5, 'remaining': 5,
              'completed_experiment': exp.to_dict(), 'next_allowed': 'EX084', 'last_allowed': 'EX088',
              'pause_after_EX088': True, 'new_accounts_this_round': 0, 'objective_achieved': False}
    d.write(d.OUT / 'budget_receipt.json', budget)
    refs['budget_receipt.json'] = d.put(ctx, exp, d.OUT / 'budget_receipt.json')
    for value in (*refs.values(), *plan['input_references'].values(), plan['continuation_budget_reference']):
        d.public(value)
    tests = tuple(m.ComponentTestResult('CLOCK-' + name, exp.experiment_id, EvidenceRef.from_dict(refs['plan.json']),
                  m.ComponentTestStatus.INEFFECTIVE, explanation,
                  tuple(EvidenceRef.from_dict(refs[k]) for k in ('statistics.json', 'verification.json', 'root_review.json')))
                  for name, explanation in (
                      ('OPPORTUNITY-STABILITY', '当前日期有利代理未稳定跨五组预设入场时点，只有一组同时2022/23为正；不选择赢家组或将其代替32点'),
                      ('PROFIT-MARGIN', '2022利润余量去最大一笔即负，2023删本年前两大盈利仍正，保留有利反证；不将事后删项设成硬门')))
    entry = m.ComponentEntry('CALENDAR-OPPORTUNITY-CLOCK-ATTRIBUTION',
        m.ExperimentDefinitionRef(EvidenceRef.from_dict(refs['.tmp/s013-calendar-clock/kernel.py']), 'entries'),
        '原日期等表达的固定入场时序与盈利余量归因，非新增可交易Alpha',
        '原HFQ h4扣费OPEN价格代理，非连续自然年账户', '固定h4与5交易日候选间隔',
        '六列EX082原预测复用、原贪心＋五组原T相位全保留，无选相位',
        'T因果计数及T原预测，未来标签只事后归因，不作信号',
        '原510500已见开发池HFQ固定锚/无分红叠加/原费用及1%执行合同保持；0账户',
        '机会数/持仓不同，删盈利是事后诊断；已见样本未校正研究选择；非真实账户或32点自检',
        judgment, tests)
    evidence = tuple(dict.fromkeys(EvidenceRef.from_dict(v) for v in (*refs.values(), *plan['input_references'].values(), plan['continuation_budget_reference'])))
    report += '\n\n正式证据：\n\n' + ''.join(f'- [{name}]({EvidenceRef.from_dict(ref).path})\n' for name, ref in refs.items())
    predecessors = tuple(m.DeliveryReference.from_dict(v) for v in plan['predecessors'])
    receipt = assemble_delivery(ctx.repository,
        m.DeliveryDefinition(m.ResearchBatchRef('S013'), m.DeliveryStage.COMPONENTS, 17, predecessors),
        m.DeliveryContent(m.ComponentPanel((entry,), judgment), m.DeliveryStatus.COMPLETE, (), (), report=report, evidence=evidence))
    d.write(path / 'protocols/delivery_reference.json', receipt.reference.to_dict())
    validation = validate_delivery(ctx.repository, receipt.reference, scope=m.DeliveryValidationScope.FULL)
    d.write(path / 'protocols/delivery_validation.json', validation.to_dict())
    d.write(path / 'protocols/closeout_references.json', refs)
    if validation.status.value != 'PASS':
        raise RuntimeError(validation.to_dict())
    formal, copy = ROOT / 'research/S013/deliveries/COMPONENTS/17/report.md', path / 'others/report.md'
    with copy.open('xb') as stream:
        stream.write(formal.read_bytes())
    assert copy.read_bytes() == formal.read_bytes()
    d.write(path / 'protocols/report_copy_verification.json', {'status': 'PASS', 'formal_report': formal.relative_to(ROOT).as_posix(),
            'experiment_report': copy.relative_to(ROOT).as_posix(), 'formal_sha256': d.digest(formal),
            'copy_sha256': d.digest(copy), 'exact_bytes': True,
            'human_instruction': 'RSCH，请在后续的每个实验目录下保存一份report副本'})
    with (path / 'src/closeout_driver.py').open('xb') as stream:
        stream.write(Path(__file__).read_bytes())
    assert not c.SOURCE_CALLS
    print({'experiment': exp.experiment_id, 'COMPONENTS': 17, 'FULL': 'PASS', 'report_copy': 'EXACT', 'completed': 5, 'remaining': 5})


if __name__ == '__main__':
    run()
