"""Root review, formal EX081 negative component delivery and report copy."""
from pathlib import Path
import sys
from czsc_trader.application import assemble_delivery, validate_delivery
from czsc_trader.research_tools import delivery as m
from czsc_trader.research_tools.evidence import EvidenceRef

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
sys.path.insert(0, str(ROOT / '.tmp'))
import s013_context_driver_v2 as d


def run():
    exp, plan = d.stage()
    path = exp.resolve(ROOT)
    ctx = d.base.common().context(1)
    refs = {**d.read(path / 'protocols/method_references.json'), **d.read(path / 'protocols/caller_repair_references.json'),
            **d.read(path / 'protocols/result_references.json'), 'verification.json': d.read(path / 'protocols/audit_reference.json')}
    stats = d.read(d.public(refs['statistics.json']))
    audit = d.read(d.public(refs['verification.json']))
    if audit['status'] != 'PASS' or audit['new_accounts'] or stats['new_accounts'] or stats['new_annual_models'] != 12:
        raise ValueError('Actual full independent zero-account result required')
    if audit['result_references'] != d.read(path / 'protocols/result_references.json') or audit['plan_reference'] != refs['plan.json']:
        raise ValueError('Independent audit must bind exact results/method')
    kernel = d.base.load('context_review_kernel', d.WORK / 'kernel.py')
    if tuple(stats['bootstrap']['summary']) != kernel.QUANTITIES:
        raise ValueError('All ten prospective quantities required')
    core = stats['bootstrap']['summary']
    # Root judgment from adverse utility and economic margins, not a new hardgate.
    if not (core['interaction_mse_improvement_vs_control']['value'] < 0
            and core['interaction_positive_mean']['value'] < 0
            and core['control_mse_improvement_vs_confirmation']['ci95'][1] < 0):
        raise ValueError('This root negative review no longer matches actual evidence')
    judgment = '本轮固定涨跌方向主效应与确认交互未增加可用净机会识别能力；停止此表达，不追加完整账户，不调期限、分界、符号或正则系数救援。原确认有限线索保留为历史事实，仍不足以独立实现原四门和抗扰动目标。'
    pct = lambda x: '不可得' if x is None else f'{100 * x:.4f}%'
    report = f'''# EX081：确认信息是否需要结合涨跌状态

{judgment}

通俗说，同样的“价格有延续性、交易较活跃”，在上涨与下跌时可能意味着不同的事情。本轮固定原20日涨跌方向，与确认分数做最小嵌套对照：先同时使用两个因素，再只增加“确认分数×涨跌方向”一个关系项。该关系能解释历史训练样本，却没有改善后续年份的预测和选中机会。

## 事前方法与范围

原510500.SH开发池，原后复权固定锚，无分红现金叠加；原14项共同完整行、1635个信号T、原四日标签Open[T+5]/Open[T+1]×.999/1.001−1。确认仍是原ADJUSTED120分数；涨跌方向是原momentum20的正/负/零，不拟合分界。

年度训练只用2020起、早于测试年度且标签已成熟的数据；训练ECDF、中点并列秩、固定ridge10、不惩罚截距。2020无预测，尾部有特征但缺少未来标签时保留预测。不使用未来全年的测试样本数控制当前预测。

新主效应对照与交互表达各6次年度拟合，共12个新年度模型；原历史均值、确认单分数及14项联合的全部预测精确复用。独立标量正规方程、因果日期、正预测判定、全部分组、持有时钟、500次×10项重抽样记录复算通过。本轮0新账户、0数据拉取、0新增资产、0参数扫描。

## 核心预测结果

“改善”以正数表示误差降低；负数表示误差增加。所有比较使用相同的1388个成熟预测T。

|固定比较|相对MSE改善|共享40日块95%区间|
|---|---:|---:|
'''
    names = [('交互 vs 两个主效应对照', 'interaction_mse_improvement_vs_control'),
             ('两个主效应 vs 原确认单分数', 'control_mse_improvement_vs_confirmation'),
             ('交互 vs 原确认单分数', 'interaction_mse_improvement_vs_confirmation'),
             ('交互 vs 历史均值', 'interaction_mse_improvement_vs_mean'),
             ('两个主效应 vs 历史均值', 'control_mse_improvement_vs_mean')]
    for label, key in names:
        row = core[key]
        report += f"|{label}|{pct(row['value'])}|[{pct(row['ci95'][0])}, {pct(row['ci95'][1])}]|\n"
    report += '''
简单增加涨跌方向也不能带来更好的预测：相对原确认误差恶化的条件性区间没有包含零；再加交互的点估计更差，区间仍跨零。这里的MSE是预测诊断，不是新经济硬门，也不是以预测误差替代账户收益。

## 正预测机会的扣费后结果

以下均为允许信号重叠的四日OPEN价格代理，非真实账户年化收益。

|模型|正预测数|成熟正预测数|平均净代理收益|误报比例|
|---|---:|---:|---:|---:|
'''
    labels = {'training_mean': '历史均值（复用）', 'confirmation_only': '原确认单分数（复用）',
              'original14_joint': '原14项联合（复用）', 'confirmation_trend': '确认＋涨跌主效应',
              'confirmation_trend_interaction': '主效应＋单一交互'}
    for model, title in labels.items():
        row = stats['panels']['all'][model]
        report += f"|{title}|{row['positive_forecasts']}|{row['mature_positive']}|{pct(row['positive_mean'])}|{pct(row['false_positive_rate'])}|\n"
    difference = core['interaction_positive_mean_minus_confirmation']
    report += f"\n交互表达选中机会的平均净收益，比原确认少{100 * -difference['value']:.4f}个百分点；条件性95%区间为[{100 * difference['ci95'][0]:.4f}, {100 * difference['ci95'][1]:.4f}]个百分点。它没有修复原2022/2023下跌年份的问题。\n"
    report += '''
## 全部年度反证

表中是正预测且标签成熟的机会均值；不是账户年收益，样本不足20时不可得。

|年份|原确认数量/均值|两个主效应数量/均值|交互数量/均值|
|---|---:|---:|---:|
'''
    for year in range(2020, 2027):
        cells = []
        for model in ('confirmation_only', 'confirmation_trend', 'confirmation_trend_interaction'):
            row = stats['panels']['year_' + str(year)][model]
            cells.append(f"{row['mature_positive']} / {pct(row['positive_mean'])}")
        report += f"|{year}|" + '|'.join(cells) + '|\n'
    report += '''
## 有利反证与限制

训练出来的交互系数在六次年度拟合中均为正，符合原假设；但训练关系并未兑现为后续收益提升。不能用训练系数符号代替后续检验，也不能由这一固定表达失败推断所有价格状态或非线性机制都无效。

按相同四日贪心时钟、到期不重入，非重叠价格代理结果如下。没有末期强平，缺少未来标签的最后意图保留。

|表达|入场意图/成熟代理|成熟代理平均净收益|成熟代理复合收益|
|---|---:|---:|---:|
'''
    for model in labels:
        if model == 'training_mean':
            continue
        row = stats['nonoverlap_proxies'][model]
        report += f"|{labels[model]}|{row['accepted']} / {row['mature']}|{pct(row['mean_proxy'])}|{pct(row['compound_proxy'])}|\n"
    control_proxy = stats['nonoverlap_proxies']['confirmation_trend']
    control_cagr = (1 + control_proxy['compound_proxy']) ** (252 / 1636) - 1
    report += f'''
两个主效应的非重叠代理优于原确认，这是本轮必须保留的有利反证：不能因MSE较差就声称其账户一定更差。其完整区间复合代理{pct(control_proxy['compound_proxy'])}折算年化约{pct(control_cagr)}，仍只是描述，未证明原整体收益门或下跌年份盈利门，更未证明抗标准扰动。原确认本轮的194/193代理意图及收益与EX080一致，说明时钟对照没有换口径。

入场时序和信号重叠会改变抽到的机会。非重叠均值改善不是新的信息增量证据，也不是基于完整限价、整手、现金、费用和最终持仓的账本；不作为真实闭合交易计数。原2022/2023重叠机会均值更差、预测关系无增量、薄净利润及既有EX080真实反证共同支持当前不追加账户的研究判断。它不是新设MSE或置信区间硬门。

区间采用共享完整1635T轴500次重叠40日块，种子13，原始/重抽样有效分组至少20、至少400有效才报LINEAR95区间，全部5000项记录留存；年度模型不重拟合。十项区间均为固定预测下的条件性探索诊断，未校正历史重复研究及多重比较，不是未来获利概率或封存验证。

## 验收、技术留证与下一步

原四项经济要求、只做多及固定1%执行合同均不变。本轮只有组件统计，没有新完整账户，原硬门状态未取得新证据；五项策略自检未启动，参数收益Q10、回撤Q90、32点逐项/联合达标率及双费结果均不可得，不填0或写通过。

原prices.csv成交价列名是严格小写open，初次输入核验在进入分析前因使用Open而拒绝；同EX调用方修正已留证，核心方法/源码和数据未改变。实际统计分析1次，新年度模型12个，账户0个。独立复算通过，科学结论为当前表达不支持继续进入账户。

停止确认＋单一涨跌方向/交互这条固定表达，不用换期限、分界、符号或alpha补救。下一步在既有数据与额度内转向有不同依据的信息或功能表达，首先检验净盈利余量；不把单轮结束当作总体目标达成。

新增额度已完成3/10（EX079–EX081），剩余7轮，最后允许EX088；用完暂停，不启动EX089。正式报告完整副本保存到实验others/report.md，逐字节及SHA256校验。
'''
    review = {'status': 'ROOT_SCIENTIFIC_REVIEWED', 'judgment': judgment, 'objective_achieved': False,
              'original_four_hard_gates_changed': False, 'new_economic_hard_gates': False, 'new_accounts': 0,
              'component_status': 'INEFFECTIVE', 'append_account': False,
              'favorable_counterevidence': 'Positive6annual interaction coefficients; additive control nonoverlap proxy better than original confirmation; not suppressed or treated as account failure proof',
              'evidence_references': {k: refs[k] for k in ('plan.json', 'statistics.json', 'verification.json')},
              'report_markdown': report}
    d.write(d.OUT / 'root_review.json', review)
    refs['root_review.json'] = d.put(ctx, exp, d.OUT / 'root_review.json')
    refs['closeout_driver.py'] = d.put(ctx, exp, Path(__file__))
    budget = {'status': 'ROUND3_COMPLETED_SUBJECT_TO_FULL_CLOSEOUT', 'authorization_reference': plan['continuation_budget_reference'],
              'maximum_additional_experiments': 10, 'started': 3, 'completed': 3, 'remaining': 7,
              'completed_experiment': exp.to_dict(), 'next_allowed': 'EX082', 'last_allowed': 'EX088',
              'pause_after_EX088': True, 'new_accounts_this_round': 0, 'objective_achieved': False}
    d.write(d.OUT / 'budget_receipt.json', budget)
    refs['budget_receipt.json'] = d.put(ctx, exp, d.OUT / 'budget_receipt.json')
    for value in (*refs.values(), *plan['input_references'].values(), plan['continuation_budget_reference']):
        d.public(value)
    tests = tuple(m.ComponentTestResult('CONTEXT-' + name, exp.experiment_id, EvidenceRef.from_dict(refs['plan.json']),
                  m.ComponentTestStatus.INEFFECTIVE, explanation,
                  tuple(EvidenceRef.from_dict(refs[k]) for k in ('statistics.json', 'verification.json', 'root_review.json')))
                  for name, explanation in (
                      ('MAIN-EFFECTS', '涨跌主效应使预测误差相对原确认增加约0.617%，条件性区间为不利；非重叠代理的有利结果完整保留，但无原四门账户证明'),
                      ('ONE-INTERACTION', '一个交互项没有提高后续净机会识别；正预测机会均值转负，2022/23未改善；不是全状态机制普遍无效的证明')))
    entry = m.ComponentEntry('CONFIRMATION-SIGNED-MOMENTUM20-INTERACTION',
        m.ExperimentDefinitionRef(EvidenceRef.from_dict(refs['.tmp/s013-confirm-context/kernel.py']), 'design'),
        '确认信息作用关系：两个主效应对照与单一涨跌状态交互',
        '固定原HFQ下一OPEN至第五未来OPEN乘.999/1.001−1；净价格代理', '原h4，不扫描期限',
        '成熟年度ECDF/ridge10；旧均值/确认/14联合复用；新两模型嵌套对照',
        'T完成可得原ADJUSTED120确认与原20日动量符号；标签严格成熟后才训练；无未来测试数门',
        '原510500.SH开发池HFQ固定锚、无现金分红叠加、原资金/费用/限价合同保持；0账户',
        '同一已见开发池适应性探索、重叠标签及非重叠代理不是真实账户；无新四门或五自检证明，条件性区间未校正选择',
        judgment, tests)
    evidence = tuple(dict.fromkeys(EvidenceRef.from_dict(v) for v in (*refs.values(), *plan['input_references'].values(), plan['continuation_budget_reference'])))
    report += '\n\n正式证据：\n\n' + ''.join(f'- [{name}]({EvidenceRef.from_dict(ref).path})\n' for name, ref in refs.items())
    predecessors = tuple(m.DeliveryReference.from_dict(x) for x in plan['predecessors'])
    receipt = assemble_delivery(ctx.repository,
        m.DeliveryDefinition(m.ResearchBatchRef('S013'), m.DeliveryStage.COMPONENTS, 15, predecessors),
        m.DeliveryContent(m.ComponentPanel((entry,), judgment), m.DeliveryStatus.COMPLETE, (), (), report=report, evidence=evidence))
    d.write(path / 'protocols/delivery_reference.json', receipt.reference.to_dict())
    validation = validate_delivery(ctx.repository, receipt.reference, scope=m.DeliveryValidationScope.FULL)
    d.write(path / 'protocols/delivery_validation.json', validation.to_dict())
    d.write(path / 'protocols/closeout_references.json', refs)
    if validation.status.value != 'PASS':
        raise RuntimeError(validation.to_dict())
    formal = ROOT / 'research/S013/deliveries/COMPONENTS/15/report.md'
    copy = path / 'others/report.md'
    with copy.open('xb') as stream:
        stream.write(formal.read_bytes())
    if formal.read_bytes() != copy.read_bytes():
        raise ValueError('Report copy differs')
    d.write(path / 'protocols/report_copy_verification.json', {'status': 'PASS', 'formal_report': formal.relative_to(ROOT).as_posix(),
           'experiment_report': copy.relative_to(ROOT).as_posix(), 'formal_sha256': d.digest(formal), 'copy_sha256': d.digest(copy),
           'exact_bytes': True, 'human_instruction': 'RSCH，请在后续的每个实验目录下保存一份report副本'})
    for name, ref in refs.items():
        if name.endswith('.py'):
            content = d.public(ref).read_bytes()
            target = path / 'src' / ('closeout_' + Path(name).name)
            if target.exists():
                if target.read_bytes() != content:
                    raise ValueError('Source retention collision')
            else:
                with target.open('xb') as stream:
                    stream.write(content)
    print({'experiment': exp.experiment_id, 'COMPONENTS': 15, 'FULL': 'PASS', 'report_copy': 'EXACT', 'completed': 3, 'remaining': 7}, flush=True)


if __name__ == '__main__':
    run()
