"""Publish the bounded retrospective diagnosis; never evaluate a new account."""
from hashlib import sha256

from diagnose import ROOT, HERE, PREV, EX, REPS, read, save, context, material
from czsc_trader.application import (
    RepositoryContext, publish_evidence, validate_experiment, update_research_intent,
    ResearchIntentUpdate,
)
from czsc_trader.research_tools import (
    EvidenceRef, ExperimentOutcome, ExperimentReportWrite, ExperimentValidationRequest,
    ExperimentValidationScope, ResearchBatchRef,
)


def main():
    assert not (HERE / 'others/publication_validation.json').exists()
    result = read(HERE / 'others/diagnosis_results.json')
    refs = [EvidenceRef.from_dict(x) for x in read(HERE / 'others/protocol_refs.json')]
    assert refs[1].sha256 == sha256((HERE / 'src/diagnose.py').read_bytes()).hexdigest()
    refs += [EvidenceRef.from_dict(result[k]) for k in ('source', 'baseline')]
    refs += [EvidenceRef.from_dict(v['source']) for v in result['accounts'].values() if 'source' in v]
    history = {}
    for name in ('EX003_20261021', 'EX004_20261022', 'EX010_20261023',
                 'EX011_20261023', 'EX012_20261023', 'EX013_20261023'):
        folder = HERE.parent / name
        ref = EvidenceRef.from_dict(read(folder / 'report_ref.json')['report'])
        snapshot = read(ref.resolve(ROOT))
        digest = sha256((folder / 'report.md').read_bytes()).hexdigest()
        assert snapshot['report_sha256'] == digest
        refs.append(ref)
        history[name] = {'report': ref.to_dict(), 'report_sha256': digest}
    overview_ref = EvidenceRef.from_dict(read(PREV / 'others/overview_ref.json'))
    overview = read(overview_ref.resolve(ROOT))
    refs.append(overview_ref)
    candidates = ROOT / 'research/registrations/S015/candidates'
    candidate_hashes = {p.name: sha256(p.read_bytes()).hexdigest() for p in candidates.glob('*.json')}
    assert len(candidate_hashes) == overview['candidate_count'] == 117
    assert result['new_account_evaluations'] == 0
    max_residual = max(a['max_residual'] for a in result['accounts'].values())
    assert max_residual < 1e-7
    save(HERE / 'others/verification.json', {
        'status': 'PASS_ACCOUNTING_AND_REFERENCES_ONLY', 'accounts': 87,
        'new_account_evaluations': 0, 'max_daily_residual_yuan': max_residual,
        'historical_reports': history, 'candidate_registration_hashes': candidate_hashes,
        'prior_overview': overview_ref.to_dict(), 'prior_snapshot': overview['snapshot_sha256'],
        'overview_scope': 'Reuse authenticated EX013 same-work-segment overview; no fresh whole-repository overview or historical FULL rerun. New report validated separately.',
        'public_diagnosis': 'UNSUPPORTED; RSCH arithmetic does not turn it into PASS',
    })
    text = '''# S015 研究诊断：回撤集中于买入当日，尚无直接改规则的依据

Status: COMPLETED

RSCH，2026-10-23。用户“同意，请继续执行研究诊断”授权范围内，完成既有账本诊断和下一步问题设计。诊断任务已完成；未新增有效组件，S015完整策略目标仍未达成。本次新增策略账户、参数搜索和组件预测实验均为0。

## 目标、范围与结论

承接[EX013](../EX013_20261023/report.md)：原434日完整合格的86个候选，在415日共同窗口中收益严格优于S011的11个、回撤严格更小的0个、两项同时通过的0个。原434日开发池、415日比较窗口、目标及历史候选资格保持不变。

本次固定分析上述86个账户和原S011账本；三个代表为旧中心C0031、收益合格组回撤最小的C0228、全体回撤最小的C0307，选择发生在结果已知之后。问题、公式及分类先记录于[协议](protocols/diagnosis.json)，再执行算术；不改变账户、不删除交易重算净值。

研究判断：现有证据优先指向“入场日方向判断不足”，不支持立即以延长/缩短持仓或一律禁止超时再入作为突破口。建议维持旧候选路线受限收口，先做一项有界的阶段二标签对齐检验；目前不进入阶段三策略搜索。

## 1. 损失发生在哪一段

86个身份的最大回撤谷值：2026-07-20有70个，2026-10-15有10个，2026-03-23有5个，2025-04-07有1个。候选高度相关；这些数量不是独立市场事件数，也不是70次独立验证。

三个代表都从2026-06-30高点至2026-07-20低点，跨度14个交易日。将每一天真实净值变化拆为：空仓后新买份额从成交价到收盘的损益、已有仓位加买份额的同段损益、未卖旧份额从前收盘到本收盘的损益、卖出旧份额从前收盘到成交价的损益、实际费用。费用列为正并从其余项之和扣除。拆分包含开盘跳空，不声称精确日内成交路径已知。

| 账户 | 最大回撤 | 新入场损益/元 | 加买损益/元 | 持有损益/元 | 卖出损益/元 | 费用/元 | 峰谷净亏损/元 | 新入场毛亏损占净亏损 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
'''
    for cid in REPS:
        d = result['accounts'][cid]['maximum_drawdown']
        p = d['pieces_yuan']
        text += (f"| {cid} | {d['magnitude']:.4%} | {p['new_entry']:.2f} | {p['addition']:.2f} | "
                 f"{p['holding']:.2f} | {p['exit']:.2f} | {p['fees']:.2f} | {p['net_pnl']:.2f} | "
                 f"{p['new_entry']/p['net_pnl']:.2%} |\n")
    text += '''
约八成是会计金额占比，不能说成“八成损失可以避开”或“八成亏损交易发生于入场日”。限制持仓天数不能直接消除已经发生的入场日损失；改变入场规则也会改变后续资金、持仓和收益，仍须真实账户验证。

S011自身最大回撤7.2487%，高点是2026-07-03，低点也是2026-07-20；其自身峰谷区间新入场损益−13746.70元、持有+510.30元、卖出−272.10元、费用1175.38元。峰值日期及本金不同，不能把不同账户的元数差直接归因于某个组件。S011同样暴露于入场当日风险，只是实际入场和暴露路径不同。

入场当日也贡献大量收益：C0031完整415日新入场份额毛损益为+84490.90元。账户费用、后续持有和卖出另计。这既说明研究该段具有经济意义，也反驳“回避入场段就是免费降低风险”。

## 2. 两个看似可改的交易规则，为什么不优先实施

历史EX003的max_days实际计数的是信号周期年龄，包括未成交的日子，并非成交后的持仓年龄。这个区别真实存在，但三个代表各101个实际持仓周期中，入场信号年龄大于1的都只有1个；均在2026-08-03，且完整周期净盈利。因此它不能解释本次7月主要回撤，不能仅凭命名差异就推出改年龄能改善结果。

“未恢复超时再入”使用原三个代表共同的退出阈值0.005和最大信号年龄3：上一次实际持仓周期仅因超时退出，至本次实际新入场信号，卖压尚未触及原退出恢复阈值。首周期边界未知单列，其余情况归其他入场。这套分类只用于三个已核对参数的代表，不扩展到全部86个候选。

| 代表 | 已闭合再入周期 | 盈利周期 | 盈利合计/元 | 亏损合计/元 | 费用后净额/元 | 2025入场组净额/元 | 2026入场组净额/元 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
'''
    for cid in REPS:
        groups = {g['entry_cohort']: g for g in result['representatives'][cid]['groups']
                  if g['class'] == 'UNRECOVERED_TIMEOUT_REENTRY'}
        g = groups['ALL']
        text += (f"| {cid} | {g['closed_count']} | {g['positive_cycles']} | {g['positive_pnl']:.2f} | "
                 f"{g['negative_pnl']:.2f} | {g['net_pnl']:.2f} | {groups['2025']['net_pnl']:.2f} | "
                 f"{groups['2026']['net_pnl']:.2f} |\n")
    text += '''
三个账户的入场日期高度一致，仓位表达不同，不是三份独立复制。2025组均20笔、14笔盈利；2026组均7笔、2笔盈利。按入场年份分组的完整周期金额不是自然年账户收益，不能将“2026”当成事前交易条件。原始结果中的归一化周期损益之和也不是可投资组合收益。

各代表共100个已闭合周期、1个未闭合周期。分组表只列已闭合周期；全部周期加末日未平仓市值已与完整账户权益增量对账。holding_sessions是入场与退出交易日索引之差，不是含首尾的天数。

这条再入规则确实会遇到连续下跌，也贡献过盈利；全期仍净正。现有证据不支持优先“一律禁止再入”，更不能将旧盈利/亏损记录直接删去后宣称得到了改规则后的账户表现。

## 3. 历史实验已经回答什么，尚未回答什么

- [EX003](../EX003_20261021/report.md)：入场过滤、退出阈值和信号周期长度已有搜索；延长周期常被原退出条件提前截断，不能把尚未做过某个变体等同于有改进依据。
- [EX004](../EX004_20261022/report.md)：已有振幅仓位、匹配平均仓位、反向及边界对照；缩放风险没有解决收益和回撤双优，信息增益不能只按较低回撤认定。
- [EX010](../EX010_20261023/report.md)、[EX011](../EX011_20261023/report.md)、[EX012](../EX012_20261023/report.md)：共66项成对条件，最终没有证实对强日线控制仍稳定的新增分钟价值。午后相对上午变化的一日风险预测改善，在加body控制后从0.981%降为0.314%，2025几乎为零、四段中两段变差。该结论保持不变。
- 旧风险标签取入场日至计划退出前的最低价，可能含实际成交之前的低点；旧h1收益标签从T+1成交算至T+2退出，包含隔夜/退出段。它们都不是本次准确定位的“T+1实际成交至当日收盘的有符号损益”。新问题是评价对象与损失段对齐，不是找到了新信息，也不构成推翻旧负面证据。

## 4. 下一步建议：一项固定阶段二检验，先不改策略

具体问题：T日已有日线信息，在卖压和振幅之外，能否辨别T+1成交后到收盘的亏损，同时保留该段盈利机会？这是下一轮待批准方案，本轮没有执行预测拟合、事件标签生成或账户回测。

建议固定如下范围，正式开跑前单独发布协议与代码：

1. 只复用原434日开发池及预热、原始成交规则与已留存数据，截止2026-10-21；不读取新日期或独立验证池，不增加信息类别。
2. 唯一主标签为原1%限价合同下T+1实际可成交份额到当日收盘的有符号毛损益/10万元；同时明确入场费及其扣后金额，不虚构当日卖出。未成交、缺失和边界单列，不填为零。它是事件诊断标签，不是完整账户收益。
3. 一个固定模型对照：EX011的PR日线控制（近1/5日收益、20日波动、卖压、振幅），对比EX012的AllDaily既有8种日线定义。沿用固定岭回归alpha=10、训练内标准化、原四段向前检验；训练标签结束日严格早于测试起点。先不重新搜索分钟组件、方向、阈值或持有期限。
4. 同时报告预测误差、亏损识别和错过的盈利金额；训练期三分位分组仅作描述，保留中间组及所有正负结果。报告全部事件和旧C0031实际首次入场子集，披露子集较小且由已选策略形成；各年、四段、删除极端值及块区间只作诊断，不新增经济硬门。
5. 若增量依旧弱或代价抵消改善，建议收口现有输入路线；若有可解释线索，再提交一个完整账户对照方案，请用户决定是否进入阶段三。标签改善本身不够证明新组件或策略目标已达成，也不授权自动反复换标签。

提出这项后续检验，是因为现有损失发生段和过去标签存在明确错位；不是因为相信再做一次就必然成功。历史已被多轮观察，改标签仍有开发选择偏差，没有新的独立样本。原434日完整要求及415日严格收益/回撤比较均保持不变。

## 验证与交付边界

87份既有账户通过EvidenceRef校验来源；86候选最大回撤重算与EX013逐项一致。每日持仓数量及现金权益增量、峰谷金额、代表完整周期现金流加末日持仓市值均对账。最大逐日金额残差见[核验记录](others/verification.json)，小于0.0000001元。

公开diagnose_accounts对C0031返回UNSUPPORTED，原因是一个持仓周期有多次成交或仓位调整；该状态原样保留于[公开诊断结果](others/public_diagnosis.json)。这里是RSCH单独声明的实际账本算术，未修改平台、未把公开诊断冒充PASS。

完整结果见[诊断数据](others/diagnosis_results.json)，四份逐日拆分CSV及源码与报告显式关联正式证据。先前EX013全量证据核验和overview在同一工作段复用，仅认证该快照并检查本轮117个登记身份未变化；没有重复宣称新的全仓overview或旧FULL重算。最终REPORT_PUBLICATION校验只认证交付完整性，不代表经济目标通过。

证据发布首次因沙箱拒绝硬链接写入而失败，保留[恢复记录](others/publication_recovery.json)，随后在同一协议下完成发布；未触发新账户评价。未修改历史证据、候选资格或旧阶段交付。本次不合并master、不推送、不打tag、不进入冻结/PTE或生产操作。
'''
    (HERE / 'report.md').write_text(text, encoding='utf-8', newline='\n')
    materials = {}
    paths = sorted((HERE / 'others').glob('*.csv')) + [HERE / 'others' / n for n in (
        'diagnosis_results.json', 'public_diagnosis.json', 'publication_recovery.json', 'verification.json')]
    paths.append(HERE / 'src/deliver.py')
    for path in paths:
        ref = material(path.stem, path)
        refs.append(ref)
        materials[path.name] = ref.to_dict()
    report_ref = publish_evidence(context(), ExperimentReportWrite(EX,
        sha256((HERE / 'report.md').read_bytes()).hexdigest(), ExperimentOutcome.COMPLETED, tuple(refs)))
    repo = RepositoryContext.discover(ROOT)
    check = validate_experiment(repo, ExperimentValidationRequest(EX, ExperimentValidationScope.REPORT_PUBLICATION))
    save(HERE / 'others/publication_validation.json', {
        'status': check.status.value, 'validation': check.to_dict(), 'report': report_ref.to_dict(), 'materials': materials})
    assert check.status.value == 'PASS', check.issues
    assert candidate_hashes == {p.name: sha256(p.read_bytes()).hexdigest() for p in candidates.glob('*.json')}
    intent = dict(read(ROOT / 'research/registrations/S015/family.json')['research_intent'])
    intent.update(current_experiment=EX.to_dict(), selected_candidate=None,
        current_phase='研究诊断完成；入场日损失为主要线索，冷却及真实持仓年龄解释不足；未新增组件或账户',
        current_diagnosis_report=report_ref.to_dict(),
        next_gate='等待用户批准单一入场当日损益标签的阶段二固定对照；不自动策略搜索、冻结或PTE')
    update_research_intent(repo, ResearchBatchRef('S015'), ResearchIntentUpdate(research_intent=intent),
        actor='RSCH', reason='按用户授权完成既有86候选及基线账本诊断，保留反证并提出有界阶段二问题。')
    print({'publication': check.status.value, 'new_accounts': 0, 'max_residual': max_residual}, flush=True)


if __name__ == '__main__':
    main()
