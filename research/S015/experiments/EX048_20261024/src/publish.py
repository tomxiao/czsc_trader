"""Publish the P0 conclusions and explicitly linked inputs/results."""
from hashlib import sha256
from diagnose import ROOT, HERE, EX, read, save, material
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence, validate_experiment
from czsc_trader.research_tools import (ResearchBatchRef, ExecutionResources, EvidenceRef,
    ExperimentReportWrite, ExperimentOutcome, ExperimentValidationRequest, ExperimentValidationScope)

def main():
    history=read(HERE/'others/historical_results.json'); bridge=read(HERE/'others/bridge_results.json')
    lines=['# S015 P0：历史账户诊断与统一事件桥接', '', 'Status: COMPLETED', '',
        '2026-10-24，RSCH。用户已批准恢复研究并自主完成阶段二。本实验完成历史诊断及统一事件桥接；新增模型拟合、账户、候选和外部数据均为0。新P1模型属于EX049，本实验只读取其正式预测材料。当前合格候选数仍为0。', '',
        '## 账户事实与公共诊断边界', '',
        '固定核对EX042六组原型及计划指定C4307、C4507、C4607，均为原434日连续账户。公共diagnose_accounts对C4203、C4307、C4507返回COMPUTED，对其余六个返回UNSUPPORTED，原因是单周期多次成交/加仓。未以研究脚本把UNSUPPORTED改写为平台通过。', '',
        '下表为正式账本的独立会计算术：周期实际买卖现金流加末端未平仓估值，入场日毛损益单列，全部实际费用另扣。九账户最大绝对核对残差小于3×10⁻¹⁰元；三个可支持账户的公共诊断权益变化一致。补买收益按实际日期归入后续时段；这不是取消某笔交易后的反事实。', '',
        '| 原型 | 入场日毛损益/元 | 后续毛损益/元 | 费用/元 | 净损益/元 | 公共诊断 |', '| --- | ---: | ---: | ---: | ---: | --- |']
    for a in history['accounts']:
        lines.append(f"| {a['candidate']} | {a['entry_day_gross_yuan']:.2f} | {a['later_gross_yuan']:.2f} | {a['fees_yuan']:.2f} | {a['net_yuan']:.2f} | {a['official_diagnosis']} |")
    lines += ['', 'C4203的入场日毛收益集中，不能推广为“所有原型都应更快退出”：C4307的入场日毛损益为负，但后续持有毛收益68415.80元；C4507、C4607后续持有同样贡献较大。原入场许可失效即卖出是否有价值已在历史对照研究，不能据本次分解重复宣称普遍有效。', '',
        'EX042的许可并非每次都能成为独立入场。C4200共269个可许可决策，其中119个发生在已有正意图内、61个在退出意图日；C4203相应为219、99、46。它们是相同资金和意图时钟下的机会重叠事实，不能把全部独立事件净收益相加成账户回报。“持仓排斥”与“结束周期当天不可重入”分别保留；未成交、补买、周期数量见结果明细。', '',
        '信号日至首次成交前的价格变化仅是尚未持仓的价格路径，不属于账户实际损益。cycle_accounting保留按首笔数量换算的这一描述量，不将其与账户盈亏求和、不假设能在信号价提前成交。', '',
        '## 是否仍只有超跌反弹在赚钱', '',
        '按首次实际BUY对应决策时已知的过去5日收益正、负、零分类，不以结果删样本。金额是这些实际周期的全部已实现或期末估值净损益；各组共享同一账户资金，不是各组独立10万元回测。', '',
        '| 原型 | 下跌组周期/净损益 | 上涨组周期/净损益 | 零变化组周期/净损益 |', '| --- | --- | --- | --- |']
    for a in history['accounts']:
        groups={x['r5_sign']:x for x in a['r5_groups']}
        values=[]
        for key in ('down','up','zero'):
            x=groups.get(key);values.append('0 / 无样本' if x is None else f"{x['cycles']} / {x['net']:.2f}元")
        lines.append('| '+a['candidate']+' | '+' | '.join(values)+' |')
    lines += ['', 'C4203及三个后续代表点的主要净收益来自过去5日上涨背景，削弱了“这些结果只能依赖过去下跌后反弹”的解释。但它既未证明与S011经济机制独立，也未证明所有上涨背景事件更有利。分类只在既有成交样本上完成，不据此立即增加r5过滤或宣称过滤后的收益。', '',
        '## 原四折与新学习日程的同队列桥接', '',
        'EX032四折从位置100开始，固定测试段100—183、184—267、268—351、352—433；EX042及新P1从位置34、2025-02-27开始，每20交易日更新，至少30个已成熟三日标签。两者起点、更新频率和队列不同。新P1先固定原EX032的323个已闭合三日事件，应用两种日程的B/B+F三日预测；下表所有金额分母来自完全相同事件。', '',
        '| 延迟 | 信息 | 日程 | 标签 | 识别亏损金额 | 遗漏盈利金额 | 避开事件数 |', '| --- | --- | --- | --- | ---: | ---: | ---: |']
    for row in bridge['rows']:
        lines.append(f"| T−{row['lag']} | {row['family']} | {row['schedule']} | {'三日净损益' if row['target']=='net' else '入场日扣买费损益'} | {100*row['identified_loss_fraction']:.4f}% | {100*row['missed_profit_fraction']:.4f}% | {row['reject_n']} |")
    lines += ['', '关键变化：在相同323个三日事件上，旧日程B→B+F把识别亏损由30.7591%提高至42.9089%，同时遗漏盈利由34.7930%降至32.8213%；新日程则由32.6205%提高至45.2517%，但遗漏盈利由33.7252%升至39.9518%。份额在旧日程下同时改善两项的表现，并未在新更新日程复现；不能沿用旧数字预言账户必然改善。T−3也出现避损增加、遗漏盈利增加的取舍。', '',
        '对同一组事件的入场当天，新日程B识别41.9325%亏损金额、遗漏32.5776%盈利；B+F识别49.9408%、遗漏38.3145%。它识别更多当天亏损，也错过更多当天盈利。此处仍不能推出连续账户能避免相同比例的亏损。', '',
        '本表入场日栏使用的是“三日预测是否小于0”这一固定许可，观察它对入场当天亏损的识别；不是EX032直接预测entry_net_h1的326事件试验。该试验原结论仍保留：原量价47.9790%识别亏损/32.6240%遗漏盈利，份额T−1为48.0308%/32.7800%，几乎没有改善。不得混用目标、队列与分母。', '',
        '重新训练仍使用已反复观察的开发池；本次同队列桥接只排除了比较事件集合差异，未将新日程变成独立验证，更不能把其变化全部归因于份额信息。各事件各自重置10万元并可重叠，金额识别率不是连续账户的可避免损失比例。', '',
        '## 诊断更新与下一对照', '',
        '| 已有事实 | 尚存竞争解释 | 有辨别力的对照 |', '| --- | --- | --- |',
        '| 原四折份额增量集中末折；新日程产生不同许可 | 信息增量、学习更新及参与数量可能混合 | EX049同日程U/B/B+F/B+P/B+P+F，新资金合同100%及T−3敏感性 |',
        '| 独立事件大量重叠；实际账户费用和补买影响净结果 | 信息虽有用但资金/重复交易消耗收益；或只是一般暴露差异 | 同一真实资金账户、相同退出时钟，逐项比较收益回撤与实际频率 |',
        '| 风险许可和收益许可表现不同 | 风险状态选择有针对性，或普通少持仓足以解释 | EX050全部新周期合同的100%/50%/75%/拒绝/条件半仓五臂 |',
        '| 入场日和后续持有贡献依原型不同 | 持有价值与入场价值需不同判断；也可能仅为固定长持有有效 | 只有P1/P2给出具体新增持仓问题时才设计P3，并保留固定长持有对照 |', '',
        '完整159配置摘要保留在historical_159_centers.csv，联合中心通过0；这里对九个预定代表账户做了诊断，并未重新审计159个账户全部经济账本。本实验不改变历史资格、经济硬门或选择历史。', '',
        '下一步由EX049/EX050完整账户结果决定用途支持与阶段二收口。P0已完成；没有根据会计分解临时搜索阈值、删掉亏损交易、切换目标或进入阶段三。', '',
        '证据：[公共诊断](others/public_diagnoses.json)、[账户结果](others/historical_results.json)、[周期明细](others/cycle_accounting.csv)、[完整159配置](others/historical_159_centers.csv)、[历史日程](others/historical_schedules.json)、[同队列桥接](others/bridge_results.json)、[桥接逐事件](others/common_event_bridge.csv)、[来源引用](others/published_refs.json)。']
    (HERE/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    ctx=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=ExecutionResources(1,1,13))
    refs=read(HERE/'others/published_refs.json')
    refs['materials']['src/publish.py']=material(ctx,HERE/'src/publish.py').to_dict()
    allrefs=[*refs['materials'].values(),*refs['account_sources'],*refs['protocol_and_source'],*history['sources'],*bridge['sources']]
    evidence=tuple({r['sha256']:EvidenceRef.from_dict(r) for r in allrefs}.values())
    previous=EvidenceRef.from_dict(read(HERE/'report_ref.json')['report']) if (HERE/'report_ref.json').exists() else None
    report=publish_evidence(ctx,ExperimentReportWrite(EX,sha256((HERE/'report.md').read_bytes()).hexdigest(),ExperimentOutcome.COMPLETED,evidence,previous))
    result=validate_experiment(RepositoryContext.discover(ROOT),ExperimentValidationRequest(EX,ExperimentValidationScope.REPORT_PUBLICATION))
    assert result.status.value=='PASS',result.issues
    refs.update(report=report.to_dict(),validation=result.to_dict());save(HERE/'others/published_refs.json',refs)
    print('EX048_PUBLISHED',report.sha256,'VALIDATION',result.status.value)

if __name__=='__main__': main()
