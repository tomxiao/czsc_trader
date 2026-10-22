"""Deliver the fixed entry-day contrast and preserve prior component evidence."""
import argparse
from hashlib import sha256
from pathlib import Path

from entry_day_study import ROOT, HERE, EX, COLS, read, save, material, context, sources
from czsc_trader.application import (
    RepositoryContext, publish_evidence, assemble_delivery, validate_experiment,
    update_research_intent, ResearchIntentUpdate,
)
from czsc_trader.research_tools import (
    EvidenceRef, ExperimentReportWrite, ExperimentOutcome, ExperimentValidationRequest,
    ExperimentValidationScope, ResearchBatchRef,
)
from czsc_trader.research_tools import delivery as d


def pct(v):
    return '不适用' if v is None else f'{v:.2%}'


def report():
    r = read(HERE/'others/results.json')
    text = '''# S015 阶段二固定对照：未建立入场日亏损辨别能力，过滤会错过较多盈利

Status: COMPLETED

RSCH，2026-10-23。用户已批准自主完成EX014所提阶段二固定对照。本项研究任务已完成；没有发现足以支持入场过滤的新增有效信息，S015收益与回撤双优目标仍未达成。建议收口本次固定输入和模型路线，不据此进入阶段三。

## 直接回答用户关切

**能否识别买入当天的亏损？本次没有建立可靠的增量辨别能力。** 完整日线模型AllDaily比基础日线模型PR的预测均方误差高2.30%，四个时间段均变差。PR、AllDaily相对仅用过去平均值预测也分别差2.18%、4.53%。这不是模型训练失败，而是按既定方法检验得到的负面研究结果。

**会错过多少盈利？在原C0031实际首次入场对应的82个测试机会中，AllDaily拟筛除16个，其中10个当天盈利、6个亏损。** 按每个机会独立10万元且仅扣一次入场费，低组包含6147.10元负金额，占全部负金额12.07%；同时包含16154.16元正金额，占全部正金额17.57%。两者相差10007.07元，筛掉的这一组本身在该标签上仍为正。金额不能当成更改策略后会减少或增加的实际账户利润。

## 固定方法与真实覆盖

依据[事前协议](protocols/fixed_contrast.json)，唯一拟合目标为T+1实际可成交份额从成交价至当天收盘的有符号毛损益/10万元。另列一次买入费及扣费后结果；没有虚构当日卖出，没有计入次日退出，也不使用可能发生在成交之前的日内最低价。原1%限价、100份整手、最大100万份、HFQ_RESEARCH价格及DAILY_RANGE_V3规则不变。

仅复用原434个决策日（2025-01-02至2026-10-21）及75日预热、已认证特征和已准备日线数据。原415日S011比较窗口与基线保持不变。本项没有新策略账户，不能重判任何候选的双窗口资格。

- 434个决策日生成426个可成交标签、7个买入未成交、1个右端缺失；未成交或缺失不填0。相对旧h1标签多恢复1个有效事件，因为这里只需T+1收盘，不需T+2退出。
- 沿用原四段向前检验位置，训练有效样本99/182/265/345个，测试83/83/80/80个，合计326个。测试决策日2025-06-06至2026-10-20，末次成交日2026-10-21；前100个开发决策日用于初始训练，不冒充测试证据。
- PR使用近1日/5日收益、20日波动、卖压、振幅。AllDaily再加已有的开收盘变化、20日趋势位置、收盘区间位置、下影、五日有向效率；合计覆盖原8种日线定义，剔除重复列后10个输入。没有新增数据或分钟组件。
- 唯一成对条件、一个毛标签、固定岭回归alpha=10、四段训练；训练标签结束日严格早于测试起点，标准化仅用训练数据。训练均值只作无信息参照。没有参数、方向、期限或分组阈值搜索。
- 每个模型以自身训练内拟合预测值的三分位划分低/中/高，测试时沿用固定界限；只将低组作为假设筛除组。界限并非独立校准，测试低组不必占1/3。所有组完整报告，不根据结果改筛中组或反转方向。
- C0031旧434日账户共105个实际持仓周期；1次入场的信号日在决策窗口之前，余104次匹配成交日期与价格，其中82次进入向前测试。子集只标识每个周期首次买入，补买不计；独立10万元数量与原账户实际数量分开保存。它是已选策略形成的描述子集，不是模型输入，也不是独立样本。

## 识别能力与盈利机会代价

下表只汇总测试事件。负金额捕捉比例的分母是全部负金额绝对值；正金额错失比例的分母是全部正金额；金额为每个独立10万元事件的加总，不能作为连续投资回报。低组人数与覆盖率用同一测试集合计算。扣入场费后仍没有扣卖出费或后续持仓盈亏。

| 集合 | 模型 | 低组/全部 | 覆盖率 | 毛亏损识别精度 | 毛亏损笔数召回 | 扣入场费后负金额/元 | 捕捉负金额 | 同时错失正金额/元 | 错失正金额 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
'''
    for key,label in [('all','全部测试机会'),('actual_C0031_first_entry','C0031实际首次入场')]:
        s = r[key]
        for model in COLS:
            m = s['models'][model]
            gross,net = (m['groups']['-1'][k] for k in ('gross','net_entry'))
            text += (f"| {label} | {model} | {gross['n']}/{s['n']} | {pct(m['exclusion_fraction'])} | "
                f"{pct(gross['loss_precision'])} | {pct(gross['loss_count_recall'])} | {net['negative_yuan']:.2f} | "
                f"{pct(net['captured_negative_fraction'])} | {net['positive_yuan']:.2f} | {pct(net['missed_positive_fraction'])} |\n")
    text += '''
精度指被标低的机会中实际毛亏损比例；召回指全部毛亏损机会有多少被标低。全部测试毛亏损比例为44.17%，AllDaily低组47.10%，只略有提高；实际入场子集毛亏损比例37.80%，AllDaily低组37.50%，没有亏损集中效果。按预测是否小于0判断亏损的平衡准确率（分别计算亏损与非亏损的正确率再平均），AllDaily全部测试为50.65%，实际入场为46.30%，不能据此声称可靠识别。

毛损益口径下，AllDaily全部低组捕捉40.29%负金额、错失33.62%正金额；实际入场低组只捕捉11.63%负金额、错失17.70%正金额。两类百分比分母不同，即使捕捉负比例高于错失正比例，也不自动代表金额得失划算。全部测试低组毛损益+9657.40元，扣入场费后−3978.00元；实际入场低组毛损益+11586.30元，扣入场费后+10007.07元。

### 模型换组带来的代价

AllDaily筛除138个机会，PR筛除132个，覆盖不同，不能只比捕获亏损绝对值。两模型共同低组115个；AllDaily新增低组23个、放回PR低组17个。新增低组的扣费后正金额24062.32元、负金额12045.48元；放回组正金额7518.09元、负金额6447.90元。新增信息更多地筛掉了有盈利贡献的机会。

在实际入场子集中，两模型共同低组10个；AllDaily新增筛掉6个、放回2个。新增6个虽然4亏2盈，但扣入场费后正金额10104.97元，负金额4274.42元；说明“识别出更多亏损笔数”仍可能错过少数较大的盈利。完整四种换组关系保留于[结果](others/results.json)。

### 三组全部保留，防止事后换筛选方向

| 集合 | 模型 | 低/中/高人数 | 低组扣费后有符号金额/元 | 中组金额/元 | 高组金额/元 |
| --- | --- | ---: | ---: | ---: | ---: |
'''
    for key,label in [('all','全部'),('actual_C0031_first_entry','实际入场')]:
        for model in COLS:
            z = r[key]['models'][model]['groups']
            counts = '/'.join(str(z[str(k)]['gross']['n']) for k in (-1,0,1))
            text += f"| {label} | {model} | {counts} | " + ' | '.join(f"{z[str(k)]['net_entry']['signed_yuan']:.2f}" for k in (-1,0,1)) + ' |\n'
    text += '''
这些金额总和受组大小影响，不是组均值或可执行净值。AllDaily中组出现负金额，而低组在实际入场中仍为正，说明排序和经济区分并不充分；本轮没有据此改为筛中组。

## 时间反证与不确定性

改善率=1−AllDaily均方误差/PR均方误差，负数表示新增输入更差，不能解释为账户收益变化。以下年份按信号日归属，都是不完整年份；不是逐年独立投入本金的账户。

| 时间范围 | 测试数 | 预测误差改善率 | AllDaily低组数 | 捕捉毛负金额 | 错失毛正金额 |
| --- | ---: | ---: | ---: | ---: | ---: |
'''
    for name,s in [*r['years'].items(),*[(f'第{int(k)+1}段',v) for k,v in r['periods'].items()]]:
        low = s['models']['AllDaily']['groups']['-1']['gross']
        text += f"| {name} | {s['n']} | {pct(s['AllDaily_gain_vs_PR'])} | {low['n']} | {pct(low['captured_negative_fraction'])} | {pct(low['missed_positive_fraction'])} |\n"
    ci = r['intervals']['20']['AllDaily_gain_vs_PR']['interval']
    actual_ci = r['actual_intervals']['20']['AllDaily_gain_vs_PR']['interval']
    text += f'''
全部测试误差改善−2.30%；2025为+0.87%、2026为−3.78%，四段分别−1.81%、−2.41%、−2.48%、−2.22%。年度与分段划分不同，年度合并结果不与分段符号矛盾。删去5个绝对毛标签最大事件后，改善仍为{pct(r['drop5_extreme']['AllDaily_gain_vs_PR'])}；实际入场子集为{pct(r['actual_C0031_first_entry']['AllDaily_gain_vs_PR'])}。

20个有效事件块的探索性95%区间：误差改善[{pct(ci[0])}, {pct(ci[1])}]，实际入场子集[{pct(actual_ci[0])}, {pct(actual_ci[1])}]。两者均跨0，不能证明真实误差一定更差，也不能据此主张有正增量。毛负金额捕捉比例减毛正金额错失比例的区间，全部为[−6.21,17.42]个百分点，实际入场为[−21.93,10.18]个百分点，同样不稳定。

区间使用固定种子13、10/20个连续有效事件为块、499次共同抽样；未成交日已经被过滤，因此不是严格10/20交易日块。实际入场子集在全有效事件序列抽样后再取子集，避免将稀疏入场直接连排。区间只重采样既有预测结果，没有重新训练和重新选择，未校正长期开发选择，不能当作独立验证或确认性显著。

原训练预测分位点在第一测试段把AllDaily的60/83个事件划为低组，覆盖72.29%，展示了训练到测试分布变化；没有以测试分位点重新凑成1/3。该问题是方法局限，不能结果出来后追加校准优化并算在同一固定对照内。

### 对此前主要回撤的事后解释性核对

在结果已生成后，仅取EX014已经确定的2026-06-30至2026-07-20回撤区间查看原C0031实际首次入场，作为解释性案例，不增加拟合或假设检验：7月2、8、13、16日的4次入场，当天独立事件毛标签全负；PR均列高组，AllDaily列中/高/高/高。预定低组过滤一个也没标出。它直接限制了“这套过滤能解决已定位的7月损失”的解释，但不能由一个已见区间推广为所有行情。

## 研究结论与下一步

本次把标签准确对齐到了损失发生段，仍未建立新增日线组合在PR之外的有效辨别能力。仅定位损失发生在入场当天，并不能推出已有信息足以提前规避。尤其原策略实际入场集合，正机会代价大于捕捉的负金额，简单照搬全日事件过滤缺乏支持。

建议现在停止本项固定输入、模型与标签路线的扩展，不自动追加分钟阈值、反向分组、邻近参数或策略回测。原阶段二分钟负面证据、EX013的0/86双优结果均保留，未恢复旧选型、冻结或PTE授权。结论只约束这项固定方法和已研究用途，不能扩张为现有数据绝无信息、所有模型皆无效。

若用户希望继续，应先提出相对现有实验有独立机制依据的新研究假设，再评审所需信息、范围和最小对照；不以“还有参数没试过”作为继续依据。本项没有足够理由请求直接进入阶段三。策略目标、原434日开发池及415日严格比较要求均不修改。

## 验证与正式交付

输入EvidenceRef、预发布协议与实际执行源码一致；全部425个与旧h1重叠的可成交事件，数量、限价、成交价复算一致，7个未成交状态一致；新标签按价量及一次买入费独立验算。326行日期唯一，训练标签时序和相同有效集合核对通过，无开发决策日特征缺失。

首fold做了后续标签及后续特征扰动隔离，结果完全不变；其余fold以源码和显式训练边界核对支持，没有宣称逐fold都执行了动态未来扰动。另用带惩罚的增广最小二乘独立复算全部8次模型拟合，预测最大差小于1.2e−16，三分位分组完全相同。这些是技术验证复算，仍为唯一一个研究对照，不增加假设数量。

检查见[主检查](others/checks.json)、[独立复核](others/independent_audit.json)和[标签覆盖](others/label_checks.json)。原117个候选登记哈希全部不变，新增策略账户和候选均为0。测试没有扩展到仓库全量回归或完整策略验收。

本轮正式交付COMPONENTS/7，继承COMPONENTS/6。保留12个既有单项组件记录，新增1条“已有日线组合的入场日用途检验”结构化组合记录，状态INEFFECTIVE；这是试验归档条目，不是发现第13个独立信息组件。累计研究成对条件由66到67；共享数据、标签选择和模型变更使它们不是67份独立证据。INEFFECTIVE表示本次用途证据不足，不改写历史支持或增加经济硬门。

技术装配与报告发布校验只认证身份和交付链，不代表经济目标通过。历史数据发布时钟、调整价可得性及日价格区间成交路径局限保留。所有历史已被多轮开发观察，本轮向前计算不是新的独立保留样本。

报告、源码、标签、预测、完整正负结果和引用显式关联正式证据。Git提交保存研究工作材料及引用；assets/evidence/EX015_20261023/、assets/deliveries/COMPONENTS/7/及继承资产需独立保留。已核验EX013概览在同工作段复用，本轮核对新交付、报告和117个候选未变，不声称又做了全仓概览或原434日FULL重算。不合并master、不推送、不打tag，不变更生产。
'''
    (HERE/'report.md').write_text(text,encoding='utf-8',newline='\n')
    return text


def publish():
    assert not (HERE/'others/delivery_validation.json').exists()
    assert read(HERE/'others/checks.json')['status'] == read(HERE/'others/independent_audit.json')['status'] == 'PASS'
    text = report()
    refs = [EvidenceRef.from_dict(v) for v in read(HERE/'others/protocol_refs.json').values()]
    refs += list(sources().values())
    prior = ROOT/'research/S015/experiments/EX012_20261023'
    refs += [EvidenceRef.from_dict(v) for v in read(prior/'others/published_refs.json')['references']]
    materials = {}
    for p in [*sorted((HERE/'others').glob('*.csv')),
              *[HERE/'others'/n for n in ('results.json','label_checks.json','checks.json','independent_audit.json')],
              HERE/'src/audit.py',Path(__file__)]:
        ref = material(p)
        refs.append(ref)
        materials[p.name] = ref.to_dict()
    refs = list(dict.fromkeys(refs))
    report_ref = publish_evidence(context(), ExperimentReportWrite(EX,sha256((HERE/'report.md').read_bytes()).hexdigest(),ExperimentOutcome.COMPLETED,tuple(refs)))
    refs.append(report_ref)
    save(HERE/'others/published_refs.json',{'references':[v.to_dict() for v in refs]})
    receipt = read(ROOT/'research/S015/deliveries/COMPONENTS/6/receipt.json')
    path = ROOT/'research/S015/assets/deliveries/COMPONENTS/6/delivery.json'
    assert sha256(path.read_bytes()).hexdigest() == next(v['sha256'] for v in receipt['files'] if v['path']=='delivery.json')
    panel = d.ComponentPanel.from_dict(read(path)['content']['payload'])
    protocol = EvidenceRef.from_dict(read(HERE/'others/protocol_refs.json')['fixed_contrast.json'])
    source = EvidenceRef.from_dict(read(HERE/'others/protocol_refs.json')['entry_day_study.py'])
    evidence = EvidenceRef.from_dict(materials['results.json'])
    test = d.ComponentTestResult('ex015-entry-day-PR-vs-AllDaily', EX.experiment_id,protocol,
        d.ComponentTestStatus.INEFFECTIVE,
        '唯一固定日线组合用途检验：AllDaily较PR误差恶化2.30%，四段均差；实际入场扣入场费后捕捉12.07%负金额同时错失17.57%正金额。未建立可靠增量；非经济硬门。',(evidence,))
    entry = d.ComponentEntry('existing_daily_bundle_entry_day',d.ExperimentDefinitionRef(source,'predict'),
        '既有日线组合的入场日亏损辨别用途；组合对照记录，不是新增独立信息组件',
        'T+1实际成交至收盘毛损益/独立10万元；单列一次入场费后标签',
        '成交至当日收盘，不假设当日卖出','PR对比AllDaily，alpha10、四段、训练预测三分位',
        '特征只用T日及以前；历史17:30发布时钟仍未认证','原限价合同与HFQ_RESEARCH',
        '159326.SZ已见434日开发池；全部机会及已选C0031实际入场描述子集',
        '本用途未证实增量，机会代价明显；停止本项路线，不据此进入阶段三；不否定所有潜在模型。',(test,))
    assert len(panel.components) == 12
    final_panel = d.ComponentPanel((*panel.components,entry),
        '阶段二固定对照完成：保留12单项组件与1组合用途记录，累计67个成对条件；没有新增有效独立组件。入场日标签对齐后仍无足够识别依据，建议收口该路线。')
    adapted = text.replace('](others/',f'](../../../experiments/{EX.experiment_id}/others/').replace('](protocols/',f'](../../../experiments/{EX.experiment_id}/protocols/')
    repo = RepositoryContext.discover(ROOT)
    assembled = assemble_delivery(repo,
        d.DeliveryDefinition(ResearchBatchRef('S015'),d.DeliveryStage.COMPONENTS,7,(d.DeliveryReference.from_dict(receipt['reference']),)),
        d.DeliveryContent(final_panel,d.DeliveryStatus.COMPLETE,(),(),report=adapted,evidence=tuple(refs)))
    assert assembled.validation.status.value == 'PASS',assembled.validation.issues
    check = validate_experiment(repo,ExperimentValidationRequest(EX,ExperimentValidationScope.REPORT_PUBLICATION))
    assert check.status.value == 'PASS',check.issues
    save(HERE/'others/delivery_validation.json',{'delivery':assembled.receipt.reference.to_dict(),
        'assembly_validation':assembled.validation.to_dict(),'report':report_ref.to_dict(),
        'experiment_publication':check.to_dict(),'materials':materials})
    intent = dict(read(ROOT/'research/registrations/S015/family.json')['research_intent'])
    intent.update(current_experiment=EX.to_dict(),current_components=assembled.receipt.reference.to_dict(),selected_candidate=None,
        current_phase='阶段二入场日固定对照完成；未建立有效增量，盈利机会代价明显，建议收口该路线',
        next_gate='当前固定路线停止；若继续先评审新的机制依据及范围，不自动阈值搜索、阶段三、冻结或PTE')
    update_research_intent(repo,ResearchBatchRef('S015'),ResearchIntentUpdate(research_intent=intent),
        actor='RSCH',reason='用户批准的唯一入场日损益固定对照完成，保留负面证据并正式交付COMPONENTS/7。')
    print({'assembly':assembled.validation.status.value,'report':check.status.value,'delivery':'COMPONENTS/7'},flush=True)


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=('report','publish'))
    {'report':report,'publish':publish}[p.parse_args().mode]()
