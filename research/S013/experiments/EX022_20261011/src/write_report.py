"""Report bounded early exit mechanisms with every center and parameter counterexample."""
from common import SRC,RUNS,PROTOCOLS,read,write,file_hash


def main():
    a=read(RUNS/'analysis.json')
    p=read(RUNS/'parameter_analysis.json')
    assert a['status']=='PASS' and p['status'] in ('PASS','NOT_APPLICABLE')
    qualified=[label for label,row in a['rows'].items() if not row['reused'] and row['qualified']]
    text='''# S013：有上限的价格条件提前退出与参数敏感性

RSCH阶段三；用户授权自主完成目标，无需逐轮评审。S013既有数据、MANDATE/6、原四项经济目标及执行合同保持。COMPLETE仅指本轮正式证据完整交付，目标判断另列。

## 假说、完整对照与最强反证

原H4改H3显著改变收益及2023盈亏。EX016在H期限后按价格条件才卖出的机制会无限延长信号持仓，全部未达标。已留存的2023事件描述中，正相对入场价bear定时退出的随后3日均值弱于非正组，但10日方向反转，事件重叠非独立，不能据此挑持有窗或直接推算新政策收益。

本轮将退出选择限制在原期限的前一天，并保留原最迟期限：EARLY_POSITIVE在bear age>=max(1,H-1)且age<H、当前HFQ信号Close严格高于入场信号Close时提前退出；EARLY_NONPOSITIVE测试相反条件Close<=anchor。等号只归非正组，H=1不提前，H仍完整1..60活跃参数。原H最迟信号年龄无条件保留，两个方向不会无限延长。上涨时间限制及两路其他退出优先级保持loss>trailing>range>time(提前或默认)>regime。

两个对应组合另叠加EX020 NEW_BULL_BODY_UP：仅raw bear转bull当日、空仓原入场机会成立时，当前Close>Open AND原确认分；stablebull与bear不加门。四个中心均为原ACF0.1/H4，事前固定，原C2132 H4、原H3未达标诊断控制、EX020 BODY H4完整账户核对后复用，共3控制。单独提前退出、相反条件、组合与既有BODY逐对比较，不能把单组件收益相加当作组合效果。

选择历史完整披露：BODY H4既有年化16.6697%、回撤13.3493%、2023盈利，但仅109笔而未满足110笔要求；本轮组合由已见开发证据启发。提前退出是否增加完成交易、改善收益，必须重新运行整套账户，不能从旧交易补一笔或推断独立贡献。EX021参考均值平滑4中心全失败，证明数值平滑不是经济稳定性的证据。

最强反证：相对信号价上涨并不等于实际净盈利（1%买入溢价、实际成交与费用仍计算）；提前卖出可能截断后续反弹、改变空仓机会和资金、增加成本，组合可能放大H/ACF及边界切换脆弱性。单日提前缓冲是新固定结构，不搜索新期限；已有H4/H3跳变并未凭结构名自动解决。只在反复研究的S013开发池测试，无独立验证。中心漂亮、更多交易或相对退化小，均不能单独宣布目标完成。

参考锚为原信号入场Close，非实际买价；信号年龄不因实际未成交或买卖回执重置，沿用原策略语义。最迟H约束是信号状态约束，实际账户持仓与执行延迟仍完整对账。所有价格和前raw状态在T时点已知，T+1执行；body条件缺失不填充。

510500.SH、2020-01-02至2026-09-30、1636实际交易日、100万元、HFQ研究单位、整手100、每侧10bp、策略与LimitBuyHold统一1%买入溢价。仅S013已有数据，无新增依赖、外部数据或独立验证。

原四门：净年化≥正收益基准1.5倍、每自然年回撤严格小于基准、每60交易日平均≥4闭合交易、基准亏损年2022/2023实际年度收益严格为正。参数诊断与全窗回撤不新增经济硬门。

## 全部中心完整账户

|机制/背景|候选|年化|全期回撤|闭合交易|2022收益|2023收益|原四门|
|---|---|---:|---:|---:|---:|---:|---|
'''
    for cell in a['cells']:
        row=a['rows'][cell['label']]
        failures='、'.join(key for key,passed in row['gates'].items() if not passed)
        text+=f"|{cell['mechanism']}/{cell['background']}|{row['candidate_id']}|{row['net_cagr']:.4%}|{row['drawdown']:.4%}|{row['closed_trades']}|{row['annual']['2022']['return']:.4%}|{row['annual']['2023']['return']:.4%}|{'通过' if row['qualified'] else failures}|\n"
    text+='\n提前与默认退出信号独立核对：\n'
    for label,row in a['rows'].items():
        if 'early_diagnostic' in row:
            b=row['early_diagnostic']
            text+=f"\n{label}：真正提前退出信号{b['early_signals']}、默认bear期限退出信号{b['default_bear_time_signals']}、最大bear信号年龄{b['max_bear_signal_age']}。逐日独立重建route/age/anchor/peak，提前条件与优先级精确一致；信号计数不是实际交易盈亏贡献。\n"
    text+='\n## 完整参数诊断\n\n'
    improvement=[]
    business=actual=reused=0
    if p['status']=='PASS':
        manifest=read(PROTOCOLS/'parameter_plans.json')
        business=manifest['new_parameter_business_accounts']
        reused=manifest['reused_parameter_accounts']
        actual=p['actual_parameter_evaluations']
        text+='事前声明与EX015一致的全部13个活跃中心数值坐标及完整域；固定提前1日缓冲/信号锚方向与可选边界body结构单列。域宽标准化总L2=5%、32点/中心、seed13、PCG64、整数HALF_EVEN与LINEAR分位数；所有新四门达标中心完整检验。原C2132 H4及未达标原H3控制各已有32点经身份、绑定、域、坐标、原生账户核对完整复用，不创建新身份或重放。无按结果删点、替换点或缩窄域。\n\n'
        text+='|中心|收益Q10|回撤Q90|收益退化pp|回撤恶化pp|邻点四门通过|\n|---|---:|---:|---:|---:|---:|\n'
        for row in p['summaries'].values():
            text+=f"|{row['candidate_id']}|{row['q10_cagr']:.4%}|{row['q90_drawdown']:.4%}|{row['return_degradation']*100:.4f}|{row['drawdown_degradation']*100:.4f}|{row['qualified_points']}/32|\n"
        for label,delta in p['differences_from_original'].items():
            text+=f"\n{label}相对原策略：收益Q10差{delta['q10_cagr_difference']*100:+.6f}、回撤Q90差{delta['q90_drawdown_difference']*100:+.6f}、收益退化差{delta['return_degradation_difference']*100:+.6f}、回撤恶化差{delta['drawdown_degradation_difference']*100:+.6f}个百分点。\n"
            if label in qualified and delta['return_degradation_difference']<0 and delta['drawdown_degradation_difference']<0:
                improvement.append(label)
        text+='\n相对退化与绝对较差参数账户表现一起解释，不能只凭较弱中心机械缩小退化宣布目标完成。32个有限点不是未来成功概率或独立验证；邻点资格数量为诊断，不改变中心四门资格。\n'
    else:
        assert not qualified
        text+='四个中心均未通过原四门，未追加参数账户；事前完整13维几何与不适用原因留存。不能用稳定但不达标的账户宣布目标达成。\n'
    if p['status']=='PASS':
        pairs=read(RUNS/'parameter_pairs.json')
        assert pairs['status']=='PASS'
        text+='\n原H3控制C7009未通过原亏损年盈利门，只作诊断，不登记或纳入新达标候选。各新中心与其原H4/H3控制采用完全相同32组数值坐标；四门资格保持，以下配对为机制诊断。\n'
        for label,row in pairs['comparisons'].items():
            text+=f"\n{label}同坐标{row['complete_pairs']}对：年化更好{row['cagr_better_points']}、更差{row['cagr_worse_points']}；回撤更小{row['drawdown_better_points']}、更大{row['drawdown_worse_points']}。平均年化差{row['mean_cagr_difference']*100:+.6f}、回撤差{row['mean_drawdown_difference']*100:+.6f}个百分点；收益Q10差{row['q10_cagr_difference']*100:+.6f}、回撤Q90差{row['q90_drawdown_difference']*100:+.6f}个百分点。\n"
    substantive=[]
    if improvement:
        substantive=[label for label in improvement if p['differences_from_original'][label]['q10_cagr_difference']>0 and p['differences_from_original'][label]['q90_drawdown_difference']<0]
    achieved=bool(substantive)
    text+='\n## 验证、结论与下一步\n\n'
    text+=f"4个新业务中心、5次实际评价（含一次串行/spawn技术重复）、3个原控制复用；参数新业务配置{business}、实际评价{actual}、既有参数复用{reused}。合计新业务配置{4+business}、实际评价{5+actual}。各原生完整账户、现金/数量/费用/周期/尾仓/年度回报对账、共同基准与原买入确认逐日独立核对，技术与身份验证完整留存。\n\n"
    text+='合成前缀/未来修改因果性、H1/2/4/60期限边界/正零负锚/最迟H/原score和退出优先级/body切换与稳定状态/非法价格输入及代表串行/spawn双方5账本精确一致；研究源码Ruff通过，未做仓库全量回归。全部历史证据保持不可变，Git不是数据资产备份。FULL公共交付验证只确认关联证据完整性，不保证交易效果。\n\n'
    text+=('本轮有限点集内得到保留原四门、相对退化和绝对尾部同时改善的方案；仍有反复搜索偏差，不能外推未来稳定。' if achieved else '本轮完整对照结束，未证明保留原四门的实质参数敏感性改善；总目标仍未达成。')+'\n\n'
    text+='未推进正式阶段四五项自检/族排名/交接、冻结、PTE或生产。下一步依据全账户与同坐标反证判断有界提前退出是否提供可用信息；不按已见亏损重选条件或缓冲日数、放宽原目标或擅自新增数据。\n'
    path=SRC.parent/'others/report.md'
    path.write_text(text,encoding='utf-8',newline='\n')
    write(RUNS/'conclusion.json',{'status':'COMPLETE','completion_scope':'this experimental delivery',
        'objective_achieved':achieved,'improvement_labels':substantive,
        'relative_degradation_improvement_labels':improvement,'new_qualified':len(qualified),
        'new_mechanism_business_accounts':4,'mechanism_actual_evaluations':5,
        'new_parameter_business_accounts':business,'parameter_actual_evaluations':actual,
        'reused_parameter_accounts':reused,'report_sha256':file_hash(path),
        'original_economic_criteria':'unchanged; diagnostics do not change center qualification'})
    print({'report':'COMPLETE','qualified':qualified,'objective_achieved':achieved})


if __name__=='__main__':
    main()
